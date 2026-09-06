"""
Per-tool/connector simulation capability declarations (Phase 11 spec
§10). A separate registry keyed by `tool_id`/`connector_type.value`
rather than adding fields directly to `orca.agent.contracts.ToolSpec`
(a foundational, heavily-tested Phase 8 contract) -- mirrors the same
"wrap, don't modify a core contract" discipline Phase 9's
`orca.connectors.agent_bridge` and Phase 10's `orca.godmode.capability`
already established. Never inferred from a tool's name -- every entry
below is a deliberate, reviewed declaration.
"""
from __future__ import annotations

from orca.simulation.contracts import ToolSimulationCapability

_REGISTRY: dict[str, ToolSimulationCapability] = {
    "read_file": ToolSimulationCapability(supports_static_validation=True, supports_dry_run=False, supports_sandbox=False, simulation_fidelity="LOW"),
    "write_file": ToolSimulationCapability(supports_static_validation=True, supports_dry_run=False, supports_sandbox=True, simulation_fidelity="HIGH"),
    "shell": ToolSimulationCapability(supports_static_validation=True, supports_dry_run=False, supports_sandbox=False, simulation_fidelity="LOW"),
    "web_search": ToolSimulationCapability(supports_static_validation=True, supports_dry_run=False, supports_sandbox=False, simulation_fidelity="LOW"),
    "CONNECTOR_TICKETING": ToolSimulationCapability(supports_static_validation=True, supports_dry_run=False, supports_sandbox=False, supports_preview=True, simulation_fidelity="MEDIUM"),
    "CONNECTOR_DOCUMENT_STORE": ToolSimulationCapability(supports_static_validation=True, supports_dry_run=False, supports_sandbox=False, supports_preview=False, simulation_fidelity="LOW"),
}

_DEFAULT = ToolSimulationCapability(supports_static_validation=True)


def capability_for(tool_id: str) -> ToolSimulationCapability:
    """Never guesses from substrings in `tool_id` -- an exact-key lookup
    only, falling back to the conservative default (static-analysis-only,
    every other mode UNAVAILABLE) for anything not explicitly declared."""
    return _REGISTRY.get(tool_id, _DEFAULT)


def register_capability(tool_id: str, capability: ToolSimulationCapability) -> None:
    _REGISTRY[tool_id] = capability
