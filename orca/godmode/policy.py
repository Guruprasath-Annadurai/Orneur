"""
Elevated Policy Engine (Phase 10 spec §19-20, §37). Wraps
`orca.agent.policy.evaluate_policy()` -- NEVER replaces it (spec §19:
"Policy Engine remains authoritative"). The normal Policy Engine always
runs first; a lease is only ever CONSULTED when the normal decision is
not already ALLOW, and even a fully valid, scope-matched lease can still
be denied on top (kill switch, missing approval elsewhere, etc -- lease
validity is necessary, never sufficient, mirroring Capability's own
"necessary but not sufficient" discipline from Phase 8).
"""
from __future__ import annotations

from orca.agent.contracts import (
    AgentGoal,
    CapabilityDecision,
    PolicyDecision,
    PolicyDecisionState,
    SideEffectClass,
    ToolSpec,
)
from orca.agent.policy import evaluate_policy
from orca.godmode.contracts import (
    CapabilityDomain,
    ElevatedPolicyDecision,
    ElevatedPolicyDecisionState,
)
from orca.godmode.cancellation import CancellationSignal
from orca.godmode.kill_switch import is_active as kill_switch_active
from orca.godmode.resolution import _SENTINEL, resolve_and_consume_lease

# Denials this deliberately elevation-eligible for (spec §37: "not every
# denied action should request Godmode" -- only these two normal-policy
# outcomes are ever reconsidered against a lease; a flat structural DENY
# for a reason unrelated to scope/risk, e.g. a missing tool spec, is not).
_ELEVATION_ELIGIBLE_STATES = {PolicyDecisionState.DENY, PolicyDecisionState.REQUIRE_APPROVAL}


def evaluate_elevated_policy(
    *,
    goal: AgentGoal,
    tool_spec: ToolSpec,
    capability_decision: CapabilityDecision,
    tenant_id: str,
    lease_id: str | None,
    capability_domain: CapabilityDomain,
    capability: str,
    resource_scope: str,
    operation_scope: str,
    resolved_side_effect_class: SideEffectClass | None = None,
    arguments: dict | None = _SENTINEL,  # type: ignore[assignment]
    cancellation: "CancellationSignal | None" = None,
) -> ElevatedPolicyDecision:
    """
    Returns the full decision trace (spec §20). `lease_id` is the ONE
    lease being considered for this specific action -- callers never pass
    an effective capability *set* here; each elevated action names the
    exact lease it is trying to use.

    `arguments` (Phase 10.1): the action's actual PAYLOAD arguments,
    forwarded to `resolve_and_consume_lease()` -- this is the ONE place
    in the whole elevation flow that both validates the exact-action
    argument binding AND atomically consumes the lease's use, and it
    only ever runs once normal policy has already been checked (never
    consumes speculatively during a mere capability-membership probe --
    see `orca.godmode.capability.compute_effective_capabilities()`,
    which stays read-only).

    `cancellation` (Phase 14B.2): forwarded unchanged to
    `resolve_and_consume_lease()` -- see its docstring for the exact
    checkpoint semantics. `None` (the default) preserves existing
    behavior exactly.
    """
    normal = evaluate_policy(
        goal=goal, tool_spec=tool_spec, capability_decision=capability_decision,
        resolved_side_effect_class=resolved_side_effect_class,
    )

    decision = ElevatedPolicyDecision(normal_decision_state=normal.state.value, reasons=list(normal.reasons))

    if normal.state == PolicyDecisionState.ALLOW:
        decision.state = ElevatedPolicyDecisionState.ALLOW
        return decision

    if normal.state not in _ELEVATION_ELIGIBLE_STATES:
        decision.state = ElevatedPolicyDecisionState.DENY
        return decision

    if lease_id is None:
        decision.state = ElevatedPolicyDecisionState.ELEVATION_REQUIRED
        decision.reasons.append("normal policy denied/requires-approval and no lease was supplied -- elevation may be requested")
        return decision

    lease_decision = resolve_and_consume_lease(
        lease_id, tenant_id=tenant_id, capability_domain=capability_domain, capability=capability,
        resource_scope=resource_scope, operation_scope=operation_scope, arguments=arguments,
        cancellation=cancellation,
    )
    decision.lease_considered_id = lease_id
    decision.cancelled = lease_decision.cancelled
    decision.scope_match = lease_decision.scope_match
    decision.argument_match = lease_decision.argument_match
    decision.binding_mode = lease_decision.binding_mode
    decision.expiry_ok = lease_decision.expiry_ok
    decision.revocation_ok = lease_decision.revocation_ok
    decision.kill_switch_active = lease_decision.kill_switch_active
    decision.reasons.extend(lease_decision.reasons)

    if lease_decision.state != ElevatedPolicyDecisionState.ALLOW:
        decision.state = ElevatedPolicyDecisionState.DENY
        return decision

    decision.state = ElevatedPolicyDecisionState.ALLOW
    return decision
