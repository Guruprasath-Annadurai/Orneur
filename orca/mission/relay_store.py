"""
Phase 15.11 -- ORNEUR Relay session core: durable device identity,
durable Relay session lifecycle, authenticated-principal-bound mission
access, and a governed, secret-safe RelaySnapshot that lets an
authorized user reconnect from a second device to the SAME durable
ORNEUR Code mission (spec sections 9-11, 13, 14, 18, 22-27).

Canonical distinction (spec section 9): ORNEUR Code engineers the
software; ORNEUR Relay securely reconnects to and continues/reviews
that SAME mission. This module is Relay's server-side core -- it does
not engineer anything, run tools, execute operations, or approve
anything (spec section 21: "no side effect on read").

Uses the EXISTING `devices` and `relay_sessions` tables from
`orca/mission/schema.py` (Phase 15.2) -- no migration was required or
added this phase (spec section 26: "prefer NO migration"; both tables
were already declared and simply unused until now).

Authenticated-principal boundary (spec section 2): every function that
touches a device, session, or mission takes an explicit
`authenticated_user_id` parameter. That value is a CONTRACT, not a
verification -- it must be supplied by the caller's own auth layer
(the already-verified identity of the current request), never taken
from a client-supplied `user_id`/`owner_user_id` field. This module
does not implement authentication itself (no HTTP routes are added in
this phase); it implements the authorization checks that make a
correctly-authenticated caller's access decisions honest:
cross-user access to another user's device, session, or mission is
always denied, fail-closed, regardless of what identifiers the caller
supplies.

IDs are always generated server-side (`register_device()`,
`create_session()`) -- a caller can never choose or reuse an existing
session/device ID, which is what makes session fixation structurally
unreachable through this module's public API.

Secret safety (spec section 19): every text field that ends up inside
a `RelaySnapshot` is passed through `orca.mission.production_proof
.redact_secrets()` -- the same regex-based scrubber already relied on
and tested by Production Proof, reused here as a narrow shared helper
rather than re-implemented, and without touching (or weakening) that
module or its own tests.
"""
from __future__ import annotations

import json
import uuid
from dataclasses import dataclass, fields, is_dataclass, replace
from datetime import datetime, timedelta, timezone
from enum import Enum

from orca.mission.mission_store import get_latest_checkpoint, get_mission
from orca.mission.production_proof import redact_secrets
from orca.mission.production_proof_store import is_proof_stale, latest_proof_for_mission


def _now_iso() -> str:
    return datetime.now(timezone.utc).isoformat()


def _parse_iso(value: str) -> datetime:
    dt = datetime.fromisoformat(value)
    if dt.tzinfo is None:
        dt = dt.replace(tzinfo=timezone.utc)
    return dt


def _default_clock() -> datetime:
    return datetime.now(timezone.utc)


# ── Errors ────────────────────────────────────────────────────────────

class RelayError(Exception):
    """Base class for Relay errors."""


class DeviceNotFoundError(RelayError):
    pass


class RelaySessionNotFoundError(RelayError):
    pass


class MissionNotFoundError(RelayError):
    pass


class RelayAccessDeniedError(RelayError):
    """Raised for any cross-user access attempt (IDOR) -- fail closed,
    never leaks whether the underlying resource exists to a caller who
    does not own it."""


class DeviceRevokedError(RelayError):
    """Raised when an operation requires an active (non-revoked) device."""


class RelaySessionInvalidError(RelayError):
    """Raised when an operation requires an ACTIVE Relay session but the
    session is EXPIRED or REVOKED. Carries the actual status so callers
    can distinguish the two without re-deriving it."""

    def __init__(self, message: str, *, status: "RelaySessionStatus"):
        super().__init__(message)
        self.status = status


# ── Core types ────────────────────────────────────────────────────────

class DeviceTrustLevel(Enum):
    TRUSTED = "TRUSTED"
    PUBLIC = "PUBLIC"


class RelayMode(Enum):
    TRUSTED_DEVICE = "TRUSTED_DEVICE"
    PUBLIC_DEVICE = "PUBLIC_DEVICE"
    MOBILE_REVIEW = "MOBILE_REVIEW"


class RelaySessionStatus(Enum):
    ACTIVE = "ACTIVE"
    EXPIRED = "EXPIRED"
    REVOKED = "REVOKED"


@dataclass(frozen=True)
class RelayDevice:
    id: str
    user_id: str
    name: str | None
    trust_level: DeviceTrustLevel
    first_seen_at: str
    last_seen_at: str
    revoked_at: str | None

    @property
    def is_revoked(self) -> bool:
        return self.revoked_at is not None

    @classmethod
    def from_row(cls, row: dict) -> "RelayDevice":
        return cls(
            id=row["id"], user_id=row["user_id"], name=row["name"],
            trust_level=DeviceTrustLevel(row["trust_level"]),
            first_seen_at=row["first_seen_at"], last_seen_at=row["last_seen_at"],
            revoked_at=row["revoked_at"],
        )


@dataclass(frozen=True)
class RelaySession:
    id: str
    mission_id: str | None
    device_id: str
    user_id: str
    mode: RelayMode
    created_at: str
    expires_at: str
    last_seen_at: str
    revoked_at: str | None
    revoked_reason: str | None

    @classmethod
    def from_row(cls, row: dict) -> "RelaySession":
        return cls(
            id=row["id"], mission_id=row["mission_id"], device_id=row["device_id"],
            user_id=row["user_id"], mode=RelayMode(row["mode"]), created_at=row["created_at"],
            expires_at=row["expires_at"], last_seen_at=row["last_seen_at"],
            revoked_at=row["revoked_at"], revoked_reason=row["revoked_reason"],
        )


def session_status(session: RelaySession, *, now: datetime | None = None) -> RelaySessionStatus:
    """Derives Relay session status from durable state -- REVOKED and
    EXPIRED are never persisted flags, they are always computed (spec
    section 4: 'status may be derived rather than persisted'). A
    session revoked at ANY point is always REVOKED, even past its
    expiry. `now == expires_at` is EXPIRED, not ACTIVE (spec section 5:
    the boundary itself is not valid)."""
    if session.revoked_at is not None:
        return RelaySessionStatus.REVOKED
    now = now or _default_clock()
    if now >= _parse_iso(session.expires_at):
        return RelaySessionStatus.EXPIRED
    return RelaySessionStatus.ACTIVE


# ── Governed snapshot sub-summaries (spec section 22) ────────────────
# Every text-bearing field here is redacted at construction time by
# `_sanitize()` before the snapshot is ever returned -- see
# `build_relay_snapshot()`. Missing durable data is represented as
# `None` / an empty tuple, never fabricated (spec section 32.15).

@dataclass(frozen=True)
class MissionSummary:
    mission_id: str
    repository: str
    branch: str | None
    base_revision: str | None
    current_revision: str | None
    mission_state: str


@dataclass(frozen=True)
class StepSummary:
    current_step_id: str | None
    completed_step_ids: tuple[str, ...]
    remaining_step_ids: tuple[str, ...]
    failed_step_ids: tuple[str, ...]
    integrity_warning: str | None = None


@dataclass(frozen=True)
class RequirementSummary:
    requirement_id: str
    status: str
    statement: str | None
    evidence_ref: str | None


@dataclass(frozen=True)
class VerificationSummary:
    requirement_id: str
    outcome: str | None
    revision: str | None
    evidence_refs: tuple[str, ...]
    stale: bool


@dataclass(frozen=True)
class ProductionProofSummary:
    proof_id: str | None
    revision: str | None
    release_state: str | None
    proof_hash: str | None
    generated_at: str | None
    available: bool
    stale: bool


@dataclass(frozen=True)
class ApprovalSummary:
    id: str
    operation_id: str | None
    decision: str
    requested_at: str
    decided_by: str | None
    reason: str | None


@dataclass(frozen=True)
class OperationSummary:
    id: str
    kind: str
    status: str
    requested_by: str | None
    requested_at: str
    result_ref: str | None


@dataclass(frozen=True)
class CheckpointSummary:
    checkpoint_id: str | None
    created_at: str | None
    mission_state: str | None
    current_step_id: str | None
    current_revision: str | None
    diff_ref: str | None
    active_blocker: str | None
    evidence_refs: tuple[str, ...]


@dataclass(frozen=True)
class ModelActivitySummary:
    id: str
    provider: str
    model: str
    purpose: str | None
    started_at: str
    completed_at: str | None
    outcome_summary: str | None


@dataclass(frozen=True)
class ToolActivitySummary:
    id: str
    tool_name: str
    status: str | None
    started_at: str
    completed_at: str | None
    outcome_summary: str | None


@dataclass(frozen=True)
class AuthorityContextSummary:
    id: str
    operation_id: str | None
    decision: str
    decided_at: str
    detail: str | None


@dataclass(frozen=True)
class RelaySnapshot:
    relay_session_id: str
    mission_id: str
    device_id: str
    user_id: str
    repository: str
    branch: str | None
    current_revision: str | None
    mission_state: str
    snapshot_generated_at: str
    mission_updated_at: str | None

    mission: MissionSummary
    step: StepSummary
    requirements: tuple[RequirementSummary, ...]
    verifications: tuple[VerificationSummary, ...]
    production_proof: ProductionProofSummary
    pending_approvals: tuple[ApprovalSummary, ...]
    pending_operations: tuple[OperationSummary, ...]
    checkpoint: CheckpointSummary
    model_activity: tuple[ModelActivitySummary, ...]
    tool_activity: tuple[ToolActivitySummary, ...]
    authority_context: tuple[AuthorityContextSummary, ...]


def _sanitize(value):
    """Recursively redacts every string reachable from `value` via
    `orca.mission.production_proof.redact_secrets()`. Mirrors that
    module's own `_sanitize_value()` walk (Enum members, dataclasses,
    tuples, dicts, strings) without importing its private helper --
    this is the module's PUBLIC `redact_secrets()` reused as a narrow
    shared building block, per spec section 19."""
    if isinstance(value, Enum):
        return value
    if isinstance(value, str):
        return redact_secrets(value) or ""
    if isinstance(value, tuple):
        return tuple(_sanitize(v) for v in value)
    if isinstance(value, dict):
        return {k: _sanitize(v) for k, v in value.items()}
    if is_dataclass(value) and not isinstance(value, type):
        changes = {f.name: _sanitize(getattr(value, f.name)) for f in fields(value)}
        return replace(value, **changes)
    return value


# ── Device core (spec section 3) ─────────────────────────────────────

def register_device(
    conn, *, user_id: str, trust_level: DeviceTrustLevel, name: str | None = None,
    now_fn=_default_clock,
) -> RelayDevice:
    """Creates a durable device row. The ID is always generated HERE,
    server-side -- callers never supply or choose one (spec section 3:
    'IDs generated server-side')."""
    device_id = f"dev_{uuid.uuid4().hex[:20]}"
    now = now_fn().isoformat()
    with conn.cursor() as cur:
        cur.execute(
            """
            INSERT INTO devices (id, user_id, name, trust_level, first_seen_at, last_seen_at, revoked_at)
            VALUES (%s, %s, %s, %s, %s, %s, NULL)
            """,
            (device_id, user_id, name, trust_level.value, now, now),
        )
    conn.commit()
    return get_device(conn, device_id)  # type: ignore[return-value]


def get_device(conn, device_id: str) -> RelayDevice | None:
    with conn.cursor() as cur:
        cur.execute("SELECT * FROM devices WHERE id = %s", (device_id,))
        row = cur.fetchone()
    conn.commit()
    return RelayDevice.from_row(dict(row)) if row else None


def get_device_for_user(conn, device_id: str, *, authenticated_user_id: str) -> RelayDevice:
    """Ownership-checked device lookup. Raises DeviceNotFoundError if
    the device genuinely does not exist, or RelayAccessDeniedError if
    it exists but belongs to a different user (spec section 25 IDOR
    boundary) -- a caller can distinguish the two only because this is
    an internal server-side check, never exposed to an unauthenticated
    client as a existence oracle."""
    device = get_device(conn, device_id)
    if device is None:
        raise DeviceNotFoundError(f"No such device: {device_id}")
    if device.user_id != authenticated_user_id:
        raise RelayAccessDeniedError(f"device {device_id} does not belong to the authenticated user")
    return device


def touch_device(conn, device_id: str, *, authenticated_user_id: str, now_fn=_default_clock) -> RelayDevice:
    device = get_device_for_user(conn, device_id, authenticated_user_id=authenticated_user_id)
    if device.is_revoked:
        raise DeviceRevokedError(f"device {device_id} is revoked and cannot be touched active again")
    now = now_fn().isoformat()
    with conn.cursor() as cur:
        cur.execute(
            "UPDATE devices SET last_seen_at = %s WHERE id = %s AND last_seen_at < %s",
            (now, device_id, now),
        )
    conn.commit()
    return get_device(conn, device_id)  # type: ignore[return-value]


def revoke_device(conn, device_id: str, *, authenticated_user_id: str, now_fn=_default_clock) -> RelayDevice:
    """Revocation is irreversible for this device record (spec section
    3) -- if already revoked, this is a no-op that returns the
    existing (still-revoked) row rather than overwriting `revoked_at`
    or raising."""
    device = get_device_for_user(conn, device_id, authenticated_user_id=authenticated_user_id)
    if device.is_revoked:
        return device
    now = now_fn().isoformat()
    with conn.cursor() as cur:
        cur.execute("UPDATE devices SET revoked_at = %s WHERE id = %s AND revoked_at IS NULL", (now, device_id))
    conn.commit()
    return get_device(conn, device_id)  # type: ignore[return-value]


def is_device_active(device: RelayDevice) -> bool:
    return not device.is_revoked


# ── Relay session core (spec section 4) ──────────────────────────────

def create_session(
    conn, *, device_id: str, mission_id: str, authenticated_user_id: str, mode: RelayMode,
    ttl_seconds: int, now_fn=_default_clock,
) -> RelaySession:
    """Creates a durable Relay session. The session ID is always
    generated HERE (anti-fixation, spec section 4). Requires:
      - the device to exist, belong to `authenticated_user_id`, and not
        be revoked (DeviceRevokedError otherwise);
      - the mission to exist and be OWNED by `authenticated_user_id`
        (the Phase 15.11 V1 access policy -- spec section 2: cross-user
        mission access is denied, no team-sharing policy is invented
        here).
    `ttl_seconds` is supplied by the CALLER's own trusted server
    policy (spec section 4) -- this function has no built-in default,
    so no hidden expiry policy is invented inside the store layer."""
    device = get_device_for_user(conn, device_id, authenticated_user_id=authenticated_user_id)
    if device.is_revoked:
        raise DeviceRevokedError(f"device {device_id} is revoked and cannot create a new Relay session")

    mission = get_mission(conn, mission_id)
    if mission is None:
        raise MissionNotFoundError(f"No such mission: {mission_id}")
    if mission["owner_user_id"] != authenticated_user_id:
        raise RelayAccessDeniedError(f"mission {mission_id} is not owned by the authenticated user")

    session_id = f"rlysess_{uuid.uuid4().hex[:20]}"
    now_dt = now_fn()
    now = now_dt.isoformat()
    expires_at = (now_dt + timedelta(seconds=ttl_seconds)).isoformat()
    with conn.cursor() as cur:
        cur.execute(
            """
            INSERT INTO relay_sessions
                (id, mission_id, device_id, user_id, mode, created_at, expires_at, last_seen_at, revoked_at, revoked_reason)
            VALUES (%s, %s, %s, %s, %s, %s, %s, %s, NULL, NULL)
            """,
            (session_id, mission_id, device_id, authenticated_user_id, mode.value, now, expires_at, now),
        )
    conn.commit()
    return get_session(conn, session_id)  # type: ignore[return-value]


def get_session(conn, session_id: str) -> RelaySession | None:
    with conn.cursor() as cur:
        cur.execute("SELECT * FROM relay_sessions WHERE id = %s", (session_id,))
        row = cur.fetchone()
    conn.commit()
    return RelaySession.from_row(dict(row)) if row else None


def get_session_for_user(conn, session_id: str, *, authenticated_user_id: str) -> RelaySession:
    session = get_session(conn, session_id)
    if session is None:
        raise RelaySessionNotFoundError(f"No such Relay session: {session_id}")
    if session.user_id != authenticated_user_id:
        raise RelayAccessDeniedError(f"Relay session {session_id} does not belong to the authenticated user")
    return session


def touch_session(conn, session_id: str, *, authenticated_user_id: str, now_fn=_default_clock) -> RelaySession:
    """Reconnect/heartbeat path. Rejects (RelaySessionInvalidError) a
    session that is EXPIRED or REVOKED -- neither can be revived by
    touching (spec section 5). `last_seen_at` is monotonic: a clock
    regression never moves it backwards (the SQL `WHERE last_seen_at <
    %s` guard)."""
    session = get_session_for_user(conn, session_id, authenticated_user_id=authenticated_user_id)
    now_dt = now_fn()
    status = session_status(session, now=now_dt)
    if status is not RelaySessionStatus.ACTIVE:
        raise RelaySessionInvalidError(f"Relay session {session_id} is {status.value}, cannot be touched active", status=status)
    now = now_dt.isoformat()
    with conn.cursor() as cur:
        cur.execute(
            "UPDATE relay_sessions SET last_seen_at = %s WHERE id = %s AND last_seen_at < %s",
            (now, session_id, now),
        )
    conn.commit()
    return get_session(conn, session_id)  # type: ignore[return-value]


def revoke_session(
    conn, session_id: str, *, authenticated_user_id: str, reason: str | None = None, now_fn=_default_clock,
) -> RelaySession:
    session = get_session_for_user(conn, session_id, authenticated_user_id=authenticated_user_id)
    if session.revoked_at is not None:
        return session
    now = now_fn().isoformat()
    with conn.cursor() as cur:
        cur.execute(
            "UPDATE relay_sessions SET revoked_at = %s, revoked_reason = %s WHERE id = %s AND revoked_at IS NULL",
            (now, reason, session_id),
        )
    conn.commit()
    return get_session(conn, session_id)  # type: ignore[return-value]


def revoke_other_session(
    conn, *, current_session_id: str, target_session_id: str, authenticated_user_id: str,
    reason: str | None = None, now_fn=_default_clock,
) -> RelaySession:
    """Revokes `target_session_id`, which must belong to the SAME
    authenticated user as `current_session_id` (both ownership-checked
    independently -- spec section 6 cross-user revoke must DENY).
    Rejects revoking the current session through this entrypoint (use
    `revoke_session()` for that) to keep the 'other' contract honest."""
    if target_session_id == current_session_id:
        raise RelayError("revoke_other_session cannot target the caller's own current session -- use revoke_session()")
    get_session_for_user(conn, current_session_id, authenticated_user_id=authenticated_user_id)
    return revoke_session(
        conn, target_session_id, authenticated_user_id=authenticated_user_id,
        reason=reason or "revoked by another session of the same user", now_fn=now_fn,
    )


def revoke_all_other_sessions(
    conn, *, current_session_id: str, authenticated_user_id: str, now_fn=_default_clock,
) -> tuple[RelaySession, ...]:
    """Atomically revokes every OTHER active Relay session belonging
    to `authenticated_user_id`, preserving `current_session_id` (spec
    section 6). Single UPDATE statement -- either all matching rows
    are revoked together or none are, and the current session's row is
    excluded by the WHERE clause itself, not by a separate check."""
    current = get_session_for_user(conn, current_session_id, authenticated_user_id=authenticated_user_id)
    now = now_fn().isoformat()
    with conn.cursor() as cur:
        cur.execute(
            """
            UPDATE relay_sessions
            SET revoked_at = %s, revoked_reason = %s
            WHERE user_id = %s AND id != %s AND revoked_at IS NULL
            RETURNING id
            """,
            (now, "revoked via revoke_all_other_sessions", authenticated_user_id, current_session_id),
        )
        revoked_ids = [row["id"] for row in cur.fetchall()]
    conn.commit()
    assert session_status(get_session(conn, current_session_id), now=now_fn()) is not RelaySessionStatus.REVOKED  # type: ignore[arg-type]
    return tuple(get_session(conn, sid) for sid in revoked_ids)  # type: ignore[misc]


def list_active_sessions(conn, *, authenticated_user_id: str, now_fn=_default_clock) -> tuple[RelaySession, ...]:
    with conn.cursor() as cur:
        cur.execute(
            "SELECT * FROM relay_sessions WHERE user_id = %s AND revoked_at IS NULL",
            (authenticated_user_id,),
        )
        rows = cur.fetchall()
    conn.commit()
    sessions = tuple(RelaySession.from_row(dict(r)) for r in rows)
    now = now_fn()
    return tuple(s for s in sessions if session_status(s, now=now) is RelaySessionStatus.ACTIVE)


# ── RelaySnapshot assembly (spec sections 7-18, 20-22) ───────────────
# Bounded row limits on activity/history feeds -- Relay shows recent
# context to continue/review a mission, not an unbounded raw dump
# (spec section 7: "expose the minimum information needed").
_ACTIVITY_LIMIT = 25


def build_relay_snapshot(conn, *, session_id: str, authenticated_user_id: str, now_fn=_default_clock) -> RelaySnapshot:
    """Assembles a governed, secret-safe RelaySnapshot for an ACTIVE
    Relay session. Read-only: no mission/step/operation/checkpoint/
    proof state is ever mutated by this function, and it does not even
    touch the session's own `last_seen_at` (spec section 21) -- callers
    that want a reconnect heartbeat call `touch_session()` separately
    and explicitly.

    Every access boundary is re-checked here defensively, even though
    `create_session()` already enforced them at session-creation time
    -- a session's mission/device ownership cannot have silently
    changed later, but the check costs nothing and this function must
    never be the one place that trusts stale state."""
    session = get_session(conn, session_id)
    if session is None:
        raise RelaySessionNotFoundError(f"No such Relay session: {session_id}")
    if session.user_id != authenticated_user_id:
        raise RelayAccessDeniedError(f"Relay session {session_id} does not belong to the authenticated user")

    now_dt = now_fn()
    status = session_status(session, now=now_dt)
    if status is not RelaySessionStatus.ACTIVE:
        raise RelaySessionInvalidError(f"Relay session {session_id} is {status.value}, cannot produce a snapshot", status=status)
    if session.mission_id is None:
        raise RelayError(f"Relay session {session_id} is not bound to any mission")

    device = get_device(conn, session.device_id)
    if device is None or device.user_id != authenticated_user_id:
        raise RelayAccessDeniedError(f"device {session.device_id} bound to session {session_id} is not owned by the authenticated user")
    if device.is_revoked:
        raise DeviceRevokedError(f"device {session.device_id} is revoked; its sessions cannot produce a snapshot")

    mission = get_mission(conn, session.mission_id)
    if mission is None:
        raise MissionNotFoundError(f"No such mission: {session.mission_id}")
    if mission["owner_user_id"] != authenticated_user_id:
        raise RelayAccessDeniedError(f"mission {session.mission_id} is not owned by the authenticated user")

    mission_id = mission["id"]
    current_revision = mission["current_revision"]

    mission_summary = MissionSummary(
        mission_id=mission_id, repository=mission["repository"], branch=mission["branch"],
        base_revision=mission["base_revision"], current_revision=current_revision,
        mission_state=mission["state"],
    )

    step = _build_step_summary(conn, mission_id)
    requirements = _build_requirement_summaries(conn, mission_id)
    verifications = _build_verification_summaries(conn, mission_id, current_revision=current_revision)
    proof_summary = _build_production_proof_summary(conn, mission_id, current_revision=current_revision)
    approvals = _build_pending_approvals(conn, mission_id)
    operations = _build_pending_operations(conn, mission_id)
    checkpoint = _build_checkpoint_summary(conn, mission_id)
    model_activity = _build_model_activity(conn, mission_id)
    tool_activity = _build_tool_activity(conn, mission_id)
    authority_context = _build_authority_context(conn, mission_id)

    snapshot = RelaySnapshot(
        relay_session_id=session.id, mission_id=mission_id, device_id=device.id, user_id=authenticated_user_id,
        repository=mission["repository"], branch=mission["branch"], current_revision=current_revision,
        mission_state=mission["state"], snapshot_generated_at=now_dt.isoformat(),
        mission_updated_at=mission.get("updated_at"),
        mission=mission_summary, step=step, requirements=requirements, verifications=verifications,
        production_proof=proof_summary, pending_approvals=approvals, pending_operations=operations,
        checkpoint=checkpoint, model_activity=model_activity, tool_activity=tool_activity,
        authority_context=authority_context,
    )
    return _sanitize(snapshot)


def _build_step_summary(conn, mission_id: str) -> StepSummary:
    with conn.cursor() as cur:
        cur.execute(
            "SELECT id, status FROM mission_steps WHERE mission_id = %s ORDER BY step_index ASC",
            (mission_id,),
        )
        rows = [dict(r) for r in cur.fetchall()]
    conn.commit()

    running = [r["id"] for r in rows if r["status"] == "RUNNING"]
    completed = tuple(r["id"] for r in rows if r["status"] == "COMPLETED")
    remaining = tuple(r["id"] for r in rows if r["status"] in ("PENDING", "RUNNING"))
    failed = tuple(r["id"] for r in rows if r["status"] == "FAILED")

    integrity_warning = None
    current_step_id = None
    if len(running) == 1:
        current_step_id = running[0]
    elif len(running) > 1:
        integrity_warning = f"{len(running)} steps are simultaneously RUNNING -- durable step state is inconsistent"

    return StepSummary(
        current_step_id=current_step_id, completed_step_ids=completed, remaining_step_ids=remaining,
        failed_step_ids=failed, integrity_warning=integrity_warning,
    )


def _build_requirement_summaries(conn, mission_id: str) -> tuple[RequirementSummary, ...]:
    with conn.cursor() as cur:
        cur.execute(
            "SELECT id, status, statement, evidence_ref FROM requirements WHERE mission_id = %s ORDER BY id ASC",
            (mission_id,),
        )
        rows = [dict(r) for r in cur.fetchall()]
    conn.commit()
    return tuple(
        RequirementSummary(requirement_id=r["id"], status=r["status"], statement=r["statement"], evidence_ref=r["evidence_ref"])
        for r in rows
    )


def _build_verification_summaries(conn, mission_id: str, *, current_revision: str | None) -> tuple[VerificationSummary, ...]:
    with conn.cursor() as cur:
        cur.execute(
            """
            SELECT DISTINCT requirement_id FROM verification_records
            WHERE mission_id = %s AND requirement_id IS NOT NULL
            """,
            (mission_id,),
        )
        requirement_ids = [r["requirement_id"] for r in cur.fetchall()]

    summaries = []
    for req_id in requirement_ids:
        with conn.cursor() as cur:
            cur.execute(
                "SELECT outcome, revision, evidence_refs FROM verification_records "
                "WHERE mission_id = %s AND requirement_id = %s ORDER BY created_at DESC LIMIT 1",
                (mission_id, req_id),
            )
            row = cur.fetchone()
        if row is None:
            continue
        evidence_refs = tuple(json.loads(row["evidence_refs"])) if row["evidence_refs"] else ()
        stale = current_revision is not None and row["revision"] != current_revision
        summaries.append(VerificationSummary(
            requirement_id=req_id, outcome=row["outcome"], revision=row["revision"],
            evidence_refs=evidence_refs, stale=stale,
        ))
    conn.commit()
    return tuple(summaries)


def _build_production_proof_summary(conn, mission_id: str, *, current_revision: str | None) -> ProductionProofSummary:
    latest = latest_proof_for_mission(conn, mission_id)
    if latest is None:
        return ProductionProofSummary(
            proof_id=None, revision=None, release_state=None, proof_hash=None, generated_at=None,
            available=False, stale=False,
        )
    proof, proof_hash = latest
    stale = current_revision is not None and is_proof_stale(proof, current_revision=current_revision)
    return ProductionProofSummary(
        proof_id=proof.proof_id, revision=proof.revision, release_state=proof.release_state,
        proof_hash=proof_hash, generated_at=proof.generated_at, available=True, stale=stale,
    )


def _build_pending_approvals(conn, mission_id: str) -> tuple[ApprovalSummary, ...]:
    with conn.cursor() as cur:
        cur.execute(
            """
            SELECT id, operation_id, decision, requested_at, decided_by, reason
            FROM approvals WHERE mission_id = %s AND decision = 'PENDING'
            ORDER BY requested_at DESC LIMIT %s
            """,
            (mission_id, _ACTIVITY_LIMIT),
        )
        rows = [dict(r) for r in cur.fetchall()]
    conn.commit()
    return tuple(
        ApprovalSummary(
            id=r["id"], operation_id=r["operation_id"], decision=r["decision"], requested_at=r["requested_at"],
            decided_by=r["decided_by"], reason=r["reason"],
        )
        for r in rows
    )


def _build_pending_operations(conn, mission_id: str) -> tuple[OperationSummary, ...]:
    with conn.cursor() as cur:
        cur.execute(
            """
            SELECT id, kind, status, requested_by, requested_at, result_ref
            FROM operations WHERE mission_id = %s AND status NOT IN ('SUCCEEDED', 'CANCELLED')
            ORDER BY requested_at DESC LIMIT %s
            """,
            (mission_id, _ACTIVITY_LIMIT),
        )
        rows = [dict(r) for r in cur.fetchall()]
    conn.commit()
    return tuple(
        OperationSummary(
            id=r["id"], kind=r["kind"], status=r["status"], requested_by=r["requested_by"],
            requested_at=r["requested_at"], result_ref=r["result_ref"],
        )
        for r in rows
    )


def _build_checkpoint_summary(conn, mission_id: str) -> CheckpointSummary:
    checkpoint = get_latest_checkpoint(conn, mission_id)
    if checkpoint is None:
        return CheckpointSummary(
            checkpoint_id=None, created_at=None, mission_state=None, current_step_id=None,
            current_revision=None, diff_ref=None, active_blocker=None, evidence_refs=(),
        )
    return CheckpointSummary(
        checkpoint_id=checkpoint.id, created_at=checkpoint.created_at, mission_state=checkpoint.mission_state,
        current_step_id=checkpoint.current_step_id, current_revision=checkpoint.current_revision,
        diff_ref=checkpoint.diff_ref, active_blocker=checkpoint.active_blocker,
        evidence_refs=checkpoint.evidence_refs[:_ACTIVITY_LIMIT],
    )


def _build_model_activity(conn, mission_id: str) -> tuple[ModelActivitySummary, ...]:
    with conn.cursor() as cur:
        cur.execute(
            """
            SELECT id, provider, model, purpose, started_at, completed_at, outcome_summary
            FROM model_invocations WHERE mission_id = %s ORDER BY started_at DESC LIMIT %s
            """,
            (mission_id, _ACTIVITY_LIMIT),
        )
        rows = [dict(r) for r in cur.fetchall()]
    conn.commit()
    return tuple(
        ModelActivitySummary(
            id=r["id"], provider=r["provider"], model=r["model"], purpose=r["purpose"],
            started_at=r["started_at"], completed_at=r["completed_at"], outcome_summary=r["outcome_summary"],
        )
        for r in rows
    )


def _build_tool_activity(conn, mission_id: str) -> tuple[ToolActivitySummary, ...]:
    with conn.cursor() as cur:
        cur.execute(
            """
            SELECT id, tool_name, status, started_at, completed_at, outcome_summary
            FROM tool_invocations WHERE mission_id = %s ORDER BY started_at DESC LIMIT %s
            """,
            (mission_id, _ACTIVITY_LIMIT),
        )
        rows = [dict(r) for r in cur.fetchall()]
    conn.commit()
    return tuple(
        ToolActivitySummary(
            id=r["id"], tool_name=r["tool_name"], status=r["status"], started_at=r["started_at"],
            completed_at=r["completed_at"], outcome_summary=r["outcome_summary"],
        )
        for r in rows
    )


def _build_authority_context(conn, mission_id: str) -> tuple[AuthorityContextSummary, ...]:
    """Never exposes `policy_ref` (the operation's lease id, spec
    section 18: 'never expose capability secrets or lease material')."""
    with conn.cursor() as cur:
        cur.execute(
            """
            SELECT id, operation_id, decision, decided_at, detail
            FROM authority_decisions WHERE mission_id = %s ORDER BY decided_at DESC LIMIT %s
            """,
            (mission_id, _ACTIVITY_LIMIT),
        )
        rows = [dict(r) for r in cur.fetchall()]
    conn.commit()
    return tuple(
        AuthorityContextSummary(
            id=r["id"], operation_id=r["operation_id"], decision=r["decision"], decided_at=r["decided_at"],
            detail=r["detail"],
        )
        for r in rows
    )
