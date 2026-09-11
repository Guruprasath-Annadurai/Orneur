"""
Phase 8.1 spec §22, §40: the full integration order, and proof that
simple/safe requests skip Memory/Truth/Court unless a real trigger exists.
"""
from __future__ import annotations

import pytest

from orca.agent.contracts import ActionRiskLevel, AgentGoal, AgentRunStatus, Capability, SideEffectClass
from orca.agent.orchestrator import run_agent_request
from orca.agent.tool_registry import build_agent_tool_registry


class _FakeCheckpointRecord:
    def is_routable(self) -> bool:
        return True


@pytest.fixture(autouse=True)
def _hermetic_model_society_routing(monkeypatch):
    """Phase 15.15 CI truthfulness closure: run_agent_request() ->
    AgentPlanner.compile_plan() -> resolve_tier_for_role() -> route()
    resolves its DEFAULT checkpoint_lookup from orca.society.router's
    own module globals -- a real CheckpointRecord read from
    ORCA_HOME/registry/checkpoints/, present on a development machine
    (real historical checkpoint imports) but genuinely absent on a
    fresh CI checkout, which silently made every role ineligible there
    (`NO_ELIGIBLE_REASONER`, short-circuiting orchestration before it
    ever reached the mocked gateway_json_call). Patched module-wide
    for this file since every test here exercises the same real
    production routing path."""
    from orca.society import router as router_mod

    monkeypatch.setattr(router_mod, "_default_checkpoint_lookup", lambda checkpoint_id: _FakeCheckpointRecord())


@pytest.mark.asyncio
async def test_simple_safe_goal_skips_court_review(monkeypatch):
    called = {"n": 0}

    async def fake_request_court_review(*args, **kwargs):
        called["n"] += 1
        return None, None, None

    monkeypatch.setattr("orca.agent.orchestrator.request_court_review", fake_request_court_review)

    async def fake_gateway_json_call(prompt, system, tier="nano", max_tokens=400, **kwargs):
        return {"tasks": [{"description": "read"}], "actions": [{"task_index": 0, "tool_id": "read_file", "arguments": {"path": "x"}}]}

    monkeypatch.setattr("orca.truth.llm.gateway_json_call", fake_gateway_json_call)

    registry = build_agent_tool_registry()
    goal = AgentGoal(objective="read a file", risk=ActionRiskLevel.LOW, allowed_action_classes=frozenset({SideEffectClass.READ_ONLY}))

    result = await run_agent_request(goal, registry=registry, capabilities=frozenset({Capability.FILE_READ}), use_memory=False)

    assert called["n"] == 0  # Court was never invoked for a low-risk, non-destructive goal
    assert result.run.status == AgentRunStatus.COMPLETED


@pytest.mark.asyncio
async def test_high_risk_goal_does_invoke_court_review(monkeypatch):
    called = {"n": 0}

    async def fake_request_court_review(*args, **kwargs):
        called["n"] += 1
        return None, None, None

    monkeypatch.setattr("orca.agent.orchestrator.request_court_review", fake_request_court_review)

    async def fake_gateway_json_call(prompt, system, tier="nano", max_tokens=400, **kwargs):
        return {"tasks": [{"description": "read"}], "actions": [{"task_index": 0, "tool_id": "read_file", "arguments": {"path": "x"}}]}

    monkeypatch.setattr("orca.truth.llm.gateway_json_call", fake_gateway_json_call)

    registry = build_agent_tool_registry()
    goal = AgentGoal(objective="do something risky", risk=ActionRiskLevel.HIGH, allowed_action_classes=frozenset({SideEffectClass.READ_ONLY}))

    await run_agent_request(goal, registry=registry, capabilities=frozenset({Capability.FILE_READ}), use_memory=False)

    assert called["n"] == 1


@pytest.mark.asyncio
async def test_full_orchestration_end_to_end_deterministic(monkeypatch):
    async def fake_gateway_json_call(prompt, system, tier="nano", max_tokens=400, **kwargs):
        return {"tasks": [{"description": "read"}], "actions": [{"task_index": 0, "tool_id": "read_file", "arguments": {"path": "x"}}]}

    monkeypatch.setattr("orca.truth.llm.gateway_json_call", fake_gateway_json_call)

    registry = build_agent_tool_registry()
    goal = AgentGoal(objective="read a file", allowed_action_classes=frozenset({SideEffectClass.READ_ONLY}))

    result = await run_agent_request(goal, registry=registry, capabilities=frozenset({Capability.FILE_READ}), use_memory=False)

    assert result.planning_outcome.plan is not None
    assert result.run.status == AgentRunStatus.COMPLETED
    assert result.world_state.known_facts
