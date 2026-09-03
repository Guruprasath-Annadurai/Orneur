"""
Parent-cancellation-cancels-child tests (Phase 8.1 spec §27, §31).
"""
from __future__ import annotations

import asyncio

import pytest

from orca.agent.contracts import AgentAction, AgentGoal, AgentPlan, AgentRunStatus, AgentTask, Capability, DelegationRequest, SideEffectClass, ToolSpec
from orca.agent.delegation import run_delegation_async
from orca.agent.tool_registry import build_agent_tool_registry
from orca.cognitive.contracts import CognitiveBudget


async def _slow_async_tool(seconds: float = 5.0):
    await asyncio.sleep(seconds)
    return "finished"


@pytest.mark.asyncio
async def test_parent_cancellation_cancels_active_child_task():
    registry = build_agent_tool_registry()
    registry.register(ToolSpec(tool_id="slow_async", side_effect_class=SideEffectClass.READ_ONLY, required_capabilities=frozenset(), idempotent=True), _slow_async_tool)

    child_task_obj = AgentTask(description="slow")
    child_plan = AgentPlan(tasks=[child_task_obj], actions=[AgentAction(task_id=child_task_obj.task_id, tool_id="slow_async", arguments={"seconds": 5.0}, expected_side_effect=SideEffectClass.READ_ONLY)])
    req = DelegationRequest(goal=AgentGoal(objective="sub", allowed_action_classes=frozenset({SideEffectClass.READ_ONLY})), capabilities_subset=frozenset(), budget_subset={"TOOL_CALLS": 1})
    parent_budget = CognitiveBudget(max_agent_calls=2, max_tool_calls=5)

    delegation_task = asyncio.create_task(
        run_delegation_async(req, child_plan, parent_capabilities=frozenset(), parent_budget=parent_budget, registry=registry)
    )
    await asyncio.sleep(0.05)
    delegation_task.cancel()

    # The child's own execute_async() catches CancelledError internally
    # and returns a structured CANCELLED result (the same graceful-return
    # design used everywhere else in this runtime) -- so the delegation
    # task completes normally with that result rather than re-raising.
    # This IS genuine cancellation propagation: the child's in-flight tool
    # call was interrupted (never ran to completion), just surfaced as a
    # structured status instead of a raw exception at this layer.
    result = await delegation_task
    assert result.status == AgentRunStatus.CANCELLED

    # The child's own internal TOOL_CALLS reservation was released by its
    # own execute_async() cancellation handling. The delegation itself
    # still counts as one attempt against the parent's AGENT_CALLS (spec
    # §28: already-consumed/attempted work is not refunded merely because
    # the child was cancelled mid-flight).
    assert parent_budget.consumed_agent_calls == 1
