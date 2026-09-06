"""
Complexity Assessment -- deterministic scoring, documented mapping to a
controlled enum (Phase 3 spec §9). Explicitly does NOT equate input length
with complexity: length is one of several signals, weighted low on its
own. Reuses orca/serve/routing.py's QueryComplexity (already real, tested,
rules-based complexity/freshness signal-detection) rather than
reimplementing pattern matching that already exists -- see
docs/orneur/phase-3/CURRENT_COGNITIVE_ORCHESTRATION.md's "duplicated
logic" section for why this reuse was a deliberate decision, not an
oversight.
"""
from __future__ import annotations

from orca.cognitive.contracts import ComplexityAssessment, ComplexityLevel, IntentPlan
from orca.serve.routing import classify_query

# Deterministic score -> level mapping, documented explicitly (never
# implicit thresholds scattered across call sites).
_LEVEL_THRESHOLDS: list[tuple[float, ComplexityLevel]] = [
    (0.85, ComplexityLevel.DEEP),
    (0.6, ComplexityLevel.HIGH),
    (0.35, ComplexityLevel.MEDIUM),
    (0.15, ComplexityLevel.LOW),
]


def _score_to_level(score: float) -> ComplexityLevel:
    for threshold, level in _LEVEL_THRESHOLDS:
        if score >= threshold:
            return level
    return ComplexityLevel.TRIVIAL


def assess_complexity(message: str, intent: IntentPlan) -> ComplexityAssessment:
    """
    Deterministic 0.0-1.0 score built from documented, bounded signal
    weights -- never raw word count alone. Signals:
      - routing.py's existing is_complex language match (0.30)
      - multi-label intent (more than one detected category) (0.15 per
        extra label, capped)
      - requires_reasoning / requires_agents / requires_tools each add a
        fixed weight, since each represents genuine additional subproblem
        structure, not just longer text
      - word count only contributes past a floor, and only a small amount
        -- a long but simple message must not outrank a short but
        multi-step one
    """
    factors: list[str] = []
    score = 0.0

    complexity = classify_query(message)
    if complexity.is_complex:
        score += 0.30
        factors.append("complex-reasoning language matched")

    extra_labels = len(intent.secondary_intents)
    if extra_labels:
        contribution = min(0.15 * extra_labels, 0.30)
        score += contribution
        factors.append(f"multi-label intent ({extra_labels} secondary intent(s))")

    if intent.requires_reasoning:
        score += 0.15
        factors.append("requires_reasoning")
    if intent.requires_tools:
        score += 0.10
        factors.append("requires_tools")
    if intent.requires_agents:
        score += 0.20
        factors.append("requires_agents")

    if complexity.word_count > 60:
        score += 0.10
        factors.append(f"long query ({complexity.word_count} words)")
    elif complexity.word_count > 25:
        score += 0.05
        factors.append(f"moderate-length query ({complexity.word_count} words)")

    score = min(score, 1.0)
    if not factors:
        factors.append("no complexity signals found")

    return ComplexityAssessment(level=_score_to_level(score), score=round(score, 3), factors=factors)
