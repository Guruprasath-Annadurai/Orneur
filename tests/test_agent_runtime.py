"""
Agent Runtime core execution-loop tests (Phase 8 spec §60's required
scenarios). Deterministic -- uses real tools (read_file/write_file/shell)
against the sandboxed workspace, plus small controlled test tools
(bounded-failing, timeout) registered directly, per spec §61.
"""
from __future__ import annotations

import time

import pytest

from orca.agent.contracts import (
    ActionRiskLevel,
    AgentAction,
    AgentGoal,
    AgentPlan,
    AgentRunStatus,
    AgentTask,
    Capability,
    ExecutionStopReason,
    SideEffectClass,
    TaskStatus,
    ToolSpec,
)
from orca.agent.runtime import AgentRuntime
from orca.agent.tool_registry import build_agent_tool_registry
from orca.cognitive.contracts import CognitiveBudget


def _read_only_goal(**kwargs) -> AgentGoal:
    return AgentGoal(objective="test", allowed_action_classes=frozenset({SideEffectClass.READ_ONLY}), **kwargs)


def test_simple_read_only_tool_action_succeeds():
    registry = build_agent_tool_registry()
    goal = _read_only_goal()
    task = AgentTask(description="read")
    action = AgentAction(task_id=task.task_id, tool_id="read_file", arguments={"path": "does-not-exist.txt"}, expected_side_effect=SideEffectClass.READ_ONLY)
    plan = AgentPlan(tasks=[task], actions=[action])

    rt = AgentRuntime(registry=registry, goal=goal, capabilities=frozenset({Capability.FILE_READ}))
    run, trace, world_state = rt.execute(plan)

    assert run.status == AgentRunStatus.COMPLETED
    assert task.task_id in run.completed_task_ids
    assert len(trace.observation_ids) == 1


def test_action_succeeds_and_updates_world_state():
    registry = build_agent_tool_registry()
    goal = _read_only_goal()
    task = AgentTask(description="read")
    action = AgentAction(task_id=task.task_id, tool_id="read_file", arguments={"path": "does-not-exist.txt"}, expected_side_effect=SideEffectClass.READ_ONLY)
    plan = AgentPlan(tasks=[task], actions=[action])

    rt = AgentRuntime(registry=registry, goal=goal, capabilities=frozenset({Capability.FILE_READ}))
    run, trace, world_state = rt.execute(plan)

    assert world_state.known_facts  # a real fact was added from the observation
    assert any(f"tool:read_file:{action.action_id}" in ref for ref in world_state.evidence_refs)


def test_tool_failure_triggers_one_local_replan():
    """A bounded-failing test tool -- fails once, then a replan_fn swaps
    in a working tool for the same task (spec §25's 'local revision'
    example: 'tool A unavailable -> substitute permitted tool B')."""
    registry = build_agent_tool_registry()
    registry.register(
        ToolSpec(tool_id="flaky", side_effect_class=SideEffectClass.READ_ONLY, required_capabilities=frozenset()),
        lambda: (_ for _ in ()).throw(RuntimeError("tool A unavailable")),
    )
    goal = _read_only_goal()
    task = AgentTask(description="do work")
    action = AgentAction(task_id=task.task_id, tool_id="flaky", expected_side_effect=SideEffectClass.READ_ONLY)
    plan = AgentPlan(tasks=[task], actions=[action])

    def replan_fn(plan, failed_task, world_state):
        new_task = AgentTask(task_id=failed_task.task_id + "-retry", description="fallback")
        new_action = AgentAction(task_id=new_task.task_id, tool_id="read_file", arguments={"path": "x"}, expected_side_effect=SideEffectClass.READ_ONLY)
        return AgentPlan(tasks=[new_task], actions=[new_action], version=plan.version + 1, parent_version=plan.version)

    rt = AgentRuntime(registry=registry, goal=goal, capabilities=frozenset({Capability.FILE_READ}), replan_fn=replan_fn)
    run, trace, world_state = rt.execute(plan)

    assert len(trace.replan_events) == 1
    assert run.status == AgentRunStatus.COMPLETED  # the substituted tool succeeded


def test_policy_denied_action_stops_safely():
    registry = build_agent_tool_registry()
    goal = AgentGoal(objective="test", allowed_action_classes=frozenset({SideEffectClass.READ_ONLY}))  # no WRITE
    task = AgentTask(description="write")
    action = AgentAction(task_id=task.task_id, tool_id="write_file", arguments={"path": "x", "content": "y"}, expected_side_effect=SideEffectClass.REVERSIBLE_WRITE)
    plan = AgentPlan(tasks=[task], actions=[action])

    rt = AgentRuntime(registry=registry, goal=goal, capabilities=frozenset({Capability.FILE_WRITE}))
    run, trace, world_state = rt.execute(plan)

    assert run.stop_reason == ExecutionStopReason.POLICY_DENIED
    assert task.status == TaskStatus.FAILED
    # No write ever happened -- WorldState has no observation from it.
    assert not world_state.known_facts


def test_missing_capability_blocks_execution():
    registry = build_agent_tool_registry()
    goal = AgentGoal(objective="test", allowed_action_classes=frozenset({SideEffectClass.READ_ONLY, SideEffectClass.REVERSIBLE_WRITE}))
    task = AgentTask(description="write")
    action = AgentAction(task_id=task.task_id, tool_id="write_file", arguments={"path": "x", "content": "y"}, expected_side_effect=SideEffectClass.REVERSIBLE_WRITE)
    plan = AgentPlan(tasks=[task], actions=[action])

    rt = AgentRuntime(registry=registry, goal=goal, capabilities=frozenset({Capability.FILE_READ}))  # no FILE_WRITE
    run, trace, world_state = rt.execute(plan)

    assert run.stop_reason == ExecutionStopReason.CAPABILITY_MISSING


def test_destructive_action_requires_approval_and_never_executes():
    registry = build_agent_tool_registry()
    executed = {"called": False}
    registry.register(
        ToolSpec(tool_id="delete_prod", side_effect_class=SideEffectClass.DESTRUCTIVE, required_capabilities=frozenset({Capability.PROCESS_EXECUTION})),
        lambda: executed.__setitem__("called", True) or "done",
    )
    goal = AgentGoal(objective="test", allowed_action_classes=frozenset({SideEffectClass.DESTRUCTIVE}))  # even if "allowed" by goal
    task = AgentTask(description="destroy")
    action = AgentAction(task_id=task.task_id, tool_id="delete_prod", expected_side_effect=SideEffectClass.DESTRUCTIVE)
    plan = AgentPlan(tasks=[task], actions=[action])

    rt = AgentRuntime(registry=registry, goal=goal, capabilities=frozenset({Capability.PROCESS_EXECUTION}))
    run, trace, world_state = rt.execute(plan)

    assert run.status == AgentRunStatus.BLOCKED
    assert run.stop_reason == ExecutionStopReason.APPROVAL_REQUIRED
    assert executed["called"] is False  # never actually ran


def test_budget_exhaustion_before_tool_call_prevents_execution():
    registry = build_agent_tool_registry()
    executed = {"count": 0}
    registry.register(
        ToolSpec(tool_id="counter", side_effect_class=SideEffectClass.READ_ONLY, required_capabilities=frozenset()),
        lambda: executed.__setitem__("count", executed["count"] + 1) or "ok",
    )
    goal = _read_only_goal()
    tasks = [AgentTask(description=f"t{i}") for i in range(3)]
    actions = [AgentAction(task_id=t.task_id, tool_id="counter", expected_side_effect=SideEffectClass.READ_ONLY) for t in tasks]
    plan = AgentPlan(tasks=tasks, actions=actions)
    budget = CognitiveBudget(max_tool_calls=1)

    rt = AgentRuntime(registry=registry, goal=goal, capabilities=frozenset(), budget=budget)
    run, trace, world_state = rt.execute(plan)

    assert executed["count"] == 1  # only the affordable one ran
    assert run.stop_reason == ExecutionStopReason.BUDGET_EXHAUSTED


def test_tool_timeout_is_classified_as_transient_and_retried_once():
    registry = build_agent_tool_registry()
    attempts = {"n": 0}

    def flaky_timeout():
        attempts["n"] += 1
        if attempts["n"] == 1:
            raise TimeoutError("simulated transient timeout")
        return "recovered"

    registry.register(ToolSpec(tool_id="timeout_tool", side_effect_class=SideEffectClass.READ_ONLY, required_capabilities=frozenset()), flaky_timeout)
    goal = _read_only_goal()
    task = AgentTask(description="t")
    action = AgentAction(task_id=task.task_id, tool_id="timeout_tool", expected_side_effect=SideEffectClass.READ_ONLY)
    plan = AgentPlan(tasks=[task], actions=[action])

    rt = AgentRuntime(registry=registry, goal=goal, capabilities=frozenset())
    run, trace, world_state = rt.execute(plan)

    assert attempts["n"] == 2  # one real attempt + one bounded retry
    assert run.status == AgentRunStatus.COMPLETED


def test_permission_denied_is_never_blindly_retried():
    """spec §26: DENY/schema/permission failures must not be retried --
    only classified transient errors are."""
    registry = build_agent_tool_registry()
    attempts = {"n": 0}

    def permission_error():
        attempts["n"] += 1
        raise PermissionError("not allowed")

    registry.register(ToolSpec(tool_id="perm_tool", side_effect_class=SideEffectClass.READ_ONLY, required_capabilities=frozenset()), permission_error)
    goal = _read_only_goal()
    task = AgentTask(description="t")
    action = AgentAction(task_id=task.task_id, tool_id="perm_tool", expected_side_effect=SideEffectClass.READ_ONLY)
    plan = AgentPlan(tasks=[task], actions=[action])

    rt = AgentRuntime(registry=registry, goal=goal, capabilities=frozenset())
    run, trace, world_state = rt.execute(plan)

    assert attempts["n"] == 1  # never retried
    assert run.stop_reason == ExecutionStopReason.TOOL_ERROR


def test_partial_multi_task_success_is_reported_honestly():
    """3 tasks: 1 succeeds, 1 policy-denied, 1 depends on the denied one
    -- AgentRun must report PARTIAL, never falsely COMPLETED."""
    registry = build_agent_tool_registry()
    goal = AgentGoal(objective="test", allowed_action_classes=frozenset({SideEffectClass.READ_ONLY}))

    t1 = AgentTask(description="read ok")
    t2 = AgentTask(description="write denied")
    t3 = AgentTask(description="depends on t2", dependencies=[t2.task_id])
    plan = AgentPlan(
        tasks=[t1, t2, t3],
        actions=[
            AgentAction(task_id=t1.task_id, tool_id="read_file", arguments={"path": "x"}, expected_side_effect=SideEffectClass.READ_ONLY),
            AgentAction(task_id=t2.task_id, tool_id="write_file", arguments={"path": "x", "content": "y"}, expected_side_effect=SideEffectClass.REVERSIBLE_WRITE),
            AgentAction(task_id=t3.task_id, tool_id="read_file", arguments={"path": "x"}, expected_side_effect=SideEffectClass.READ_ONLY),
        ],
    )

    rt = AgentRuntime(registry=registry, goal=goal, capabilities=frozenset({Capability.FILE_READ, Capability.FILE_WRITE}))
    run, trace, world_state = rt.execute(plan)

    assert run.status != AgentRunStatus.COMPLETED
    assert t1.task_id in run.completed_task_ids
    assert t2.status == TaskStatus.FAILED
    assert t3.task_id in run.blocked_task_ids


def test_run_never_exceeds_its_deadline():
    registry = build_agent_tool_registry()
    registry.register(ToolSpec(tool_id="slow", side_effect_class=SideEffectClass.READ_ONLY, required_capabilities=frozenset()), lambda: time.sleep(0.3) or "done")
    goal = _read_only_goal()
    tasks = [AgentTask(description=f"t{i}") for i in range(20)]
    actions = [AgentAction(task_id=t.task_id, tool_id="slow", expected_side_effect=SideEffectClass.READ_ONLY) for t in tasks]
    plan = AgentPlan(tasks=tasks, actions=actions)

    rt = AgentRuntime(registry=registry, goal=goal, capabilities=frozenset(), deadline_s=0.5)
    run, trace, world_state = rt.execute(plan)

    assert run.stop_reason == ExecutionStopReason.TIMEOUT
    assert len(run.completed_task_ids) < 20  # did not run all 20 slow tasks
