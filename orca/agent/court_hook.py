"""
Explicit Cognitive Court runtime integration (Phase 8.1 spec §19-21).
Court is advisory/deliberative for agent plans -- Court ACCEPT NEVER
authorizes an action; `orca.agent.policy.evaluate_policy()` remains the
sole authorization boundary, completely unaware Court was ever consulted
(no import of `orca.deliberation` anywhere in `orca/agent/policy.py`).
"""
from __future__ import annotations

from orca.agent.contracts import ActionRiskLevel, AgentGoal, SideEffectClass


def should_request_court_review(goal: AgentGoal, *, has_unresolved_contradiction: bool = False) -> bool:
    """
    Real, structured triggers only (spec §19) -- never "the plan is
    complex" alone: HIGH/CRITICAL risk, an unresolved evidence
    contradiction, AUDIT_GRADE evidence requirement, or a
    DESTRUCTIVE-class allowed action (irreversible/dangerous enough to
    warrant deliberative review before even reaching Policy).
    """
    if goal.risk in (ActionRiskLevel.HIGH, ActionRiskLevel.CRITICAL):
        return True
    if has_unresolved_contradiction:
        return True
    if goal.evidence_requirement == "AUDIT_GRADE":
        return True
    if SideEffectClass.DESTRUCTIVE in goal.allowed_action_classes:
        return True
    return False


async def request_court_review(objective: str, *, truth_result=None, risk_level=None, budget=None):
    """
    Runs ONE bounded Cognitive Court round (Phase 6/7, unchanged) --
    consumes the EXISTING shared `CognitiveBudget` (spec §21: "do not give
    Agent Runtime a fresh deliberation budget"), never a second,
    independent deliberation allocation. Returns the real `CourtVerdict`.
    Callers record it in `AgentTrace` for audit but MUST NOT treat
    `ACCEPT` as permission to execute -- that decision is, and remains,
    `orca.agent.policy.evaluate_policy()`'s alone.
    """
    from orca.cognitive.contracts import RiskLevel
    from orca.deliberation.court import CognitiveCourt

    court = CognitiveCourt()
    case, verdict, stop_reason = await court.run(
        objective, truth_result=truth_result, risk_level=risk_level or RiskLevel.LOW, budget=budget,
    )
    return case, verdict, stop_reason
