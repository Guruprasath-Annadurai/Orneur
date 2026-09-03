"""
Phase 8.1 spec §12-18: explicit Truth Fabric / Memory Continuum runtime
integration. Truth Fabric is NOT forced on every action; Memory is
advisory only and never authorizes.
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
)
from orca.agent.runtime import AgentRuntime
from orca.agent.tool_registry import build_agent_tool_registry


def _goal():
    return AgentGoal(objective="t", allowed_action_classes=frozenset({SideEffectClass.READ_ONLY}))


@pytest.mark.asyncio
async def test_action_without_requires_truth_check_never_calls_the_checker():
    calls = {"n": 0}

    async def checker(action):
        calls["n"] += 1
        return True

    registry = build_agent_tool_registry()
    task = AgentTask(description="r")
    action = AgentAction(task_id=task.task_id, tool_id="read_file", arguments={"path": "x"}, expected_side_effect=SideEffectClass.READ_ONLY, requires_truth_check=False)
    plan = AgentPlan(tasks=[task], actions=[action])
    rt = AgentRuntime(registry=registry, goal=_goal(), capabilities=frozenset({Capability.FILE_READ}), truth_checker=checker)
    run, trace, ws = await rt.execute_async(plan)

    assert calls["n"] == 0
    assert run.status == AgentRunStatus.COMPLETED


@pytest.mark.asyncio
async def test_insufficient_truth_check_prevents_execution_never_guesses():
    executed = {"called": False}
    registry = build_agent_tool_registry()

    async def insufficient(action):
        return False

    task = AgentTask(description="r")
    action = AgentAction(task_id=task.task_id, tool_id="read_file", arguments={"path": "x"}, expected_side_effect=SideEffectClass.READ_ONLY, requires_truth_check=True)
    plan = AgentPlan(tasks=[task], actions=[action])
    rt = AgentRuntime(registry=registry, goal=_goal(), capabilities=frozenset({Capability.FILE_READ}), truth_checker=insufficient)
    run, trace, ws = await rt.execute_async(plan)

    assert run.stop_reason == ExecutionStopReason.UNRESOLVED_WORLD_STATE
    assert not ws.known_facts  # no observation was ever recorded from the (never-run) tool


@pytest.mark.asyncio
async def test_sufficient_truth_check_allows_execution():
    async def sufficient(action):
        return True

    registry = build_agent_tool_registry()
    task = AgentTask(description="r")
    action = AgentAction(task_id=task.task_id, tool_id="read_file", arguments={"path": "x"}, expected_side_effect=SideEffectClass.READ_ONLY, requires_truth_check=True)
    plan = AgentPlan(tasks=[task], actions=[action])
    rt = AgentRuntime(registry=registry, goal=_goal(), capabilities=frozenset({Capability.FILE_READ}), truth_checker=sufficient)
    run, trace, ws = await rt.execute_async(plan)

    assert run.status == AgentRunStatus.COMPLETED


def test_memory_recall_is_firewall_gated_and_advisory_only():
    from orca.agent.memory_hook import recall_advisory_context
    advisory = recall_advisory_context("some objective that matches nothing", scope_id="test-scope-does-not-exist")
    assert advisory.advisory_text == ""  # no records exist for this scope -- honest empty result, not fabricated
    assert advisory.memory_ids == []


def test_procedural_record_incompatible_with_current_tools_is_rejected():
    from orca.agent.memory_hook import procedural_record_is_compatible
    from orca.memory.contracts import ProceduralMemoryRecord

    record = ProceduralMemoryRecord(name="deploy via legacy_ftp_tool", steps=["use legacy_ftp_tool to upload"])
    assert procedural_record_is_compatible(record, allowed_tool_ids=frozenset({"read_file", "write_file"})) is False


def test_procedural_record_compatible_with_current_tools_is_accepted():
    from orca.agent.memory_hook import procedural_record_is_compatible
    from orca.memory.contracts import ProceduralMemoryRecord

    record = ProceduralMemoryRecord(name="read then write", steps=["read_file the source", "write_file the result"])
    assert procedural_record_is_compatible(record, allowed_tool_ids=frozenset({"read_file", "write_file"})) is True
