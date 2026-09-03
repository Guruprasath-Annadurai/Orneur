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

from orca.godmode.contracts import (
    CapabilityDomain,
    ElevatedPolicyDecision,
    ElevatedPolicyDecisionState,
    LeaseRevocationState,
)
from orca.godmode.integrity import verify_lease_integrity
from orca.godmode.kill_switch import is_active as kill_switch_active
from orca.godmode.lease_store import get as get_lease
from orca.godmode.lease_store import is_expired


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
) -> ElevatedPolicyDecision:
    """
    Returns a full decision trace (spec §20) -- never just a bool. ALLOW
    only when every one of the following holds:

      lease exists, integrity verifies, not revoked, not expired,
      tenant matches exactly, capability domain+value match exactly,
      resource scope matches (canonically normalized), operation scope
      matches (canonically normalized), kill switch is not active.

    Any single failure is DENY with a specific reason -- this function
    never partially succeeds.
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

    decision.reasons.append("lease valid and scope-matched")
    decision.state = ElevatedPolicyDecisionState.ALLOW
    return decision
