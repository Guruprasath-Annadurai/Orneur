"""
Phase 8.1 spec §43: at least one controlled live-Ollama test exercising
AgentGoal -> TOOL_REASONER via Model Society -> validated AgentPlan, using
only safe read-only tools (never destructive/external actions).
"""
from __future__ import annotations

import pytest

from orca.agent.contracts import AgentGoal, SideEffectClass
from orca.agent.planner import AgentPlanner
from orca.agent.tool_registry import build_agent_tool_registry
from orca.cognitive.contracts import CognitiveBudget
from tests.ollama_test_support import require_ollama, warm_model


@pytest.mark.asyncio
@pytest.mark.live_ollama_smoke
async def test_live_goal_produces_a_validated_plan_using_only_read_only_tools():
    require_ollama()
    warm_model("nano")  # Phase 11.2: absorb cold-load latency here, not in this test's own budget
    registry = build_agent_tool_registry()
    # Only offer read-only tools -- the plan CANNOT propose a write/shell/
    # destructive action even if the model wanted to (spec §8's "planner
    # receives only tools allowed to be considered").
    allowed = {"read_file": registry.get_spec("read_file")}

    planner = AgentPlanner()
    goal = AgentGoal(
        objective="Read the file named notes.txt and summarize what it contains.",
        allowed_action_classes=frozenset({SideEffectClass.READ_ONLY}),
    )
    budget = CognitiveBudget(max_model_calls=6)
    outcome = await planner.compile_plan(goal, allowed_tool_specs=allowed, budget=budget)

    assert outcome.plan is not None, outcome.failure
    assert outcome.model_id is not None
    assert outcome.checkpoint_id is not None
    for action in outcome.plan.actions:
        assert action.tool_id == "read_file"  # never invented, never a write/shell/destructive tool
    assert budget.consumed_model_calls >= 1
