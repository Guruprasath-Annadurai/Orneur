"""
Cognitive Planner -- builds a CognitivePlan from the outputs of the
intent/complexity/risk/freshness/evidence classifiers plus a budget (Phase
3 spec §16-18, §21-23). Operation support states are declared honestly
against what the repository can ACTUALLY do today (Phase 2/2.1's
ModelGateway, the existing AgentLoop tool loop including a real
`web_search` tool, the existing MemoryEngine, the existing DocStore-backed
RAG path) versus what later phases will add (Truth Fabric verification,
a general-purpose Agent Runtime delegation, Simulation Chamber) -- see
docs/orneur/phase-3/CURRENT_COGNITIVE_ORCHESTRATION.md for the audit this
mapping is based on.

The planner never silently substitutes an unavailable operation for a
different one: if a plan cannot be satisfied by SUPPORTED_NOW operations,
it abstains explicitly (Phase 3 spec §21) instead of degrading silently.
"""
from __future__ import annotations

from orca.cognitive.budget import DEFAULT_BUDGET, has_any_capacity
from orca.cognitive.contracts import (
    AbstentionReason,
    BudgetDimension,
    CognitiveBudget,
    CognitiveOperation,
    CognitivePlan,
    CompletionCondition,
    ComplexityAssessment,
    ComplexityLevel,
    EvidenceLevel,
    EvidenceRequirement,
    FreshnessRequirement,
    IntentPlan,
    ModelPolicy,
    OperationSupportState,
    OperationType,
    RiskAssessment,
    SubObjective,
)
from orca.cognitive.decomposition import decompose

# Honest, documented support-state map for Phase 3 -- see module docstring.
# ANSWER_DIRECTLY/REASON/RECALL_MEMORY/RETRIEVE/SEARCH/USE_TOOL/ABSTAIN are
# real, working paths through the existing serving stack (ModelGateway,
# MemoryEngine, DocStore, AgentLoop's web_search tool). DELEGATE_AGENT,
# VERIFY, and SIMULATE have no general-purpose Kernel-invokable
# implementation yet (OrcaUltra is a separate, narrower, user-selected
# entry point today, not a Kernel operation -- see
# CURRENT_COGNITIVE_ORCHESTRATION.md).
_SUPPORT_STATES: dict[OperationType, tuple[OperationSupportState, str]] = {
    OperationType.ANSWER_DIRECTLY: (OperationSupportState.SUPPORTED_NOW, "ModelGateway direct completion"),
    OperationType.RETRIEVE: (OperationSupportState.SUPPORTED_NOW, "existing DocStore-backed RAG path"),
    OperationType.SEARCH: (OperationSupportState.SUPPORTED_NOW, "existing AgentLoop web_search tool (heuristic-quality, pre-Truth-Fabric)"),
    OperationType.RECALL_MEMORY: (OperationSupportState.SUPPORTED_NOW, "existing MemoryEngine"),
    OperationType.REASON: (OperationSupportState.SUPPORTED_NOW, "ModelGateway completion/streaming"),
    OperationType.USE_TOOL: (OperationSupportState.SUPPORTED_NOW, "existing AgentLoop tool registry"),
    OperationType.DELEGATE_AGENT: (OperationSupportState.PLANNED, "general-purpose Agent Runtime delegation does not exist yet"),
    OperationType.VERIFY: (OperationSupportState.PLANNED, "Truth Fabric / Deliberation Fabric verification does not exist yet"),
    OperationType.SIMULATE: (OperationSupportState.PLANNED, "Simulation Chamber does not exist yet"),
    OperationType.ABSTAIN: (OperationSupportState.SUPPORTED_NOW, "the Kernel can always decline to answer"),
}

def _operation_for(op_type: OperationType) -> CognitiveOperation:
    state, detail = _SUPPORT_STATES[op_type]
    return CognitiveOperation(type=op_type, support_state=state, detail=detail)


def _required_operations(intent: IntentPlan) -> list[OperationType]:
    ops: list[OperationType] = []
    if intent.requires_memory:
        ops.append(OperationType.RECALL_MEMORY)
    if intent.requires_retrieval:
        ops.append(OperationType.RETRIEVE)
    if intent.requires_search:
        ops.append(OperationType.SEARCH)
    if intent.requires_tools:
        ops.append(OperationType.USE_TOOL)
    if intent.requires_agents:
        ops.append(OperationType.DELEGATE_AGENT)
    if intent.requires_reasoning or not ops:
        ops.append(OperationType.REASON)
    ops.append(OperationType.ANSWER_DIRECTLY)
    return ops


def _completion_conditions(evidence: EvidenceRequirement, requires_verify: bool) -> list[CompletionCondition]:
    conditions = [CompletionCondition.DIRECT_ANSWER_PRODUCED]
    if evidence.level in (EvidenceLevel.SUPPORTED, EvidenceLevel.STRICT, EvidenceLevel.AUDIT_GRADE):
        conditions.append(CompletionCondition.EVIDENCE_OBTAINED)
    if requires_verify:
        conditions.append(CompletionCondition.VERIFICATION_COMPLETE)
    conditions.append(CompletionCondition.BUDGET_EXHAUSTED)
    conditions.append(CompletionCondition.MAX_ROUNDS_REACHED)
    conditions.append(CompletionCondition.OPERATION_UNAVAILABLE_ABSTAIN)
    return conditions


def build_plan(
    request_id: str,
    trace_id: str,
    objective: str,
    intent: IntentPlan,
    complexity: ComplexityAssessment,
    risk: RiskAssessment,
    freshness: FreshnessRequirement,
    evidence: EvidenceRequirement,
    model_policy: ModelPolicy,
    budget: CognitiveBudget | None = None,
) -> CognitivePlan:
    budget = budget or CognitiveBudget(
        max_tokens=DEFAULT_BUDGET.max_tokens,
        max_latency_ms=DEFAULT_BUDGET.max_latency_ms,
        max_model_calls=DEFAULT_BUDGET.max_model_calls,
        max_retrieval_calls=DEFAULT_BUDGET.max_retrieval_calls,
        max_tool_calls=DEFAULT_BUDGET.max_tool_calls,
        max_agent_calls=DEFAULT_BUDGET.max_agent_calls,
        max_cost_usd=DEFAULT_BUDGET.max_cost_usd,
        max_reasoning_rounds=DEFAULT_BUDGET.max_reasoning_rounds,
    )

    # AUDIT_GRADE evidence requires VERIFY, which is PLANNED (not
    # SUPPORTED_NOW) in Phase 3 -- this plan is honestly unsatisfiable
    # rather than silently downgraded to a lesser evidence standard.
    requires_verify = evidence.level == EvidenceLevel.AUDIT_GRADE

    required_types = _required_operations(intent)
    operations = [_operation_for(t) for t in required_types]
    if requires_verify:
        operations.append(_operation_for(OperationType.VERIFY))

    sub_objectives: list[SubObjective] = []
    if intent.requires_agents or complexity.level == ComplexityLevel.DEEP:
        sub_objectives = decompose(objective)

    completion_conditions = _completion_conditions(evidence, requires_verify)

    return CognitivePlan(
        request_id=request_id,
        trace_id=trace_id,
        intent=intent,
        complexity=complexity,
        risk=risk,
        freshness=freshness,
        evidence_requirement=evidence,
        operations=operations,
        model_policy=model_policy,
        budget=budget,
        completion_conditions=completion_conditions,
        sub_objectives=sub_objectives,
    )


def plan_abstention_reason(plan: CognitivePlan) -> AbstentionReason | None:
    """
    Returns the reason the plan cannot be executed as-is, or None if it
    can. Checked BEFORE execution begins (Phase 3 spec §21: never produce
    a fabricated answer when the plan can't be satisfied).
    """
    for op in plan.operations:
        if op.support_state in (OperationSupportState.UNAVAILABLE, OperationSupportState.FORBIDDEN):
            return AbstentionReason.REQUIRED_OPERATION_UNAVAILABLE
        if op.support_state == OperationSupportState.PLANNED and op.type == OperationType.VERIFY:
            # VERIFY is required (AUDIT_GRADE evidence) but only PLANNED --
            # the plan is honestly unsatisfiable, not silently downgraded.
            return AbstentionReason.INSUFFICIENT_CAPABILITY

    if not has_any_capacity(plan.budget, BudgetDimension.MODEL_CALLS):
        return AbstentionReason.BUDGET_EXHAUSTED

    return None
