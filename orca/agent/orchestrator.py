"""
The full integration order for a complex agent request (Phase 8.1
spec §22):

  AgentGoal
  -> Memory recall if useful
  -> Truth check if needed
  -> AgentPlanner / TOOL_REASONER
  -> optional Cognitive Court review
  -> validated AgentPlan
  -> Capability Engine -> Policy Engine -> budget reservation
  -> Tool execution -> Observation -> WorldState -> verify -> replan -> stop

Simple, safe requests skip the heavy stages (spec §22's own instruction,
verified by `tests/test_agent_orchestrator_fast_path.py`): Memory/Truth/
Court are only invoked when the corresponding trigger condition is real.
"""
from __future__ import annotations

from dataclasses import dataclass

from orca.agent.contracts import AgentGoal, Capability
from orca.agent.court_hook import request_court_review, should_request_court_review
from orca.agent.memory_hook import recall_advisory_context
from orca.agent.planner import AgentPlanner, PlanningOutcome
from orca.agent.runtime import AgentRuntime
from orca.agent.tool_registry import AgentToolRegistry


@dataclass
class OrchestrationResult:
    planning_outcome: PlanningOutcome
    court_verdict: object | None = None
    memory_advisory_used: bool = False
    run: object | None = None
    trace: object | None = None
    world_state: object | None = None


async def run_agent_request(
    goal: AgentGoal,
    *,
    registry: AgentToolRegistry,
    capabilities: frozenset[Capability],
    budget=None,
    deadline_s: float = 120.0,
    scope_id: str = "default",
    allow_experimental_reasoner: bool = False,
    use_memory: bool = True,
    replan_fn=None,
    truth_checker=None,
) -> OrchestrationResult:
    """
    The one production entry point implementing spec §22's full order.
    Every heavy stage is conditional on a real trigger -- never invoked
    "just in case" (spec §22/§40's fast-path requirement).
    """
    memory_advisory_text = None
    memory_used = False
    if use_memory:
        advisory = recall_advisory_context(goal.objective, scope_id=scope_id)
        if advisory.advisory_text:
            memory_advisory_text = advisory.advisory_text
            memory_used = True

    court_verdict = None
    if should_request_court_review(goal):
        _case, court_verdict, _stop = await request_court_review(goal.objective, risk_level=None, budget=budget)
        # Court's verdict is recorded for audit ONLY -- it is never
        # consulted by the Planner's bounds/schema validation, nor by
        # Policy. A REJECT/INSUFFICIENT_EVIDENCE verdict does not, by
        # itself, stop planning: Policy Engine remains the sole
        # authorization boundary once a concrete AgentPlan exists.

    planner = AgentPlanner(allow_experimental_reasoner=allow_experimental_reasoner)
    allowed_tool_specs = {spec.tool_id: spec for spec in registry.all_specs()}
    outcome = await planner.compile_plan(
        goal, allowed_tool_specs=allowed_tool_specs, budget=budget,
        memory_context=memory_advisory_text,
    )

    result = OrchestrationResult(planning_outcome=outcome, court_verdict=court_verdict, memory_advisory_used=memory_used)
    if outcome.plan is None:
        return result

    runtime = AgentRuntime(
        registry=registry, goal=goal, capabilities=capabilities, budget=budget,
        deadline_s=deadline_s, replan_fn=replan_fn, truth_checker=truth_checker,
    )
    run, trace, world_state = await runtime.execute_async(outcome.plan)
    result.run, result.trace, result.world_state = run, trace, world_state
    return result
