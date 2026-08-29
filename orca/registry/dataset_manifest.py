"""
Versioned dataset manifests -- every future training run should reference
an immutable dataset identity instead of a bare filename. This is the gap
identified in docs/orneur/phase-0/MODEL_TRAINING_STATUS.md: "no dataset
versioning or checksums anywhere in the repo, for any tier."

Manifests are persisted as JSON under ORCA_HOME/registry/datasets/ so they
survive across processes and are inspectable outside Python.
"""
from __future__ import annotations

import hashlib
import json
from dataclasses import asdict, dataclass, field
from datetime import datetime, timezone
from pathlib import Path

from orca.config import ORCA_HOME
from orca.registry._ids import validate_id

DATASET_MANIFEST_DIR = ORCA_HOME / "registry" / "datasets"
DATASET_MANIFEST_DIR.mkdir(parents=True, exist_ok=True)


def sha256_of_file(path: Path) -> str:
    h = hashlib.sha256()
    with open(path, "rb") as f:
        for chunk in iter(lambda: f.read(1 << 20), b""):
            h.update(chunk)
    return h.hexdigest()


@dataclass
class DatasetManifest:
    dataset_id: str            # e.g. "orneur-novus-combined-safety-calibration"
    version: str                # e.g. "v2"
    purpose: str                 # e.g. "joint safety+calibration SFT"
    source_paths: list[str]      # human-readable source file paths/domains
    record_count: int
    schema: str                  # e.g. '{"text": str}'
    train_checksum: str
    eval_checksum: str
    creation_code_sha: str        # git SHA of the build script's repo state
    filters_applied: str
    deduplication_result: str
    known_limitations: list[str] = field(default_factory=list)
    created_at: str = field(default_factory=lambda: datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ"))

    def manifest_path(self) -> Path:
        validate_id(self.dataset_id, "dataset_id")
        validate_id(self.version, "version")
        return DATASET_MANIFEST_DIR / f"{self.dataset_id}-{self.version}.json"

    def save(self) -> Path:
        path = self.manifest_path()
        with open(path, "w") as f:
            json.dump(asdict(self), f, indent=2)
        return path

    @classmethod
    def load(cls, dataset_id: str, version: str) -> "DatasetManifest":
        validate_id(dataset_id, "dataset_id")
        validate_id(version, "version")
        path = DATASET_MANIFEST_DIR / f"{dataset_id}-{version}.json"
        if not path.exists():
            raise FileNotFoundError(f"No dataset manifest at {path}")
        with open(path) as f:
            return cls(**json.load(f))

    def verify_against_files(self, train_path: Path, eval_path: Path) -> tuple[bool, str]:
        """Re-hashes the actual files and confirms they match this manifest's recorded checksums."""
        actual_train = sha256_of_file(train_path)
        actual_eval = sha256_of_file(eval_path)
        if actual_train != self.train_checksum:
            return False, f"train checksum mismatch: manifest={self.train_checksum} actual={actual_train}"
        if actual_eval != self.eval_checksum:
            return False, f"eval checksum mismatch: manifest={self.eval_checksum} actual={actual_eval}"
        return True, "ok"


def list_manifests() -> list[str]:
    return sorted(p.stem for p in DATASET_MANIFEST_DIR.glob("*.json"))
