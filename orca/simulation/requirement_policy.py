"""
Simulation Requirement Policy (Phase 11 spec §8-9). Fully deterministic
-- no model call -- mirroring `orca.agent.policy`/`orca.connectors.policy`'s
own discipline. Decides whether simulation is required BEFORE any
simulation work happens; never simulates every read-only operation.
"""
from __future__ import annotations

from dataclasses import dataclass, field

from orca.agent.contracts import ActionRiskLevel, SideEffectClass
from orca.simulation.contracts import SimulationRequirement, ToolSimulationCapability

# spec §8's trigger list, each independently sufficient to require
# simulation.
_ALWAYS_REQUIRES_SIMULATION = {SideEffectClass.DESTRUCTIVE, SideEffectClass.IRREVERSIBLE_WRITE}


@dataclass
class SimulationRequirementContext:
    side_effect_class: SideEffectClass = SideEffectClass.READ_ONLY
    risk: ActionRiskLevel = ActionRiskLevel.LOW
    is_elevated_action: bool = False               # Godmode/elevated
    is_production_resource: bool = False
    is_bulk_operation: bool = False
    has_uncertain_effect_scope: bool = False
    has_weak_rollback: bool = False
    has_unresolved_court_contradiction: bool = False
    provider_state_unknown: bool = False


def decide_simulation_requirement(
    ctx: SimulationRequirementContext, capability: ToolSimulationCapability,
) -> SimulationRequirement:
    """
    Read-only actions with none of the risk triggers are NOT_REQUIRED
    (spec §8's "do not simulate every read-only operation"). Any single
    trigger below escalates to at least REQUIRED. If a genuine
    simulation mechanism is unavailable for this tool/connector at the
    point of REQUIRED, the caller must ask again via
    `capability_permits_any_mode()` and fall back to
    UNAVAILABLE_BUT_REVIEW_REQUIRED -- this function itself only decides
    the POLICY requirement, never whether a mechanism exists (kept
    separate on purpose: policy is deterministic and static;
    availability depends on the specific tool/connector).
    """
    triggers = []

    if ctx.side_effect_class in _ALWAYS_REQUIRES_SIMULATION:
        triggers.append(f"side_effect_class={ctx.side_effect_class.value}")
    if ctx.side_effect_class == SideEffectClass.EXTERNAL_SIDE_EFFECT:
        triggers.append("side_effect_class=EXTERNAL_SIDE_EFFECT")
    if ctx.is_elevated_action:
        triggers.append("elevated_action")
    if ctx.risk in (ActionRiskLevel.HIGH, ActionRiskLevel.CRITICAL):
        triggers.append(f"risk={ctx.risk.value}")
    if ctx.is_production_resource:
        triggers.append("production_resource")
    if ctx.is_bulk_operation:
        triggers.append("bulk_operation")
    if ctx.has_uncertain_effect_scope:
        triggers.append("uncertain_effect_scope")
    if ctx.has_weak_rollback:
        triggers.append("weak_rollback")
    if ctx.has_unresolved_court_contradiction:
        triggers.append("unresolved_court_contradiction")
    if ctx.provider_state_unknown:
        triggers.append("unknown_provider_state")

    if not triggers:
        if ctx.side_effect_class == SideEffectClass.READ_ONLY:
            return SimulationRequirement.NOT_REQUIRED
        return SimulationRequirement.OPTIONAL

    if not capability.supports_static_validation and not capability.supports_dry_run and not capability.supports_sandbox and not capability.supports_preview:
        return SimulationRequirement.UNAVAILABLE_BUT_REVIEW_REQUIRED

    return SimulationRequirement.REQUIRED


def any_mechanism_available(capability: ToolSimulationCapability) -> bool:
    return capability.supports_static_validation or capability.supports_dry_run or capability.supports_sandbox or capability.supports_preview
