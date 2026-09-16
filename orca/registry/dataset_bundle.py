"""
Dataset BUNDLE manifest -- binds the exact combined train/eval files a
canonical training run actually consumes when built from MULTIPLE source
DatasetManifest records. Phase 21B.2 closure: prior canonical training
accepted multiple dataset_manifest_ids by checking only that each named
manifest EXISTS ("v1 exists, v2 exists"), never that the actual combined
file bytes about to be trained on came from those exact sources. This is
existence-only provenance, not binding provenance -- forbidden for
canonical (family-set) training by orca.registry.provenance.
verify_dataset_binding().

A DatasetBundleManifest is the single-manifest case's DatasetManifest,
one layer up: it names its own train_checksum/eval_checksum (the exact
combined bytes), AND records which source DatasetManifest ids/versions/
digests went into building it -- full lineage, not just a list of names.
"""
from __future__ import annotations

import json
from dataclasses import asdict, dataclass, field
from datetime import datetime, timezone
from pathlib import Path

from orca.config import ORCA_HOME
from orca.registry._ids import validate_id
from orca.registry.dataset_manifest import sha256_of_file

DATASET_BUNDLE_DIR = ORCA_HOME / "registry" / "dataset_bundles"
DATASET_BUNDLE_DIR.mkdir(parents=True, exist_ok=True)


@dataclass(frozen=True)
class SourceManifestLineage:
    dataset_manifest_id: str  # "<dataset_id>-<version>"
    train_checksum: str
    eval_checksum: str


@dataclass
class DatasetBundleManifest:
    bundle_id: str
    version: str
    source_manifests: list[SourceManifestLineage]
    train_checksum: str        # sha256 of the exact combined train file
    eval_checksum: str          # sha256 of the exact combined eval file
    held_out_checksum: str | None = None
    record_count: int = 0
    creation_code_sha: str = ""
    creation_procedure: str = ""  # human-readable description of how sources were combined
    seed: int | None = None
    created_at: str = field(default_factory=lambda: datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ"))

    def manifest_path(self) -> Path:
        validate_id(self.bundle_id, "bundle_id")
        validate_id(self.version, "version")
        return DATASET_BUNDLE_DIR / f"{self.bundle_id}-{self.version}.json"

    def save(self) -> Path:
        path = self.manifest_path()
        payload = asdict(self)
        with open(path, "w") as f:
            json.dump(payload, f, indent=2)
        return path

    @classmethod
    def load(cls, bundle_id: str, version: str) -> "DatasetBundleManifest":
        validate_id(bundle_id, "bundle_id")
        validate_id(version, "version")
        path = DATASET_BUNDLE_DIR / f"{bundle_id}-{version}.json"
        if not path.exists():
            raise FileNotFoundError(f"No dataset bundle manifest at {path}")
        with open(path) as f:
            raw = json.load(f)
        raw = dict(raw)
        raw["source_manifests"] = [SourceManifestLineage(**s) for s in raw["source_manifests"]]
        return cls(**raw)

    def verify_against_files(self, train_path: Path, eval_path: Path) -> tuple[bool, str]:
        """Re-hashes the actual combined files and confirms they match
        this bundle's recorded checksums -- the cryptographic check
        that closes the existence-only multi-manifest loophole."""
        actual_train = sha256_of_file(train_path)
        actual_eval = sha256_of_file(eval_path)
        if actual_train != self.train_checksum:
            return False, f"bundle train checksum mismatch: manifest={self.train_checksum} actual={actual_train}"
        if actual_eval != self.eval_checksum:
            return False, f"bundle eval checksum mismatch: manifest={self.eval_checksum} actual={actual_eval}"
        return True, "ok"
