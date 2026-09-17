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

Phase 21B.2.1 closes the remaining seams a further independent audit
found in the 21B.2 closure itself:

  - BUNDLE NOT WIRED THROUGH THE REAL ENTRYPOINT: start_training_run()
    accepted dataset_bundle_id, but orca.train.finetune.train() (the
    real public training path) had no parameter to forward one --
    multi-manifest canonical training could never actually reach the
    DatasetBundleManifest path except via direct (test-only) calls to
    start_training_run(). train() now accepts and forwards
    dataset_bundle_id -- no alternative or hidden path.
  - BUNDLE LINEAGE NOT ENFORCED: verify_dataset_binding() checked only
    that a bundle's source-manifest ID *set* matched the declared
    dataset_manifest_ids -- never that each source DatasetManifest's
    CURRENT content checksums still matched what the bundle recorded as
    that source's lineage at bundle-build time. A source manifest could
    be replaced/mutated under the same ID without invalidating the
    bundle's lineage claim. _verify_bundle_source_lineage() now
    re-verifies every lineage entry's checksums against the live source
    manifest, and rejects duplicate/malformed lineage entries.
  - CHECKPOINT IDENTITY/INTEGRITY ALGORITHM MISMATCH: hash_artifact_directory()
    (registration-time identity) lived only here, while
    CheckpointRecord.verify_integrity() (orca.registry.checkpoint) still
    called sha256_of_file() on what is, for every merged checkpoint this
    project produces, a DIRECTORY -- registration and reverification
    disagreed about the very algorithm used to prove integrity.
    hash_artifact_directory() now lives in orca.registry.checkpoint (the
    layer both this module and CheckpointRecord already depend on) and
    is imported here, not redefined -- there is exactly one canonical
    directory-checkpoint digest algorithm, and verify_integrity() now
    branches explicitly on path.is_dir() to use it.
  - SYMLINK ESCAPE: validate_checkpoint_artifact()'s shard-index checks
    already resolved paths and rejected escapes, but non-index files
    (config.json, tokenizer artifacts, an unsharded weight file) were
    still accepted via Path.is_file(), which follows symlinks. Both
    validate_checkpoint_artifact() and hash_artifact_directory() now
    apply one fail-closed policy: ANY symlink anywhere in a canonical
    checkpoint artifact directory is rejected outright, so the validator
    and the hasher can never disagree about which bytes are trusted.

Phase 21B.2.2 closes one remaining seam a further independent audit
found in the 21B.2.1 closure:

  - VERIFIED SOURCE -> SNAPSHOT RACE: verify_dataset_binding() computed
    a verified digest for the SOURCE file; create_run_snapshot() then
    independently copied and re-hashed that same source file, with
    nothing binding the snapshot's digest to the digest that was
    actually verified. A source mutated in the window between those two
    steps would be silently copied into the snapshot, re-hashed, and
    recorded as if it were the verified bytes -- verify_run_snapshot()
    later would only ever compare the snapshot against ITSELF (a digest
    computed from the already-mutated copy), never against what
    verify_dataset_binding() actually verified. create_run_snapshot()
    now takes expected_split_digests (the just-verified digests) and
    REQUIRES the freshly-computed snapshot digest to equal them --
    mismatch deletes the snapshot directory and raises
    SnapshotIntegrityError before any TrainingRunManifest is
    constructed or saved. Additionally: canonical (family=None) training
    could previously pass create_snapshot=False and obtain a "canonical"
    manifest with verified digests but no protected snapshot at all --
    now rejected outright for family-set configs; and
    orca.train.finetune._train_impl() no longer infers "no snapshot ==
    generic experiment" from absence alone -- a canonical manifest
    missing snapshot paths fails closed as defense in depth, and
    snapshot verification (plus dataset loading) is now ordered BEFORE
    the expensive base-model load, not after.

Phase 21B.3 closes two carry-forward trust hardenings identified
alongside the Genesis intelligence-qualification work (dataset/eval
suite build-out -- see docs/orneur/phase-21/GENESIS_PRETRAINING_QUALIFICATION.md):

  - SINGLE-MANIFEST + BUNDLE-ID DRIFT: verify_dataset_binding()'s
    single-manifest path returned early without checking whether a
    dataset_bundle_id had also been supplied -- since
    start_training_run() forwards dataset_bundle_id to the
    TrainingRunManifest independently of what verify_dataset_binding()
    returns, a run manifest could record a bundle_id that was never
    actually verified against anything. Now rejected outright:
    dataset_bundle_id must be None on the single-manifest path.
    Duplicate dataset_manifest_ids are also now rejected -- a
    provenance record must never name an artifact more than once.
  - PRACTICAL SNAPSHOT READ-WINDOW HARDENING: create_run_snapshot() now
    chmod's the snapshot files read-only (0o444) and the snapshot
    directory read+execute-only (0o555) after successful verification,
    and orca.train.finetune._train_impl() now re-verifies the snapshot
    digest a SECOND time immediately after load_dataset() returns (not
    only before it, as Phase 21B.2 established) -- both pre-load and
    post-load digests must equal the manifest's recorded expectation.
    Threat model stated honestly: filesystem permissions and digest
    re-checks protect against accidental/concurrent mutation; neither
    claims to defeat a malicious actor with root/filesystem-owner
    access, who could chmod a file back to writable before modifying it
    -- the digest re-verification (not the permissions) is what
    actually catches that case.

Deliberately CPU-safe and import-light (no unsloth/torch/transformers)
so the full manifest/checkpoint/registry lifecycle -- including every
trust seam above -- can be unit-tested without a GPU or the heavy
training dependency stack. See tests/test_training_provenance.py and
orca/train/finetune.py::train() for the real (GPU-only) integration
point.
"""
from __future__ import annotations

import hashlib
import os
import re
import shutil
import stat
import time
from pathlib import Path

from orca.config import ORCA_HOME
from orca.registry.checkpoint import (
    ArtifactAvailability,
    CheckpointRecord,
    hash_artifact_directory,
    validate_checkpoint_artifact,
)
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

    if len(dataset_manifest_ids) != len(set(dataset_manifest_ids)):
        dupes = sorted({m for m in dataset_manifest_ids if dataset_manifest_ids.count(m) > 1})
        raise DatasetBindingInvalid(
            f"dataset_manifest_ids contains duplicate entries: {dupes} -- a provenance record must "
            "never name an artifact more than once or claim participation that isn't distinct."
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
        if dataset_bundle_id is not None:
            # Phase 21B.3 (§3A) carry-forward hardening: a single-manifest
            # canonical run has no bundle to verify against -- a bundle_id
            # supplied here would never be checked by anything below, yet
            # a caller could still have it recorded onto the
            # TrainingRunManifest (start_training_run() passes
            # dataset_bundle_id straight through independently of this
            # function's return value). That is exactly the "provenance
            # record names an artifact that did not participate in
            # verification" defect this closes. No current contract
            # defines a meaningful bundle around a single source, so this
            # is unconditionally rejected rather than silently ignored.
            raise DatasetBindingInvalid(
                f"dataset_bundle_id={dataset_bundle_id!r} was supplied alongside exactly one "
                f"dataset_manifest_id ({dataset_manifest_ids[0]!r}) -- a single-manifest canonical "
                "run must not name a bundle, since no bundle verification occurs on this path. "
                "Pass dataset_bundle_id=None for single-manifest training."
            )
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
    # a DatasetBundleManifest binding the exact combined bytes, AND a
    # verified per-source content lineage (see _verify_bundle_source_lineage()),
    # is required.
    source_manifests_by_id: dict[str, DatasetManifest] = {}
    for dataset_manifest_id in dataset_manifest_ids:
        dataset_id, _, version = dataset_manifest_id.rpartition("-")
        if not dataset_id or not version:
            raise DatasetBindingInvalid(
                f"dataset_manifest_id {dataset_manifest_id!r} is not in '<dataset_id>-<version>' form"
            )
        try:
            source_manifests_by_id[dataset_manifest_id] = DatasetManifest.load(dataset_id, version)
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

    _verify_bundle_source_lineage(bundle, dataset_manifest_ids, source_manifests_by_id)
    ok, msg = bundle.verify_against_files(resolved.train_path, resolved.eval_path)
    if not ok:
        raise DatasetBindingInvalid(f"Dataset bundle {dataset_bundle_id!r} failed binding verification: {msg}")
    return {"train": bundle.train_checksum, "validation": bundle.eval_checksum}


_SHA256_HEX_RE = re.compile(r"^[0-9a-f]{64}$")


def _verify_bundle_source_lineage(
    bundle: DatasetBundleManifest,
    dataset_manifest_ids: list[str],
    source_manifests_by_id: dict[str, DatasetManifest],
) -> None:
    """Phase 21B.2.1 closure: verify_dataset_binding() previously checked
    only that the SET of dataset_manifest_ids a bundle's own lineage
    named matched the SET declared for this run -- it never checked that
    the CURRENTLY loaded source DatasetManifest for each id still has the
    same content digests the bundle recorded when it was built (the
    SourceManifestLineage.train_checksum/eval_checksum fields). That left
    a bundle's lineage claim spoofable: replace or mutate a source
    manifest file under the same dataset_id-version on disk after the
    bundle was built, and nothing would ever notice the bundle's lineage
    claim no longer reflects reality -- the bundle's OWN combined-file
    checksum (verify_against_files()) still passes, since that check is
    only about the combined bytes, not about what built them. This
    function binds source-manifest IDENTITY, not just combined bytes:
    every SourceManifestLineage entry's checksums must still match its
    named DatasetManifest's CURRENT checksums, with no duplicate,
    missing, or unexpected lineage entries, and no malformed digest
    values (must be a real 64-hex-char sha256)."""
    lineage_ids = [s.dataset_manifest_id for s in bundle.source_manifests]
    if len(lineage_ids) != len(set(lineage_ids)):
        dupes = sorted({i for i in lineage_ids if lineage_ids.count(i) > 1})
        raise DatasetBindingInvalid(
            f"Dataset bundle {bundle.bundle_id}-{bundle.version}'s source lineage has duplicate "
            f"entries for: {dupes} -- each source dataset_manifest_id must appear at most once."
        )

    if set(lineage_ids) != set(dataset_manifest_ids):
        raise DatasetBindingInvalid(
            f"Dataset bundle {bundle.bundle_id}-{bundle.version}'s source lineage {sorted(set(lineage_ids))} "
            f"does not match the declared dataset_manifest_ids {sorted(dataset_manifest_ids)}"
        )

    for source in bundle.source_manifests:
        for field_name, checksum in (
            ("train_checksum", source.train_checksum),
            ("eval_checksum", source.eval_checksum),
        ):
            if not isinstance(checksum, str) or not _SHA256_HEX_RE.match(checksum):
                raise DatasetBindingInvalid(
                    f"Dataset bundle {bundle.bundle_id}-{bundle.version}'s lineage entry for "
                    f"{source.dataset_manifest_id!r} has a malformed {field_name} "
                    f"(must be a 64-character lowercase hex sha256 digest): {checksum!r}"
                )

        current = source_manifests_by_id[source.dataset_manifest_id]
        if current.train_checksum != source.train_checksum:
            raise DatasetBindingInvalid(
                f"Dataset bundle {bundle.bundle_id}-{bundle.version}'s recorded lineage train_checksum "
                f"for {source.dataset_manifest_id!r} ({source.train_checksum}) does not match that source "
                f"manifest's CURRENT train_checksum ({current.train_checksum}) -- the source manifest was "
                f"replaced or mutated after this bundle was built."
            )
        if current.eval_checksum != source.eval_checksum:
            raise DatasetBindingInvalid(
                f"Dataset bundle {bundle.bundle_id}-{bundle.version}'s recorded lineage eval_checksum "
                f"for {source.dataset_manifest_id!r} ({source.eval_checksum}) does not match that source "
                f"manifest's CURRENT eval_checksum ({current.eval_checksum}) -- the source manifest was "
                f"replaced or mutated after this bundle was built."
            )


def create_run_snapshot(
    run_id: str,
    *,
    train_path: Path,
    eval_path: Path | None,
    expected_split_digests: dict[str, str] | None = None,
) -> dict:
    """Closes the TOCTOU window between dataset-binding verification and
    actual training consumption: copies the verified source files into
    a run-scoped, uniquely-named snapshot directory and re-hashes them
    there. The trainer must load ONLY from these snapshot paths, never
    the original (still-mutable) source paths. Returns
    {"train": {"path": str, "sha256": str}, "eval": {...} | None} --
    this structure is what verify_run_snapshot() re-checks immediately
    before load_dataset().

    Phase 21B.2.2: closes a second, narrower TOCTOU window this
    function itself previously left open -- between
    verify_dataset_binding() computing a verified digest for the SOURCE
    file and this function copying that same source file into the
    snapshot, the source could be mutated, and create_run_snapshot()
    would happily hash and record the MUTATED bytes as if they were the
    verified ones (the manifest would then record a "verified" digest
    that was never actually checked against anything). `expected_split_digests`
    (keyed "train"/"validation", matching verify_dataset_binding()'s
    return shape) makes the already-verified source digest the
    EXPECTATION the snapshot must satisfy, not something the snapshot
    can silently overwrite: after copying and re-hashing each split,
    a mismatch against the corresponding expected digest deletes the
    (partial, untrustworthy) snapshot directory and raises
    SnapshotIntegrityError -- the caller (start_training_run()) has not
    yet constructed or saved a TrainingRunManifest at this point, so no
    runnable manifest is ever persisted for a race that was caught here.
    Passing None (the default) skips this check entirely -- used only
    by direct/legacy callers that have no prior verified digest to
    compare against; the real canonical path (start_training_run())
    always passes the just-verified digests.

    Phase 21B.3 (§3B) hardening: once both splits are copied and pass
    digest verification, the snapshot files are chmod'd read-only
    (0o444) and the snapshot directory is chmod'd read+execute-only
    (0o555, i.e. no write bit -- entries cannot be added, removed, or
    renamed) before this function returns. THREAT MODEL, stated
    honestly: this protects against accidental overwrite and ordinary
    concurrent-process mutation of the snapshot after creation. It is
    NOT a claim of cryptographic filesystem immutability and does NOT
    defeat a malicious actor with root/filesystem-owner access, who can
    always chmod a file back to writable before modifying it -- the
    only guarantee against that is the digest re-verification
    (verify_run_snapshot(), now called by orca.train.finetune._train_impl()
    both immediately before AND immediately after load_dataset())."""
    snapshot_dir = RUN_SNAPSHOT_DIR / run_id
    snapshot_dir.mkdir(parents=True, exist_ok=True)

    def _expect(split_key: str) -> str | None:
        return expected_split_digests.get(split_key) if expected_split_digests is not None else None

    try:
        train_snapshot_path = snapshot_dir / "train.jsonl"
        shutil.copyfile(train_path, train_snapshot_path)
        train_sha = sha256_of_file(train_snapshot_path)
        expected_train = _expect("train")
        if expected_train is not None and train_sha != expected_train:
            raise SnapshotIntegrityError(
                f"Run-scoped train snapshot digest ({train_sha}) does not match the previously "
                f"verified source digest ({expected_train}) for run {run_id!r} -- the source file "
                f"was mutated between dataset-binding verification and snapshot creation."
            )
        info: dict = {"train": {"path": str(train_snapshot_path), "sha256": train_sha}}

        if eval_path is not None:
            eval_snapshot_path = snapshot_dir / "eval.jsonl"
            shutil.copyfile(eval_path, eval_snapshot_path)
            eval_sha = sha256_of_file(eval_snapshot_path)
            expected_eval = _expect("validation")
            if expected_eval is not None and eval_sha != expected_eval:
                raise SnapshotIntegrityError(
                    f"Run-scoped validation snapshot digest ({eval_sha}) does not match the "
                    f"previously verified source digest ({expected_eval}) for run {run_id!r} -- the "
                    f"source file was mutated between dataset-binding verification and snapshot "
                    f"creation."
                )
            info["eval"] = {"path": str(eval_snapshot_path), "sha256": eval_sha}
        else:
            info["eval"] = None
    except SnapshotIntegrityError:
        shutil.rmtree(snapshot_dir, ignore_errors=True)
        raise

    _READONLY_FILE = stat.S_IRUSR | stat.S_IRGRP | stat.S_IROTH
    _READONLY_DIR = stat.S_IRUSR | stat.S_IXUSR | stat.S_IRGRP | stat.S_IXGRP | stat.S_IROTH | stat.S_IXOTH
    os.chmod(train_snapshot_path, _READONLY_FILE)
    if eval_path is not None:
        os.chmod(info["eval"]["path"], _READONLY_FILE)
    os.chmod(snapshot_dir, _READONLY_DIR)

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
    validate_training_identity(); (2) canonical create_snapshot=False
    rejection (see below); (3) resolve_pinned_revisions(); (4)
    verify_dataset_binding() (now always against the resolved, real
    consumption paths -- see module docstring); (5), for canonical
    training, create_run_snapshot() copies the verified files into a
    run-scoped snapshot -- passing the just-verified digests as
    expected_split_digests, so the snapshot is bound to what was
    actually verified, not merely re-hashed independently -- and
    records ITS digests as dataset_split_digests -- the exact bytes
    orca.train.finetune will be required to re-verify immediately
    before load_dataset().

    Phase 21B.2.2: `create_snapshot=False` is no longer honored for
    canonical (family-set) training -- a caller could previously obtain
    a fully "canonical" TrainingRunManifest with verified
    dataset_content_digests but NO run-scoped snapshot, silently
    reintroducing the exact TOCTOU window Phase 21B.2 closed (see
    orca.train.finetune._train_impl(), which now also independently
    refuses to fall back to mutable source files for a canonical
    manifest missing snapshot paths, as defense in depth). Only a
    generic (family=None) experimental config may still pass
    create_snapshot=False."""
    validate_training_identity(cfg)
    if cfg.family is not None and not create_snapshot:
        raise SnapshotIntegrityError(
            f"Canonical training (family={cfg.family!r}) requires a verified run-scoped dataset "
            "snapshot -- create_snapshot=False is not permitted for canonical training. Only a "
            "generic (family=None) experimental config may disable the snapshot."
        )
    base_model_revision, tokenizer_revision = resolve_pinned_revisions(cfg)
    verified_digests = verify_dataset_binding(
        cfg, dataset_manifest_ids=dataset_manifest_ids, dataset_bundle_id=dataset_bundle_id,
    )

    resolved_run_id = run_id or deterministic_run_id(cfg, nonce=str(time.time_ns()))

    dataset_split_digests = dict(verified_digests)
    dataset_snapshot_paths: dict[str, str] = {}
    if cfg.family is not None and create_snapshot:
        resolved = resolve_training_data_inputs(cfg)
        snapshot_info = create_run_snapshot(
            resolved_run_id, train_path=resolved.train_path, eval_path=resolved.eval_path,
            expected_split_digests=verified_digests,
        )
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
