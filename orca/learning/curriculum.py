"""
Difficulty scoring (spec §18) and the deterministic CurriculumCompiler
(spec §45, §50).
"""
from __future__ import annotations

from collections import Counter
from dataclasses import dataclass, field

from orca.learning.contracts import CurriculumCandidate, FailureEvent

# Structured, disclosed weighting -- not an arbitrary "hard" label (spec
# §18's explicit instruction). Each factor is a real, inspectable count
# already present on the inputs, never a model's own subjective guess.
_WEIGHTS = {
    "reasoning_depth": 0.20,
    "retrieval_depth": 0.15,
    "tool_count": 0.10,
    "contradiction_count": 0.20,
    "context_length_norm": 0.10,
    "failure_frequency_norm": 0.15,
    "court_disagreement": 0.05,
    "confidence_mismatch": 0.05,
}


@dataclass
class DifficultyFactors:
    reasoning_depth: int = 0
    retrieval_depth: int = 0
    tool_count: int = 0
    contradiction_count: int = 0
    context_length_tokens: int = 0
    failure_frequency: int = 1
    court_disagreement: bool = False
    model_confidence: float = 0.5     # the model's own reported confidence
    ground_truth_confidence: float = 0.5  # verified/Truth-Fabric confidence


def score_difficulty(factors: DifficultyFactors) -> float:
    """Returns a value in [0, 1]. Each raw factor is normalized against a
    fixed, documented cap before weighting -- caps are conservative bounds
    on this project's own observed ranges (Court/Truth depth rarely exceeds
    these in practice), not tuned against any specific dataset."""
    confidence_mismatch = abs(factors.model_confidence - factors.ground_truth_confidence)
    normalized = {
        "reasoning_depth": min(factors.reasoning_depth / 5.0, 1.0),
        "retrieval_depth": min(factors.retrieval_depth / 5.0, 1.0),
        "tool_count": min(factors.tool_count / 5.0, 1.0),
        "contradiction_count": min(factors.contradiction_count / 3.0, 1.0),
        "context_length_norm": min(factors.context_length_tokens / 8192.0, 1.0),
        "failure_frequency_norm": min(factors.failure_frequency / 10.0, 1.0),
        "court_disagreement": 1.0 if factors.court_disagreement else 0.0,
        "confidence_mismatch": min(confidence_mismatch, 1.0),
    }
    return round(sum(_WEIGHTS[k] * normalized[k] for k in _WEIGHTS), 4)


@dataclass
class CurriculumBalanceReport:
    """Spec §50: track distribution to prevent one failure class dominating."""
    by_failure_type: Counter = field(default_factory=Counter)
    by_role: Counter = field(default_factory=Counter)
    by_model_family: Counter = field(default_factory=Counter)
    by_difficulty_band: Counter = field(default_factory=Counter)
    by_security_class: Counter = field(default_factory=Counter)
    total: int = 0


def _difficulty_band(d: float) -> str:
    if d < 0.25:
        return "EASY"
    if d < 0.5:
        return "MEDIUM"
    if d < 0.75:
        return "HARD"
    return "VERY_HARD"


def compute_balance(candidates: list[CurriculumCandidate]) -> CurriculumBalanceReport:
    report = CurriculumBalanceReport(total=len(candidates))
    for c in candidates:
        report.by_role[c.target_role.value if c.target_role else "UNASSIGNED"] += 1
        report.by_model_family[c.target_model_family.value] += 1
        report.by_difficulty_band[_difficulty_band(c.difficulty)] += 1
        report.by_security_class[c.security_class.value] += 1
    return report


class CurriculumCompiler:
    """
    Spec §45: deterministic compiler from approved candidates to versioned
    dataset records. No hidden free-form transformation without provenance
    -- every compiled record carries its candidate_id and failure_ids back,
    and the compiler itself performs no model calls (an LLM may assist
    upstream candidate authoring, per spec §45, but that is a separate,
    schema-validated, human-reviewed step BEFORE compilation, never inside
    this deterministic function).
    """

    def compile(self, candidates: list[CurriculumCandidate]) -> list[dict]:
        records = []
        for c in candidates:
            records.append({
                "candidate_id": c.candidate_id,
                "failure_ids": list(c.failure_ids),
                "task_type": c.task_type,
                "target_role": c.target_role.value if c.target_role else None,
                "target_model_family": c.target_model_family.value,
                "input": c.input_summary,
                "expected_behavior": c.expected_behavior,
                "negative_behavior": c.negative_behavior,
                "evidence_refs": list(c.evidence_refs),
                "difficulty": c.difficulty,
                "is_synthetic": c.is_synthetic,
                "synthetic_generator_model": c.synthetic_generator_model,
                "synthetic_generator_checkpoint": c.synthetic_generator_checkpoint,
                "synthetic_generation_ref": c.synthetic_generation_ref,
                "synthetic_verification_state": c.synthetic_verification_state.value,
                "source_lineage": list(c.source_lineage),
            })
        return records
