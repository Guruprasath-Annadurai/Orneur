"""
GodmodeSession lifecycle (Phase 10 spec §5, §13-14, §39). A session is a
bookkeeping wrapper around one or more `CapabilityLease`s issued for one
elevation episode -- it holds NO authority of its own (spec §4: "level
alone does NOT grant capabilities"). Every action still resolves its OWN
named lease via `orca.godmode.resolution.resolve_lease()`; a session
being ACTIVE never substitutes for that per-action check.
"""
from __future__ import annotations

from orca.godmode.contracts import (
    AuthorityLevel,
    GodmodeSession,
    GodmodeSessionState,
    now_iso,
    parse_iso,
)
from orca.godmode.kill_switch import is_active as kill_switch_active
from orca.godmode.lease_store import get as get_lease
from orca.godmode.lease_store import is_expired as lease_is_expired

_MAX_SESSION_DURATION_S = 900.0  # spec §39: conservative default


def request_session(*, principal_id: str, tenant_id: str, requested_level: AuthorityLevel, reason: str, trace_id: str | None = None) -> GodmodeSession:
    return GodmodeSession(
        principal_id=principal_id, tenant_id=tenant_id, requested_level=requested_level,
        effective_level=AuthorityLevel.NORMAL, reason=reason, state=GodmodeSessionState.REQUESTED,
        trace_id=trace_id,
    )


def activate_session(session: GodmodeSession, *, lease_ids: list[str], duration_s: float) -> GodmodeSession:
    """
    Only ever called by trusted platform code AFTER real leases already
    exist (issued via `orca.godmode.issuance.issue_lease()`) -- activation
    never creates authority, it only records which already-issued leases
    this session is bundling for audit/UX purposes.
    """
    if kill_switch_active():
        session.state = GodmodeSessionState.DENIED
        session.reason = f"{session.reason} [denied: kill switch active]"
        return session
    from datetime import timedelta
    duration_s = min(duration_s, _MAX_SESSION_DURATION_S)
    session.lease_ids = list(lease_ids)
    session.effective_level = session.requested_level
    session.expires_at = (parse_iso(now_iso()) + timedelta(seconds=duration_s)).strftime("%Y-%m-%dT%H:%M:%SZ")
    session.state = GodmodeSessionState.ACTIVE
    return session


def refresh_session_state(session: GodmodeSession) -> GodmodeSession:
    """Re-derives EXPIRED from the trusted clock, and REVOKED from
    whether every one of the session's leases is now revoked -- never
    trusts a stale in-memory `state` field once time has passed or a
    lease was revoked out from under it (spec §41: revocation propagates,
    no stale cache may permit continued treatment as active)."""
    if session.state != GodmodeSessionState.ACTIVE:
        return session
    if session.expires_at and parse_iso(now_iso()) >= parse_iso(session.expires_at):
        session.state = GodmodeSessionState.EXPIRED
        return session
    if session.lease_ids:
        leases = [get_lease(lid) for lid in session.lease_ids]
        if leases and all(l is None or l.revocation_state.value == "REVOKED" for l in leases):
            session.state = GodmodeSessionState.REVOKED
    return session


def terminate_session(session: GodmodeSession) -> GodmodeSession:
    """Explicit termination (e.g. run cancelled) -- does not itself revoke
    the underlying leases (a caller wanting that calls
    `orca.godmode.lease_store.revoke()` per lease explicitly); this only
    marks the session bookkeeping record closed."""
    session.state = GodmodeSessionState.TERMINATED
    return session
