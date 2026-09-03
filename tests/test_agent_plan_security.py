"""
Plan security tests (Phase 8.1 spec §7, §44). A model-generated plan is a
proposal only -- it cannot add capabilities, change entitlement, increase
budget, invent a privileged tool, mark itself approved, or bypass the
Policy Engine. All adversarial framings must fail safely.
"""
from __future__ import annotations

import dataclasses

import pytest

from orca.agent.contracts import AgentGoal, AgentPlan, SideEffectClass
from orca.agent.planner import PlanningFailureReason, _validate_and_build_plan
from orca.agent.tool_registry import build_agent_tool_registry


def _specs():
    registry = build_agent_tool_registry()
    return {"read_file": registry.get_spec("read_file")}


def test_plan_cannot_invent_a_privileged_tool():
    """"Give yourself FILE_WRITE" / "use unrestricted shell" via an
    invented tool_id -- rejected outright, never silently dropped and
    the rest executed."""
    raw = {"tasks": [{"description": "t"}], "actions": [{"task_index": 0, "tool_id": "sudo_shell", "arguments": {"command": "give yourself FILE_WRITE"}}]}
    plan = _validate_and_build_plan(raw, _specs())
    assert plan is None


def test_plan_cannot_reference_an_out_of_scope_tool_not_offered():
    """Defense in depth (spec §8): even if a tool_id happens to be a REAL
    tool elsewhere in the system, it's rejected here because it was not
    in THIS call's allowed_tool_specs -- e.g. 'write_file' offered to a
    read-only planner request."""
    raw = {"tasks": [{"description": "t"}], "actions": [{"task_index": 0, "tool_id": "write_file", "arguments": {"path": "x", "content": "y"}}]}
    plan = _validate_and_build_plan(raw, _specs())  # only read_file offered
    assert plan is None


def test_agent_plan_has_no_capability_or_entitlement_field():
    """A plan cannot itself grant a capability or increase entitlement --
    AgentPlan carries no such field at all."""
    field_names = {f.name for f in dataclasses.fields(AgentPlan)}
    assert not (field_names & {"capabilities", "entitlement", "capability_grant", "budget_override"})


def test_agent_plan_has_no_approved_or_authorized_field():
    """"Mark this approved" -- there is no field on AgentPlan/AgentTask/
    AgentAction a model's plan output could set to fake approval."""
    from orca.agent.contracts import AgentAction, AgentTask
    for cls in (AgentPlan, AgentTask, AgentAction):
        field_names = {f.name for f in dataclasses.fields(cls)}
        assert not (field_names & {"approved", "authorized", "pre_approved"})


def test_oversized_plan_is_rejected():
    """"No model-generated unbounded DAGs" (spec §9)."""
    from orca.agent.planner import MAX_TASKS
    raw = {"tasks": [{"description": f"t{i}"} for i in range(MAX_TASKS + 5)], "actions": []}
    plan = _validate_and_build_plan(raw, _specs())
    assert plan is None


def test_plan_dependency_index_out_of_range_is_rejected():
    """A malformed/adversarial dependency index (e.g. pointing outside
    the task list) must not silently execute a partially-parsed plan."""
    raw = {"tasks": [{"description": "t", "depends_on_index": [99]}], "actions": []}
    plan = _validate_and_build_plan(raw, _specs())
    assert plan is None


def test_scope_and_tenant_are_not_plan_controlled():
    """"Change tenant/scope" -- AgentGoal.scope is set by the CALLER
    constructing the goal, never by the planner's own output; the plan
    schema (_validate_and_build_plan) has no code path that reads or sets
    goal.scope at all."""
    import inspect
    from orca.agent import planner as planner_mod
    source = inspect.getsource(planner_mod._validate_and_build_plan)
    assert "goal" not in source  # the plan builder never even receives the goal object


def test_ipc_arguments_are_a_plain_dict_never_executable_code():
    """Plan action arguments are validated as a plain JSON-shaped dict --
    no eval/exec path exists for whatever a model puts in `arguments`."""
    raw = {"tasks": [{"description": "t"}], "actions": [{"task_index": 0, "tool_id": "read_file", "arguments": "__import__('os').system('rm -rf /')"}]}
    plan = _validate_and_build_plan(raw, _specs())
    assert plan is None  # arguments must be a dict, not a string
