"""
Phase 15.5 -- the integration point between the Mission/Operation
engine (Neon-backed, this package) and ORNEUR's existing, real
authority engine (`orca.godmode`, Supabase-backed, battle-tested
across Phases 9-14B).

This module deliberately does NOT reimplement authorization. Every
actual "is this allowed" decision is made by
`orca.godmode.resolution.resolve_and_consume_lease()` -- the exact
same race-safe, fail-closed, durably-audited primitive real agent
tool calls and connector elevation already use. This module only:

  1. constructs a narrowly-scoped `CapabilityLease` for exactly one
     operation (`issue_operation_lease()` -- resource_scope is the
     operation's own id, so a lease issued for operation A cannot
     later be reused to authorize operation B: `resolve_lease()`'s
     own exact-match discipline rejects the scope mismatch, proven
     live in tests/test_operation_store_live_neon.py);
  2. consumes that lease atomically (`consume_operation_lease()`,
     a thin wrapper over `resolve_and_consume_lease()`);
  3. never lets caller-supplied text (a model's own claim that
     something is approved) substitute for either of the above --
     `approved_by` must be a real principal, and the ONLY thing that
     can turn a decision into ALLOW is godmode's own
     `ElevatedPolicyDecisionState.ALLOW`.

Per spec section 5 ("authority must be external to model prose"):
`orca.mission.operation_store.authorize_operation()` (the only Phase
15 caller of this module) REJECTS any attempt where `approved_by ==
requested_by` before this module is even invoked -- a model cannot
approve its own request by claiming to be someone else, and a
requester cannot approve themselves even honestly.
"""
from __future__ import annotations

from orca.godmode.contracts import (
    CapabilityDomain,
    ElevatedCapabilityRequest,
    ElevatedPolicyDecision,
    LeaseIssuanceError,
    LeaseIssuerClass,
)
from orca.godmode.issuance import issue_lease, make_approval
from orca.godmode.resolution import resolve_and_consume_lease

_OPERATION_LEASE_DURATION_S = 300.0  # 5 minutes -- ample for START-then-execute, far under godmode's own 900s cap


def _resource_scope_for_operation(operation_id: str) -> str:
    """Narrow, single-operation scope -- the actual mechanism that
    makes 'a lease for operation A cannot authorize operation B' true
    (spec section 6.I). Never a wildcard, never the mission_id alone
    (which would span every operation in the mission)."""
    return f"mission-operation:{operation_id}"


def issue_operation_lease(
    *,
    operation_id: str,
    operation_kind: str,
    tenant_id: str,
    requested_by: str,
    approved_by: str,
    reason: str,
    arguments: dict | None = None,
    issuer: LeaseIssuerClass = LeaseIssuerClass.SYSTEM_POLICY,
):
    """Issues a real, signed, single-use `CapabilityLease` scoped to
    exactly this operation. Raises `LeaseIssuanceError` (from
    `orca.godmode.issuance`) on any structural violation -- never
    returns a degraded/partial lease. `approved_by` is trusted platform
    input (a real principal id), never taken from model output."""
    request = ElevatedCapabilityRequest(
        principal_id=requested_by,
        tenant_id=tenant_id,
        capability_domain=CapabilityDomain.AGENT,
        capability=operation_kind,
        resource_scope=_resource_scope_for_operation(operation_id),
        operation_scope=operation_kind,
        reason=reason,
    )
    approval = make_approval(
        request=request,
        approved_by=approved_by,
        duration_s=_OPERATION_LEASE_DURATION_S,
        arguments=arguments,
    )
    return issue_lease(approval=approval, issuer=issuer, issuer_id=approved_by, max_uses=1)


def consume_operation_lease(
    *,
    lease_id: str,
    operation_id: str,
    operation_kind: str,
    tenant_id: str,
    requested_by: str,
    arguments: dict | None = None,
    trace_id: str | None = None,
) -> ElevatedPolicyDecision:
    """Atomically consumes the lease against the EXACT scope this
    operation requires -- resource_scope MUST match the operation the
    lease was issued for. This is what makes 'operation B cannot be
    authorized with operation A's lease_id' true: passing operation
    B's id here computes a DIFFERENT resource_scope than what the
    lease was issued with, so resolve_lease()'s exact-match check
    denies it before consume_use() is ever attempted -- the lease's
    single use is preserved, not silently burned on a mismatched
    attempt."""
    return resolve_and_consume_lease(
        lease_id,
        tenant_id=tenant_id,
        capability_domain=CapabilityDomain.AGENT,
        capability=operation_kind,
        resource_scope=_resource_scope_for_operation(operation_id),
        operation_scope=operation_kind,
        arguments=arguments,
        principal_id=requested_by,
        trace_id=trace_id,
    )
