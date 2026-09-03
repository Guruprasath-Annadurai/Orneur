"""
Async cancellation propagation tests (Phase 8.1 spec §23-36). Uses a
genuinely-async controlled test tool (an `async def` awaiting
`asyncio.sleep`) so real `task.cancel()` interrupts it mid-execution --
not a sync tool wrapped in `asyncio.to_thread` (see
ASYNC_CANCELLATION.md's honest-semantics note on why that distinction
matters).
"""
from __future__ import annotations

import asyncio

import pytest

from orca.agent.contracts import (
    AgentAction,
    AgentGoal,
    AgentPlan,
    AgentRunStatus,
    AgentTask,
    Capability,
    ExecutionStopReason,
    SideEffectClass,
    ToolSpec,
)
from orca.agent.runtime import AgentRuntime
from orca.agent.tool_registry import build_agent_tool_registry
from orca.cognitive.contracts import CognitiveBudget


def _goal():
    return AgentGoal(objective="t", allowed_action_classes=frozenset({SideEffectClass.READ_ONLY}))


async def _slow_async_tool(seconds: float = 5.0):
    await asyncio.sleep(seconds)
    return "finished"


@pytest.mark.asyncio
async def test_cancel_during_tool_execution_reports_cancelled_not_timeout():
    registry = build_agent_tool_registry()
    registry.register(ToolSpec(tool_id="slow_async", side_effect_class=SideEffectClass.READ_ONLY, required_capabilities=frozenset(), idempotent=True), _slow_async_tool)
    task = AgentTask(description="t")
    plan = AgentPlan(tasks=[task], actions=[AgentAction(task_id=task.task_id, tool_id="slow_async", arguments={"seconds": 5.0}, expected_side_effect=SideEffectClass.READ_ONLY)])

    rt = AgentRuntime(registry=registry, goal=_goal(), capabilities=frozenset(), deadline_s=60.0)
    run_task = asyncio.create_task(rt.execute_async(plan))
    await asyncio.sleep(0.05)  # let the tool call actually start
    run_task.cancel()
    run, trace, world_state = await run_task

    assert run.status == AgentRunStatus.CANCELLED
    assert run.stop_reason == ExecutionStopReason.CANCELLED
    assert run.stop_reason != ExecutionStopReason.TIMEOUT


@pytest.mark.asyncio
async def test_cancelled_tool_never_emits_a_success_fact():
    """spec §34: WorldState must not claim 'operation completed' for a
    cancelled action."""
    registry = build_agent_tool_registry()
    registry.register(ToolSpec(tool_id="slow_async", side_effect_class=SideEffectClass.READ_ONLY, required_capabilities=frozenset(), idempotent=True), _slow_async_tool)
    task = AgentTask(description="t")
    plan = AgentPlan(tasks=[task], actions=[AgentAction(task_id=task.task_id, tool_id="slow_async", arguments={"seconds": 5.0}, expected_side_effect=SideEffectClass.READ_ONLY)])

    rt = AgentRuntime(registry=registry, goal=_goal(), capabilities=frozenset())
    run_task = asyncio.create_task(rt.execute_async(plan))
    await asyncio.sleep(0.05)
    run_task.cancel()
    run, trace, world_state = await run_task

    assert not world_state.known_facts  # no fact was ever recorded for the interrupted action
    assert task.task_id not in run.completed_task_ids


@pytest.mark.asyncio
async def test_unused_reservation_is_released_on_cancellation():
    registry = build_agent_tool_registry()
    registry.register(ToolSpec(tool_id="slow_async", side_effect_class=SideEffectClass.READ_ONLY, required_capabilities=frozenset(), idempotent=True), _slow_async_tool)
    task = AgentTask(description="t")
    plan = AgentPlan(tasks=[task], actions=[AgentAction(task_id=task.task_id, tool_id="slow_async", arguments={"seconds": 5.0}, expected_side_effect=SideEffectClass.READ_ONLY)])
    budget = CognitiveBudget(max_tool_calls=6)

    rt = AgentRuntime(registry=registry, goal=_goal(), capabilities=frozenset(), budget=budget)
    run_task = asyncio.create_task(rt.execute_async(plan))
    await asyncio.sleep(0.05)
    run_task.cancel()
    await run_task

    assert budget.consumed_tool_calls == 0  # the reservation was released, not leaked


@pytest.mark.asyncio
async def test_no_subsequent_actions_start_after_cancellation():
    registry = build_agent_tool_registry()
    started = {"n": 0}

    async def counting_slow_tool():
        started["n"] += 1
        await asyncio.sleep(5.0)
        return "done"

    registry.register(ToolSpec(tool_id="slow_async", side_effect_class=SideEffectClass.READ_ONLY, required_capabilities=frozenset(), idempotent=True), counting_slow_tool)
    tasks = [AgentTask(description=f"t{i}") for i in range(5)]
    plan = AgentPlan(tasks=tasks, actions=[AgentAction(task_id=t.task_id, tool_id="slow_async", expected_side_effect=SideEffectClass.READ_ONLY) for t in tasks])

    rt = AgentRuntime(registry=registry, goal=_goal(), capabilities=frozenset())
    run_task = asyncio.create_task(rt.execute_async(plan))
    await asyncio.sleep(0.05)
    run_task.cancel()
    run, trace, world_state = await run_task

    assert started["n"] == 1  # only the one in-flight action ever started
    assert run.status == AgentRunStatus.CANCELLED


@pytest.mark.asyncio
async def test_partial_completion_is_preserved_when_a_later_action_is_cancelled():
    """spec §33: A/B completed, C cancelled -- A/B must not be erased."""
    registry = build_agent_tool_registry()
    registry.register(ToolSpec(tool_id="slow_async", side_effect_class=SideEffectClass.READ_ONLY, required_capabilities=frozenset(), idempotent=True), _slow_async_tool)
    ta, tb, tc = AgentTask(description="a"), AgentTask(description="b"), AgentTask(description="c")
    plan = AgentPlan(
        tasks=[ta, tb, tc],
        actions=[
            AgentAction(task_id=ta.task_id, tool_id="read_file", arguments={"path": "x"}, expected_side_effect=SideEffectClass.READ_ONLY),
            AgentAction(task_id=tb.task_id, tool_id="read_file", arguments={"path": "y"}, expected_side_effect=SideEffectClass.READ_ONLY),
            AgentAction(task_id=tc.task_id, tool_id="slow_async", arguments={"seconds": 5.0}, expected_side_effect=SideEffectClass.READ_ONLY),
        ],
    )
    rt = AgentRuntime(registry=registry, goal=_goal(), capabilities=frozenset({Capability.FILE_READ}))
    run_task = asyncio.create_task(rt.execute_async(plan))
    await asyncio.sleep(0.05)
    run_task.cancel()
    run, trace, world_state = await run_task

    assert ta.task_id in run.completed_task_ids
    assert tb.task_id in run.completed_task_ids
    assert run.status == AgentRunStatus.CANCELLED  # the overall run reports cancelled, but completed work is preserved


@pytest.mark.asyncio
async def test_deadline_and_cancellation_are_distinct_stop_reasons():
    """spec §25/§32: a run that legitimately times out must never be
    reported as CANCELLED, and vice versa."""
    registry = build_agent_tool_registry()
    registry.register(ToolSpec(tool_id="fast_sync", side_effect_class=SideEffectClass.READ_ONLY, required_capabilities=frozenset()), lambda: __import__("time").sleep(0.05) or "ok")
    tasks = [AgentTask(description=f"t{i}") for i in range(30)]
    plan = AgentPlan(tasks=tasks, actions=[AgentAction(task_id=t.task_id, tool_id="fast_sync", expected_side_effect=SideEffectClass.READ_ONLY) for t in tasks])

    rt = AgentRuntime(registry=registry, goal=_goal(), capabilities=frozenset(), deadline_s=0.2)
    run, trace, world_state = await rt.execute_async(plan)  # no external cancel() call at all

    assert run.status == AgentRunStatus.FAILED
    assert run.stop_reason == ExecutionStopReason.TIMEOUT
    assert run.stop_reason != ExecutionStopReason.CANCELLED
