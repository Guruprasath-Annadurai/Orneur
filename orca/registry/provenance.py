"""
Training-run provenance wiring -- the mandatory lifecycle path connecting
TrainingConfig -> TrainingRunManifest -> (training happens) -> CheckpointRecord
-> ModelRegistry.register(). Phase 21B closed the gap where
TrainingRunManifest/CheckpointRecord existed but no real training entry
point ever called them. Phase 21B.1 closes three further material gaps
an independent audit found in that closure:

  (B) "recording a revision is not equivalent to loading that revision"
      -- resolve_pinned_revisions() + the real loader call in
      orca/train/finetune.py now demonstrably receive the exact pinned
      revision, never an unpinned "latest"/"main".
  (C) dataset_manifest_ids being empty/uncorrelated with the actual
      training bytes was accepted as a normal successful state --
      verify_dataset_binding() now requires at least one dataset
      manifest for canonical (family-set) training and, when the
      manifest maps 1:1 to the files actually being trained on,
      cryptographically verifies the on-disk bytes against the
      manifest's recorded digest before any model loading.
  (D) checkpoint identity was "hash the first merged-model file" --
      hash_artifact_directory() now hashes every file under the
      artifact directory into one canonical, deterministic manifest
      digest; changing ANY file changes the checkpoint's identity.

Deliberately CPU-safe and import-light (no unsloth/torch/transformers)
so the full manifest/checkpoint/registry lifecycle -- including every
new fail-closed trust seam -- can be unit-tested without a GPU or the
heavy training dependency stack. See tests/test_training_provenance.py
and orca/train/finetune.py::train() for the real (GPU-only) integration
point.
"""
from __future__ import annotations

import hashlib
import json
import time
from pathlib import Path

from orca.registry.checkpoint import ArtifactAvailability, CheckpointRecord
from orca.registry.dataset_manifest import DatasetManifest, sha256_of_file
from orca.registry.model_registry import ModelRegistry
from orca.registry.model_spec import MODEL_SPECS, get_spec, require_pinned_revision
from orca.registry.training_run import TrainingRunManifest
from orca.train.config import TrainingConfig, validate_training_identity


class DatasetBindingInvalid(ValueError):
    """A canonical training run's declared dataset manifest(s) could not
    be verified against the actual bytes about to be trained on."""


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
    either is unpinned (see model_spec.require_pinned_revision(), which
    this delegates to). For a generic (family=None) experimental
    config, returns (None, None): there is no canonical ModelSpec to
    pin against for a deliberately non-canonical run -- an explicit,
    narrow exception, not a silent default that could also apply to
    canonical training."""
    if cfg.family is None:
        return None, None
    return require_pinned_revision(cfg.family)


def verify_dataset_binding(
    cfg: TrainingConfig, *, dataset_manifest_ids: list[str],
) -> dict[str, str]:
    """Fail-closed dataset provenance: a canonical (family-set) training
    run MUST declare at least one dataset manifest -- an empty list is
    no longer accepted as a normal successful state. Every declared
    manifest must actually exist (raises DatasetBindingInvalid if not).
    When exactly one manifest is declared AND cfg.train_file/eval_file
    are set, the on-disk files are re-hashed and compared against that
    manifest's own recorded checksums -- a mismatch (wrong file,
    modified data, wrong split) raises DatasetBindingInvalid before any
    model loading occurs. Returns {dataset_manifest_id: verified_sha256}
    for every manifest whose content was actually cryptographically
    verified (not merely declared) -- callers must not treat an entry's
    ABSENCE from this dict as "verified"; see the multi-manifest note
    below.

    Known scope limitation (recorded honestly, not silently glossed
    over): when MULTIPLE dataset manifests are declared for one
    combined train/eval file (e.g. v1 + v2 concatenated), this function
    verifies that every declared manifest exists but cannot yet verify
    the COMBINED file's bytes against per-source manifests -- that
    would require a dedicated "combined dataset" manifest concept that
    does not exist yet. Single-manifest verification is fully
    cryptographic; multi-manifest verification is existence-only.
    """
    if cfg.family is not None and not dataset_manifest_ids:
        raise DatasetBindingInvalid(
            f"Canonical family training (family={cfg.family!r}) requires at least one "
            "dataset_manifest_id -- refusing to train with no declared dataset provenance."
        )

    verified_digests: dict[str, str] = {}
    manifests: list[DatasetManifest] = []
    for dataset_manifest_id in dataset_manifest_ids:
        dataset_id, _, version = dataset_manifest_id.rpartition("-")
        if not dataset_id or not version:
            raise DatasetBindingInvalid(
                f"dataset_manifest_id {dataset_manifest_id!r} is not in '<dataset_id>-<version>' form"
            )
        try:
            manifest = DatasetManifest.load(dataset_id, version)
        except FileNotFoundError as exc:
            raise DatasetBindingInvalid(f"No dataset manifest found for {dataset_manifest_id!r}") from exc
        manifests.append(manifest)

    if len(manifests) == 1 and cfg.train_file and cfg.eval_file:
        manifest = manifests[0]
        train_path, eval_path = Path(cfg.train_file), Path(cfg.eval_file)
        if not train_path.exists():
            raise DatasetBindingInvalid(f"Declared training file does not exist: {train_path}")
        if not eval_path.exists():
            raise DatasetBindingInvalid(f"Declared eval file does not exist: {eval_path}")
        ok, msg = manifest.verify_against_files(train_path, eval_path)
        if not ok:
            raise DatasetBindingInvalid(
                f"Dataset {dataset_manifest_ids[0]!r} failed binding verification: {msg}"
            )
        verified_digests[dataset_manifest_ids[0]] = manifest.train_checksum

    return verified_digests


def hash_artifact_directory(path: Path) -> dict:
    """Deterministic, multi-file checkpoint-artifact identity (replaces
    the prior "hash the first merged-model file" logic). Enumerates
    every file under `path` (sorted by relative path for determinism --
    never filesystem traversal order, never mtimes), records
    {path, size, sha256} for each, then hashes the canonical JSON of
    that file list. Changing ANY required file's content, adding a
    file, or removing a file changes the resulting `manifest_digest`.
    Supports multi-shard checkpoints (e.g. `model-00001-of-00002.
    safetensors`) with no special-casing -- every file under the
    directory is covered uniformly."""
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
    compute_provider: str | None = None,
) -> TrainingRunManifest:
    """Creates and PERSISTS a TrainingRunManifest BEFORE any expensive
    training work begins -- the mandatory first step of the real
    training path. Fails closed via, in order: (1) TrainingConfig's own
    validate_training_identity() (never a manually-overridden base
    model on a canonical family, never base_model=None); (2)
    resolve_pinned_revisions() (never an unpinned revision for
    canonical training); (3) verify_dataset_binding() (never an empty
    or unverifiable dataset declaration for canonical training)."""
    validate_training_identity(cfg)
    base_model_revision, tokenizer_revision = resolve_pinned_revisions(cfg)
    dataset_content_digests = verify_dataset_binding(cfg, dataset_manifest_ids=dataset_manifest_ids)

    resolved_run_id = run_id or deterministic_run_id(cfg, nonce=str(time.time_ns()))
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
        dataset_content_digests=dataset_content_digests,
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
    marks the manifest complete. `artifact_checksum` is now the
    deterministic multi-file artifact-manifest digest from
    hash_artifact_directory(artifact_path), never a single file's hash.
    Registers the checkpoint at EXPERIMENTAL lifecycle only
    (ModelRegistry.register()'s own default) -- training completion
    NEVER implies PROMOTABLE/PRODUCTION/AVAILABLE; those remain later,
    separately evidence-gated transitions via ModelRegistry.promote(),
    which itself refuses without a passing evaluation report."""
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
            f"artifact_checksum is a {len(artifact_manifest['files'])}-file canonical manifest digest."
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
