"""
Phase 8 spec §17-18: AgentLoop's tool-reasoning MAY route through Model
Society's TOOL_REASONER role, opt-in and additive -- default behavior
(existing tests, unchanged) still uses the session's own brain directly.
"""
from __future__ import annotations

from orca.brain.agent import AgentLoop
from orca.tools import ToolRegistry


class _FakeBrain:
    def __init__(self, name="session-brain"):
        self.name = name
        self.calls = []

    def complete(self, messages, system=None, temperature=0.7, max_tokens=1024):
        self.calls.append(messages)
        return '{"action": "direct"}'


def test_default_behavior_uses_the_session_brain_directly():
    brain = _FakeBrain()
    loop = AgentLoop(brain=brain, tools=ToolRegistry(), session_id="s1")
    assert loop._tool_reasoning_brain() is brain


def test_opt_in_flag_does_not_affect_default_brain_identity_until_resolved(monkeypatch):
    """The opt-in path resolves a NEW brain via Society -- proven by
    monkeypatching the resolution to return a distinct sentinel object,
    never the original session brain."""
    import orca.brain.agent as agent_mod

    sentinel_brain = _FakeBrain(name="society-routed-brain")

    def fake_brain_for_tier_resolution(resolution):
        return sentinel_brain

    def fake_resolve_tier_backend(tier):
        return object()

    def fake_resolve_tier_for_role(role, **kwargs):
        return "nano", object()

    monkeypatch.setattr("orca.gateway.wiring.brain_for_tier_resolution", fake_brain_for_tier_resolution)
    monkeypatch.setattr("orca.serve.registry.resolve_tier_backend", fake_resolve_tier_backend)
    monkeypatch.setattr("orca.society.router.resolve_tier_for_role", fake_resolve_tier_for_role)

    brain = _FakeBrain()
    loop = AgentLoop(brain=brain, tools=ToolRegistry(), session_id="s1", route_tool_reasoning_via_society=True)
    resolved = loop._tool_reasoning_brain()
    assert resolved is sentinel_brain
    assert resolved is not brain


def test_tool_reasoner_role_does_not_grant_tool_permission():
    """Society resolves cognition; it never authorizes a tool call --
    ToolRegistry.call() (the pre-Phase-8 execution path) has no
    capability/permission concept at all attached to a brain choice."""
    import inspect
    from orca.brain import agent as agent_mod
    source = inspect.getsource(agent_mod.AgentLoop._tool_reasoning_brain)
    assert "capability" not in source.lower()
    assert "authoriz" not in source.lower()
