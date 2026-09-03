"""
Lease issuance authority (Phase 10 spec §9-11). Only
`HUMAN_APPROVAL`/`SYSTEM_POLICY`/`ADMIN_POLICY` may ever call
`issue_lease()` -- there is no code path here that accepts a model
output, tool result, retrieved content, Memory record, or Court verdict
as the thing that activates a lease. An `ElevatedCapabilityRequest`
(which a model MAY produce) is only ever a proposal; it is never passed
directly into `issue_lease()` without a `GodmodeApproval` binding it
exactly (mirroring `orca.connectors.security.ApprovalBinding`'s exact-
match discipline, generalized beyond connectors).
"""
from __future__ import annotations

import hashlib

from orca.godmode.contracts import (
    CapabilityDomain,
    CapabilityLease,
    ElevatedCapabilityRequest,
    GodmodeApproval,
    LeaseIssuanceError,
    LeaseIssuerClass,
    now_iso,
    parse_iso,
)
from orca.godmode.integrity import apply_signature
from orca.godmode.lease_store import save as save_lease

_MAX_LEASE_DURATION_S = 900.0  # spec §39: conservative default, no 24h Godmode sessions


def arguments_hash_of(arguments: dict) -> str:
    raw = repr(sorted(arguments.items()))
    return hashlib.sha256(raw.encode()).hexdigest()


def make_approval(
    *, request: ElevatedCapabilityRequest, approved_by: str, duration_s: float,
    arguments: dict | None = None,
) -> GodmodeApproval:
    """
    Constructed ONLY by trusted platform code acting on a real human (or
    system/admin policy) decision -- never by a model. Binds to the
    EXACT capability/resource/operation the request named, plus a hash
    of any concrete arguments, so the resulting lease cannot later be
    stretched to cover a different action (spec §10).
    """
    duration_s = min(duration_s, _MAX_LEASE_DURATION_S)
    expires_at = _expiry_from_now(duration_s)
    return GodmodeApproval(
        approval_id=f"gmappr-{request.request_id}",
        principal_id=request.principal_id, tenant_id=request.tenant_id,
        capability_domain=request.capability_domain, capability=request.capability,
        resource_scope=request.resource_scope, operation_scope=request.operation_scope,
        arguments_hash=arguments_hash_of(arguments or {}),
        duration_s=duration_s, reason=request.reason, approved_by=approved_by,
        expires_at=expires_at,
    )


def _expiry_from_now(duration_s: float) -> str:
    from datetime import timedelta
    return (parse_iso(now_iso()) + timedelta(seconds=duration_s)).strftime("%Y-%m-%dT%H:%M:%SZ")


def issue_lease(
    *,
    approval: GodmodeApproval,
    issuer: LeaseIssuerClass,
    issuer_id: str,
    max_uses: int | None = 1,
    delegable: bool = False,
) -> CapabilityLease:
    """
    The ONLY function in this codebase that produces a valid, signed
    `CapabilityLease`. Structural guards, every one fail-closed
    (raises `LeaseIssuanceError`, never silently narrows and proceeds):

    - `issuer` must be one of the three trusted classes (enum-typed, so
      no other value is even representable).
    - No wildcard capability/resource/operation (spec §7's "bad lease"
      examples -- 'everything', 'admin', 'all tools forever').
    - Duration is capped at `_MAX_LEASE_DURATION_S` regardless of what
      the approval or caller requested (spec §39).
    - The resulting lease is ALWAYS signed before being persisted --
      there is no code path that saves an unsigned lease.
    """
    if issuer not in (LeaseIssuerClass.HUMAN_APPROVAL, LeaseIssuerClass.SYSTEM_POLICY, LeaseIssuerClass.ADMIN_POLICY):
        raise LeaseIssuanceError(f"issuer class {issuer!r} is not a trusted issuance authority")

    lease = CapabilityLease(
        principal_id=approval.principal_id, tenant_id=approval.tenant_id,
        capability_domain=approval.capability_domain, capability=approval.capability,
        resource_scope=approval.resource_scope, operation_scope=approval.operation_scope,
        expires_at=approval.expires_at, issuer=issuer, issuer_id=issuer_id,
        reason=approval.reason, approval_id=approval.approval_id,
        max_uses=max_uses, uses_remaining=max_uses, delegable=delegable,
    )

    if lease.is_wildcard():
        raise LeaseIssuanceError(f"wildcard lease scope rejected: capability={lease.capability!r} resource_scope={lease.resource_scope!r} operation_scope={lease.operation_scope!r}")

    apply_signature(lease)
    save_lease(lease)
    return lease
