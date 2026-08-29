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
from pathlib import Path

from orca.config import ORCA_HOME
from orca.registry._ids import validate_id
from orca.registry.dataset_manifest import sha256_of_file

CHECKPOINT_DIR = ORCA_HOME / "registry" / "checkpoints"
CHECKPOINT_DIR.mkdir(parents=True, exist_ok=True)


class CorruptCheckpointError(Exception):
    pass


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
        return True


def list_checkpoints(model_id: str | None = None) -> list[CheckpointRecord]:
    records = []
    for p in sorted(CHECKPOINT_DIR.glob("*.json")):
        with open(p) as f:
            rec = CheckpointRecord(**json.load(f))
        if model_id is None or rec.model_id == model_id:
            records.append(rec)
    return records


def latest_good_checkpoint(model_id: str) -> CheckpointRecord | None:
    """Most recent checkpoint for a family that isn't marked CORRUPT."""
    candidates = [c for c in list_checkpoints(model_id) if c.validation_state != "CORRUPT"]
    if not candidates:
        return None
    return max(candidates, key=lambda c: c.created_at)
