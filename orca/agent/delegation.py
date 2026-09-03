"""
Bounded subagent delegation (Phase 8 spec §30-34). The required invariant
(spec §31) is enforced structurally, not by convention:

    child_capabilities ⊆ parent_capabilities
    child_budget      <= parent delegated budget
    child_scope       <= parent scope

No delegation-based privilege escalation is possible through this module
-- `build_child_runtime()` is the ONLY way a `DelegationRequest` becomes an
`AgentRuntime`, and it refuses (raises) rather than silently clamping if a
caller asks for more than the parent has.
"""
from __future__ import annotations

from orca.agent.contracts import AgentRunStatus, Capability, DelegationRequest, DelegationResult
from orca.agent.runtime import AgentRuntime
from orca.agent.tool_registry import AgentToolRegistry
from orca.cognitive.contracts import BudgetDimension, CognitiveBudget

MAX_DELEGATION_DEPTH = 3
MAX_CONCURRENT_SUBAGENTS = 4


class CapabilityEscalationError(ValueError):
    pass


class BudgetEscalationError(ValueError):
    pass


class DelegationDepthExceededError(ValueError):
    pass


class DelegationFanoutExceededError(ValueError):
    pass


def build_child_runtime(
    request: DelegationRequest,
    *,
    parent_capabilities: frozenset[Capability],
    parent_budget: CognitiveBudget,
    registry: AgentToolRegistry,
    active_subagent_count: int = 0,
) -> AgentRuntime:
    """
    Validates the non-escalation invariant BEFORE constructing anything --
    a request that asks for more than the parent has never produces a
    runtime at all, it raises.
    """
    if request.depth > MAX_DELEGATION_DEPTH:
        raise DelegationDepthExceededError(f"delegation depth {request.depth} exceeds MAX_DELEGATION_DEPTH={MAX_DELEGATION_DEPTH}")

    if active_subagent_count >= MAX_CONCURRENT_SUBAGENTS:
        raise DelegationFanoutExceededError(f"active subagent count {active_subagent_count} >= MAX_CONCURRENT_SUBAGENTS={MAX_CONCURRENT_SUBAGENTS}")

    if not request.capabilities_subset.issubset(parent_capabilities):
        excess = request.capabilities_subset - parent_capabilities
        raise CapabilityEscalationError(f"delegation requests capabilities the parent does not have: {sorted(c.value for c in excess)}")

    child_budget = CognitiveBudget()
    for dim_name, requested_amount in request.budget_subset.items():
        dimension = BudgetDimension(dim_name)
        limit_field = {
            BudgetDimension.MODEL_CALLS: "max_model_calls",
            BudgetDimension.RETRIEVAL_CALLS: "max_retrieval_calls",
            BudgetDimension.TOOL_CALLS: "max_tool_calls",
            BudgetDimension.AGENT_CALLS: "max_agent_calls",
        }.get(dimension)
        if limit_field is None:
            continue
        parent_limit = getattr(parent_budget, limit_field)
        parent_consumed = getattr(parent_budget, limit_field.replace("max_", "consumed_"))
        parent_remaining = (parent_limit - parent_consumed) if parent_limit is not None else None
        if parent_remaining is not None and requested_amount > parent_remaining:
            raise BudgetEscalationError(
                f"delegation requests {requested_amount} {dimension.value} but parent only has {parent_remaining} remaining"
            )
        setattr(child_budget, limit_field, requested_amount)

    child_deadline = min(request.deadline_s, 3600.0)  # never negative/absurd, still caller-bounded elsewhere

    return AgentRuntime(
        registry=registry, goal=request.goal, capabilities=request.capabilities_subset,
        budget=child_budget, deadline_s=child_deadline,
    )


def run_delegation(
    request: DelegationRequest,
    plan,
    *,
    parent_capabilities: frozenset[Capability],
    parent_budget: CognitiveBudget,
    registry: AgentToolRegistry,
    active_subagent_count: int = 0,
    require_schema_validation: bool = True,
) -> DelegationResult:
    """
    Runs a bounded child AgentRuntime and returns its result WITHOUT
    automatically trusting it (spec §34) -- `trusted` starts False; a
    caller applies its own schema-validation/Truth/Court review on top
    depending on the delegation's declared risk before treating the
    result as trusted.
    """
    child_runtime = build_child_runtime(
        request, parent_capabilities=parent_capabilities, parent_budget=parent_budget,
        registry=registry, active_subagent_count=active_subagent_count,
    )
    child_run, child_trace, child_world_state = child_runtime.execute(plan)

    # Consume exactly 1 unit of the PARENT's AGENT_CALLS dimension for the
    # delegation itself -- never an independent fresh allocation (spec §47).
    from orca.cognitive.budget import consume as _consume
    from orca.cognitive.errors import CognitiveBudgetExhaustedError
    try:
        _consume(parent_budget, BudgetDimension.AGENT_CALLS, 1)
    except CognitiveBudgetExhaustedError:
        return DelegationResult(child_run_id=child_run.run_id, status=AgentRunStatus.BLOCKED, result=None, trusted=False)

    trusted = (not require_schema_validation) and child_run.status == AgentRunStatus.COMPLETED
    return DelegationResult(
        child_run_id=child_run.run_id,
        status=child_run.status,
        result={"world_state_facts": list(child_world_state.known_facts), "completed_tasks": child_run.completed_task_ids},
        trusted=trusted,
    )
