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

from orca.godmode.canonical import hash_arguments
from orca.godmode.contracts import (
    ArgumentBindingMode,
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
    """Phase 10.1 (spec §3): delegates to the one canonical hasher --
    kept as a thin, named wrapper so callers/tests written against this
    function name keep working, but it no longer uses `repr(sorted(...))`
    (unstable across nested structures/types -- exactly the anti-pattern
    spec §3 forbids)."""
    return hash_arguments(arguments)


def make_approval(
    *, request: ElevatedCapabilityRequest, approved_by: str, duration_s: float,
    arguments: dict | None = None, binding_mode: ArgumentBindingMode = ArgumentBindingMode.EXACT_ARGUMENTS,
) -> GodmodeApproval:
    """
    Constructed ONLY by trusted platform code acting on a real human (or
    system/admin policy) decision -- never by a model. Binds to the
    EXACT capability/resource/operation the request named, plus a
    canonical hash of the action PAYLOAD arguments (spec §4: distinct
    from `resource_scope`/`operation_scope`, which remain the lease's
    coarse-grained scope), so the resulting lease cannot later be
    stretched to cover a different action (spec §10).

    `arguments=None` (the default) is NOT "no binding" -- it hashes to
    "canonically empty payload," an EXACT binding that only an action
    genuinely called with no payload arguments will match. True
    argument-agnostic behavior requires `binding_mode=SCOPED_ARGUMENTS`
    explicitly (spec §13) -- never inferred from an absent `arguments`.
    """
    duration_s = min(duration_s, _MAX_LEASE_DURATION_S)
    expires_at = _expiry_from_now(duration_s)
    return GodmodeApproval(
        approval_id=f"gmappr-{request.request_id}",
        principal_id=request.principal_id, tenant_id=request.tenant_id,
        capability_domain=request.capability_domain, capability=request.capability,
        resource_scope=request.resource_scope, operation_scope=request.operation_scope,
        arguments_hash=hash_arguments(arguments or {}),
        duration_s=duration_s, reason=request.reason, approved_by=approved_by,
        expires_at=expires_at, binding_mode=binding_mode,
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

    # Phase 10.1 spec §6's required invariant: lease.arguments_hash ==
    # approval.arguments_hash for an exact-action approval -- enforced
    # structurally by COPYING it directly from the approval; there is no
    # parameter on this function through which a caller could supply a
    # different value.
    lease = CapabilityLease(
        principal_id=approval.principal_id, tenant_id=approval.tenant_id,
        capability_domain=approval.capability_domain, capability=approval.capability,
        resource_scope=approval.resource_scope, operation_scope=approval.operation_scope,
        expires_at=approval.expires_at, issuer=issuer, issuer_id=issuer_id,
        reason=approval.reason, approval_id=approval.approval_id,
        max_uses=max_uses, uses_remaining=max_uses, delegable=delegable,
        arguments_hash=(approval.arguments_hash if approval.binding_mode == ArgumentBindingMode.EXACT_ARGUMENTS else None),
        binding_mode=approval.binding_mode,
    )

    if lease.is_wildcard():
        raise LeaseIssuanceError(f"wildcard lease scope rejected: capability={lease.capability!r} resource_scope={lease.resource_scope!r} operation_scope={lease.operation_scope!r}")

    if not lease.is_argument_binding_consistent():
        raise LeaseIssuanceError("EXACT_ARGUMENTS lease requires a non-empty arguments_hash -- use binding_mode=SCOPED_ARGUMENTS explicitly for argument-agnostic leases")

    apply_signature(lease)
    save_lease(lease)
    return lease
