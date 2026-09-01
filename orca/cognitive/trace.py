"""
CognitiveTrace construction -- the Cognitive Flight Recorder (Phase 3 spec
§25-26). A CognitiveTraceBuilder accumulates short, structured, auditable
decision labels as the Kernel progresses; it never stores raw model output
or chain-of-thought, only labels like "freshness=CURRENT" or "model
unavailable" (Phase 3 spec §26).
"""
from __future__ import annotations

import time

from orca.cognitive.contracts import (
    AbstentionReason,
    CognitiveBudget,
    CognitivePlan,
    CognitiveTrace,
    ModelPolicyCharacteristic,
    StateTransition,
)


class CognitiveTraceBuilder:
    def __init__(self, request_id: str, trace_id: str):
        self._trace = CognitiveTrace(request_id=request_id, trace_id=trace_id)
        self._start = time.monotonic()

    def record_plan(self, plan: CognitivePlan) -> None:
        t = self._trace
        t.intent_decision = plan.intent.primary_intent.value
        t.complexity = plan.complexity.level
        t.risk = plan.risk.level
        t.freshness = plan.freshness.level
        t.evidence_requirement = plan.evidence_requirement.level
        t.model_policy = plan.model_policy.characteristic
        t.plan_operations = [op.type.value for op in plan.operations]
        t.budget_allocated = _budget_snapshot(plan.budget)
        t.decision_explanations.extend(f"complexity: {r}" for r in plan.complexity.factors)
        t.decision_explanations.extend(f"risk: {r}" for r in plan.risk.factors)
        t.decision_explanations.extend(f"freshness: {r}" for r in plan.freshness.reasons)
        t.decision_explanations.extend(f"evidence: {r}" for r in plan.evidence_requirement.reasons)
        t.decision_explanations.extend(f"model_policy: {r}" for r in plan.model_policy.reasons)

    def record_transition(self, transition: StateTransition) -> None:
        self._trace.state_transitions.append(transition)

    def record_operation_outcome(self, outcome: str) -> None:
        self._trace.operation_outcomes.append(outcome)

    def record_model_resolved(self, model: str | None) -> None:
        self._trace.model_resolved = model

    def record_abstention(self, reason: AbstentionReason) -> None:
        self._trace.abstention_reason = reason
        self._trace.decision_explanations.append(f"abstained: {reason.value}")

    def record_reconciliation(self, effective) -> None:
        """`effective` is an EffectiveExecutionPolicy (Phase 3.1) -- typed
        loosely here to avoid a circular import (reconciliation.py imports
        contracts.py); only enum values/short strings are ever stored."""
        t = self._trace
        t.entitlement_ceiling = effective.permitted_ceiling.value
        t.effective_capability = effective.resolved_characteristic.value
        t.reconciliation_outcome = effective.outcome.value
        t.resolved_tier = effective.resolved_tier
        t.decision_explanations.append(f"reconciliation: {effective.reason}")

    def finalize(self, budget: CognitiveBudget | None = None) -> CognitiveTrace:
        self._trace.latency_ms = (time.monotonic() - self._start) * 1000
        if budget is not None:
            self._trace.resource_consumption = _consumption_snapshot(budget)
        return self._trace


def _budget_snapshot(budget: CognitiveBudget) -> dict:
    return {
        "max_tokens": budget.max_tokens,
        "max_latency_ms": budget.max_latency_ms,
        "max_model_calls": budget.max_model_calls,
        "max_retrieval_calls": budget.max_retrieval_calls,
        "max_tool_calls": budget.max_tool_calls,
        "max_agent_calls": budget.max_agent_calls,
        "max_reasoning_rounds": budget.max_reasoning_rounds,
    }


def _consumption_snapshot(budget: CognitiveBudget) -> dict:
    return {
        "consumed_tokens": budget.consumed_tokens,
        "consumed_model_calls": budget.consumed_model_calls,
        "consumed_latency_ms": budget.consumed_latency_ms,
    }
