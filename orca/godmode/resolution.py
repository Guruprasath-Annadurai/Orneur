"""
Lease resolution and validation (Phase 10 spec §17-20, §48-49). This is
the single place that decides whether a specific `(tenant, capability
domain, capability, resource, operation)` request is covered by a named,
valid, active lease. Fail-closed on every ambiguity (spec §16): any
missing/invalid/expired/revoked/mismatched condition is DENY, never a
"best effort" fallback.
"""
from __future__ import annotations

import posixpath

from orca.godmode.canonical import hash_arguments
from orca.godmode.contracts import (
    ArgumentBindingMode,
    CapabilityDomain,
    ElevatedPolicyDecision,
    ElevatedPolicyDecisionState,
    LeaseRevocationState,
)
from orca.godmode.integrity import verify_lease_integrity
from orca.godmode.kill_switch import is_active as kill_switch_active
from orca.godmode.lease_store import consume_use, get as get_lease
from orca.godmode.lease_store import is_expired

_SENTINEL = object()


def _canonicalize(resource_scope: str) -> str:
    """Spec §48: prefix confusion, case normalization, encoded traversal,
    trailing-slash inconsistency must not create a false scope match or a
    false mismatch. Normalizes path-shaped scopes via posixpath (resolves
    `..`/`.`/duplicate slashes) and lower-cases connector/table-style
    identifiers uniformly. This is comparison-time normalization only --
    it never widens what a lease covers, it only ensures two spellings of
    the SAME resource compare equal and two DIFFERENT resources never
    accidentally compare equal."""
    normalized = posixpath.normpath(resource_scope) if "/" in resource_scope else resource_scope
    return normalized.strip().lower()


def resolve_lease(
    lease_id: str,
    *,
    tenant_id: str,
    capability_domain: CapabilityDomain,
    capability: str,
    resource_scope: str,
    operation_scope: str,
    arguments: dict | None = _SENTINEL,  # type: ignore[assignment]
) -> ElevatedPolicyDecision:
    """
    Returns a full decision trace (spec §20) -- never just a bool. Pure
    / read-only: never consumes a lease use itself (see
    `resolve_and_consume_lease()` for the side-effecting entry point real
    callers should use). ALLOW only when every one of the following
    holds, checked in this order (Phase 10.1 spec §19 -- kill switch
    first since it is a system-wide gate cheaper and safer to check
    before touching any per-lease state; documented deviation from the
    spec's suggested ordering, which is otherwise followed):

      kill switch inactive, lease exists, integrity verifies, not
      revoked, not expired, has uses remaining, tenant matches exactly,
      capability domain+value match exactly, resource/operation scope
      match (canonically normalized), AND -- Phase 10.1 -- if the lease's
      `binding_mode` is `EXACT_ARGUMENTS` (the default), the caller's
      canonicalized `arguments` hash matches `lease.arguments_hash`
      exactly.

    `arguments` (Phase 10.1 spec §8-9): omitting it entirely is
    DIFFERENT from passing `arguments={}` -- omitting it means "the
    caller did not supply the actual action arguments at all," which
    FAILS CLOSED against an `EXACT_ARGUMENTS` lease (spec §9: "if the
    lease requires exact action binding and the runtime does not supply
    current arguments: DENY. Do not silently skip the comparison.").
    Passing `arguments={}` is a real, exact claim that the action's
    canonicalized payload is empty, and is compared normally.
    """
    decision = ElevatedPolicyDecision(lease_considered_id=lease_id)

    if kill_switch_active():
        decision.kill_switch_active = True
        decision.reasons.append("kill switch is active -- no new elevated actions")
        decision.state = ElevatedPolicyDecisionState.DENY
        return decision

    lease = get_lease(lease_id)
    if lease is None:
        decision.reasons.append("lease not found")
        decision.state = ElevatedPolicyDecisionState.DENY
        return decision

    if not verify_lease_integrity(lease):
        decision.reasons.append("lease failed integrity verification (tampered or unsigned)")
        decision.state = ElevatedPolicyDecisionState.DENY
        return decision

    decision.revocation_ok = lease.revocation_state != LeaseRevocationState.REVOKED
    if not decision.revocation_ok:
        decision.reasons.append("lease is revoked")
        decision.state = ElevatedPolicyDecisionState.DENY
        return decision

    decision.expiry_ok = not is_expired(lease)
    if not decision.expiry_ok:
        decision.reasons.append("lease is expired")
        decision.state = ElevatedPolicyDecisionState.DENY
        return decision

    if lease.uses_remaining is not None and lease.uses_remaining <= 0:
        decision.reasons.append("lease has no uses remaining")
        decision.state = ElevatedPolicyDecisionState.DENY
        return decision

    if lease.tenant_id != tenant_id:
        decision.reasons.append(f"tenant mismatch: lease belongs to '{lease.tenant_id}', request is '{tenant_id}'")
        decision.state = ElevatedPolicyDecisionState.DENY
        return decision

    if lease.capability_domain != capability_domain or lease.capability != capability:
        decision.reasons.append(f"capability mismatch: lease grants {lease.capability_domain.value}:{lease.capability!r}, request is {capability_domain.value}:{capability!r}")
        decision.state = ElevatedPolicyDecisionState.DENY
        return decision

    decision.scope_match = (
        _canonicalize(lease.resource_scope) == _canonicalize(resource_scope)
        and _canonicalize(lease.operation_scope) == _canonicalize(operation_scope)
    )
    if not decision.scope_match:
        decision.reasons.append(f"scope mismatch: lease covers resource={lease.resource_scope!r} operation={lease.operation_scope!r}")
        decision.state = ElevatedPolicyDecisionState.DENY
        return decision

    decision.binding_mode = lease.binding_mode.value

    if lease.binding_mode == ArgumentBindingMode.EXACT_ARGUMENTS:
        if arguments is _SENTINEL:
            decision.reasons.append("EXACT_ARGUMENTS lease requires the caller's actual action arguments, none were supplied")
            decision.state = ElevatedPolicyDecisionState.DENY
            return decision
        try:
            computed_hash = hash_arguments(arguments or {})
        except TypeError as e:
            decision.reasons.append(f"arguments could not be canonicalized: {e}")
            decision.state = ElevatedPolicyDecisionState.DENY
            return decision
        decision.argument_match = _constant_time_eq(computed_hash, lease.arguments_hash or "")
        if not decision.argument_match:
            decision.reasons.append("argument mismatch: canonicalized action arguments do not match the lease's bound arguments_hash")
            decision.state = ElevatedPolicyDecisionState.DENY
            return decision
    else:
        decision.argument_match = True  # SCOPED_ARGUMENTS: no per-payload binding by explicit policy

    decision.reasons.append("lease valid, scope-matched, and argument-bound")
    decision.state = ElevatedPolicyDecisionState.ALLOW
    return decision


def _constant_time_eq(a: str, b: str) -> bool:
    import hmac
    return hmac.compare_digest(a, b)


def resolve_and_consume_lease(
    lease_id: str,
    *,
    tenant_id: str,
    capability_domain: CapabilityDomain,
    capability: str,
    resource_scope: str,
    operation_scope: str,
    arguments: dict | None = _SENTINEL,  # type: ignore[assignment]
) -> ElevatedPolicyDecision:
    """
    The side-effecting entry point real callers (AgentRuntime, connector
    elevation) should use. Runs the exact same fail-closed validation as
    `resolve_lease()` FIRST -- a request that fails ANY check (including
    a changed-argument mismatch) NEVER reaches `consume_use()`, so it
    never burns a use (Phase 10.1 spec §18-19: "Do not consume a lease
    on a request that fails exact-action matching"). Only after
    `resolve_lease()` itself returns ALLOW does this attempt the atomic
    `consume_use()` -- if THAT loses a concurrent race (spec §18's
    "changed-argument competitor must not consume... verify ordering"
    generalizes to: only one of any N concurrent, otherwise-identical,
    valid requests may consume the single use), the decision is
    downgraded to DENY here, never silently treated as success.
    """
    decision = resolve_lease(
        lease_id, tenant_id=tenant_id, capability_domain=capability_domain, capability=capability,
        resource_scope=resource_scope, operation_scope=operation_scope, arguments=arguments,
    )
    if decision.state != ElevatedPolicyDecisionState.ALLOW:
        return decision

    if not consume_use(lease_id):
        decision.state = ElevatedPolicyDecisionState.DENY
        decision.reasons.append("lease use could not be atomically consumed (exhausted, revoked, or expired between validation and consumption)")
        return decision

    return decision
