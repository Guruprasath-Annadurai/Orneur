"""
Lease delegation (Phase 10 spec §53-54). Modeled directly on
`orca.agent.delegation`'s existing, tested non-escalation discipline
(`child_capabilities ⊆ parent_capabilities`, `child_budget <= parent
remaining`) rather than inventing a separate delegation philosophy.

Default: a `CapabilityLease` is NOT delegable (`delegable=False` is the
dataclass default in `orca.godmode.contracts`). A child lease may only
ever be issued from a delegable parent lease, and only as a scope
SUBSET, never equal-or-wider.
"""
from __future__ import annotations

from orca.godmode.contracts import (
    CapabilityLease,
    LeaseIssuanceError,
    LeaseIssuerClass,
    now_iso,
    parse_iso,
)
from orca.godmode.integrity import apply_signature, verify_lease_integrity
from orca.godmode.lease_store import get as get_lease
from orca.godmode.lease_store import is_expired as lease_is_expired
from orca.godmode.lease_store import reserve_uses as reserve_parent_uses
from orca.godmode.lease_store import save as save_lease


class LeaseDelegationError(ValueError):
    """Raised for any delegation invariant violation -- never silently
    narrowed and allowed through."""


def delegate_lease(
    parent_lease_id: str,
    *,
    child_principal_id: str,
    child_max_uses: int,
    child_duration_s: float,
    reason: str,
) -> CapabilityLease:
    """
    Issues a CHILD lease from a parent lease. Required (spec §53), all
    fail-closed via `LeaseDelegationError`:

    - parent lease must exist, be valid (integrity, not expired, not
      revoked), and have `delegable=True` (spec §54's "ordinary elevated
      lease cannot automatically flow to subagent" -- the DEFAULT is
      non-delegable, and this function is the ONLY path that produces a
      child, so a non-delegable parent can never spawn one here or
      anywhere else).
    - child scope (capability/resource/operation) is IDENTICAL to the
      parent's -- delegation in this system narrows by usage/duration
      only, never by granting a DIFFERENT resource/operation than the
      parent already covers (a genuinely different scope would be a new,
      independently-approved lease, not a delegation).
    - child `expires_at` <= parent `expires_at`.
    - child `max_uses` <= parent's remaining uses (when the parent is
      use-limited) -- Phase 13.2 finding: this used to be a bare
      READ-then-compare, never actually reserving anything from the
      parent, so a delegable parent with `uses_remaining=5` could spawn a
      child ALSO carrying its own independent `uses_remaining=5` --
      authority multiplication (spec §17: "total available authority
      cannot exceed parent's valid remaining allowance"). Fixed: the
      parent's `uses_remaining` is now atomically DECREMENTED by
      `child_max_uses` via `orca.godmode.lease_store.reserve_uses()`
      (same `BEGIN IMMEDIATE` transaction discipline as `consume_use()`)
      before the child is ever created -- two concurrent delegation
      attempts against the same parent can never both succeed in
      reserving more than the parent actually has.
    - tenant is identical (delegation never crosses tenants -- structural
      copy of the parent's own `tenant_id`, never caller-supplied).

    The child is independently signed (its own valid HMAC over its own
    fields) and independently revocable -- it is a first-class
    `CapabilityLease`, not a reference to the parent.
    """
    parent = get_lease(parent_lease_id)
    if parent is None:
        raise LeaseDelegationError("parent lease not found")
    if not parent.delegable:
        raise LeaseDelegationError(f"lease {parent_lease_id} is not delegable (delegable=False is the default)")
    if parent.revocation_state.value == "REVOKED":
        raise LeaseDelegationError("parent lease is revoked")
    if lease_is_expired(parent):
        raise LeaseDelegationError("parent lease is expired")

    if not verify_lease_integrity(parent):
        raise LeaseDelegationError("parent lease failed integrity verification")

    parent_expiry = parse_iso(parent.expires_at)
    from datetime import timedelta
    child_expiry_dt = min(parse_iso(now_iso()) + timedelta(seconds=child_duration_s), parent_expiry)
    if child_expiry_dt > parent_expiry:
        raise LeaseDelegationError("child expiry cannot exceed parent expiry")

    parent_remaining = parent.uses_remaining
    if parent_remaining is not None and child_max_uses > parent_remaining:
        raise LeaseDelegationError(f"child max_uses ({child_max_uses}) exceeds parent's remaining uses ({parent_remaining})")

    # Phase 13.2 fix: ATOMICALLY reserve (decrement) child_max_uses from
    # the parent's own uses_remaining -- the check above is a fast,
    # pre-flight rejection for an obviously-too-large request, but the
    # real, race-safe enforcement is this call. If two concurrent
    # delegation attempts both pass the check above (stale read), only
    # one of them can actually win this atomic reservation.
    if parent_remaining is not None and not reserve_parent_uses(parent_lease_id, child_max_uses):
        raise LeaseDelegationError(
            f"could not atomically reserve {child_max_uses} use(s) from parent lease {parent_lease_id} "
            f"(revoked, expired, integrity failure, or insufficient uses remaining after re-validation)"
        )

    child = CapabilityLease(
        principal_id=child_principal_id, tenant_id=parent.tenant_id,
        capability_domain=parent.capability_domain, capability=parent.capability,
        resource_scope=parent.resource_scope, operation_scope=parent.operation_scope,
        expires_at=child_expiry_dt.strftime("%Y-%m-%dT%H:%M:%SZ"),
        issuer=LeaseIssuerClass.SYSTEM_POLICY, issuer_id=f"delegated-from:{parent_lease_id}",
        reason=reason, approval_id=parent.approval_id, max_uses=child_max_uses, uses_remaining=child_max_uses,
        delegable=False,  # spec §54: delegation is never transitive by default
    )
    if child.is_wildcard():
        raise LeaseDelegationError("delegated lease scope resolved to a wildcard -- rejected")

    apply_signature(child)
    save_lease(child)
    return child
