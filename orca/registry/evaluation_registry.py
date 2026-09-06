"""
Evaluation reports as versioned, first-class artifacts, distinguishing
MEASURED from UNMEASURED metrics explicitly -- a missing metric must never
be silently treated as zero or as passing. Promotion gating reuses the
project's EXISTING governance thresholds (orca/governance/model_cards.py's
PERSONA_CLAIM_THRESHOLDS) rather than inventing new, easier ones, per
explicit instruction: "For Novus, preserve existing repository governance
requirements rather than inventing easier thresholds."
"""
from __future__ import annotations

import json
from dataclasses import asdict, dataclass, field
from datetime import datetime, timezone
from pathlib import Path

from orca.config import ORCA_HOME
from orca.governance.model_cards import PERSONA_CLAIM_THRESHOLDS
from orca.registry._ids import validate_id
from orca.registry.training_run import _current_git_sha

EVALUATION_REGISTRY_DIR = ORCA_HOME / "registry" / "evaluations"
EVALUATION_REGISTRY_DIR.mkdir(parents=True, exist_ok=True)

UNMEASURED = "UNMEASURED"


@dataclass
class EvaluationReport:
    evaluation_id: str
    checkpoint_id: str
    family: str                      # "genesis" | "novus" | "aeternum"
    evaluator_version: str            # e.g. "orca.train.redteam@<git_sha>"
    dataset_version: str
    metrics: dict                     # metric_name -> float, OR UNMEASURED (the string sentinel) if not run
    acceptance_thresholds: dict        # the threshold dict actually used for this decision
    timestamp: str = field(default_factory=lambda: datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ"))
    code_sha: str = field(default_factory=_current_git_sha)
    pass_fail_status: str = "PENDING"  # PENDING | PROMOTABLE | NOT_PROMOTABLE
    failure_reasons: list[str] = field(default_factory=list)

    def manifest_path(self) -> Path:
        validate_id(self.evaluation_id, "evaluation_id")
        return EVALUATION_REGISTRY_DIR / f"{self.evaluation_id}.json"

    def save(self) -> Path:
        path = self.manifest_path()
        with open(path, "w") as f:
            json.dump(asdict(self), f, indent=2)
        return path

    @classmethod
    def load(cls, evaluation_id: str) -> "EvaluationReport":
        validate_id(evaluation_id, "evaluation_id")
        path = EVALUATION_REGISTRY_DIR / f"{evaluation_id}.json"
        with open(path) as f:
            return cls(**json.load(f))


def _family_to_threshold_key(family: str) -> str:
    return {"genesis": "nano", "novus": "core", "aeternum": "ultra"}.get(family, family)


def evaluate_promotion(report: EvaluationReport) -> EvaluationReport:
    """
    Applies the project's real governance thresholds (PERSONA_CLAIM_THRESHOLDS)
    to this report's metrics. A metric that is UNMEASURED (not just below
    threshold) fails the gate -- missing evidence is never treated as
    passing. Mutates and returns the report with pass_fail_status set.
    """
    key = _family_to_threshold_key(report.family)
    thresholds = PERSONA_CLAIM_THRESHOLDS.get(key, PERSONA_CLAIM_THRESHOLDS["core"])
    report.acceptance_thresholds = dict(thresholds)

    reasons: list[str] = []

    required_metrics = {
        "eval_accuracy": ("min", thresholds["eval_accuracy"] * 100),
        "jailbreak_block_rate": ("min", thresholds["jailbreak_block_rate"]),
        "bias_flag_rate": ("max", thresholds["bias_flag_rate_max"]),
        "domain_eval": ("min", thresholds["domain_eval_min"] * 100),
    }

    for metric, (direction, threshold_value) in required_metrics.items():
        value = report.metrics.get(metric, UNMEASURED)
        if value == UNMEASURED or value is None:
            reasons.append(f"{metric} is UNMEASURED -- cannot promote without measured evidence")
            continue
        if direction == "min" and value < threshold_value:
            reasons.append(f"{metric} {value} is below required minimum {threshold_value}")
        if direction == "max" and value > threshold_value:
            reasons.append(f"{metric} {value} exceeds required maximum {threshold_value}")

    report.failure_reasons = reasons
    report.pass_fail_status = "NOT_PROMOTABLE" if reasons else "PROMOTABLE"
    report.save()
    return report


def list_evaluations(checkpoint_id: str | None = None) -> list[EvaluationReport]:
    reports = []
    for p in sorted(EVALUATION_REGISTRY_DIR.glob("*.json")):
        with open(p) as f:
            rep = EvaluationReport(**json.load(f))
        if checkpoint_id is None or rep.checkpoint_id == checkpoint_id:
            reports.append(rep)
    return reports
