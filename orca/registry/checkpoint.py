"""
Checkpoint lifecycle abstraction. Before this module, checkpoint identity
was "whatever the filename says" (see docs/orneur/phase-0/MODEL_TRAINING_STATUS.md:
"no adapter naming registry or 'latest' pointer file was found anywhere in
code... history is tracked only via notebook filenames"). This gives every
checkpoint a real identity record with checksum-verifiable integrity.
"""
from __future__ import annotations

import json
from dataclasses import asdict, dataclass, field
from datetime import datetime, timezone
from enum import Enum
from pathlib import Path

from orca.config import ORCA_HOME
from orca.registry._ids import validate_id
from orca.registry.dataset_manifest import sha256_of_file

CHECKPOINT_DIR = ORCA_HOME / "registry" / "checkpoints"
CHECKPOINT_DIR.mkdir(parents=True, exist_ok=True)


class CorruptCheckpointError(Exception):
    pass


class ArtifactAvailability(str, Enum):
    """
    Distinct from LifecycleState (orca/registry/model_spec.py) -- lifecycle
    is about whether a checkpoint is production-worthy; availability is
    about whether its WEIGHT FILE can currently be read at all. A checkpoint
    can be RETIRED (lifecycle) yet still LOCAL (availability), or
    EXPERIMENTAL (lifecycle) yet MISSING (availability) -- the two axes are
    independent. This distinction exists specifically because Phase 1
    overloaded "the artifact isn't reachable" into an ad-hoc checksum
    sentinel string, which this replaces with a real, checked field.
    """
    LOCAL = "LOCAL"          # weight file verified present & readable on this machine
    REMOTE = "REMOTE"        # not local, but verified recoverable from a known source (e.g. a specific Kaggle kernel)
    MISSING = "MISSING"      # not local, no verified recovery path -- the honest "just gone" state
    CORRUPT = "CORRUPT"      # present but fails checksum verification
    ARCHIVED = "ARCHIVED"    # deliberately moved to cold storage, not an accident


@dataclass
class CheckpointRecord:
    checkpoint_id: str            # e.g. "orca-core-combined-v2" -- keeps the legacy name as identity, not a rename
    model_id: str                  # canonical family, e.g. "orneur-novus"
    run_id: str                    # the training run that produced it
    step_or_epoch: str
    base_model: str
    dataset_manifest_ids: list[str]
    training_config_summary: str
    optimizer_state_available: bool
    scheduler_state_available: bool
    tokenizer_identity: str
    artifact_path: str              # where the actual weights/GGUF live (may be a remote/local path)
    artifact_checksum: str          # sha256 of the artifact at save time
    lineage_parent: str | None = None   # parent checkpoint_id, if this one resumed/derived from another
    legacy_ollama_name: str | None = None
    created_at: str = field(default_factory=lambda: datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ"))
    validation_state: str = "UNVALIDATED"  # UNVALIDATED | VALID | CORRUPT
    # Deliberately defaults to MISSING, not LOCAL -- a checkpoint is only
    # ever considered present after an explicit check sets this, never by
    # assumption. See ArtifactAvailability's docstring for why this is a
    # separate axis from lifecycle_state.
    availability: str = ArtifactAvailability.MISSING.value
    recovery_source: str | None = None   # e.g. "kaggle:guruprasathannadurai/orca-core-dpo-merge-export-v1" -- required when availability=REMOTE
    availability_note: str = ""

    def manifest_path(self) -> Path:
        validate_id(self.checkpoint_id, "checkpoint_id")
        return CHECKPOINT_DIR / f"{self.checkpoint_id}.json"

    def save(self) -> Path:
        path = self.manifest_path()
        with open(path, "w") as f:
            json.dump(asdict(self), f, indent=2)
        return path

    @classmethod
    def load(cls, checkpoint_id: str) -> "CheckpointRecord":
        validate_id(checkpoint_id, "checkpoint_id")
        path = CHECKPOINT_DIR / f"{checkpoint_id}.json"
        if not path.exists():
            raise FileNotFoundError(f"No checkpoint record for '{checkpoint_id}'")
        with open(path) as f:
            return cls(**json.load(f))

    def verify_integrity(self, artifact_path: Path | None = None) -> bool:
        """
        Re-hashes the actual artifact file (if reachable locally) and compares
        against the recorded checksum. Raises CorruptCheckpointError on
        mismatch rather than silently returning False, since a caller that
        forgets to check a bool return is exactly how a corrupt checkpoint
        gets silently loaded.
        """
        path = artifact_path or Path(self.artifact_path)
        if not path.exists():
            # Artifact not reachable from this machine (e.g. only exists on
            # Kaggle/remote storage) -- can't verify, but that's not the same
            # as corrupt. Caller must handle this explicitly.
            self.validation_state = "UNVALIDATED"
            return False
        actual = sha256_of_file(path)
        if actual != self.artifact_checksum:
            self.validation_state = "CORRUPT"
            raise CorruptCheckpointError(
                f"Checkpoint '{self.checkpoint_id}' failed integrity check: "
                f"recorded={self.artifact_checksum} actual={actual}"
            )
        self.validation_state = "VALID"
        self.availability = ArtifactAvailability.LOCAL.value
        return True

    def refresh_availability(self, artifact_path: Path | None = None) -> str:
        """
        Checks local file presence/integrity and sets availability to LOCAL
        or CORRUPT accordingly. Does NOT downgrade an existing REMOTE or
        ARCHIVED state to MISSING just because the file isn't locally
        present right now -- those states represent a deliberate, verified
        fact about a KNOWN remote location, which a missing local copy
        doesn't invalidate. Only call this after actually checking a
        specific local path; it never guesses.
        """
        path = artifact_path or Path(self.artifact_path)
        if not path.exists():
            if self.availability not in (ArtifactAvailability.REMOTE.value, ArtifactAvailability.ARCHIVED.value):
                self.availability = ArtifactAvailability.MISSING.value
            return self.availability
        try:
            self.verify_integrity(path)
        except CorruptCheckpointError:
            self.availability = ArtifactAvailability.CORRUPT.value
        return self.availability

    def is_loadable(self) -> bool:
        """
        The routing guard: a checkpoint whose weight artifact is not
        verified LOCAL must never be treated as loadable, regardless of
        its lifecycle_state. REMOTE means "recoverable with an explicit
        fetch step" -- still not loadable as-is.
        """
        return self.availability == ArtifactAvailability.LOCAL.value

    def is_routable(self) -> bool:
        return self.is_loadable()


def list_checkpoints(model_id: str | None = None) -> list[CheckpointRecord]:
    records = []
    for p in sorted(CHECKPOINT_DIR.glob("*.json")):
        with open(p) as f:
            rec = CheckpointRecord(**json.load(f))
        if model_id is None or rec.model_id == model_id:
            records.append(rec)
    return records


def latest_good_checkpoint(model_id: str, require_loadable: bool = False) -> CheckpointRecord | None:
    """
    Most recent checkpoint for a family that isn't marked CORRUPT. Pass
    require_loadable=True to additionally require the artifact be verified
    LOCAL -- the right choice for anything that intends to actually load
    the weights, as opposed to a lineage/history query.
    """
    candidates = [c for c in list_checkpoints(model_id) if c.validation_state != "CORRUPT"]
    if require_loadable:
        candidates = [c for c in candidates if c.is_loadable()]
    if not candidates:
        return None
    return max(candidates, key=lambda c: c.created_at)
