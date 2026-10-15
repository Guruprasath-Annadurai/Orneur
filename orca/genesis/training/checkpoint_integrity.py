"""
GENESIS Foundation Sprint 2, Workstream B: checkpoint integrity and
recovery.

Adds a content-hash manifest alongside `save_training_state()`'s own
atomic write (Sprint 1 / Audit #016), rather than modifying that
already-audited, already-remediated function directly -- this module
is strictly additive. A manifest records the checkpoint's SHA-256,
format version, and the architecture version it was produced under;
`load_verified_training_state()` is the trusted-load boundary this
sprint adds: it refuses to call `load_training_state()` at all unless
the on-disk content hash matches the manifest, closing the gap where a
corrupted, truncated, or substituted file would otherwise be deserialized
(and only then, inside `TrainingState.restore()`, potentially produce a
confusing downstream failure) without ever having its integrity checked
first.

This is a CONTENT-integrity check (detects corruption, truncation, or
substitution against what was actually written), not a TRUST/provenance
check (it does not establish WHO produced the checkpoint or whether its
content is the one a caller actually intends to resume from) -- that
remains `orca.registry.provenance`'s job, unchanged and not duplicated
here, exactly as `load_training_state()`'s own docstring already states.
"""
from __future__ import annotations

import fcntl
import hashlib
import json
import os
import tempfile
from dataclasses import asdict, dataclass
from pathlib import Path

from orca.config import _mkdir_owner_only
from orca.genesis.model.config import ARCHITECTURE_VERSION
from orca.genesis.training.primitives import TrainingState, load_training_state, save_training_state

CHECKPOINT_FORMAT_VERSION = "genesis-ckpt-v1"


@dataclass(frozen=True)
class CheckpointManifest:
    format_version: str
    architecture_version: str
    sha256: str
    step: int
    epoch: int

    def to_dict(self) -> dict:
        return asdict(self)

    @classmethod
    def from_dict(cls, d: dict) -> "CheckpointManifest":
        return cls(**d)


def _sha256_of_file(path: Path) -> str:
    h = hashlib.sha256()
    with open(path, "rb") as f:
        for chunk in iter(lambda: f.read(1024 * 1024), b""):
            h.update(chunk)
    return h.hexdigest()


def _manifest_path(checkpoint_path: Path) -> Path:
    return checkpoint_path.with_suffix(checkpoint_path.suffix + ".manifest.json")


def state_dict_fingerprint(state_dict: dict) -> str:
    """Audit #017 DEFECT-04 remediation building block: a deterministic
    SHA-256 digest of a `model_state_dict`'s actual tensor VALUES (not
    object identity, not a caller-supplied label). Used to prove that a
    live model's current parameters are bit-identical to what a specific,
    already content-verified checkpoint actually contains -- the
    "incorrect model/checkpoint binding" and "swapped model states"
    threat the audit's required work explicitly names. Keys are sorted
    so the digest does not depend on dict ordering; each tensor is
    detached, moved to CPU, made contiguous, and hashed by its raw bytes
    -- two tensors with the same values but different devices/dtypes
    that would not actually `torch.equal()` are NOT guaranteed to collide
    here (dtype is included in a tensor's native byte representation),
    which is the correct, conservative behavior for an identity check."""
    h = hashlib.sha256()
    for key in sorted(state_dict.keys()):
        value = state_dict[key]
        h.update(key.encode("utf-8"))
        if hasattr(value, "detach"):
            tensor = value.detach().to("cpu").contiguous()
            h.update(str(tensor.dtype).encode("utf-8"))
            h.update(tensor.numpy().tobytes())
        else:
            h.update(repr(value).encode("utf-8"))
    return h.hexdigest()


def save_verified_training_state(state: TrainingState, path: Path, *, architecture_version: str = ARCHITECTURE_VERSION) -> CheckpointManifest:
    """Saves via the existing, already-remediated `save_training_state()`
    (reused unchanged, not duplicated), then writes a sidecar manifest
    recording the checkpoint's real SHA-256 -- computed from the actual
    bytes on disk AFTER the atomic rename, not from the in-memory state
    before serialization, so the hash reflects exactly what a future
    reader will see.

    Audit #017 DEFECT-01 remediation: the manifest write previously used
    a deterministic temporary filename opened via `Path.write_text()`
    (`O_CREAT | O_TRUNC`, no `O_EXCL`/`O_NOFOLLOW`) -- a pre-planted
    symlink at that predictable path caused the write to follow it and
    overwrite an arbitrary attacker-chosen target. This now uses the
    same `tempfile.mkstemp()` + owner-only-chmod + `fsync` + atomic
    `os.replace()` discipline Sprint 1 / Audit #016 already established
    for `save_training_state()` itself -- a random, exclusively-created
    (`O_EXCL`) name that an attacker cannot pre-plant a symlink at.

    Audit #017 section 4.1 also flagged a non-atomicity window: the inner
    `save_training_state()` call acquires and releases its OWN exclusive
    lock internally, so by the time this function hashes the file and
    writes the manifest, that lock is already gone -- two concurrent
    `save_verified_training_state()` callers targeting the same `path`
    could interleave (writer A's checkpoint bytes hashed into writer B's
    manifest, or vice versa). This function now holds an outer exclusive
    lock, scoped to the verified-save operation specifically (a distinct
    `.{name}.verified.lock` file, not the inner lock `save_training_state`
    already manages on its own), across the ENTIRE save+hash+manifest
    sequence, so two concurrent verified-save calls against the same path
    fully serialize relative to each other."""
    path = Path(path)
    parent = _mkdir_owner_only(path.parent, parents=True)
    verified_lock_path = parent / f".{path.name}.verified.lock"
    with open(verified_lock_path, "a+") as lock_file:
        fcntl.flock(lock_file.fileno(), fcntl.LOCK_EX)
        try:
            save_training_state(state, path)
            manifest = CheckpointManifest(
                format_version=CHECKPOINT_FORMAT_VERSION,
                architecture_version=architecture_version,
                sha256=_sha256_of_file(path),
                step=state.step,
                epoch=state.epoch,
            )
            manifest_path = _manifest_path(path)
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


class ChecksumMismatchError(Exception):
    """Raised by `load_verified_training_state()` when the on-disk
    checkpoint's actual content hash does not match its own manifest --
    corruption, truncation, or substitution, fail-closed."""


class ManifestMissingError(Exception):
    """Raised when a checkpoint has no manifest at all. Deliberately a
    DIFFERENT exception from `ChecksumMismatchError`: a missing manifest
    means "this checkpoint was never saved through
    save_verified_training_state() (e.g. written by the older,
    unverified `save_training_state()` directly, or by something else
    entirely)", not "this checkpoint's content was tampered with" --
    collapsing the two would make a legitimate, differently-produced
    checkpoint indistinguishable from a tampered one in logs/alerts."""


class UnsupportedManifestVersionError(Exception):
    """Audit #017 DEFECT-02: raised when a manifest's `format_version` or
    `architecture_version` does not match what this code actually
    understands. The manifest's content-hash field alone proves the
    checkpoint bytes are unchanged since *some* save -- it says nothing
    about whether this version of the loading code can interpret those
    bytes correctly. A future format or architecture revision must fail
    closed here, not be silently deserialized as if it were the current
    one."""


class ManifestStateMismatchError(Exception):
    """Audit #017 DEFECT-03: raised when the manifest's recorded `step`
    and `epoch` disagree with the `step`/`epoch` actually present in the
    deserialized `TrainingState`. The SHA-256 check alone only proves the
    checkpoint *bytes* are exactly what was hashed into this manifest --
    a manifest edited (or substituted together with a re-hashed
    checkpoint) to claim a different step/epoch than the state it
    accompanies would otherwise load without any indication that its own
    metadata is self-inconsistent."""


def load_verified_training_state(path: Path) -> TrainingState:
    """The trusted-load boundary: refuses to deserialize at all unless
    the checkpoint's current on-disk content hash matches its manifest,
    the manifest's format/architecture version is one this code
    understands, and the manifest's own step/epoch agree with the
    deserialized state. Verified by this module's own adversarial tests:
    flipping a single byte in either the checkpoint or the manifest,
    deleting the manifest entirely, declaring an unsupported format or
    architecture version, or editing the manifest's step/epoch fields to
    disagree with the real checkpoint state, must each be caught here --
    the version/format check BEFORE, and the step/epoch check AFTER,
    `load_training_state()`'s own (already-hardened, `weights_only=True`)
    deserialization is reached.

    Audit #017 section 4.1 TOCTOU remediation: hashing `path` and then
    separately deserializing it (two separate opens of the same file)
    left a window where a concurrent writer could replace the file's
    content between those two reads -- the hash would be computed from
    one version of the bytes and `load_training_state()` would then
    deserialize a DIFFERENT version. This now acquires a SHARED
    (`fcntl.LOCK_SH`) lock on the exact same `.{name}.lock` file
    `save_training_state()`'s own exclusive writer lock uses, held across
    both the hash computation and the deserialization -- any concurrent
    writer (holding that lock exclusively) is blocked until this entire
    read completes, and multiple concurrent readers do not block each
    other."""
    path = Path(path)
    manifest_path = _manifest_path(path)
    if not manifest_path.exists():
        raise ManifestMissingError(f"no manifest at {manifest_path} for checkpoint {path}")
    manifest = CheckpointManifest.from_dict(json.loads(manifest_path.read_text()))
    if manifest.format_version != CHECKPOINT_FORMAT_VERSION:
        raise UnsupportedManifestVersionError(
            f"checkpoint {path} was saved under format_version={manifest.format_version!r}, "
            f"but this code only understands {CHECKPOINT_FORMAT_VERSION!r} -- refusing to load "
            f"a checkpoint whose on-disk layout this version cannot be certain it interprets correctly"
        )
    if manifest.architecture_version != ARCHITECTURE_VERSION:
        raise UnsupportedManifestVersionError(
            f"checkpoint {path} was saved under architecture_version={manifest.architecture_version!r}, "
            f"but the current architecture is {ARCHITECTURE_VERSION!r} -- refusing to load a checkpoint "
            f"produced under a different model architecture"
        )
    if not path.exists():
        raise FileNotFoundError(f"manifest exists but checkpoint file is missing: {path}")

    lock_path = path.parent / f".{path.name}.lock"
    with open(lock_path, "a+") as lock_file:
        fcntl.flock(lock_file.fileno(), fcntl.LOCK_SH)
        try:
            actual_hash = _sha256_of_file(path)
            if actual_hash != manifest.sha256:
                raise ChecksumMismatchError(
                    f"checkpoint {path} does not match its manifest's recorded SHA-256 "
                    f"(expected {manifest.sha256}, got {actual_hash}) -- refusing to load "
                    f"a checkpoint whose content has changed since it was saved"
                )
            state = load_training_state(path)
        finally:
            fcntl.flock(lock_file.fileno(), fcntl.LOCK_UN)

    if state.step != manifest.step or state.epoch != manifest.epoch:
        raise ManifestStateMismatchError(
            f"checkpoint {path}'s manifest records step={manifest.step}, epoch={manifest.epoch}, "
            f"but the deserialized state has step={state.step}, epoch={state.epoch} -- refusing to "
            f"load a checkpoint whose own manifest metadata disagrees with its content"
        )
    return state
