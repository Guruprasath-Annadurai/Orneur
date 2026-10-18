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
one**: `restore_resumable_checkpoint()` raises
`ResumeEquivalenceError` -- never silently proceeds with a partial or
best-guess restoration -- if the live `TrainingStepConfig`/model config
fingerprint, dataset manifest id, or tokenizer digest supplied at resume
time do not EXACTLY match what was recorded at save time. Per this
phase's explicit instruction ("if a state cannot be restored safely,
fail rather than claiming exact resumption"), there is no partial-resume
mode.

## Antigravity Audit #074 remediation

### AUDIT-P0-03 (partial-accumulation resume divergence)
Independently reproduced before this fix: `TrainingState.capture()`
records `model.state_dict()`/`optimizer.state_dict()` only -- it does
NOT, and (short of a much larger, independently-testable redesign)
cannot cheaply, serialize the LIVE, in-flight `p.grad` buffers a
partially-completed accumulation cycle has accumulated, nor
`TrainingStepEngine`'s own private `_accum_loss_sum` running total.
Saving mid-cycle (`microbatch_in_cycle > 0`) and restoring into a fresh
engine therefore silently discards those in-flight gradients -- the
restored run's very next `optimizer.step()` updates parameters using
ONLY whatever microbatch happens to run next, not the full accumulated
cycle the uninterrupted run would have used. Measured directly: every
parameter tensor diverged, by more than `3e-4` max absolute difference,
after exactly one post-resume step.

**Chosen remediation: Option A (fail closed), not Option B (serialize
gradient buffers).** `save_resumable_checkpoint()` now REQUIRES
`microbatch_in_cycle == 0` and raises `MidAccumulationCheckpointError`
otherwise -- a checkpoint may only ever be taken at a genuine optimizer-
step boundary, where "the full state needed to resume" and "the state
this module actually serializes" are, by construction, the same thing.
Chosen over gradient-buffer serialization because: (a) it requires no
new, separately-fragile serialization format for raw, usually-sizable
gradient tensors; (b) it does not need to reason about restoring
`torch.autograd`'s own internal graph bookkeeping, which `p.grad`
snapshots alone do not fully capture in every PyTorch version; (c) it
is trivially, independently testable (the boundary is a single integer
comparison), matching this phase's own stated preference for the "most
robust, independently testable" choice. The cost is real and stated
plainly: a caller who checkpoints only at `grad_accum_steps` boundaries
loses, at most, the in-flight microbatches of the CURRENT cycle on an
interruption -- the same, already-accepted "a crash loses at most one
batch's worth of work" trade-off this codebase's own data pipeline
(`orca.genesis.data.pipeline`) already makes for an analogous reason.

### AUDIT-P0-04 (sidecar manifest integrity)
Independently reproduced before this fix: `restore_resumable_checkpoint()`
previously verified the INNER checkpoint's content hash, and the
resume-EQUIVALENCE fields (config fingerprint, dataset identity, sampler
seed/block-count) against the CALLER's live expectations -- but never
validated `global_step`, `sampler_position`, or `microbatch_in_cycle`
against anything at all. A plaintext edit of the sidecar `.resumable.json`
file (e.g. `global_step: 10 -> 999999`) was silently accepted.

**Remediation, two independent layers, neither alone sufficient on its
own and neither claiming founder/grant signing authority (none exists
to invoke)**:
1. **Cross-consistency with the hash-protected inner body** (free,
   requires no new key): `restore_resumable_checkpoint()` now loads the
   inner `TrainingState` BEFORE trusting the sidecar's `global_step`,
   and raises `ResumableManifestTamperedError` if they disagree. The
   inner checkpoint's own content hash (already, independently verified
   by `checkpoint_integrity.py`'s own trust boundary) makes `training_
   state.step` a genuine, tamper-evident ground truth to check against.
2. **A keyed integrity tag over every sidecar field** (`sampler_position`
   and `microbatch_in_cycle` have no equivalent ground truth inside the
   inner body to check against, so layer 1 alone cannot cover them):
   `save_resumable_checkpoint()`/`restore_resumable_checkpoint()` now
   both REQUIRE an explicit `integrity_key: bytes` parameter, and the
   sidecar carries an HMAC-SHA256 tag computed over every
   resumption-relevant field with that key. This is explicitly NOT a
   fabricated founder key, grant signature, or acceptance record -- it
   is an ordinary, caller-supplied integrity key this module requires
   and documents as the CALLER'S responsibility to generate (e.g.
   `os.urandom(32)`) and keep OUTSIDE the checkpoint directory (in the
   orchestrating process's own memory, or wherever that process already
   keeps its other secrets). A bare, unkeyed self-recomputed SHA-256
   (the auditor's own named example of what NOT to do) provides zero
   protection against a local attacker who can simply recompute and
   rewrite it after editing a field -- an HMAC genuinely cannot be
   forged by anyone who does not hold `integrity_key`, which is never
   itself written into the checkpoint directory by this module. If an
   attacker obtains BOTH the checkpoint files AND this key, no integrity
   guarantee holds here, and this module makes no claim otherwise."""
from __future__ import annotations

import fcntl
import hashlib
import hmac
import json
import os
import tempfile
from dataclasses import asdict, dataclass
from pathlib import Path

from orca.config import _mkdir_owner_only
from orca.genesis.training.checkpoint_integrity import ChecksumMismatchError, _sha256_of_file
from orca.genesis.training.primitives import TrainingState, load_training_state, save_training_state

RESUMABLE_SCHEMA_VERSION = "genesis-resumable-checkpoint/2"  # Audit #074 P0-04: now includes an HMAC integrity tag


class ResumeEquivalenceError(Exception):
    """Raised by `restore_resumable_checkpoint()` whenever the live
    training setup does not EXACTLY match what was recorded at save
    time -- a different model/training config, a different authorized
    dataset, or a different tokenizer. There is no partial-resume path:
    this is always raised before any state is applied to the live
    model/optimizer/sampler, so a caller never ends up half-resumed."""


class ResumableManifestTamperedError(Exception):
    """Raised when the resumable sidecar manifest's own recorded fields
    (config fingerprint, dataset/tokenizer identity, sampler position,
    accumulation position) do not match a fresh recomputation, when the
    HMAC integrity tag does not match (Audit #074 P0-04), or when the
    sidecar's `global_step` disagrees with the inner, hash-protected
    `TrainingState.step` it is supposed to describe -- mirrors
    `checkpoint_integrity.py`'s own `ChecksumMismatchError` pattern for
    this module's additional, outer layer of state."""


class MidAccumulationCheckpointError(Exception):
    """Raised by `save_resumable_checkpoint()` when `microbatch_in_cycle
    != 0` (Audit #074 P0-03). A checkpoint may only be taken at a
    genuine optimizer-step boundary -- see this module's own docstring
    for why gradient-buffer serialization was rejected in favor of this
    fail-closed boundary."""


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


_TAGGED_FIELDS = (
    "schema_version", "inner_checkpoint_sha256", "global_step", "microbatch_in_cycle",
    "sampler_position", "sampler_seed", "sampler_num_blocks", "config_fingerprint", "dataset_identity",
)


def _compute_integrity_tag(key: bytes, fields: dict) -> str:
    """AUDIT-P0-04 fix: an HMAC-SHA256 over every resumption-relevant
    sidecar field, canonically serialized (`sort_keys=True`) so field
    order never affects the tag. See the module docstring for why this
    must be KEYED (HMAC), not a bare, attacker-recomputable SHA-256."""
    canonical = json.dumps(fields, sort_keys=True, default=str).encode("utf-8")
    return hmac.new(key, canonical, hashlib.sha256).hexdigest()


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
    integrity_tag: str  # Audit #074 P0-04: HMAC-SHA256 over every field above, keyed by the caller's integrity_key

    def _tagged_fields_dict(self) -> dict:
        d = asdict(self)
        d.pop("integrity_tag")
        return d

    def to_dict(self) -> dict:
        return asdict(self)

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
    config_fingerprint: str, dataset_identity: DatasetIdentity, integrity_key: bytes,
) -> ResumableManifest:
    """Saves the inner `TrainingState` via the existing, unmodified
    `save_training_state()` (the same atomic-write/locking discipline
    every other GENESIS checkpoint uses), then writes this module's own
    HMAC-tagged sidecar manifest recording every field a real resume
    needs beyond what `TrainingState` itself carries. Held under one
    exclusive lock for the full save+hash+manifest sequence, the same
    discipline `save_verified_training_state()` already established,
    applied here to this module's own, additional sidecar file.

    AUDIT-P0-03 fix: raises `MidAccumulationCheckpointError` if
    `microbatch_in_cycle != 0` -- see the module docstring for why a
    checkpoint may only be taken at a genuine optimizer-step boundary.

    `integrity_key` must be a real secret (e.g. `os.urandom(32)`) the
    CALLER generates and keeps outside the checkpoint directory -- see
    the module docstring's AUDIT-P0-04 section for exactly what this
    does and does not protect against."""
    if microbatch_in_cycle != 0:
        raise MidAccumulationCheckpointError(
            f"cannot save a resumable checkpoint at microbatch_in_cycle={microbatch_in_cycle} -- a checkpoint "
            f"may only be taken at a genuine optimizer-step boundary (microbatch_in_cycle == 0), since the "
            f"in-flight accumulated gradients of a partial cycle are not serialized by this module (see its "
            f"own docstring, AUDIT-P0-03, for why). Drain the current accumulation cycle to completion before "
            f"checkpointing, or discard it and resume this cycle from scratch."
        )
    if not integrity_key:
        raise ValueError("integrity_key is required and must be non-empty -- see this module's own docstring, AUDIT-P0-04")

    path = Path(path)
    parent = _mkdir_owner_only(path.parent, parents=True)
    lock_path = parent / f".{path.name}.resumable.lock"
    with open(lock_path, "a+") as lock_file:
        fcntl.flock(lock_file.fileno(), fcntl.LOCK_EX)
        try:
            save_training_state(training_state, path)
            tagged_fields = {
                "schema_version": RESUMABLE_SCHEMA_VERSION, "inner_checkpoint_sha256": _sha256_of_file(path),
                "global_step": global_step, "microbatch_in_cycle": microbatch_in_cycle,
                "sampler_position": sampler_position, "sampler_seed": sampler_seed,
                "sampler_num_blocks": sampler_num_blocks, "config_fingerprint": config_fingerprint,
                "dataset_identity": asdict(dataset_identity),
            }
            manifest = ResumableManifest(
                **{k: v for k, v in tagged_fields.items() if k != "dataset_identity"},
                dataset_identity=dataset_identity,
                integrity_tag=_compute_integrity_tag(integrity_key, tagged_fields),
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
    expected_sampler_seed: int, expected_sampler_num_blocks: int, integrity_key: bytes,
) -> RestoredRun:
    """The trusted, fail-closed restore boundary. Verifies, IN ORDER,
    before applying anything:
    1. The resumable manifest exists and its own `schema_version` is
       recognized.
    2. **(AUDIT-P0-04)** The HMAC-SHA256 integrity tag over every
       sidecar field matches, recomputed with the caller's own
       `integrity_key` -- any single-field edit (including `global_step`,
       `sampler_position`, or `microbatch_in_cycle`, none of which were
       previously validated at all) invalidates the tag and raises
       `ResumableManifestTamperedError`.
    3. The inner checkpoint's live content hash matches the manifest's
       recorded `inner_checkpoint_sha256` (content-integrity, the same
       class of check `checkpoint_integrity.py` already performs for its
       own manifest -- re-verified here independently since this is a
       different manifest file).
    4. `config_fingerprint`, `dataset_identity`, `sampler_seed`, and
       `sampler_num_blocks` all EXACTLY match what the caller supplies
       as the live, current setup -- any mismatch raises
       `ResumeEquivalenceError` immediately, before `TrainingState`
       itself is even deserialized from disk.
    5. **(AUDIT-P0-04)** After loading, the inner, hash-protected
       `TrainingState.step` is cross-checked against the sidecar's own
       `global_step` -- a second, independent consistency check that
       does not depend on `integrity_key` at all, since `step` lives
       inside the ALREADY content-hash-verified checkpoint body."""
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

    expected_tag = _compute_integrity_tag(integrity_key, manifest._tagged_fields_dict())
    if not hmac.compare_digest(expected_tag, manifest.integrity_tag):
        raise ResumableManifestTamperedError(
            f"resumable manifest at {manifest_path} failed its HMAC integrity check -- one or more sidecar "
            f"fields (global_step, microbatch_in_cycle, sampler_position, config_fingerprint, dataset_identity, "
            f"inner_checkpoint_sha256) were modified since this checkpoint was saved, or the wrong integrity_key "
            f"was supplied. Refusing to trust any field in this manifest."
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
    if training_state.step != manifest.global_step:
        raise ResumableManifestTamperedError(
            f"resumable manifest at {manifest_path} claims global_step={manifest.global_step}, but the "
            f"inner, content-hash-verified checkpoint's own step is {training_state.step} -- these must be "
            f"identical; refusing to resume from an internally inconsistent checkpoint"
        )
    return RestoredRun(
        training_state=training_state, global_step=manifest.global_step,
        microbatch_in_cycle=manifest.microbatch_in_cycle, sampler_position=manifest.sampler_position,
    )
