"""
Evaluation SUITE manifest -- the immutable definition of an evaluation
suite's task set, distinct from orca.registry.evaluation_registry
.EvaluationReport (which records a candidate's RESULT against a suite,
not the suite's own definition). Mirrors orca.registry.dataset_manifest
.DatasetManifest's freeze semantics exactly, per Phase 21B.3 spec
section 19: "Once a real base-model baseline is recorded against the
suite: freeze that suite version. Future changes require genesis-eval-v2.
Never silently rewrite v1 after seeing model results."

No baseline has been recorded against genesis-eval-v1 as of this
closure (no training or evaluation execution has happened -- Phase
21B.3 explicitly forbids it), so the suite is intentionally left
UNFROZEN here; freezing happens at the first real baseline recording,
not at suite-authoring time.
"""
from __future__ import annotations

import hashlib
import json
from dataclasses import asdict, dataclass, field
from datetime import datetime, timezone
from pathlib import Path

from orca.config import ORCA_HOME
from orca.registry._ids import validate_id

EVALUATION_SUITE_DIR = ORCA_HOME / "registry" / "evaluation_suites"
EVALUATION_SUITE_DIR.mkdir(parents=True, exist_ok=True)


class EvaluationSuiteFrozenError(Exception):
    pass


@dataclass
class EvaluationSuiteManifest:
    suite_id: str                      # e.g. "genesis-eval"
    version: str                        # e.g. "v1"
    task_ids: list[str]                 # every task_id in this suite, sorted
    content_digest: str                 # sha256 over the canonical JSON of every task's content
    scoring_contract_digest: str        # sha256 over the canonical JSON of every task's scoring contract
    creation_code_sha: str
    category_task_counts: dict[str, int] = field(default_factory=dict)  # {"1": 30, "2": 5, ...}
    frozen: bool = False
    frozen_at: str | None = None
    created_at: str = field(default_factory=lambda: datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ"))

    def manifest_path(self) -> Path:
        validate_id(self.suite_id, "suite_id")
        validate_id(self.version, "version")
        return EVALUATION_SUITE_DIR / f"{self.suite_id}-{self.version}.json"

    def save(self) -> Path:
        """Mirrors DatasetManifest.save()'s frozen-on-disk guard exactly:
        the only way to change a frozen suite version's content is a NEW
        version, never an overwrite of this same version's file."""
        path = self.manifest_path()
        if path.exists():
            with open(path) as f:
                existing = json.load(f)
            if existing.get("frozen"):
                raise EvaluationSuiteFrozenError(
                    f"Evaluation suite '{self.suite_id}-{self.version}' is FROZEN on disk -- cannot "
                    f"overwrite. Create a new version instead (e.g. genesis-eval-v2)."
                )
        with open(path, "w") as f:
            json.dump(asdict(self), f, indent=2)
        return path

    def freeze(self) -> None:
        """Called once a real baseline/candidate score has been recorded
        against this suite version -- after this, save() refuses to
        overwrite the on-disk copy."""
        self.frozen = True
        self.frozen_at = datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")

    @classmethod
    def load(cls, suite_id: str, version: str) -> "EvaluationSuiteManifest":
        validate_id(suite_id, "suite_id")
        validate_id(version, "version")
        path = EVALUATION_SUITE_DIR / f"{suite_id}-{version}.json"
        if not path.exists():
            raise FileNotFoundError(f"No evaluation suite manifest at {path}")
        with open(path) as f:
            return cls(**json.load(f))

    def verify_against_tasks(self, tasks: list) -> tuple[bool, str]:
        """Re-derives content_digest/scoring_contract_digest/task_ids
        from the ACTUAL current in-code task list and compares against
        this manifest's recorded values -- the same "recorded checksum
        vs freshly recomputed digest" pattern DatasetManifest.
        verify_against_files() uses, applied to code-defined tasks
        instead of files."""
        from orca.eval.genesis_suite import compute_suite_digests  # local import: avoid a module cycle

        actual_task_ids, actual_content_digest, actual_scoring_digest = compute_suite_digests(tasks)
        if actual_task_ids != self.task_ids:
            return False, f"task_ids mismatch: manifest has {len(self.task_ids)}, actual has {len(actual_task_ids)}"
        if actual_content_digest != self.content_digest:
            return False, f"content_digest mismatch: manifest={self.content_digest} actual={actual_content_digest}"
        if actual_scoring_digest != self.scoring_contract_digest:
            return False, f"scoring_contract_digest mismatch: manifest={self.scoring_contract_digest} actual={actual_scoring_digest}"
        return True, "ok"


def sha256_of_json(obj) -> str:
    canonical = json.dumps(obj, sort_keys=True, separators=(",", ":"))
    return hashlib.sha256(canonical.encode("utf-8")).hexdigest()
