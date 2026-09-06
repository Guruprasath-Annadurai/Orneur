"""
Capability Engine (Phase 8 spec §10-11). Capability describes what an
agent may REQUEST -- having a capability does NOT automatically authorize
an action; the Policy Engine (orca/agent/policy.py) still evaluates scope/
path/risk/resource on top of a granted capability (spec §11's explicit
"capability is necessary, not sufficient").
"""
from __future__ import annotations

from orca.agent.contracts import Capability, CapabilityDecision, ToolSpec


def check_capabilities(granted: frozenset[Capability], spec: ToolSpec) -> CapabilityDecision:
    """
    Purely a membership check: does the agent's granted capability set
    cover everything `spec.required_capabilities` names? No godmode
    wildcard, no capability escalation path -- an agent's capability set
    is fixed for the duration of its run (spec §31: child_capabilities ⊆
    parent_capabilities; nothing here ever WIDENS a set after creation).
    """
    missing = spec.required_capabilities - granted
    if missing:
        return CapabilityDecision(granted=False, missing=frozenset(missing), reasons=[f"missing capability: {c.value}" for c in missing])
    return CapabilityDecision(granted=True, missing=frozenset(), reasons=["all required capabilities present"])
