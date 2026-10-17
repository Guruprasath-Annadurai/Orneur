"""
GENESIS Native Learning Engine, Phase 1, Workstream 3: extends the
existing, already-audited checkpoint infrastructure
(`orca.genesis.training.primitives.TrainingState` +
`orca.genesis.training.checkpoint_integrity`'s content-hash manifest
boundary) with every additional field a REAL training run's exact
resumption needs that those two modules don't already carry: scheduler
configuration (the LR schedule here is a pure function of step, per
`orca.genesis.training.primitives.cosine_warmup_lr` -- its "state" is
therefore its CONFIG, bound explicitly below so a resume can never
silently apply a different schedule), the gradient-accumulation
microbatch position, the dataset sampler's position, a training-config
fingerprint, and the dataset/tokenizer identity the run was validated
against.

Strictly additive, matching this codebase's own established pattern
(Sprint 2 Workstream B added `checkpoint_integrity.py` on top of
`primitives.py` without modifying it): this module does not alter
`TrainingState`, `save_training_state`, or `checkpoint_integrity.py`'s
own functions. It wraps a `TrainingState` with the extra fields, and
reuses `save_verified_training_state`/`load_verified_training_state`'s
content-hash trust boundary unchanged for the inner, model/optimizer
portion of the state.

**Exact resume-equivalence, as a fail-closed contract, not a best-effort
one**: `ResumableCheckpoint.restore()` raises
`ResumeEquivalenceError` -- never silently proceeds with a partial or
best-guess restoration -- if the live `TrainingStepConfig`/model config
fingerprint, dataset manifest id, or tokenizer digest supplied at resume
time do not EXACTLY match what was recorded at save time. Per this
phase's explicit instruction ("if a state cannot be restored safely,
fail rather than claiming exact resumption"), there is no partial-resume
mode."""
from __future__ import annotations

import fcntl
import hashlib
import json
import os
import tempfile
from dataclasses import asdict, dataclass
from pathlib import Path

from orca.config import _mkdir_owner_only
from orca.genesis.training.checkpoint_integrity import ChecksumMismatchError, _sha256_of_file
from orca.genesis.training.primitives import TrainingState, load_training_state, save_training_state

RESUMABLE_SCHEMA_VERSION = "genesis-resumable-checkpoint/1"


class ResumeEquivalenceError(Exception):
    """Raised by `ResumableCheckpoint.restore()` whenever the live
    training setup does not EXACTLY match what was recorded at save
    time -- a different model/training config, a different authorized
    dataset, or a different tokenizer. There is no partial-resume path:
    this is always raised before any state is applied to the live
    model/optimizer/sampler, so a caller never ends up half-resumed."""


class ResumableManifestTamperedError(Exception):
    """Raised when the resumable sidecar manifest's own recorded fields
    (config fingerprint, dataset/tokenizer identity, sampler position,
    accumulation position) do not match a fresh recomputation, or when
    the inner checkpoint's content hash fails -- mirrors
    `checkpoint_integrity.py`'s own `ChecksumMismatchError` pattern for
    this module's additional, outer layer of state."""


def compute_config_fingerprint(*objs: object) -> str:
    """A single, deterministic SHA-256 over any number of JSON-
    serializable config objects (dataclasses, via `asdict`, or plain
    dicts) -- used to bind BOTH the model config and the
    `TrainingStepConfig` (including its embedded `OptimizerConfig`) into
    one fingerprint. Field order within each object does not affect the
    result (`sort_keys=True`); the ORDER of `objs` passed in does --
    callers must pass them in a fixed, documented order (model config
    first, then training-step config, by this module's own convention)."""
    parts = []
    for obj in objs:
        if hasattr(obj, "__dataclass_fields__"):
            obj = asdict(obj)
        parts.append(json.dumps(obj, sort_keys=True, default=str))
    canonical = "␟".join(parts)  # a control character, never legitimately present in JSON, joins parts unambiguously
    return hashlib.sha256(canonical.encode("utf-8")).hexdigest()


@dataclass(frozen=True)
class DatasetIdentity:
    """The dataset/tokenizer identity a training run was validated
    against -- bound into the resumable manifest so a resume can detect
    "this is a different dataset or tokenizer than the run that produced
    this checkpoint," which neither `TrainingState` nor
    `CheckpointManifest` tracks today."""
    dataset_manifest_id: str
    dataset_content_digest: str
    tokenizer_digest: str


@dataclass(frozen=True)
class ResumableManifest:
    schema_version: str
    inner_checkpoint_sha256: str  # the SAME sha256 checkpoint_integrity.py's own manifest records, re-stated here for this manifest's own self-consistency
    global_step: int
    microbatch_in_cycle: int
    sampler_position: int
    sampler_seed: int
    sampler_num_blocks: int
    config_fingerprint: str
    dataset_identity: DatasetIdentity

    def to_dict(self) -> dict:
        d = asdict(self)
        return d

    @classmethod
    def from_dict(cls, d: dict) -> "ResumableManifest":
        d = dict(d)
        d["dataset_identity"] = DatasetIdentity(**d["dataset_identity"])
        return cls(**d)


def _resumable_manifest_path(checkpoint_path: Path) -> Path:
    return checkpoint_path.with_suffix(checkpoint_path.suffix + ".resumable.json")


def save_resumable_checkpoint(
    *, path: Path, training_state: TrainingState, global_step: int, microbatch_in_cycle: int,
    sampler_position: int, sampler_seed: int, sampler_num_blocks: int,
    config_fingerprint: str, dataset_identity: DatasetIdentity,
) -> ResumableManifest:
    """Saves the inner `TrainingState` via the existing, unmodified
    `save_training_state()` (the same atomic-write/locking discipline
    every other GENESIS checkpoint uses), then writes this module's own
    sidecar manifest recording every field a real resume needs beyond
    what `TrainingState` itself carries. Held under one exclusive lock
    for the full save+hash+manifest sequence, the same discipline
    `save_verified_training_state()` already established, applied here
    to this module's own, additional sidecar file."""
    path = Path(path)
    parent = _mkdir_owner_only(path.parent, parents=True)
    lock_path = parent / f".{path.name}.resumable.lock"
    with open(lock_path, "a+") as lock_file:
        fcntl.flock(lock_file.fileno(), fcntl.LOCK_EX)
        try:
            save_training_state(training_state, path)
            manifest = ResumableManifest(
                schema_version=RESUMABLE_SCHEMA_VERSION,
                inner_checkpoint_sha256=_sha256_of_file(path),
                global_step=global_step, microbatch_in_cycle=microbatch_in_cycle,
                sampler_position=sampler_position, sampler_seed=sampler_seed,
                sampler_num_blocks=sampler_num_blocks, config_fingerprint=config_fingerprint,
                dataset_identity=dataset_identity,
            )
            manifest_path = _resumable_manifest_path(path)
            fd, tmp_str = tempfile.mkstemp(dir=parent, prefix=f".{manifest_path.name}.tmp-")
            tmp = Path(tmp_str)
            try:
                with os.fdopen(fd, "w") as f:
                    f.write(json.dumps(manifest.to_dict()))
                    f.flush()
                    os.fsync(f.fileno())
                tmp.chmod(0o600)
                os.replace(tmp, manifest_path)
            except BaseException:
                tmp.unlink(missing_ok=True)
                raise
            return manifest
        finally:
            fcntl.flock(lock_file.fileno(), fcntl.LOCK_UN)


@dataclass
class RestoredRun:
    """Everything `TrainingStepEngine` + `ReproducibleSampler` need to
    continue EXACTLY where a prior run stopped -- the caller is
    responsible for constructing a fresh `TrainingStepEngine`/
    `ReproducibleSampler` and applying these fields to them (this module
    does not import `learning_step.py`/`loader.py` itself, so it gains
    no dependency on the exact engine/sampler class shapes -- only on
    the plain data those classes expose)."""
    training_state: TrainingState
    global_step: int
    microbatch_in_cycle: int
    sampler_position: int


def restore_resumable_checkpoint(
    *, path: Path, expected_config_fingerprint: str, expected_dataset_identity: DatasetIdentity,
    expected_sampler_seed: int, expected_sampler_num_blocks: int,
) -> RestoredRun:
    """The trusted, fail-closed restore boundary. Verifies, IN ORDER,
    before applying anything:
    1. The resumable manifest exists and its own `schema_version` is
       recognized.
    2. The inner checkpoint's live content hash matches the manifest's
       recorded `inner_checkpoint_sha256` (content-integrity, the same
       class of check `checkpoint_integrity.py` already performs for its
       own manifest -- re-verified here independently since this is a
       different manifest file).
    3. `config_fingerprint`, `dataset_identity`, `sampler_seed`, and
       `sampler_num_blocks` all EXACTLY match what the caller supplies
       as the live, current setup -- any mismatch raises
       `ResumeEquivalenceError` immediately, before `TrainingState`
       itself is even deserialized from disk.

    Only after every check passes does this function call
    `load_training_state()` (the same trusted primitive every other
    GENESIS checkpoint load path uses) and return the restored state."""
    path = Path(path)
    manifest_path = _resumable_manifest_path(path)
    if not manifest_path.exists():
        raise ResumableManifestTamperedError(f"no resumable manifest found at {manifest_path} for checkpoint {path}")
    manifest = ResumableManifest.from_dict(json.loads(manifest_path.read_text()))
    if manifest.schema_version != RESUMABLE_SCHEMA_VERSION:
        raise ResumableManifestTamperedError(
            f"resumable manifest at {manifest_path} declares schema_version={manifest.schema_version!r}, "
            f"but this code only understands {RESUMABLE_SCHEMA_VERSION!r}"
        )
    actual_sha256 = _sha256_of_file(path)
    if actual_sha256 != manifest.inner_checkpoint_sha256:
        raise ChecksumMismatchError(
            f"checkpoint at {path} has sha256 {actual_sha256}, but its resumable manifest at "
            f"{manifest_path} recorded {manifest.inner_checkpoint_sha256} -- refusing to resume from "
            f"content that does not match what was actually saved"
        )

    mismatches = []
    if manifest.config_fingerprint != expected_config_fingerprint:
        mismatches.append("config_fingerprint")
    if manifest.dataset_identity != expected_dataset_identity:
        mismatches.append("dataset_identity")
    if manifest.sampler_seed != expected_sampler_seed:
        mismatches.append("sampler_seed")
    if manifest.sampler_num_blocks != expected_sampler_num_blocks:
        mismatches.append("sampler_num_blocks")
    if mismatches:
        raise ResumeEquivalenceError(
            f"cannot safely resume from {path}: the live setup does not exactly match what this "
            f"checkpoint was saved under -- mismatched field(s): {mismatches}. Exact resumption is "
            f"not possible; this is a fail-closed rejection, not a best-effort partial resume."
        )

    training_state = load_training_state(path)
    return RestoredRun(
        training_state=training_state, global_step=manifest.global_step,
        microbatch_in_cycle=manifest.microbatch_in_cycle, sampler_position=manifest.sampler_position,
    )
