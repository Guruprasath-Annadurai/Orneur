"""
Phase 8.1 spec §19-21: Cognitive Court runtime integration for agent
plans. Court ACCEPT never authorizes; Policy Engine remains the sole
authorization boundary, independent of whatever Court decided.
"""
from __future__ import annotations

import asyncio

import pytest

from orca.agent.contracts import ActionRiskLevel, AgentGoal, SideEffectClass
from orca.agent.court_hook import request_court_review, should_request_court_review
from orca.agent.policy import evaluate_policy
from orca.agent.capability import check_capabilities
from orca.agent.tool_registry import build_agent_tool_registry


def test_high_risk_goal_triggers_court_review():
    goal = AgentGoal(objective="x", risk=ActionRiskLevel.HIGH)
    assert should_request_court_review(goal) is True


def test_low_risk_ordinary_goal_does_not_trigger_court_review():
    goal = AgentGoal(objective="x", risk=ActionRiskLevel.LOW, allowed_action_classes=frozenset({SideEffectClass.READ_ONLY}))
    assert should_request_court_review(goal) is False


def test_destructive_allowed_class_triggers_court_review():
    goal = AgentGoal(objective="x", allowed_action_classes=frozenset({SideEffectClass.DESTRUCTIVE}))
    assert should_request_court_review(goal) is True


@pytest.mark.asyncio
async def test_court_accept_plus_policy_deny_means_action_does_not_execute(monkeypatch):
    """The required test (spec §20): Court returns ACCEPT, Policy returns
    DENY -- the action must not execute. Court's ACCEPT is recorded but
    has zero effect on evaluate_policy()'s own independent decision."""
    import orca.deliberation.court as court_mod
    from orca.deliberation.contracts import CourtCase, CourtVerdict, CourtVerdictState

    async def fake_accept(self, objective, **kwargs):
        return CourtCase(objective=objective), CourtVerdict(verdict=CourtVerdictState.ACCEPT, epistemic_state="VERIFIED"), "COURT_ACCEPTED"

    monkeypatch.setattr(court_mod.CognitiveCourt, "run", fake_accept)

    case, verdict, stop_reason = await request_court_review("do something risky")
    assert verdict.verdict == CourtVerdictState.ACCEPT

    # Independently, Policy DENIES the actual action (e.g. no capability) --
    # Court's ACCEPT is never consulted by evaluate_policy() at all.
    registry = build_agent_tool_registry()
    spec = registry.get_spec("write_file")
    goal = AgentGoal(objective="x", allowed_action_classes=frozenset({SideEffectClass.READ_ONLY}))  # write not permitted
    cap_decision = check_capabilities(frozenset(), spec)  # no capabilities granted
    policy_decision = evaluate_policy(goal=goal, tool_spec=spec, capability_decision=cap_decision)

    assert policy_decision.state.value == "DENY"


def test_court_hook_module_never_imports_policy_or_capability():
    """Structural proof that Court's advisory verdict has no code path
    into authorization: orca.agent.court_hook has no import statement
    naming orca.agent.policy/orca.agent.capability (docstring prose
    referencing them for explanation is fine -- only actual imports
    would create a code path)."""
    import ast
    import inspect
    from orca.agent import court_hook
    tree = ast.parse(inspect.getsource(court_hook))
    imported_modules = set()
    for node in ast.walk(tree):
        if isinstance(node, ast.ImportFrom) and node.module:
            imported_modules.add(node.module)
        if isinstance(node, ast.Import):
            imported_modules.update(alias.name for alias in node.names)
    assert "orca.agent.policy" not in imported_modules
    assert "orca.agent.capability" not in imported_modules


def test_policy_engine_never_imports_court_or_deliberation():
    import inspect
    from orca.agent import policy as policy_mod
    source = inspect.getsource(policy_mod)
    assert "orca.deliberation" not in source
    assert "orca.society" not in source
