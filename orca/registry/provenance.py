"""
Training-run provenance wiring -- the mandatory lifecycle path connecting
TrainingConfig -> TrainingRunManifest -> (training happens) -> CheckpointRecord
-> ModelRegistry.register(). Phase 21B closed the gap where
TrainingRunManifest/CheckpointRecord existed but no real training entry
point ever called them. Phase 21B.1 wired revision pinning, single-
manifest dataset binding, and multi-file checkpoint digests. Phase
21B.2 closes the remaining trust-boundary gaps an independent audit
found in that closure:

  - DEFAULT-PATH BYPASS: verify_dataset_binding() previously only
    cryptographically verified files when cfg.train_file/eval_file were
    explicitly set -- the common default-path case (cfg.train_file="")
    was accepted with dataset_content_digests={}. Now ALWAYS resolves
    the exact files via orca.train.config.resolve_training_data_inputs()
    (the single source of truth _train_impl() also uses) and requires
    every consumed split to have a verified digest for canonical
    training -- no exceptions.
  - EXISTENCE-ONLY MULTI-MANIFEST: multiple dataset_manifest_ids were
    accepted by checking only that each named manifest exists, never
    that the actual combined training bytes came from those sources.
    Now requires a DatasetBundleManifest (orca.registry.dataset_bundle)
    binding the exact combined file digests when more than one source
    manifest is declared for canonical training.
  - TOCTOU: verification and actual training consumption read the same
    mutable source path at two different times. create_run_snapshot()/
    verify_run_snapshot() close this: verified source files are copied
    into a run-scoped snapshot directory, re-hashed, and the digest is
    checked AGAIN immediately before orca.train.finetune._train_impl()
    calls load_dataset() -- the trainer only ever reads the snapshot.
  - CHECKPOINT VALIDITY: hash_artifact_directory() proves identity for
    whatever files are present, never structural completeness.
    complete_training_run() now calls
    orca.registry.checkpoint.validate_checkpoint_artifact() FIRST and
    refuses to register a structurally incomplete checkpoint no matter
    how clean its digest is.

Deliberately CPU-safe and import-light (no unsloth/torch/transformers)
so the full manifest/checkpoint/registry lifecycle -- including every
trust seam above -- can be unit-tested without a GPU or the heavy
training dependency stack. See tests/test_training_provenance.py and
orca/train/finetune.py::train() for the real (GPU-only) integration
point.
"""
from __future__ import annotations

import hashlib
import json
import shutil
import time
from pathlib import Path

from orca.config import ORCA_HOME
from orca.registry.checkpoint import ArtifactAvailability, CheckpointRecord, validate_checkpoint_artifact
from orca.registry.dataset_bundle import DatasetBundleManifest
from orca.registry.dataset_manifest import DatasetManifest, sha256_of_file
from orca.registry.model_registry import ModelRegistry
from orca.registry.model_spec import MODEL_SPECS, get_spec, require_pinned_revision
from orca.registry.training_run import TrainingRunManifest
from orca.train.config import TrainingConfig, resolve_training_data_inputs, validate_training_identity

RUN_SNAPSHOT_DIR = ORCA_HOME / "training" / "run_snapshots"


class DatasetBindingInvalid(ValueError):
    """A canonical training run's declared dataset manifest(s)/bundle
    could not be verified against the actual bytes about to be trained
    on."""


class SnapshotIntegrityError(ValueError):
    """A run-scoped input snapshot was modified between verification
    and actual training consumption (the TOCTOU window this module
    closes), or is missing/unreadable when it should exist."""


def deterministic_run_id(cfg: TrainingConfig, *, nonce: str) -> str:
    """Deterministic given (cfg identity fields, nonce) -- never uuid4()
    or a bare wall-clock read alone. `nonce` is caller-supplied (e.g. a
    fresh timestamp or an explicit experiment label) so this function
    itself stays pure and testable; the real training path supplies a
    fresh nonce per invocation."""
    payload = f"{cfg.family}:{cfg.base_model}:{cfg.model_name}:{nonce}"
    return f"run-{hashlib.sha256(payload.encode('utf-8')).hexdigest()[:16]}"


def resolve_pinned_revisions(cfg: TrainingConfig) -> tuple[str | None, str | None]:
    """For a canonical family config, returns the exact pinned
    (base_model_revision, tokenizer_revision) -- raising ValueError if
    either is unpinned. For a generic (family=None) experimental
    config, returns (None, None): no canonical ModelSpec to pin
    against for a deliberately non-canonical run."""
    if cfg.family is None:
        return None, None
    return require_pinned_revision(cfg.family)


def verify_dataset_binding(
    cfg: TrainingConfig, *, dataset_manifest_ids: list[str], dataset_bundle_id: str | None = None,
) -> dict[str, str]:
    """Fail-closed dataset provenance for canonical (family-set)
    training. Always resolves the EXACT files that will be consumed via
    resolve_training_data_inputs() -- the same function
    orca.train.finetune._train_impl() uses -- never a caller-optional
    path. Returns {"train": sha256, "validation": sha256|omitted,
    "held_out": ...|omitted} for every split that was actually
    cryptographically verified. A canonical run with an empty result
    (no split verified) is never acceptable -- callers must treat that
    as a binding failure, not a valid-but-unverified state.

    Rules:
      - cfg.family is None (generic/experimental): no dataset provenance
        requirement at all; returns {}.
      - Exactly one dataset_manifest_id: verified directly against that
        DatasetManifest's own checksums (Phase 21B.1 behavior,
        unchanged), but now ALWAYS using resolve_training_data_inputs()
        -- no more "only if cfg.train_file/eval_file happen to be set".
      - Zero dataset_manifest_ids: REJECTED for canonical training.
      - More than one dataset_manifest_id: REQUIRES dataset_bundle_id
        naming a DatasetBundleManifest that (a) lists every declared
        source manifest in its own lineage and (b) cryptographically
        verifies the exact combined train/eval bytes. Existence-only
        (checking that each source manifest merely exists) is no longer
        accepted for canonical training.
    """
    if cfg.family is None:
        return {}

    if not dataset_manifest_ids:
        raise DatasetBindingInvalid(
            f"Canonical family training (family={cfg.family!r}) requires at least one "
            "dataset_manifest_id -- refusing to train with no declared dataset provenance."
        )

    resolved = resolve_training_data_inputs(cfg)
    if not resolved.train_path.exists():
        raise DatasetBindingInvalid(f"Resolved training file does not exist: {resolved.train_path}")
    if resolved.eval_path is None or not resolved.eval_path.exists():
        raise DatasetBindingInvalid(
            "Canonical training requires a resolvable, existing validation file -- "
            f"resolved eval path: {resolved.eval_path!r}"
        )

    if len(dataset_manifest_ids) == 1:
        dataset_id, _, version = dataset_manifest_ids[0].rpartition("-")
        if not dataset_id or not version:
            raise DatasetBindingInvalid(
                f"dataset_manifest_id {dataset_manifest_ids[0]!r} is not in '<dataset_id>-<version>' form"
            )
        try:
            manifest = DatasetManifest.load(dataset_id, version)
        except FileNotFoundError as exc:
            raise DatasetBindingInvalid(f"No dataset manifest found for {dataset_manifest_ids[0]!r}") from exc
        ok, msg = manifest.verify_against_files(resolved.train_path, resolved.eval_path)
        if not ok:
            raise DatasetBindingInvalid(f"Dataset {dataset_manifest_ids[0]!r} failed binding verification: {msg}")
        return {"train": manifest.train_checksum, "validation": manifest.eval_checksum}

    # Multiple source manifests declared: existence-only is forbidden --
    # a DatasetBundleManifest binding the exact combined bytes is required.
    for dataset_manifest_id in dataset_manifest_ids:
        dataset_id, _, version = dataset_manifest_id.rpartition("-")
        if not dataset_id or not version:
            raise DatasetBindingInvalid(
                f"dataset_manifest_id {dataset_manifest_id!r} is not in '<dataset_id>-<version>' form"
            )
        try:
            DatasetManifest.load(dataset_id, version)
        except FileNotFoundError as exc:
            raise DatasetBindingInvalid(f"No dataset manifest found for {dataset_manifest_id!r}") from exc

    if dataset_bundle_id is None:
        raise DatasetBindingInvalid(
            f"{len(dataset_manifest_ids)} source dataset manifests declared for canonical training "
            "without a dataset_bundle_id -- existence-only multi-manifest provenance is forbidden. "
            "Build and pass a DatasetBundleManifest binding the exact combined train/eval bytes."
        )
    bundle_id, _, bundle_version = dataset_bundle_id.rpartition("-")
    if not bundle_id or not bundle_version:
        raise DatasetBindingInvalid(f"dataset_bundle_id {dataset_bundle_id!r} is not in '<bundle_id>-<version>' form")
    try:
        bundle = DatasetBundleManifest.load(bundle_id, bundle_version)
    except FileNotFoundError as exc:
        raise DatasetBindingInvalid(f"No dataset bundle manifest found for {dataset_bundle_id!r}") from exc

    bundle_source_ids = {s.dataset_manifest_id for s in bundle.source_manifests}
    if bundle_source_ids != set(dataset_manifest_ids):
        raise DatasetBindingInvalid(
            f"Dataset bundle {dataset_bundle_id!r}'s source lineage {sorted(bundle_source_ids)} does not match "
            f"the declared dataset_manifest_ids {sorted(dataset_manifest_ids)}"
        )
    ok, msg = bundle.verify_against_files(resolved.train_path, resolved.eval_path)
    if not ok:
        raise DatasetBindingInvalid(f"Dataset bundle {dataset_bundle_id!r} failed binding verification: {msg}")
    return {"train": bundle.train_checksum, "validation": bundle.eval_checksum}


def create_run_snapshot(run_id: str, *, train_path: Path, eval_path: Path | None) -> dict:
    """Closes the TOCTOU window between dataset-binding verification and
    actual training consumption: copies the verified source files into
    a run-scoped, uniquely-named snapshot directory and re-hashes them
    there. The trainer must load ONLY from these snapshot paths, never
    the original (still-mutable) source paths. Returns
    {"train": {"path": str, "sha256": str}, "eval": {...} | None} --
    this structure is what verify_run_snapshot() re-checks immediately
    before load_dataset()."""
    snapshot_dir = RUN_SNAPSHOT_DIR / run_id
    snapshot_dir.mkdir(parents=True, exist_ok=True)

    train_snapshot_path = snapshot_dir / "train.jsonl"
    shutil.copyfile(train_path, train_snapshot_path)
    info: dict = {"train": {"path": str(train_snapshot_path), "sha256": sha256_of_file(train_snapshot_path)}}

    if eval_path is not None:
        eval_snapshot_path = snapshot_dir / "eval.jsonl"
        shutil.copyfile(eval_path, eval_snapshot_path)
        info["eval"] = {"path": str(eval_snapshot_path), "sha256": sha256_of_file(eval_snapshot_path)}
    else:
        info["eval"] = None

    return info


def verify_run_snapshot(snapshot_info: dict) -> None:
    """Re-hashes the run-scoped snapshot files and compares against the
    digests recorded at create_run_snapshot() time -- called
    immediately before load_dataset() in orca.train.finetune._train_impl().
    Raises SnapshotIntegrityError on any mismatch or missing file. No
    model/trainer is ever loaded on input that fails this check."""
    for split in ("train", "eval"):
        entry = snapshot_info.get(split)
        if entry is None:
            continue
        path = Path(entry["path"])
        if not path.exists():
            raise SnapshotIntegrityError(f"Run-scoped {split} snapshot file is missing: {path}")
        actual = sha256_of_file(path)
        if actual != entry["sha256"]:
            raise SnapshotIntegrityError(
                f"Run-scoped {split} snapshot file was modified after verification: {path} "
                f"(expected sha256={entry['sha256']}, actual={actual})"
            )


def hash_artifact_directory(path: Path) -> dict:
    """Deterministic, multi-file checkpoint-artifact IDENTITY (distinct
    from VALIDITY -- see orca.registry.checkpoint.validate_checkpoint_artifact(),
    always called before this in complete_training_run()). Enumerates
    every file under `path` (sorted by relative path for determinism --
    never filesystem traversal order, never mtimes), records
    {path, size, sha256} for each, then hashes the canonical JSON of
    that file list. Changing ANY required file's content, adding a
    file, or removing a file changes the resulting `manifest_digest`."""
    if not path.exists():
        raise FileNotFoundError(f"Artifact directory does not exist: {path}")
    files = []
    for file_path in sorted(p for p in path.rglob("*") if p.is_file()):
        rel = file_path.relative_to(path).as_posix()
        files.append({"path": rel, "size": file_path.stat().st_size, "sha256": sha256_of_file(file_path)})
    canonical_json = json.dumps(files, sort_keys=True, separators=(",", ":"))
    manifest_digest = hashlib.sha256(canonical_json.encode("utf-8")).hexdigest()
    return {"files": files, "manifest_digest": manifest_digest}


def start_training_run(
    cfg: TrainingConfig,
    *,
    dataset_manifest_ids: list[str],
    hardware_info: str,
    run_id: str | None = None,
    dataset_bundle_id: str | None = None,
    compute_provider: str | None = None,
    create_snapshot: bool = True,
) -> TrainingRunManifest:
    """Creates and PERSISTS a TrainingRunManifest BEFORE any expensive
    training work begins. Fails closed via, in order: (1)
    validate_training_identity(); (2) resolve_pinned_revisions(); (3)
    verify_dataset_binding() (now always against the resolved, real
    consumption paths -- see module docstring); (4), when
    create_snapshot=True (the default, and always true for the real
    training path), create_run_snapshot() copies the verified files
    into a run-scoped snapshot and records ITS digests as
    dataset_split_digests -- the exact bytes orca.train.finetune will
    be required to re-verify immediately before load_dataset()."""
    validate_training_identity(cfg)
    base_model_revision, tokenizer_revision = resolve_pinned_revisions(cfg)
    verified_digests = verify_dataset_binding(
        cfg, dataset_manifest_ids=dataset_manifest_ids, dataset_bundle_id=dataset_bundle_id,
    )

    resolved_run_id = run_id or deterministic_run_id(cfg, nonce=str(time.time_ns()))

    dataset_split_digests = dict(verified_digests)
    dataset_snapshot_paths: dict[str, str] = {}
    if cfg.family is not None and create_snapshot:
        resolved = resolve_training_data_inputs(cfg)
        snapshot_info = create_run_snapshot(resolved_run_id, train_path=resolved.train_path, eval_path=resolved.eval_path)
        dataset_snapshot_paths["train"] = snapshot_info["train"]["path"]
        dataset_split_digests["train"] = snapshot_info["train"]["sha256"]
        if snapshot_info["eval"] is not None:
            dataset_snapshot_paths["validation"] = snapshot_info["eval"]["path"]
            dataset_split_digests["validation"] = snapshot_info["eval"]["sha256"]

    model_id = get_spec(cfg.family).model_id if cfg.family else cfg.model_name
    manifest = TrainingRunManifest(
        run_id=resolved_run_id,
        model_id=model_id,
        base_model=cfg.base_model,
        dataset_manifest_ids=list(dataset_manifest_ids),
        training_config={
            "preset_family": cfg.family,
            "is_legacy_experimental": cfg.is_legacy_experimental,
            "data_format": cfg.data_format,
        },
        hyperparameters={
            "lora_r": cfg.lora.r,
            "lora_alpha": cfg.lora.lora_alpha,
            "lora_dropout": cfg.lora.lora_dropout,
            "target_modules": list(cfg.lora.target_modules),
            "max_seq_length": cfg.max_seq_length,
            "batch_size": cfg.batch_size,
            "gradient_accumulation_steps": cfg.gradient_accumulation_steps,
            "num_epochs": cfg.num_epochs,
            "learning_rate": cfg.learning_rate,
            "lr_scheduler": cfg.lr_scheduler,
            "warmup_ratio": cfg.warmup_ratio,
            "weight_decay": cfg.weight_decay,
            "max_grad_norm": cfg.max_grad_norm,
        },
        seed=42,  # matches finetune.py's hardcoded TrainingArguments/get_peft_model seed
        precision="bf16" if cfg.bf16 else ("fp16" if cfg.fp16 else "fp32"),
        hardware_info=hardware_info,
        base_model_revision=base_model_revision,
        tokenizer_revision=tokenizer_revision,
        dataset_content_digests=dict(verified_digests),
        dataset_split_digests=dataset_split_digests,
        dataset_snapshot_paths=dataset_snapshot_paths,
        dataset_bundle_id=dataset_bundle_id,
        compute_provider=compute_provider,
    )
    manifest.save()
    return manifest


def complete_training_run(
    manifest: TrainingRunManifest,
    *,
    checkpoint_id: str,
    artifact_path: str,
    step_or_epoch: str,
    training_config_summary: str,
    tokenizer_identity: str,
) -> CheckpointRecord:
    """Records a CheckpointRecord for a successfully completed run and
    marks the manifest complete. Phase 21B.2: validate_checkpoint_artifact()
    runs FIRST and raises CheckpointStructureInvalid for a structurally
    incomplete artifact (missing config/tokenizer/weight-shard) -- a
    checkpoint is never registered merely because
    hash_artifact_directory() produced a clean digest for whatever files
    happened to be present. `artifact_checksum` is the deterministic
    multi-file artifact-manifest digest. Registers the checkpoint at
    EXPERIMENTAL lifecycle only -- training completion NEVER implies
    PROMOTABLE/PRODUCTION/AVAILABLE."""
    validate_checkpoint_artifact(Path(artifact_path))
    artifact_manifest = hash_artifact_directory(Path(artifact_path))

    record = CheckpointRecord(
        checkpoint_id=checkpoint_id,
        model_id=manifest.model_id,
        run_id=manifest.run_id,
        step_or_epoch=step_or_epoch,
        base_model=manifest.base_model,
        dataset_manifest_ids=manifest.dataset_manifest_ids,
        training_config_summary=training_config_summary,
        optimizer_state_available=False,
        scheduler_state_available=False,
        tokenizer_identity=tokenizer_identity,
        artifact_path=artifact_path,
        artifact_checksum=artifact_manifest["manifest_digest"],
        availability=ArtifactAvailability.LOCAL.value,
        availability_note=(
            f"Registered immediately after training completion by orca.registry.provenance; "
            f"artifact_checksum is a {len(artifact_manifest['files'])}-file canonical manifest digest; "
            f"structural validity confirmed by validate_checkpoint_artifact() before registration."
        ),
    )
    record.save()

    family = _family_from_model_id(manifest.model_id)
    if family is not None:
        ModelRegistry().register(record, family=family)

    manifest.mark_complete(checkpoint_id)
    return record


def fail_training_run(manifest: TrainingRunManifest, reason: str) -> None:
    """Records a failed run. Never creates a CheckpointRecord on this
    path -- a failure must never leave the registry looking as if a
    checkpoint succeeded when the output is incomplete or absent."""
    manifest.mark_failed(reason)


def _family_from_model_id(model_id: str) -> str | None:
    prefix = "orneur-"
    if not model_id.startswith(prefix):
        return None
    candidate = model_id[len(prefix):]
    return candidate if candidate in MODEL_SPECS else None
