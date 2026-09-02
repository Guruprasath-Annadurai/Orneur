"""
First real, bounded replan execution (Phase 7 spec §31-33). Phase 6 only
had trigger CONTRACTS (`ReasoningPlan.completion_conditions`) with no
running loop -- this module is the loop, bounded by `MAX_REPLANS` and
scoped to LOCAL plan revisions (spec §32: never regenerate the whole plan
by default).
"""
from __future__ import annotations

from dataclasses import dataclass, field
from enum import Enum

from orca.deliberation.contracts import CourtVerdictState, ReasoningPlan

MAX_REPLANS = 2


class ReplanTrigger(str, Enum):
    HYPOTHESIS_FALSIFIED = "HYPOTHESIS_FALSIFIED"
    CRITICAL_EVIDENCE_CONTRADICTION = "CRITICAL_EVIDENCE_CONTRADICTION"
    TOOL_RUNTIME_FAILURE = "TOOL_RUNTIME_FAILURE"
    MODEL_UNAVAILABLE = "MODEL_UNAVAILABLE"
    WORLD_STATE_CHANGE = "WORLD_STATE_CHANGE"
    BUDGET_CHANGE = "BUDGET_CHANGE"
    COMPLETION_CONDITION_FAILED = "COMPLETION_CONDITION_FAILED"
    COURT_REVISE = "COURT_REVISE"


@dataclass
class ReplanEvent:
    trigger: ReplanTrigger
    from_version: int
    to_version: int
    revision: str
    reason: str


@dataclass
class ReplanState:
    """Tracks how many replans a single request has consumed -- bounded,
    never recursive/unbounded (spec §31's explicit MAX_REPLANS cap)."""
    count: int = 0
    events: list[ReplanEvent] = field(default_factory=list)

    def can_replan(self) -> bool:
        return self.count < MAX_REPLANS


def revise_plan_for_court_verdict(plan: ReasoningPlan, verdict: CourtVerdictState, state: ReplanState) -> ReasoningPlan:
    """
    A LOCAL revision (spec §32): on REVISE, add a verification/falsification
    round rather than regenerating the whole plan. Bounded by `state`
    (raises if the request has already exhausted MAX_REPLANS -- caller
    must check `state.can_replan()` first and abstain honestly if not).
    """
    if not state.can_replan():
        raise ReplanBudgetExhaustedError(f"MAX_REPLANS={MAX_REPLANS} already reached for this request")

    if verdict == CourtVerdictState.REVISE:
        revised = ReasoningPlan(
            goal=plan.goal,
            mode=plan.mode,
            subproblems=list(plan.subproblems),
            requires_hypotheses=plan.requires_hypotheses,
            evidence_needs=list(plan.evidence_needs),
            requires_falsification=True,
            requires_counterfactual=plan.requires_counterfactual,
            requires_court=True,
            max_rounds=plan.max_rounds,
            max_hypotheses=plan.max_hypotheses,
            model_policy_hint=plan.model_policy_hint,
            completion_conditions=list(plan.completion_conditions),
            reasons=list(plan.reasons) + [f"replan: Court REVISE at v{plan.version}"],
            version=plan.version + 1,
            parent_version=plan.version,
            revision_reason="Court verdict REVISE -- added a bounded second falsification round",
        )
        state.count += 1
        state.events.append(
            ReplanEvent(
                trigger=ReplanTrigger.COURT_REVISE, from_version=plan.version, to_version=revised.version,
                revision="added falsification round", reason=revised.revision_reason,
            )
        )
        return revised

    return plan


class ReplanBudgetExhaustedError(Exception):
    pass
