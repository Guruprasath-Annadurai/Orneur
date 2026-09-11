"""
Cancellation during planning (Phase 8.1 spec §29). Expected: no plan
execution happens, the model task is cancelled, budget accounting is
correct (the reservation for the in-flight planning attempt is not
double-counted), and the run/outcome reflects cancellation honestly.
"""
from __future__ import annotations

import asyncio

import pytest

from orca.agent.contracts import AgentGoal, SideEffectClass
from orca.agent.planner import AgentPlanner
from orca.agent.tool_registry import build_agent_tool_registry
from orca.cognitive.contracts import CognitiveBudget


@pytest.mark.asyncio
async def test_cancel_during_planning_never_produces_a_plan(monkeypatch):
    import orca.truth.llm as llm_mod

    async def slow_gateway_json_call(prompt, system, tier="nano", max_tokens=400, **kwargs):
        await asyncio.sleep(5.0)
        return {"tasks": [], "actions": []}

    monkeypatch.setattr(llm_mod, "gateway_json_call", slow_gateway_json_call)

    # Phase 15.15 CI truthfulness closure: AgentPlanner.compile_plan()
    # resolves TOOL_REASONER via resolve_tier_for_role() -> route()
    # BEFORE ever reaching the mocked gateway_json_call above. Without
    # this, route()'s DEFAULT checkpoint_lookup (a real CheckpointRecord
    # read from ORCA_HOME/registry/checkpoints/, present on a
    # development machine but genuinely absent on a fresh CI checkout)
    # made every candidate ineligible there, so compile_plan() returned
    # a NO_ELIGIBLE_REASONER failure SYNCHRONOUSLY -- the task completed
    # before plan_task.cancel() could ever apply, so
    # `await plan_task` returned normally instead of raising
    # CancelledError, and this test's own real cancellation-timing
    # assertion was never actually exercised in CI.
    import orca.society.router as router_mod

    class _FakeCheckpointRecord:
        def is_routable(self) -> bool:
            return True

    monkeypatch.setattr(router_mod, "_default_checkpoint_lookup", lambda checkpoint_id: _FakeCheckpointRecord())

    registry = build_agent_tool_registry()
    planner = AgentPlanner()
    goal = AgentGoal(objective="x", allowed_action_classes=frozenset({SideEffectClass.READ_ONLY}))
    budget = CognitiveBudget(max_model_calls=6)

    plan_task = asyncio.create_task(planner.compile_plan(goal, allowed_tool_specs={"read_file": registry.get_spec("read_file")}, budget=budget))
    await asyncio.sleep(0.05)
    plan_task.cancel()

    with pytest.raises(asyncio.CancelledError):
        await plan_task

    # The reservation for the in-flight (never-completed) planning attempt
    # was made before the call started (spec §10: reserve BEFORE invoking)
    # -- it is real, accounted consumption for an attempt that was made,
    # not a leak; no SECOND unaccounted unit appears.
    assert budget.consumed_model_calls == 1
