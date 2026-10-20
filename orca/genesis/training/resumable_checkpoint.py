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
   guarantee holds here, and this module makes no claim otherwise.

## Antigravity Audit #075 (independent successor requalification) remediation

### Rollback protection
Independently reproduced before this fix: `restore_resumable_checkpoint()`
validated the sidecar's own internal consistency (HMAC, inner-step
cross-check) but never checked a restored checkpoint's `global_step`
against anything OUTSIDE that one checkpoint's own files -- an older,
validly signed checkpoint (step 5) could be restored in place of a
newer one (step 100) and would pass every existing check, since nothing
recorded that step 100 had ever existed.

**Fix**: a small, append-only, HMAC-protected ledger (`_ledger_path()`),
keyed by a caller-supplied `run_id` and stored OUTSIDE the checkpoint's
own directory (under `orca.config.ORCA_HOME`), records the highest
`global_step` ever saved or restored for that run. Both
`save_resumable_checkpoint()` and `restore_resumable_checkpoint()`
monotonically advance it; `restore_resumable_checkpoint()` additionally
REJECTS (`CheckpointRollbackError`) any restore whose `global_step` is
lower than the ledger's current high-water mark.

**Explicitly, honestly NOT claimed -- re-examined and sharpened per the
CTO pre-handoff security directive's own challenge**: this ledger is a
local file, HMAC-protected against FIELD TAMPERING, but it is NOT an
independent, externally-anchored trust root, and the gap is sharper
than "an attacker who also knows the key." The precise attack this
module does NOT prevent: an attacker who, at any earlier point, saved
a COPY of this run's `run_id` ledger file from when it was legitimately
at a lower `highest_global_step` (e.g. by reading it off disk, or from
a backup/snapshot) can later REPLACE the current ledger file with that
OLD copy, together with the matching OLD checkpoint+manifest pair, and
restore both simultaneously. The replayed ledger file's HMAC tag is
STILL VALID -- it was genuinely computed by this same process with
this same `integrity_key` at the time it was first written; replaying
it verbatim requires no knowledge of `integrity_key` at all, only
filesystem write access to both the checkpoint directory and
`ORCA_HOME`'s ledger directory. `test_audit075_simultaneous_old_checkpoint_and_old_ledger_replay_is_not_detected`
in `tests/test_genesis_resumable_checkpoint.py` independently
reproduces this exact scenario and documents that it currently
SUCCEEDS (the restore is accepted) -- recorded here as a known,
unresolved gap, not silently patched over.

Put precisely: this mechanism provides HMAC integrity (a field cannot
be edited in place without detection) and a LOCAL, process-relative
monotonic progress claim (within one continuously-running process's
own view of `run_id`, it will never accept going backward), but it is
NOT an independently anchored anti-rollback authority. The checkpoint
body, its manifest, and the ledger all live under the same filesystem
trust boundary; whoever can write to one can, with enough foresight
(saving old copies in advance), write a self-consistent OLDER triple
back. Genuinely closing this requires a trust anchor OUTSIDE that
filesystem -- a remote append-only service, a hardware monotonic
counter, or any store the training process can append to but cannot
rewrite -- explicitly out of scope here (no paid infrastructure in
this phase) and NOT claimed as closed. `CheckpointRollbackError` only
fires when the CURRENT, un-replayed ledger disagrees with a restore
attempt in the SAME filesystem state; it is real, useful defense-in-
depth against a casual or partial rollback (e.g. restoring an old
checkpoint while the real, current ledger is still in place), but it
is not a substitute for an independent anchor. A FIRST-EVER restore of
a checkpoint (nothing newer ever recorded under that `run_id`) also
cannot be detected as a rollback, by construction -- there is nothing
yet to roll back FROM.

### Weak key custody
Independently reproduced: the prior code only checked `if not
integrity_key`, silently accepting e.g. a 1-byte key. `_require_strong
_integrity_key()` now rejects any `integrity_key` shorter than
`MIN_INTEGRITY_KEY_BYTES` (32 bytes / 256 bits) in both save and
restore, raising `WeakIntegrityKeyError`.

## Antigravity Audit #077 remediation

### Cross-run checkpoint ownership
Independently reproduced before this fix: `restore_resumable_checkpoint()`
never recorded, or checked, WHICH run a checkpoint was originally saved
under -- `run_id` was used only to look up the anti-rollback ledger
(Audit #075), never bound into the checkpoint's own manifest. A
checkpoint saved under one `run_id` could therefore be restored under
an entirely DIFFERENT `run_id` with no explicit authorization at all,
as long as `config_fingerprint`/`dataset_identity` happened to match
(e.g. the same model/dataset, re-authorized under a fresh grant) --
nothing in this module's governance contract declared this an
intended, permitted capability, and nothing required a separately
authorized path for it.

**Fixed**: the manifest now carries `owning_run_id` (the `run_id` the
checkpoint was SAVED under), HMAC-bound exactly like every other
tagged field -- it cannot be forged without `integrity_key`.
`restore_resumable_checkpoint()` now REQUIRES `manifest.owning_run_id
== run_id`, unconditionally; a mismatch raises
`CrossRunCheckpointAccessError`, binding checkpoint ownership to the
verified run. This does not weaken, replace, or bypass the existing
HMAC integrity tag or the anti-rollback ledger check in any way -- it
is an additional, independent check alongside them.

**AUDIT-077 P0-02 update (CTO security remediation directive)**: an
earlier version of this fix added an explicitly named
`allow_cross_run_migration: bool = False` parameter for a genuinely
intended migration. Antigravity's independent requalification found
that, while never exposed over any untrusted worker IPC surface, ANY
direct Python caller (an orchestration script, a test, a future
feature) could bypass run ownership entirely merely by passing that
boolean -- no cryptographic proof of authorization was required or
checked at all. Per the CTO's explicit instruction, that parameter is
now DISABLED on every callable path: passing `allow_cross_run_migration
=True` raises `CrossRunMigrationDisabledError` instead of proceeding.
If genuine cross-run migration is ever required, it needs a SEPARATE,
explicitly designed governance contract -- not reinstated here --
carrying: an authenticated source run, an authenticated target run,
the exact checkpoint digest being migrated, the authorizing principal,
a signed and independently verifiable grant, expiry and revocation
semantics, single-purpose scope (a grant usable for exactly one
migration, not a standing capability), replay resistance, and durable
evidence of the migration having occurred. No such mechanism is
invented, designed in detail, or issued here -- this module simply
refuses the previously-unauthenticated bypass until one exists."""
from __future__ import annotations

import fcntl
import hashlib
import hmac
import json
import os
import tempfile
from dataclasses import asdict, dataclass
from pathlib import Path

import orca.config as orca_config
from orca.config import _dirfd_mkstemp, _mkdir_owner_only, _open_dir_no_symlinks
from orca.genesis.training.checkpoint_integrity import ChecksumMismatchError
from orca.genesis.training.primitives import TrainingState, load_training_state, save_training_state

RESUMABLE_SCHEMA_VERSION = "genesis-resumable-checkpoint/3"  # AUDIT-077 Phase 2: now also binds owning_run_id (see CrossRunCheckpointAccessError)
LEDGER_SCHEMA_VERSION = "genesis-checkpoint-ledger/1"  # Audit #075 P0-04: anti-rollback monotonic ledger
MIN_INTEGRITY_KEY_BYTES = 32  # Audit #075: minimum acceptable HMAC key strength (256 bits)


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


class CheckpointRollbackError(Exception):
    """Raised by `restore_resumable_checkpoint()` (Audit #075 P0-04)
    when the checkpoint being restored claims a `global_step` lower
    than the highest step this `run_id`'s own monotonic ledger has
    already recorded -- i.e. an attempt to resume from an OLDER, validly
    signed checkpoint after the run has already progressed further.
    See this module's own docstring, "Anti-rollback ledger", for the
    explicit, honest scope of what this does and does not guarantee."""


class WeakIntegrityKeyError(Exception):
    """Raised when `integrity_key` is shorter than
    `MIN_INTEGRITY_KEY_BYTES` -- Audit #075's "weak key custody"
    finding: the prior code only checked `if not integrity_key`,
    silently accepting a 1-byte key with no real HMAC security margin."""


class CrossRunCheckpointAccessError(Exception):
    """AUDIT-077 Phase 2: raised by `restore_resumable_checkpoint()`
    when the checkpoint's own HMAC-bound `owning_run_id` does not match
    the `run_id` the restore is being performed under. See the module
    docstring, "Cross-run checkpoint ownership", for why this exists."""


class CrossRunMigrationDisabledError(Exception):
    """AUDIT-077 P0-02 (CTO security remediation directive, "Remove the
    unauthenticated cross-run migration override"): raised when a
    caller passes `allow_cross_run_migration=True` to
    `restore_resumable_checkpoint()`. Antigravity's independent
    requalification found that parameter let ANY direct Python caller
    adopt a foreign run's checkpoint merely by passing a boolean -- no
    cryptographic proof of authorization (no signed migration grant, no
    founder signature, no expiry/revocation semantics) was required or
    checked. Per the CTO's explicit instruction, this override is now
    DISABLED on every callable path -- not merely undocumented or
    discouraged -- until a proper governance contract is designed and
    approved (authenticated source/target run, exact checkpoint digest,
    authorizing principal, signed/verifiable grant, expiry/revocation,
    single-purpose scope, replay resistance, durable evidence -- see
    this module's own docstring, "Cross-run checkpoint ownership", for
    the proposed shape). Ordinary same-run restoration is unaffected;
    this exception fires ONLY when a caller explicitly asks for
    migration, never for a normal same-run restore."""


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
    "owning_run_id",
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
    owning_run_id: str  # AUDIT-077 Phase 2: the run_id this checkpoint was SAVED under; HMAC-bound, checked on restore unless migration is explicitly requested
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


def _require_strong_integrity_key(integrity_key: bytes) -> None:
    if not integrity_key:
        raise ValueError("integrity_key is required and must be non-empty -- see this module's own docstring, AUDIT-P0-04")
    if len(integrity_key) < MIN_INTEGRITY_KEY_BYTES:
        raise WeakIntegrityKeyError(
            f"integrity_key is {len(integrity_key)} bytes; AUDIT-075 requires at least "
            f"{MIN_INTEGRITY_KEY_BYTES} bytes (256 bits) of real key material -- a short key gives an HMAC "
            f"no meaningful forgery-resistance margin. Generate one with e.g. os.urandom(32)."
        )


def _ledger_path(run_id: str) -> Path:
    """Audit #075 P0-04, anti-rollback ledger: deliberately lives under
    `orca.config.ORCA_HOME` -- a location SEPARATE from wherever the
    checkpoint directory itself is -- keyed by a SHA-256 of the
    caller-supplied `run_id` (the logical training run's identity, not
    a file path). This is read dynamically at call time (not imported
    as a bound constant) so it honors `ORCA_HOME` being monkeypatched
    per-test, matching this codebase's own established test-isolation
    convention.

    **Explicit, honest scope**: this raises the bar for a rollback
    attack (an attacker must now also control this separate location,
    not just the checkpoint directory being restored from), but it is
    NOT a cryptographically independent authority -- it is still a
    local file on the same machine, protected only by filesystem
    permissions and the same HMAC key as the checkpoint itself. Genuine
    rollback protection against an attacker with full local filesystem
    access requires an external, append-only ledger (a remote service,
    or a hardware monotonic counter) -- explicitly out of scope here
    (no paid infrastructure is available in this phase) and recorded as
    a residual limitation, not silently claimed as closed."""
    ledger_dir = _mkdir_owner_only(orca_config.ORCA_HOME / "genesis_checkpoint_ledger", parents=True)
    digest = hashlib.sha256(run_id.encode("utf-8")).hexdigest()
    return ledger_dir / f"{digest}.ledger.json"


def _read_ledger(run_id: str, integrity_key: bytes) -> int:
    """Returns the highest `global_step` ever recorded for `run_id`, or
    0 if no ledger entry exists yet. Raises `ResumableManifestTamperedError`
    if a ledger entry exists but fails its own HMAC check (its fields
    are the same class of tamper-evident binding as the checkpoint
    sidecar's own, using the SAME caller-supplied `integrity_key`)."""
    path = _ledger_path(run_id)
    if path.is_symlink():
        raise ResumableManifestTamperedError(f"refusing to trust {path} as a checkpoint ledger -- it is a symlink, not a regular file")
    if not path.exists():
        return 0
    data = json.loads(path.read_text())
    tag = data.pop("integrity_tag", None)
    expected = _compute_integrity_tag(integrity_key, data)
    if tag is None or not hmac.compare_digest(expected, tag):
        raise ResumableManifestTamperedError(
            f"checkpoint ledger at {path} failed its HMAC integrity check -- refusing to trust its recorded "
            f"highest_global_step; this would otherwise silently defeat anti-rollback protection"
        )
    if data.get("schema_version") != LEDGER_SCHEMA_VERSION:
        raise ResumableManifestTamperedError(f"checkpoint ledger at {path} declares an unrecognized schema_version={data.get('schema_version')!r}")
    return int(data["highest_global_step"])


def _advance_ledger(run_id: str, integrity_key: bytes, observed_step: int) -> None:
    """Held under the SAME exclusive lock `save_resumable_checkpoint()`
    already takes for its own manifest write. Monotonically raises the
    ledger's recorded `highest_global_step` to `max(current, observed_step)`
    -- never lowers it, regardless of what `observed_step` is."""
    current = _read_ledger(run_id, integrity_key)
    new_highest = max(current, observed_step)
    path = _ledger_path(run_id)
    fields = {
        "schema_version": LEDGER_SCHEMA_VERSION,
        "run_id_digest": hashlib.sha256(run_id.encode("utf-8")).hexdigest(),
        "highest_global_step": new_highest,
    }
    record = dict(fields)
    record["integrity_tag"] = _compute_integrity_tag(integrity_key, fields)
    fd, tmp_str = tempfile.mkstemp(dir=path.parent, prefix=f".{path.name}.tmp-")
    tmp = Path(tmp_str)
    try:
        with os.fdopen(fd, "w") as f:
            f.write(json.dumps(record))
            f.flush()
            os.fsync(f.fileno())
        tmp.chmod(0o600)
        os.replace(tmp, path)
    except BaseException:
        tmp.unlink(missing_ok=True)
        raise


def _sha256_via_dirfd(dir_fd: int, name: str) -> str:
    """Same content-hash as `checkpoint_integrity._sha256_of_file()`, but
    reads the file by opening `name` relative to an already-open,
    no-follow-verified `dir_fd` (from `_open_dir_no_symlinks()`) instead
    of re-resolving a fresh path string -- AUDIT-077 P0-01: once
    `save_resumable_checkpoint()` holds `dir_fd`, every operation it
    performs on the checkpoint it just wrote must go through that same
    descriptor, never a new string resolution an attacker could have
    redirected in the interim."""
    fd = os.open(name, os.O_RDONLY, dir_fd=dir_fd)
    h = hashlib.sha256()
    with os.fdopen(fd, "rb") as f:
        for chunk in iter(lambda: f.read(1024 * 1024), b""):
            h.update(chunk)
    return h.hexdigest()


def save_resumable_checkpoint(
    *, path: Path, training_state: TrainingState, global_step: int, microbatch_in_cycle: int,
    sampler_position: int, sampler_seed: int, sampler_num_blocks: int,
    config_fingerprint: str, dataset_identity: DatasetIdentity, integrity_key: bytes, run_id: str,
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
    _require_strong_integrity_key(integrity_key)
    if not run_id:
        raise ValueError("run_id is required and must be non-empty -- Audit #075 P0-04 binds every save to this run's own anti-rollback ledger")

    # AUDIT-077 P0-01 fix (intermediate-ancestor TOCTOU escape,
    # independently reproduced and found by Antigravity's requalification
    # before this fix): this function used to re-resolve `path.parent` as
    # a fresh string via `_mkdir_owner_only()` -- which deliberately
    # FOLLOWS a same-uid-owned ancestor symlink, the exact loophole a
    # same-uid attacker exploited by racing a symlink substitution into
    # the window between `_enforce_checkpoint_path_confinement()`'s
    # validation and this function's own directory resolution -- then
    # performed the lock file, temp file, and manifest rename each via
    # ANOTHER independent path-string resolution. `save_training_state()`
    # (called below) now hardens its OWN inner checkpoint write the same
    # way; this function separately opens ITS OWN held `dir_fd` via
    # `_open_dir_no_symlinks()` (never following a non-root-owned ancestor
    # symlink) and performs every subsequent operation of its own --
    # hashing the just-written checkpoint, the `.resumable.lock` file,
    # and the manifest's temp-write + rename -- through that one held
    # descriptor, never re-resolving a path string again.
    path = Path(path)
    save_training_state(training_state, path)
    parent_fd = _open_dir_no_symlinks(path.parent, parents=True)
    try:
        lock_fd = os.open(f".{path.name}.resumable.lock", os.O_RDWR | os.O_CREAT, 0o600, dir_fd=parent_fd)
        try:
            fcntl.flock(lock_fd, fcntl.LOCK_EX)
            try:
                tagged_fields = {
                    "schema_version": RESUMABLE_SCHEMA_VERSION, "inner_checkpoint_sha256": _sha256_via_dirfd(parent_fd, path.name),
                    "global_step": global_step, "microbatch_in_cycle": microbatch_in_cycle,
                    "sampler_position": sampler_position, "sampler_seed": sampler_seed,
                    "sampler_num_blocks": sampler_num_blocks, "config_fingerprint": config_fingerprint,
                    "dataset_identity": asdict(dataset_identity), "owning_run_id": run_id,
                }
                manifest = ResumableManifest(
                    **{k: v for k, v in tagged_fields.items() if k != "dataset_identity"},
                    dataset_identity=dataset_identity,
                    integrity_tag=_compute_integrity_tag(integrity_key, tagged_fields),
                )
                manifest_name = _resumable_manifest_path(path).name
                tmp_fd, tmp_name = _dirfd_mkstemp(parent_fd, prefix=f".{manifest_name}.tmp-")
                try:
                    os.fchmod(tmp_fd, 0o600)
                    with os.fdopen(tmp_fd, "w") as f:
                        f.write(json.dumps(manifest.to_dict()))
                        f.flush()
                        os.fsync(f.fileno())
                    os.replace(tmp_name, manifest_name, src_dir_fd=parent_fd, dst_dir_fd=parent_fd)
                except BaseException:
                    try:
                        os.unlink(tmp_name, dir_fd=parent_fd)
                    except FileNotFoundError:
                        pass
                    raise
                _advance_ledger(run_id, integrity_key, global_step)
                return manifest
            finally:
                fcntl.flock(lock_fd, fcntl.LOCK_UN)
        finally:
            os.close(lock_fd)
    finally:
        os.close(parent_fd)


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
    expected_sampler_seed: int, expected_sampler_num_blocks: int, integrity_key: bytes, run_id: str,
    allow_cross_run_migration: bool = False,
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
       inside the ALREADY content-hash-verified checkpoint body.
    6. **(AUDIT-075)** `global_step` is checked against `run_id`'s own
       anti-rollback ledger (stored OUTSIDE this checkpoint's own
       directory -- see `_ledger_path()`'s docstring for its explicit,
       honest scope): restoring a checkpoint older than the highest
       step this run has already recorded raises `CheckpointRollbackError`.
    7. **(AUDIT-077 Phase 2 / P0-02)** The manifest's own HMAC-bound
       `owning_run_id` (the `run_id` it was SAVED under) must equal the
       `run_id` this restore is being performed under, unconditionally
       -- `allow_cross_run_migration` is accepted for signature
       compatibility but DISABLED: passing `True` raises
       `CrossRunMigrationDisabledError` rather than bypassing this
       check. See the module docstring, "Cross-run checkpoint
       ownership"."""
    _require_strong_integrity_key(integrity_key)
    if not run_id:
        raise ValueError("run_id is required and must be non-empty -- Audit #075 P0-04 checks this run's own anti-rollback ledger")
    path = Path(path)
    manifest_path = _resumable_manifest_path(path)

    # AUDIT-077 P0-01 ("ensure restore operations use equally safe
    # file-opening semantics"): open the checkpoint's parent directory
    # ONCE via `_open_dir_no_symlinks()` (never following a non-root-
    # owned ancestor symlink) and read both the manifest and the
    # checkpoint's content hash through that single held descriptor --
    # never a freshly re-resolved path string, which a same-uid attacker
    # could have redirected via an ancestor symlink swap between an
    # earlier validation and this read. This is read-side defense in
    # depth: a redirected read would in any case be caught below by the
    # HMAC/content-hash checks (an attacker without `integrity_key`
    # cannot forge a matching manifest), but closing the same structural
    # class of gap as the save-side fix keeps the two paths consistent.
    try:
        parent_fd = _open_dir_no_symlinks(path.parent, parents=False)
    except FileNotFoundError:
        raise ResumableManifestTamperedError(f"no resumable manifest found at {manifest_path} for checkpoint {path}") from None
    try:
        try:
            manifest_fd = os.open(manifest_path.name, os.O_RDONLY, dir_fd=parent_fd)
        except FileNotFoundError:
            raise ResumableManifestTamperedError(f"no resumable manifest found at {manifest_path} for checkpoint {path}") from None
        with os.fdopen(manifest_fd, "r") as f:
            raw_text = f.read()
        try:
            raw_manifest = json.loads(raw_text)
        except (json.JSONDecodeError, UnicodeDecodeError) as e:
            raise ResumableManifestTamperedError(f"resumable manifest at {manifest_path} is not valid JSON -- refusing to trust it: {e}") from e
        try:
            actual_sha256 = _sha256_via_dirfd(parent_fd, path.name)
        except FileNotFoundError:
            raise ResumableManifestTamperedError(f"no checkpoint file found at {path} (manifest exists, but the checkpoint it describes does not)") from None
    finally:
        os.close(parent_fd)

    # AUDIT-077 Phase 6: the schema_version check MUST happen on the raw,
    # untrusted dict -- BEFORE ever attempting to construct a
    # `ResumableManifest` from it. A legacy (pre-Audit-077) schema-v1/v2
    # manifest lacks `owning_run_id` entirely; constructing the
    # dataclass directly from such a dict previously raised a bare,
    # unintentional-looking `TypeError` (a missing constructor argument)
    # instead of a clean, deliberate rejection -- independently
    # reproduced before this fix. Every unrecognized or legacy
    # schema_version, including one from a manifest this code cannot
    # even fully parse into today's shape, is now rejected the SAME way:
    # fail closed, with the SAME `ResumableManifestTamperedError`, never
    # a generic crash that could be mistaken for a bug rather than the
    # deliberate boundary it is. An old manifest's own HMAC tag (computed
    # under a DIFFERENT, no-longer-current field set) could never
    # validate against today's `_TAGGED_FIELDS` shape regardless -- this
    # check simply makes that rejection explicit and legible rather than
    # accidental.
    if not isinstance(raw_manifest, dict) or raw_manifest.get("schema_version") != RESUMABLE_SCHEMA_VERSION:
        raise ResumableManifestTamperedError(
            f"resumable manifest at {manifest_path} declares schema_version="
            f"{raw_manifest.get('schema_version') if isinstance(raw_manifest, dict) else '<not a JSON object>'!r}, "
            f"but this code only understands {RESUMABLE_SCHEMA_VERSION!r} -- a legacy or unrecognized schema "
            f"version is never authenticated against today's field set and is always rejected, fail-closed, "
            f"rather than partially parsed"
        )
    manifest = ResumableManifest.from_dict(raw_manifest)

    expected_tag = _compute_integrity_tag(integrity_key, manifest._tagged_fields_dict())
    if not hmac.compare_digest(expected_tag, manifest.integrity_tag):
        raise ResumableManifestTamperedError(
            f"resumable manifest at {manifest_path} failed its HMAC integrity check -- one or more sidecar "
            f"fields (global_step, microbatch_in_cycle, sampler_position, config_fingerprint, dataset_identity, "
            f"inner_checkpoint_sha256) were modified since this checkpoint was saved, or the wrong integrity_key "
            f"was supplied. Refusing to trust any field in this manifest."
        )

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

    # AUDIT-077 Phase 2 / P0-02 (CTO security remediation directive):
    # cross-run checkpoint ownership. Independently reproduced before
    # the Phase 2 fix: a checkpoint saved under one run_id could be
    # restored under a DIFFERENT run_id with no explicit authorization
    # at all, as long as config_fingerprint/dataset_identity happened to
    # match. Phase 2 bound ownership via HMAC-tagged `owning_run_id` but
    # left an `allow_cross_run_migration: bool` escape hatch; Antigravity's
    # independent requalification found that ANY direct Python caller
    # could bypass run ownership merely by passing that boolean, with no
    # cryptographic proof of authorization whatsoever. Per the CTO's
    # explicit instruction, that escape hatch is now DISABLED on every
    # callable path: requesting it raises `CrossRunMigrationDisabledError`
    # instead of silently proceeding, rather than being silently ignored.
    # Ordinary same-run restoration (the overwhelming common case) is
    # completely unaffected by this -- the check below fires only for an
    # actual cross-run restore attempt.
    if allow_cross_run_migration:
        raise CrossRunMigrationDisabledError(
            "allow_cross_run_migration=True was requested, but cross-run checkpoint "
            "migration is disabled on every callable path pending a proper, cryptographically "
            "verifiable migration governance contract (see CrossRunMigrationDisabledError's own "
            "docstring for the proposed shape) -- no founder grant is invented or issued here."
        )
    if manifest.owning_run_id != run_id:
        raise CrossRunCheckpointAccessError(
            f"checkpoint at {path} was saved under run_id {manifest.owning_run_id!r}, but this restore is "
            f"being performed under run_id {run_id!r} -- checkpoint ownership is bound to the run that "
            f"created it, and cross-run migration is not currently supported by any callable path (see "
            f"CrossRunMigrationDisabledError)."
        )

    training_state = load_training_state(path)
    if training_state.step != manifest.global_step:
        raise ResumableManifestTamperedError(
            f"resumable manifest at {manifest_path} claims global_step={manifest.global_step}, but the "
            f"inner, content-hash-verified checkpoint's own step is {training_state.step} -- these must be "
            f"identical; refusing to resume from an internally inconsistent checkpoint"
        )

    ledger_highest = _read_ledger(run_id, integrity_key)
    if manifest.global_step < ledger_highest:
        raise CheckpointRollbackError(
            f"refusing to restore checkpoint at {path} (global_step={manifest.global_step}): run_id "
            f"{run_id!r}'s own anti-rollback ledger has already recorded a higher step "
            f"({ledger_highest}) -- this looks like an attempt to resume from an OLDER, validly signed "
            f"checkpoint after the run already progressed further. See _ledger_path()'s docstring for "
            f"this check's explicit, honest scope."
        )
    _advance_ledger(run_id, integrity_key, manifest.global_step)

    return RestoredRun(
        training_state=training_state, global_step=manifest.global_step,
        microbatch_in_cycle=manifest.microbatch_in_cycle, sampler_position=manifest.sampler_position,
    )
