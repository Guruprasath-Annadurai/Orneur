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


class DatasetFrozenError(Exception):
    pass


def sha256_of_file(path: Path) -> str:
    h = hashlib.sha256()
    with open(path, "rb") as f:
        for chunk in iter(lambda: f.read(1 << 20), b""):
            h.update(chunk)
    return h.hexdigest()


class DatasetApprovalState:
    """Phase 12 spec §25 -- string constants, not an Enum, to keep this
    dataclass's existing json.load(**dict) round-trip untouched."""
    DRAFT = "DRAFT"
    REVIEWED = "REVIEWED"
    APPROVED = "APPROVED"
    FROZEN = "FROZEN"
    RETIRED = "RETIRED"


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
    # ---- Phase 12 additions (all additive, all default-backward-compatible
    # with every manifest ever saved before this phase) ----
    approval_state: str = DatasetApprovalState.DRAFT
    approved_by: str | None = None
    approved_at: str | None = None
    frozen: bool = False
    frozen_at: str | None = None
    candidate_ids: list[str] = field(default_factory=list)          # spec §24: sample -> curriculum candidate lineage
    failure_ids: list[str] = field(default_factory=list)             # spec §24: sample -> FailureEvent lineage
    split_group_keys: dict = field(default_factory=dict)             # spec §22: {"train": [...], "val": [...], "test": [...]} of GROUP keys, not raw sample ids
    holdout_checksum: str | None = None                               # spec §23: protected holdout, checksum only -- content lives outside the training-visible manifest fields
    target_model_family: str = ""
    target_role: str | None = None

    def manifest_path(self) -> Path:
        validate_id(self.dataset_id, "dataset_id")
        validate_id(self.version, "version")
        return DATASET_MANIFEST_DIR / f"{self.dataset_id}-{self.version}.json"

    def save(self) -> Path:
        """
        Phase 12 spec §51: a frozen manifest must never mutate in place --
        the only way to change a frozen dataset's content is a NEW version
        with lineage, never an overwrite of this same version's file.

        The check reads the EXISTING ON-DISK copy's own `frozen` field
        (not merely this Python object's in-memory `frozen` flag, and not
        merely "does a file exist at this path") -- this is what makes the
        guard correct across separate processes/runs: the first save of a
        newly-frozen manifest is allowed even though this exact dataset_id+
        version's path may already exist from an earlier, not-yet-frozen
        save of the same manifest; only a save attempted against a path
        whose PERSISTED content is already frozen is rejected.
        """
        path = self.manifest_path()
        if path.exists():
            with open(path) as f:
                existing = json.load(f)
            if existing.get("frozen"):
                raise DatasetFrozenError(
                    f"Dataset '{self.dataset_id}-{self.version}' is FROZEN on disk -- cannot overwrite. "
                    f"Create a new version instead (spec §51)."
                )
        with open(path, "w") as f:
            json.dump(asdict(self), f, indent=2)
        return path

    def approve(self, approved_by: str) -> None:
        """Spec §25: frozen training dataset requires policy/human approval,
        never an automatic 'candidate count reached threshold -> train.'"""
        if approved_by.startswith("model:"):
            raise ValueError(f"Reviewer '{approved_by}' looks like a model identity -- models cannot approve datasets (spec §69).")
        self.approval_state = DatasetApprovalState.APPROVED
        self.approved_by = approved_by
        self.approved_at = datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")

    def freeze(self) -> None:
        if self.approval_state != DatasetApprovalState.APPROVED:
            raise ValueError(
                f"Cannot freeze dataset '{self.dataset_id}-{self.version}' in approval_state="
                f"{self.approval_state}; must be APPROVED first (spec §25)."
            )
        self.frozen = True
        self.frozen_at = datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")
        self.approval_state = DatasetApprovalState.FROZEN

    def check_split_safety(self) -> list[str]:
        """
        Spec §22: group-aware split safety -- candidates derived from the
        same root failure family must not appear across multiple splits.
        `split_group_keys` maps split name -> list of GROUP keys (e.g. a
        shared root failure_id or dedupe-fingerprint family), not raw
        sample ids. Returns a list of violation descriptions; empty means
        safe.
        """
        violations = []
        splits = list(self.split_group_keys.items())
        for i, (split_a, keys_a) in enumerate(splits):
            for split_b, keys_b in splits[i + 1:]:
                overlap = set(keys_a) & set(keys_b)
                if overlap:
                    violations.append(f"group keys {sorted(overlap)} appear in both '{split_a}' and '{split_b}'")
        return violations

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
