"""
Delegation non-escalation property tests (Phase 8 spec §31, §60).
"""
from __future__ import annotations

import pytest

from orca.agent.contracts import AgentGoal, AgentAction, AgentPlan, AgentRunStatus, AgentTask, Capability, SideEffectClass
from orca.agent.delegation import (
    MAX_CONCURRENT_SUBAGENTS,
    MAX_DELEGATION_DEPTH,
    BudgetEscalationError,
    CapabilityEscalationError,
    DelegationDepthExceededError,
    DelegationFanoutExceededError,
    build_child_runtime,
    run_delegation,
)
from orca.agent.contracts import DelegationRequest
from orca.agent.tool_registry import build_agent_tool_registry
from orca.cognitive.contracts import CognitiveBudget


@pytest.fixture
def registry():
    return build_agent_tool_registry()


def test_child_cannot_request_capability_parent_lacks(registry):
    parent_caps = frozenset({Capability.FILE_READ})
    req = DelegationRequest(goal=AgentGoal(objective="x"), capabilities_subset=frozenset({Capability.FILE_WRITE, Capability.FILE_READ}))
    with pytest.raises(CapabilityEscalationError):
        build_child_runtime(req, parent_capabilities=parent_caps, parent_budget=CognitiveBudget(), registry=registry)


def test_child_capabilities_are_a_subset_when_request_is_valid(registry):
    parent_caps = frozenset({Capability.FILE_READ, Capability.NETWORK_READ})
    req = DelegationRequest(goal=AgentGoal(objective="x"), capabilities_subset=frozenset({Capability.FILE_READ}))
    child = build_child_runtime(req, parent_capabilities=parent_caps, parent_budget=CognitiveBudget(), registry=registry)
    assert child.capabilities.issubset(parent_caps)


def test_child_cannot_request_more_budget_than_parent_has_remaining(registry):
    parent_budget = CognitiveBudget(max_tool_calls=3)
    parent_budget.consumed_tool_calls = 2  # only 1 remaining
    req = DelegationRequest(goal=AgentGoal(objective="x"), capabilities_subset=frozenset(), budget_subset={"TOOL_CALLS": 2})
    with pytest.raises(BudgetEscalationError):
        build_child_runtime(req, parent_capabilities=frozenset(), parent_budget=parent_budget, registry=registry)


def test_child_budget_within_parent_remaining_succeeds(registry):
    parent_budget = CognitiveBudget(max_tool_calls=5)
    req = DelegationRequest(goal=AgentGoal(objective="x"), capabilities_subset=frozenset(), budget_subset={"TOOL_CALLS": 3})
    child = build_child_runtime(req, parent_capabilities=frozenset(), parent_budget=parent_budget, registry=registry)
    assert child.budget.max_tool_calls == 3
    assert child.budget.max_tool_calls <= parent_budget.max_tool_calls


def test_delegation_depth_exceeded_is_refused(registry):
    req = DelegationRequest(goal=AgentGoal(objective="x"), capabilities_subset=frozenset(), depth=MAX_DELEGATION_DEPTH + 1)
    with pytest.raises(DelegationDepthExceededError):
        build_child_runtime(req, parent_capabilities=frozenset(), parent_budget=CognitiveBudget(), registry=registry)


def test_delegation_depth_at_the_limit_is_allowed(registry):
    req = DelegationRequest(goal=AgentGoal(objective="x"), capabilities_subset=frozenset(), depth=MAX_DELEGATION_DEPTH)
    build_child_runtime(req, parent_capabilities=frozenset(), parent_budget=CognitiveBudget(), registry=registry)  # must not raise


def test_agent_fanout_is_bounded(registry):
    req = DelegationRequest(goal=AgentGoal(objective="x"), capabilities_subset=frozenset())
    with pytest.raises(DelegationFanoutExceededError):
        build_child_runtime(req, parent_capabilities=frozenset(), parent_budget=CognitiveBudget(), registry=registry, active_subagent_count=MAX_CONCURRENT_SUBAGENTS)


def test_subagent_result_is_not_automatically_trusted(registry):
    parent_budget = CognitiveBudget(max_agent_calls=2)
    req = DelegationRequest(goal=AgentGoal(objective="x", allowed_action_classes=frozenset({SideEffectClass.READ_ONLY})), capabilities_subset=frozenset({Capability.FILE_READ}))
    task = AgentTask(description="r")
    plan = AgentPlan(tasks=[task], actions=[AgentAction(task_id=task.task_id, tool_id="read_file", arguments={"path": "x"}, expected_side_effect=SideEffectClass.READ_ONLY)])
    result = run_delegation(req, plan, parent_capabilities=frozenset({Capability.FILE_READ}), parent_budget=parent_budget, registry=registry, require_schema_validation=True)
    assert result.trusted is False  # require_schema_validation=True means caller must validate before trusting


def test_delegation_consumes_exactly_one_parent_agent_call(registry):
    parent_budget = CognitiveBudget(max_agent_calls=1)
    req = DelegationRequest(goal=AgentGoal(objective="x", allowed_action_classes=frozenset({SideEffectClass.READ_ONLY})), capabilities_subset=frozenset())
    task = AgentTask(description="r")
    plan = AgentPlan(tasks=[task], actions=[])
    run_delegation(req, plan, parent_capabilities=frozenset(), parent_budget=parent_budget, registry=registry)
    assert parent_budget.consumed_agent_calls == 1


def test_second_delegation_is_blocked_once_parent_agent_calls_exhausted(registry):
    parent_budget = CognitiveBudget(max_agent_calls=1)
    req = DelegationRequest(goal=AgentGoal(objective="x", allowed_action_classes=frozenset({SideEffectClass.READ_ONLY})), capabilities_subset=frozenset())
    plan = AgentPlan(tasks=[], actions=[])
    run_delegation(req, plan, parent_capabilities=frozenset(), parent_budget=parent_budget, registry=registry)
    result2 = run_delegation(req, plan, parent_capabilities=frozenset(), parent_budget=parent_budget, registry=registry)
    assert result2.status == AgentRunStatus.BLOCKED
