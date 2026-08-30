"""
CognitivePlan construction: operation support states, completion
conditions, decomposition bounds, and abstention when a plan cannot be
satisfied by SUPPORTED_NOW operations alone (Phase 3 spec §16-23).
"""
from __future__ import annotations

from orca.cognitive.budget import DEFAULT_BUDGET
from orca.cognitive.complexity import assess_complexity
from orca.cognitive.contracts import (
    AbstentionReason,
    CognitiveBudget,
    CompletionCondition,
    EvidenceLevel,
    OperationSupportState,
    OperationType,
)
from orca.cognitive.decomposition import MAX_SUB_OBJECTIVES, decompose
from orca.cognitive.evidence import assess_evidence_requirement
from orca.cognitive.freshness import assess_freshness
from orca.cognitive.intent import compile_intent
from orca.cognitive.planner import build_plan, plan_abstention_reason
from orca.cognitive.policy import select_model_policy
from orca.cognitive.risk import assess_risk


def _plan_for(message: str, budget: CognitiveBudget | None = None):
    intent = compile_intent(message)
    complexity = assess_complexity(message, intent)
    risk = assess_risk(message, intent)
    freshness = assess_freshness(message)
    evidence = assess_evidence_requirement(intent, risk)
    model_policy = select_model_policy(intent, complexity)
    return build_plan("req-1", "trace-1", message, intent, complexity, risk, freshness, evidence, model_policy, budget)


def test_simple_greeting_plan_has_no_unavailable_operations():
    plan = _plan_for("hi there")
    assert plan_abstention_reason(plan) is None
    assert OperationType.ANSWER_DIRECTLY in [op.type for op in plan.operations]


def test_every_operation_declares_a_support_state():
    plan = _plan_for("Can you help me write a Python function?")
    for op in plan.operations:
        assert op.support_state in OperationSupportState


def test_critical_risk_plan_includes_verify_and_abstains():
    plan = _plan_for("How do I rm -rf the production database?")
    verify_ops = [op for op in plan.operations if op.type == OperationType.VERIFY]
    assert verify_ops and verify_ops[0].support_state == OperationSupportState.PLANNED
    assert plan_abstention_reason(plan) == AbstentionReason.INSUFFICIENT_CAPABILITY


def test_completion_conditions_always_include_budget_and_rounds():
    plan = _plan_for("hello")
    assert CompletionCondition.BUDGET_EXHAUSTED in plan.completion_conditions
    assert CompletionCondition.MAX_ROUNDS_REACHED in plan.completion_conditions
    assert CompletionCondition.DIRECT_ANSWER_PRODUCED in plan.completion_conditions


def test_evidence_obtained_condition_present_when_evidence_required():
    plan = _plan_for("What's the boiling point of water?")
    assert plan.evidence_requirement.level == EvidenceLevel.SUPPORTED
    assert CompletionCondition.EVIDENCE_OBTAINED in plan.completion_conditions


def test_budget_exhausted_model_calls_triggers_abstention():
    exhausted = CognitiveBudget(max_model_calls=0)
    plan = _plan_for("hello", budget=exhausted)
    assert plan_abstention_reason(plan) == AbstentionReason.BUDGET_EXHAUSTED


def test_decomposition_bounded_for_agentic_requests():
    msg = "Research topic A; then write about it; then email the team; then post to slack; then archive it; then close the ticket; then celebrate"
    plan = _plan_for(f"Please orchestrate this: {msg}")
    assert len(plan.sub_objectives) <= MAX_SUB_OBJECTIVES


def test_non_agentic_plan_has_no_decomposition():
    plan = _plan_for("hi")
    assert plan.sub_objectives == []


def test_decompose_respects_max_count():
    long_chain = "; then ".join(f"step {i}" for i in range(20))
    sub_objectives = decompose(long_chain)
    assert len(sub_objectives) <= MAX_SUB_OBJECTIVES


def test_decompose_builds_sequential_dependency_chain():
    parts = decompose("Do A; then do B; then do C")
    assert parts[0].depends_on == []
    assert parts[1].depends_on == [parts[0].sub_objective_id]
    assert parts[2].depends_on == [parts[1].sub_objective_id]
