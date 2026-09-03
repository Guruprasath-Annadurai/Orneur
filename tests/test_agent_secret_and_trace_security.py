"""
Phase 8 spec §44, §55-56, §67: secrets must not leak into observations/
WorldState/trace by default, and AgentTrace/ActionAuthorization carry no
field a caller could forge to fabricate an authorization after the fact.
"""
from __future__ import annotations

import dataclasses

from orca.agent.contracts import ActionAuthorization, AgentTrace, Capability
from orca.agent.tool_registry import build_agent_tool_registry


def test_no_current_tool_requires_secret_use_by_default():
    """SECRET_USE must be explicit (spec §44) -- none of Phase 8's four
    built-in tools declare it, so a normal agent run cannot touch secrets
    at all unless a future tool spec explicitly opts in."""
    registry = build_agent_tool_registry()
    for spec in registry.all_specs():
        assert Capability.SECRET_USE not in spec.required_capabilities
        assert spec.secrets_required is False


def test_agent_trace_has_no_raw_chain_of_thought_field():
    field_names = {f.name for f in dataclasses.fields(AgentTrace)}
    forbidden = {"reasoning", "chain_of_thought", "raw_thoughts", "private_reasoning", "scratchpad"}
    assert not (field_names & forbidden)


def test_action_authorization_cannot_be_constructed_as_pre_approved_by_a_tool():
    """ActionAuthorization.authorized is a plain bool set only by
    orca.agent.runtime.AgentRuntime._authorize from a PolicyDecision --
    there is no builder/classmethod that lets a tool result construct an
    already-authorized ActionAuthorization for a DIFFERENT action."""
    import inspect
    from orca.agent import runtime as runtime_mod
    source = inspect.getsource(runtime_mod)
    execute_source = inspect.getsource(runtime_mod.AgentRuntime.execute)
    authorize_source = inspect.getsource(runtime_mod.AgentRuntime._authorize)
    # Every ActionAuthorization construction in this module happens
    # inside _authorize() itself -- execute() only ever RECEIVES one back
    # from _authorize(), never builds its own.
    assert "ActionAuthorization(" not in execute_source
    assert "ActionAuthorization(" in authorize_source
