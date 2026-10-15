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

import hashlib
import json
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


def save_verified_training_state(state: TrainingState, path: Path, *, architecture_version: str = ARCHITECTURE_VERSION) -> CheckpointManifest:
    """Saves via the existing, already-remediated `save_training_state()`
    (reused unchanged, not duplicated), then writes a sidecar manifest
    recording the checkpoint's real SHA-256 -- computed from the actual
    bytes on disk AFTER the atomic rename, not from the in-memory state
    before serialization, so the hash reflects exactly what a future
    reader will see."""
    path = Path(path)
    save_training_state(state, path)
    manifest = CheckpointManifest(
        format_version=CHECKPOINT_FORMAT_VERSION,
        architecture_version=architecture_version,
        sha256=_sha256_of_file(path),
        step=state.step,
        epoch=state.epoch,
    )
    manifest_path = _manifest_path(path)
    parent = _mkdir_owner_only(path.parent, parents=True)
    tmp = parent / f".{manifest_path.name}.tmp"
    tmp.write_text(json.dumps(manifest.to_dict()))
    tmp.replace(manifest_path)
    manifest_path.chmod(0o600)
    return manifest


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


def load_verified_training_state(path: Path) -> TrainingState:
    """The trusted-load boundary: refuses to deserialize at all unless
    the checkpoint's current on-disk content hash matches its manifest.
    Verified by this module's own adversarial tests: flipping a single
    byte in either the checkpoint or the manifest, or deleting the
    manifest entirely, must be caught here -- BEFORE
    `load_training_state()`'s own (already-hardened,
    `weights_only=True`) deserialization is ever reached."""
    path = Path(path)
    manifest_path = _manifest_path(path)
    if not manifest_path.exists():
        raise ManifestMissingError(f"no manifest at {manifest_path} for checkpoint {path}")
    manifest = CheckpointManifest.from_dict(json.loads(manifest_path.read_text()))
    if not path.exists():
        raise FileNotFoundError(f"manifest exists but checkpoint file is missing: {path}")
    actual_hash = _sha256_of_file(path)
    if actual_hash != manifest.sha256:
        raise ChecksumMismatchError(
            f"checkpoint {path} does not match its manifest's recorded SHA-256 "
            f"(expected {manifest.sha256}, got {actual_hash}) -- refusing to load "
            f"a checkpoint whose content has changed since it was saved"
        )
    return load_training_state(path)
