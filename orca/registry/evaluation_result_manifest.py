"""
Evaluation RESULT manifest -- a single candidate model's full run against
a specific evaluation-suite version. Distinct from
orca.registry.evaluation_registry.EvaluationReport (the pre-existing
promotion-gate record, keyed to a CheckpointRecord and the project's
PERSONA_CLAIM_THRESHOLDS governance) and from
orca.registry.evaluation_suite_manifest.EvaluationSuiteManifest (the
suite's own immutable task-set definition, not a candidate's results
against it). This module is the RESULT side of the Phase 21B.4 baseline-
freeze transaction -- see orca.eval.baseline.record_baseline_and_freeze_suite()
for the fail-closed transaction that couples a result's persistence to
the suite's freeze.
"""
from __future__ import annotations

import json
from dataclasses import asdict, dataclass, field
from datetime import datetime, timezone
from pathlib import Path

from orca.config import ORCA_HOME
from orca.registry._ids import validate_id

EVALUATION_RESULT_DIR = ORCA_HOME / "registry" / "evaluation_results"
EVALUATION_RESULT_DIR.mkdir(parents=True, exist_ok=True)


@dataclass
class EvaluationResultManifest:
    run_id: str
    candidate: str                          # logical candidate name, e.g. "qwen3-8b"
    upstream_model: str                     # canonical upstream HF repo id, e.g. "Qwen/Qwen3-8B"
    artifact_repo: str                      # actual artifact repo/mirror used for inference, e.g. "unsloth/Qwen3-8B"
    exact_revision: str                     # exact commit SHA actually used -- never "main"/a branch
    tokenizer_revision: str | None
    backend: str                            # e.g. "transformers", "vllm", "ollama"
    quantization: str
    inference_config: dict                  # {"temperature": ..., "top_p": ..., "max_new_tokens": ...}
    seed: int | None
    context_window_used: int
    system_instruction_digest: str
    software_commit_sha: str
    hardware: dict
    suite_id: str
    suite_version: str
    suite_content_digest: str
    suite_scoring_contract_digest: str
    per_task_results: list[dict] = field(default_factory=list)
    per_category_summary: dict = field(default_factory=dict)
    deterministic_summary: dict = field(default_factory=dict)
    unscored_categories: list[str] = field(default_factory=list)
    generation_failures: list[dict] = field(default_factory=list)
    started_at: str = field(default_factory=lambda: datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ"))
    completed_at: str | None = None
    # Phase 21B.4 baseline-freeze transaction fields (see orca.eval.baseline):
    is_first_baseline: bool = False   # True only for the exact run that triggered the suite freeze
    finalized: bool = False           # True only once the coupled freeze transaction fully committed

    def manifest_path(self) -> Path:
        validate_id(self.run_id, "run_id")
        return EVALUATION_RESULT_DIR / f"{self.run_id}.json"

    def save(self) -> Path:
        path = self.manifest_path()
        with open(path, "w") as f:
            json.dump(asdict(self), f, indent=2)
        return path

    def delete(self) -> None:
        """Used only by the baseline-freeze rollback path (orca.eval.baseline)
        when a staged, not-yet-finalized result must be removed because
        the coupled suite-freeze failed -- never called on a finalized
        result."""
        self.manifest_path().unlink(missing_ok=True)

    @classmethod
    def load(cls, run_id: str) -> "EvaluationResultManifest":
        validate_id(run_id, "run_id")
        path = EVALUATION_RESULT_DIR / f"{run_id}.json"
        if not path.exists():
            raise FileNotFoundError(f"No evaluation result manifest for '{run_id}'")
        with open(path) as f:
            return cls(**json.load(f))


def list_results(suite_id: str | None = None, suite_version: str | None = None) -> list[EvaluationResultManifest]:
    results = []
    for p in sorted(EVALUATION_RESULT_DIR.glob("*.json")):
        with open(p) as f:
            r = EvaluationResultManifest(**json.load(f))
        if suite_id is not None and r.suite_id != suite_id:
            continue
        if suite_version is not None and r.suite_version != suite_version:
            continue
        results.append(r)
    return results
