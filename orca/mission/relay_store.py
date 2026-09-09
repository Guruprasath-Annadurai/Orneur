"""
Phase 15.11 / 15.11.1 -- ORNEUR Relay session core: durable device
identity, durable Relay session lifecycle, authenticated-principal-
bound mission access, and a governed, secret-safe RelaySnapshot that
lets an authorized user reconnect from a second device to the SAME
durable ORNEUR Code mission (spec sections 9-11, 13, 14, 18, 22-27).

Canonical distinction (spec section 9): ORNEUR Code engineers the
software; ORNEUR Relay securely reconnects to and continues/reviews
that SAME mission. This module is Relay's server-side core -- it does
not engineer anything, run tools, execute operations, or approve
anything (spec section 21: "no side effect on read").

Uses the EXISTING `devices` and `relay_sessions` tables from
`orca/mission/schema.py` (Phase 15.2) -- no migration was required or
added this phase (spec section 26: "prefer NO migration"; both tables
were already declared and simply unused until now).

Authenticated-principal boundary (spec section 2, hardened 15.11.1
item 5): every function that creates or touches a device, session, or
mission takes an explicit `authenticated_user_id` parameter, and that
value is ALWAYS what durably becomes `devices.user_id` /
`relay_sessions.user_id` -- there is no public parameter through which
a caller can name a *different* user as the durable owner of a device
or session it is creating. That value is still a CONTRACT, not a
verification: it must be supplied by the caller's own auth layer (the
already-verified identity of the current request), never taken from a
client-supplied `user_id`/`owner_user_id` field in a request body.
This module does not implement authentication itself (no HTTP routes
are added in this phase); it implements the authorization checks that
make a correctly-authenticated caller's access decisions honest:
cross-user access to another user's device, session, or mission is
always denied, fail-closed, regardless of what identifiers the caller
supplies.

IDs are always generated server-side (`register_device()`,
`create_session()`) -- a caller can never choose or reuse an existing
session/device ID, which is what makes session fixation structurally
unreachable through this module's public API.

Dead-session guard (15.11.1 item 6): any operation that conceptually
acts "as" a current Relay session (revoking ANOTHER session) requires
that current session to be genuinely ACTIVE, on a non-revoked device
-- `_require_active_session_context()` is the one shared check. A
revoked or expired session, or one whose device has since been
revoked, is not an authority context and cannot control other
sessions.

Snapshot consistency (15.11.1 item 10): `build_relay_snapshot()` reads
every governed-state domain inside ONE PostgreSQL REPEATABLE READ,
READ ONLY transaction, committed (or rolled back) exactly once at the
end -- never a series of independently-committed reads that could
straddle different database versions. Its internal `_build_*` helpers
take a live cursor belonging to that one transaction, never opening or
committing their own.

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

from orca.mission.mission_store import Checkpoint
from orca.mission.production_proof import redact_secrets
from orca.mission.production_proof_store import _row_to_proof


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
    workspace_id: str | None
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
    """The latest known `verification_records` row for ONE
    (requirement_id, category) pair -- NOT the requirement's overall
    aggregated verified state (15.11.1 item 3). Relay does not durably
    have the `RequiredVerificationScope` that Phase 15.8's
    `evaluate_scoped_category()`/`aggregate_outcomes()` use to decide
    which records actually count toward a requirement and how they
    combine -- reconstructing that here would duplicate (and risk
    drifting from) that authoritative aggregation rule. This is
    intentionally a narrower, honestly-labeled per-category latest-
    record view: a caller who needs the real aggregated verdict must
    consult Phase 15.8's own aggregation, not this summary."""
    requirement_id: str
    category: str
    outcome: str
    revision: str
    verifier_id: str
    evidence_refs: tuple[str, ...]
    stale: bool


@dataclass(frozen=True)
class TestProgressSummary:
    """Mission-level (not per-requirement) test progress for the
    mission's CURRENT revision only, one entry per test category that
    has at least one real `verification_records` row at that revision
    (15.11.1 item 3) -- UNIT_TEST / INTEGRATION_TEST / E2E_TEST. A
    category with zero records at the current revision is simply
    absent from the tuple (never a fabricated UNVERIFIED placeholder
    with invented counts); a historical record from an OLDER revision
    never appears here (it remains visible only through
    `VerificationSummary.stale`)."""
    category: str
    verification_id: str
    outcome: str
    revision: str
    verifier_id: str
    evidence_refs: tuple[str, ...]

    __test__ = False  # not a pytest test class -- silences collection warning


_TEST_CATEGORIES = ("UNIT_TEST", "INTEGRATION_TEST", "E2E_TEST")


@dataclass(frozen=True)
class ProductionProofSummary:
    """`stale` is a TRUTHFUL tri-state, never a false positive
    'current' claim (15.11.1 item 9):
      - `True`  -- the proof's revision differs from the mission's
        current revision: definitely STALE.
      - `None`  -- revisions match, but Relay cannot reconstruct the
        full stale-proof decision context (required requirement ids,
        `RequiredVerificationScope`s, semantics fingerprints) that
        `orca.mission.production_proof.is_proof_stale()` needs for a
        complete answer: freshness is UNKNOWN, not asserted CURRENT.
      - `False` -- reserved for a future caller that DOES supply the
        full decision context; this module never produces `False`
        today, because it never has that context durably available."""
    proof_id: str | None
    revision: str | None
    release_state: str | None
    proof_hash: str | None
    generated_at: str | None
    available: bool
    stale: bool | None


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
    workspace_id: str | None
    device_id: str
    user_id: str
    repository: str
    branch: str | None
    current_revision: str | None
    mission_state: str
    snapshot_generated_at: str
    mission_updated_at: str | None
    consistency_basis: str

    mission: MissionSummary
    step: StepSummary
    requirements: tuple[RequirementSummary, ...]
    verifications: tuple[VerificationSummary, ...]
    test_progress: tuple[TestProgressSummary, ...]
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
    conn, *, authenticated_user_id: str, trust_level: DeviceTrustLevel, name: str | None = None,
    now_fn=_default_clock,
) -> RelayDevice:
    """Creates a durable device row OWNED BY `authenticated_user_id`
    (15.11.1 item 5) -- there is no separate `user_id` parameter a
    caller could use to durably register a device for a DIFFERENT
    user. The ID is always generated HERE, server-side (spec section
    3: 'IDs generated server-side') -- callers never supply or choose
    one."""
    device_id = f"dev_{uuid.uuid4().hex[:20]}"
    now = now_fn().isoformat()
    with conn.cursor() as cur:
        cur.execute(
            """
            INSERT INTO devices (id, user_id, name, trust_level, first_seen_at, last_seen_at, revoked_at)
            VALUES (%s, %s, %s, %s, %s, %s, NULL)
            """,
            (device_id, authenticated_user_id, name, trust_level.value, now, now),
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
    client as an existence oracle."""
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

    with conn.cursor() as cur:
        cur.execute("SELECT owner_user_id FROM missions WHERE id = %s", (mission_id,))
        row = cur.fetchone()
    conn.commit()
    if row is None:
        raise MissionNotFoundError(f"No such mission: {mission_id}")
    if row["owner_user_id"] != authenticated_user_id:
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


def _require_active_session_context(
    conn, current_session_id: str, *, authenticated_user_id: str, now_fn=_default_clock,
) -> RelaySession:
    """The shared dead-session guard (15.11.1 item 6): 'a revoked
    session is not an authority context.' Verifies, in order: the
    session exists and belongs to `authenticated_user_id`; its
    DERIVED status is ACTIVE (not EXPIRED, not REVOKED); its bound
    device exists, belongs to the same user, and is not revoked. Any
    action that conceptually originates FROM a current Relay session
    (e.g. revoking another session) must go through this guard before
    touching anything else."""
    session = get_session_for_user(conn, current_session_id, authenticated_user_id=authenticated_user_id)
    status = session_status(session, now=now_fn())
    if status is not RelaySessionStatus.ACTIVE:
        raise RelaySessionInvalidError(
            f"Relay session {current_session_id} is {status.value}, and cannot act as an authority "
            f"context for another session",
            status=status,
        )
    device = get_device(conn, session.device_id)
    if device is None or device.user_id != authenticated_user_id:
        raise RelayAccessDeniedError(f"device {session.device_id} bound to session {current_session_id} is not owned by the authenticated user")
    if device.is_revoked:
        raise DeviceRevokedError(f"device {session.device_id} bound to session {current_session_id} is revoked; it cannot act as an authority context")
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
    authenticated user as `current_session_id`. `current_session_id`
    itself must be a genuinely ACTIVE authority context, on a non-
    revoked device (`_require_active_session_context()`, 15.11.1 item
    6) -- a dead current session cannot revoke anything. Rejects
    revoking the current session through this entrypoint (use
    `revoke_session()` for that) to keep the 'other' contract honest."""
    if target_session_id == current_session_id:
        raise RelayError("revoke_other_session cannot target the caller's own current session -- use revoke_session()")
    _require_active_session_context(conn, current_session_id, authenticated_user_id=authenticated_user_id, now_fn=now_fn)
    return revoke_session(
        conn, target_session_id, authenticated_user_id=authenticated_user_id,
        reason=reason or "revoked by another session of the same user", now_fn=now_fn,
    )


def revoke_all_other_sessions(
    conn, *, current_session_id: str, authenticated_user_id: str, now_fn=_default_clock,
) -> tuple[RelaySession, ...]:
    """Atomically revokes every OTHER active Relay session belonging
    to `authenticated_user_id`, preserving `current_session_id` (spec
    section 6). `current_session_id` must itself be a genuinely ACTIVE
    authority context (`_require_active_session_context()`, 15.11.1
    item 6). Single UPDATE statement -- either all matching rows are
    revoked together or none are, and the current session's row is
    excluded by the WHERE clause itself, not by a separate check."""
    _require_active_session_context(conn, current_session_id, authenticated_user_id=authenticated_user_id, now_fn=now_fn)
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
    assert session_status(get_session(conn, current_session_id), now=now_fn()) is RelaySessionStatus.ACTIVE  # type: ignore[arg-type]
    return tuple(get_session(conn, sid) for sid in revoked_ids)  # type: ignore[misc]


def list_active_sessions(conn, *, authenticated_user_id: str, now_fn=_default_clock) -> tuple[RelaySession, ...]:
    """A session on a subsequently-revoked device is not operationally
    ACTIVE (15.11.1 item 7) -- the JOIN below excludes it directly at
    the SQL level, rather than as an N+1 per-session device lookup."""
    with conn.cursor() as cur:
        cur.execute(
            """
            SELECT rs.* FROM relay_sessions rs
            JOIN devices d ON d.id = rs.device_id
            WHERE rs.user_id = %s AND rs.revoked_at IS NULL AND d.revoked_at IS NULL
            """,
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

# Only genuinely non-terminal operation lifecycle states are "pending"
# (15.11.1 item 8) -- FAILED, SUCCEEDED, and CANCELLED are all
# terminal (see orca.mission.operation_store._ALLOWED_TRANSITIONS).
_PENDING_OPERATION_STATUSES = ("REQUESTED", "AUTHORIZED", "STARTED")


def build_relay_snapshot(conn, *, session_id: str, authenticated_user_id: str, now_fn=_default_clock) -> RelaySnapshot:
    """Assembles a governed, secret-safe RelaySnapshot for an ACTIVE
    Relay session. Read-only: no mission/step/operation/checkpoint/
    proof state is ever mutated by this function, and it does not even
    touch the session's own `last_seen_at` (spec section 21) -- callers
    that want a reconnect heartbeat call `touch_session()` separately
    and explicitly.

    Consistency (15.11.1 item 10): every read happens inside ONE
    PostgreSQL `REPEATABLE READ, READ ONLY` transaction, so the whole
    snapshot is taken from a single, internally-consistent database
    version -- never a mix of reads straddling an intervening write.
    That transaction is committed (harmlessly, since it is read-only)
    exactly once at the end, or rolled back exactly once if any check
    fails partway through. `consistency_basis` on the returned
    snapshot names this guarantee explicitly, rather than leaving it
    implicit.

    Every access boundary is re-checked here defensively, even though
    `create_session()` already enforced them at session-creation time
    -- a session's mission/device ownership cannot have silently
    changed later, but the check costs nothing and this function must
    never be the one place that trusts stale state."""
    now_dt = now_fn()
    try:
        with conn.cursor() as cur:
            cur.execute("SET TRANSACTION ISOLATION LEVEL REPEATABLE READ, READ ONLY")

            cur.execute("SELECT * FROM relay_sessions WHERE id = %s", (session_id,))
            session_row = cur.fetchone()
            if session_row is None:
                raise RelaySessionNotFoundError(f"No such Relay session: {session_id}")
            session = RelaySession.from_row(dict(session_row))
            if session.user_id != authenticated_user_id:
                raise RelayAccessDeniedError(f"Relay session {session_id} does not belong to the authenticated user")

            status = session_status(session, now=now_dt)
            if status is not RelaySessionStatus.ACTIVE:
                raise RelaySessionInvalidError(f"Relay session {session_id} is {status.value}, cannot produce a snapshot", status=status)
            if session.mission_id is None:
                raise RelayError(f"Relay session {session_id} is not bound to any mission")

            cur.execute("SELECT * FROM devices WHERE id = %s", (session.device_id,))
            device_row = cur.fetchone()
            device = RelayDevice.from_row(dict(device_row)) if device_row else None
            if device is None or device.user_id != authenticated_user_id:
                raise RelayAccessDeniedError(f"device {session.device_id} bound to session {session_id} is not owned by the authenticated user")
            if device.is_revoked:
                raise DeviceRevokedError(f"device {session.device_id} is revoked; its sessions cannot produce a snapshot")

            cur.execute("SELECT * FROM missions WHERE id = %s", (session.mission_id,))
            mission_row = cur.fetchone()
            mission = dict(mission_row) if mission_row else None
            if mission is None:
                raise MissionNotFoundError(f"No such mission: {session.mission_id}")
            if mission["owner_user_id"] != authenticated_user_id:
                raise RelayAccessDeniedError(f"mission {session.mission_id} is not owned by the authenticated user")

            mission_id = mission["id"]
            current_revision = mission["current_revision"]

            mission_summary = MissionSummary(
                mission_id=mission_id, workspace_id=mission["workspace_id"], repository=mission["repository"],
                branch=mission["branch"], base_revision=mission["base_revision"], current_revision=current_revision,
                mission_state=mission["state"],
            )

            step = _build_step_summary(cur, mission_id)
            requirements = _build_requirement_summaries(cur, mission_id)
            verifications = _build_verification_summaries(cur, mission_id, current_revision=current_revision)
            test_progress = _build_test_progress_summaries(cur, mission_id, current_revision=current_revision)
            proof_summary = _build_production_proof_summary(cur, mission_id, current_revision=current_revision)
            approvals = _build_pending_approvals(cur, mission_id)
            operations = _build_pending_operations(cur, mission_id)
            checkpoint = _build_checkpoint_summary(cur, mission_id)
            model_activity = _build_model_activity(cur, mission_id)
            tool_activity = _build_tool_activity(cur, mission_id)
            authority_context = _build_authority_context(cur, mission_id)
    except Exception:
        conn.rollback()
        raise
    conn.commit()

    snapshot = RelaySnapshot(
        relay_session_id=session.id, mission_id=mission_id, workspace_id=mission["workspace_id"],
        device_id=device.id, user_id=authenticated_user_id, repository=mission["repository"],
        branch=mission["branch"], current_revision=current_revision, mission_state=mission["state"],
        snapshot_generated_at=now_dt.isoformat(), mission_updated_at=mission.get("updated_at"),
        consistency_basis="single PostgreSQL REPEATABLE READ, READ ONLY transaction",
        mission=mission_summary, step=step, requirements=requirements, verifications=verifications,
        test_progress=test_progress, production_proof=proof_summary, pending_approvals=approvals,
        pending_operations=operations, checkpoint=checkpoint, model_activity=model_activity,
        tool_activity=tool_activity, authority_context=authority_context,
    )
    return _sanitize(snapshot)


def _build_step_summary(cur, mission_id: str) -> StepSummary:
    cur.execute(
        "SELECT id, status FROM mission_steps WHERE mission_id = %s ORDER BY step_index ASC",
        (mission_id,),
    )
    rows = [dict(r) for r in cur.fetchall()]

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


def _build_requirement_summaries(cur, mission_id: str) -> tuple[RequirementSummary, ...]:
    cur.execute(
        "SELECT id, status, statement, evidence_ref FROM requirements WHERE mission_id = %s ORDER BY id ASC",
        (mission_id,),
    )
    rows = [dict(r) for r in cur.fetchall()]
    return tuple(
        RequirementSummary(requirement_id=r["id"], status=r["status"], statement=r["statement"], evidence_ref=r["evidence_ref"])
        for r in rows
    )


def _build_verification_summaries(cur, mission_id: str, *, current_revision: str | None) -> tuple[VerificationSummary, ...]:
    """One entry per (requirement_id, category) pair that has at least
    one real record -- the latest by `created_at` for that pair. See
    `VerificationSummary`'s own docstring: this is explicitly NOT a
    full requirement-level aggregation."""
    cur.execute(
        """
        SELECT DISTINCT requirement_id, category FROM verification_records
        WHERE mission_id = %s AND requirement_id IS NOT NULL
        """,
        (mission_id,),
    )
    pairs = [(r["requirement_id"], r["category"]) for r in cur.fetchall()]

    summaries = []
    for req_id, category in pairs:
        cur.execute(
            "SELECT outcome, revision, verifier_id, evidence_refs FROM verification_records "
            "WHERE mission_id = %s AND requirement_id = %s AND category = %s ORDER BY created_at DESC LIMIT 1",
            (mission_id, req_id, category),
        )
        row = cur.fetchone()
        if row is None:
            continue
        evidence_refs = tuple(json.loads(row["evidence_refs"])) if row["evidence_refs"] else ()
        stale = current_revision is not None and row["revision"] != current_revision
        summaries.append(VerificationSummary(
            requirement_id=req_id, category=category, outcome=row["outcome"], revision=row["revision"],
            verifier_id=row["verifier_id"], evidence_refs=evidence_refs, stale=stale,
        ))
    return tuple(summaries)


def _build_test_progress_summaries(cur, mission_id: str, *, current_revision: str | None) -> tuple[TestProgressSummary, ...]:
    """Mission-level test progress restricted to the CURRENT revision
    only (15.11.1 item 3) -- distinct from `_build_verification_summaries()`,
    which is per-requirement and revision-agnostic (flagging `stale`
    instead of omitting). A historical record from an older revision
    never appears here, even if it is the only record that exists."""
    if current_revision is None:
        return ()
    summaries = []
    for category in _TEST_CATEGORIES:
        cur.execute(
            "SELECT id, outcome, revision, verifier_id, evidence_refs FROM verification_records "
            "WHERE mission_id = %s AND category = %s AND revision = %s ORDER BY created_at DESC LIMIT 1",
            (mission_id, category, current_revision),
        )
        row = cur.fetchone()
        if row is None:
            continue  # absent, per spec -- never a fabricated UNVERIFIED placeholder
        evidence_refs = tuple(json.loads(row["evidence_refs"])) if row["evidence_refs"] else ()
        summaries.append(TestProgressSummary(
            category=category, verification_id=row["id"], outcome=row["outcome"], revision=row["revision"],
            verifier_id=row["verifier_id"], evidence_refs=evidence_refs,
        ))
    return tuple(summaries)


def _build_production_proof_summary(cur, mission_id: str, *, current_revision: str | None) -> ProductionProofSummary:
    cur.execute("SELECT * FROM production_proofs WHERE mission_id = %s ORDER BY created_at DESC LIMIT 1", (mission_id,))
    row = cur.fetchone()
    if row is None:
        return ProductionProofSummary(
            proof_id=None, revision=None, release_state=None, proof_hash=None, generated_at=None,
            available=False, stale=None,
        )
    proof, proof_hash = _row_to_proof(dict(row))
    if current_revision is None:
        stale: bool | None = None
    elif proof.revision != current_revision:
        stale = True  # definite mismatch -- always STALE regardless of anything else
    else:
        # Revisions match, but Relay does not durably have the full
        # decision context (required requirement ids, scopes,
        # semantics fingerprints) that a complete freshness check
        # needs -- freshness is UNKNOWN, never asserted CURRENT
        # (15.11.1 item 9).
        stale = None
    return ProductionProofSummary(
        proof_id=proof.proof_id, revision=proof.revision, release_state=proof.release_state,
        proof_hash=proof_hash, generated_at=proof.generated_at, available=True, stale=stale,
    )


def _build_pending_approvals(cur, mission_id: str) -> tuple[ApprovalSummary, ...]:
    cur.execute(
        """
        SELECT id, operation_id, decision, requested_at, decided_by, reason
        FROM approvals WHERE mission_id = %s AND decision = 'PENDING'
        ORDER BY requested_at DESC LIMIT %s
        """,
        (mission_id, _ACTIVITY_LIMIT),
    )
    rows = [dict(r) for r in cur.fetchall()]
    return tuple(
        ApprovalSummary(
            id=r["id"], operation_id=r["operation_id"], decision=r["decision"], requested_at=r["requested_at"],
            decided_by=r["decided_by"], reason=r["reason"],
        )
        for r in rows
    )


def _build_pending_operations(cur, mission_id: str) -> tuple[OperationSummary, ...]:
    """Only genuinely non-terminal states (15.11.1 item 8) -- FAILED
    is terminal and must never appear here."""
    cur.execute(
        """
        SELECT id, kind, status, requested_by, requested_at, result_ref
        FROM operations WHERE mission_id = %s AND status = ANY(%s)
        ORDER BY requested_at DESC LIMIT %s
        """,
        (mission_id, list(_PENDING_OPERATION_STATUSES), _ACTIVITY_LIMIT),
    )
    rows = [dict(r) for r in cur.fetchall()]
    return tuple(
        OperationSummary(
            id=r["id"], kind=r["kind"], status=r["status"], requested_by=r["requested_by"],
            requested_at=r["requested_at"], result_ref=r["result_ref"],
        )
        for r in rows
    )


def _build_checkpoint_summary(cur, mission_id: str) -> CheckpointSummary:
    cur.execute("SELECT * FROM checkpoints WHERE mission_id = %s ORDER BY created_at DESC LIMIT 1", (mission_id,))
    row = cur.fetchone()
    if row is None:
        return CheckpointSummary(
            checkpoint_id=None, created_at=None, mission_state=None, current_step_id=None,
            current_revision=None, diff_ref=None, active_blocker=None, evidence_refs=(),
        )
    checkpoint = Checkpoint.from_row(dict(row))
    return CheckpointSummary(
        checkpoint_id=checkpoint.id, created_at=checkpoint.created_at, mission_state=checkpoint.mission_state,
        current_step_id=checkpoint.current_step_id, current_revision=checkpoint.current_revision,
        diff_ref=checkpoint.diff_ref, active_blocker=checkpoint.active_blocker,
        evidence_refs=checkpoint.evidence_refs[:_ACTIVITY_LIMIT],
    )


def _build_model_activity(cur, mission_id: str) -> tuple[ModelActivitySummary, ...]:
    cur.execute(
        """
        SELECT id, provider, model, purpose, started_at, completed_at, outcome_summary
        FROM model_invocations WHERE mission_id = %s ORDER BY started_at DESC LIMIT %s
        """,
        (mission_id, _ACTIVITY_LIMIT),
    )
    rows = [dict(r) for r in cur.fetchall()]
    return tuple(
        ModelActivitySummary(
            id=r["id"], provider=r["provider"], model=r["model"], purpose=r["purpose"],
            started_at=r["started_at"], completed_at=r["completed_at"], outcome_summary=r["outcome_summary"],
        )
        for r in rows
    )


def _build_tool_activity(cur, mission_id: str) -> tuple[ToolActivitySummary, ...]:
    cur.execute(
        """
        SELECT id, tool_name, status, started_at, completed_at, outcome_summary
        FROM tool_invocations WHERE mission_id = %s ORDER BY started_at DESC LIMIT %s
        """,
        (mission_id, _ACTIVITY_LIMIT),
    )
    rows = [dict(r) for r in cur.fetchall()]
    return tuple(
        ToolActivitySummary(
            id=r["id"], tool_name=r["tool_name"], status=r["status"], started_at=r["started_at"],
            completed_at=r["completed_at"], outcome_summary=r["outcome_summary"],
        )
        for r in rows
    )


def _build_authority_context(cur, mission_id: str) -> tuple[AuthorityContextSummary, ...]:
    """Never exposes `policy_ref` (the operation's lease id, spec
    section 18: 'never expose capability secrets or lease material')."""
    cur.execute(
        """
        SELECT id, operation_id, decision, decided_at, detail
        FROM authority_decisions WHERE mission_id = %s ORDER BY decided_at DESC LIMIT %s
        """,
        (mission_id, _ACTIVITY_LIMIT),
    )
    rows = [dict(r) for r in cur.fetchall()]
    return tuple(
        AuthorityContextSummary(
            id=r["id"], operation_id=r["operation_id"], decision=r["decision"], decided_at=r["decided_at"],
            detail=r["detail"],
        )
        for r in rows
    )
