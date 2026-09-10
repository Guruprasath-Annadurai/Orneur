"""
Phase 15.13 -- Reconnect + Idempotency truthfulness layer.

This module is a THIN, READ-MOSTLY layer on top of already-proven
machinery. It does not build a second operation ledger, a second
mission-state machine, or a second authority engine:

  * Operation lifecycle/idempotency truth comes from
    `orca.mission.operation_store` (Phase 15.5) exactly as-is --
    `request_operation()`'s atomic `ON CONFLICT (idempotency_key) DO
    NOTHING` dedup, `start_and_execute_operation()`'s
    `_NO_EXECUTOR_RECALL_STATES` exactly-once guarantee, and
    `compute_fingerprint()`'s conflict detection are all reused
    unmodified.
  * Session/device security validity comes from
    `orca.mission.relay_security` (Phase 15.12/15.12.1) exactly as-is
    -- every reconnect/control path here goes through
    `require_security_valid_session()`, `touch_relay_session_securely()`,
    `build_security_valid_relay_snapshot()`, or
    `authorize_relay_capability()`, never the lower-level Phase 15.11
    primitives directly.
  * Mission-state concurrency comes from `orca.mission.mission_store`'s
    existing `SELECT ... FOR UPDATE` row-locking (Phase 15.4) -- no
    additive revision/version column is introduced (matching that
    module's own already-made spec-section-3 decision that row-level
    locking is sufficient). `apply_mission_mutation_precondition()`
    below adds a purely-composed STALE_CONFLICT classification in
    front of that locking, from the CLIENT's point of view.

What IS new here (spec section 26's "network loss + reconnect
truthfulness", section 27's "multi-device consistency"):

  * A typed network/operation-truth model (`RelayConnectionState`,
    `RelayFreshness`, `RelayOperationTruth`) so "the connection was
    lost" and "the operation failed" can never be confused with each
    other, or with "the operation succeeded" (spec section 26: "a lost
    response must not become a fake success").
  * `RelayReconnectResult` -- a bounded, secret-safe summary of what a
    reconnecting client should see: NEVER a fabricated dangerous-
    action retry, only durable server-observed truth.
  * `reconcile_operation()` -- single-operation reconnect lookup, with
    real access control (spec section 26/33): a session can only
    reconcile operations belonging to ITS OWN mission; cross-user and
    cross-mission lookups are denied even with a guessed/valid-looking
    operation ID.
  * `apply_mission_mutation_precondition()` -- typed
    APPLIED/STALE_CONFLICT/DENIED/FAILED outcomes for pause/resume/
    cancel, so a stale device's mutation attempt against mission state
    it no longer accurately observes is reported truthfully rather
    than silently last-write-wins or silently succeeding.

SERVICE-LAYER RECONNECT / LOST-RESPONSE SEMANTICS: this module proves
and simulates response loss purely at the service boundary (a test
harness that discards a return value the server-side call has already
genuinely completed). It makes NO claim about real WebSocket/TLS
reconnect semantics, browser retry behavior, or CSRF resistance --
those require an actual network transport, which does not exist yet
in this codebase (spec section 28).
"""
from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime
from enum import Enum

from orca.mission.mission_store import (
    CheckpointNotFoundError,
    MissionNotFoundError,
    MissionStoreError,
    _apply_mutation_with_precondition_locked,
    apply_mutation_with_precondition,
    get_checkpoint,
    get_mission,
)
from orca.mission.operation_store import get_operation, list_operations_for_mission
from orca.mission.production_proof import redact_secrets
from orca.mission.relay_security import (
    RelayAccessDeniedError,
    RelaySnapshot,
    SessionSecurityInvalidError,
    _default_clock,
    build_security_valid_relay_snapshot,
    require_security_valid_session,
    require_security_valid_session_locked,
    touch_relay_session_securely,
)
from orca.mission.state_machine import MissionState


class RelayReconnectError(Exception):
    """Base class for reconnect/reconciliation errors."""


class RelayReconnectAccessDeniedError(RelayReconnectError):
    """A session attempted to reconcile an operation it does not own
    the mission for -- raised for both cross-user and cross-mission
    lookups (spec sections 26, 33: guessing an ID must not work)."""


# ── Typed network/operation-truth model (spec section 26) ───────────

class RelayConnectionState(Enum):
    CONNECTED = "CONNECTED"
    RECONNECTING = "RECONNECTING"
    OFFLINE = "OFFLINE"


class RelayFreshness(Enum):
    CURRENT = "CURRENT"
    STALE = "STALE"


class RelayOperationTruth(Enum):
    """Connection loss is NEVER converted into this truth. Only a
    real, server-observed `operations.status` value ever produces
    CONFIRMED or FAILED -- see `classify_operation_truth()`."""
    PENDING = "PENDING"
    CONFIRMED = "CONFIRMED"
    FAILED = "FAILED"


_CONFIRMED_STATUSES = frozenset({"SUCCEEDED"})
_FAILED_STATUSES = frozenset({"FAILED", "CANCELLED"})
_PENDING_STATUSES = frozenset({"REQUESTED", "AUTHORIZED", "STARTED"})


def classify_operation_truth(status: str) -> RelayOperationTruth:
    """The ONLY function that turns a durable `operations.status` value
    into a `RelayOperationTruth`. Status drives truth -- never the
    presence/absence of `result_ref` (spec section 24): a STARTED
    operation with an unknown outcome (a crash between the executor
    finishing and the write landing) is PENDING, never guessed as
    CONFIRMED or FAILED."""
    if status in _CONFIRMED_STATUSES:
        return RelayOperationTruth.CONFIRMED
    if status in _FAILED_STATUSES:
        return RelayOperationTruth.FAILED
    if status in _PENDING_STATUSES:
        return RelayOperationTruth.PENDING
    raise RelayReconnectError(f"unrecognized operation status: {status!r}")


# ── Bounded, secret-safe reconciliation summaries ────────────────────

@dataclass(frozen=True)
class OperationReconciliationSummary:
    operation_id: str
    idempotency_key: str
    kind: str
    status: str
    truth: RelayOperationTruth
    result_ref: str | None
    requested_at: str | None
    started_at: str | None
    completed_at: str | None


def _sanitize_result_ref(value: str | None) -> str | None:
    if value is None:
        return None
    return redact_secrets(value)


def _summarize_operation_row(row: dict) -> OperationReconciliationSummary:
    return OperationReconciliationSummary(
        operation_id=row["id"],
        idempotency_key=row["idempotency_key"],
        kind=row["kind"],
        status=row["status"],
        truth=classify_operation_truth(row["status"]),
        result_ref=_sanitize_result_ref(row.get("result_ref")),
        requested_at=row.get("requested_at"),
        started_at=row.get("started_at"),
        completed_at=row.get("completed_at"),
    )


@dataclass(frozen=True)
class RelayReconnectResult:
    relay_session_id: str
    mission_id: str
    connection_state: RelayConnectionState
    freshness: RelayFreshness
    server_observed_at: str
    snapshot: RelaySnapshot
    operations: tuple[OperationReconciliationSummary, ...]
    warnings: tuple[str, ...]
    requires_reauthentication: bool


# ── Reconnect: strictly read-only + one intentional heartbeat write ──

def reconnect_to_mission(
    conn, *, session_id: str, authenticated_user_id: str, now_fn=_default_clock,
    operation_history_limit: int = 25,
) -> RelayReconnectResult:
    """The canonical reconnect entrypoint (spec sections 1, 3, 4, 25).

    Strictly read-only except for ONE explicit, intentional secure
    session heartbeat (`touch_relay_session_securely()`), which itself
    goes through the full Phase 15.12.1 security-validity check before
    writing anything. Never: request/authorize/start/re-execute an
    operation, auto-resume a mission, approve anything, change a
    checkpoint, or change Production Proof state.

    A revoked/expired/idle-expired session, or a device/mode-mismatched
    session, raises `SessionSecurityInvalidError`/`RelayAccessDeniedError`
    truthfully -- this function never silently creates a replacement
    session or relabels a failed reconnect as CURRENT."""
    session = touch_relay_session_securely(
        conn, session_id, authenticated_user_id=authenticated_user_id, now_fn=now_fn,
    )
    snapshot = build_security_valid_relay_snapshot(
        conn, session_id=session_id, authenticated_user_id=authenticated_user_id, now_fn=now_fn,
    )

    mission_id = snapshot.mission_id
    history_rows = list_operations_for_mission(conn, mission_id, limit=operation_history_limit)
    operations = tuple(_summarize_operation_row(row) for row in history_rows)

    return RelayReconnectResult(
        relay_session_id=session.id,
        mission_id=mission_id,
        connection_state=RelayConnectionState.CONNECTED,
        freshness=RelayFreshness.CURRENT,
        server_observed_at=now_fn().isoformat(),
        snapshot=snapshot,
        operations=operations,
        warnings=(),
        requires_reauthentication=False,
    )


# ── Single-operation reconciliation, with real access control ───────

def reconcile_operation(
    conn, *, session_id: str, authenticated_user_id: str, operation_id: str, now_fn=_default_clock,
) -> OperationReconciliationSummary:
    """Looks up ONE operation's durable truth for a reconnecting
    client. Read-only: never authorizes, starts, or re-executes.

    Access control (spec sections 26, 33): the session must itself be
    security-valid for `authenticated_user_id` (ownership + revocation
    + expiry + inactivity + device/mode compatibility, all enforced by
    `build_security_valid_relay_snapshot()`), AND the looked-up
    operation's `mission_id` must equal the session's OWN mission_id.
    A user guessing another user's operation ID, or their own
    operation ID from a different mission/session, is denied -- not
    handed a 404-shaped information leak, and not silently
    reconciled."""
    snapshot = build_security_valid_relay_snapshot(
        conn, session_id=session_id, authenticated_user_id=authenticated_user_id, now_fn=now_fn,
    )
    row = get_operation(conn, operation_id)
    if row is None or row.get("mission_id") != snapshot.mission_id:
        raise RelayReconnectAccessDeniedError(
            f"operation {operation_id!r} is not reconcilable from relay session {session_id!r}"
        )
    return _summarize_operation_row(row)


# ── Mission mutation preconditions (spec sections 15-19) ────────────

class RelayMutationOutcome(Enum):
    APPLIED = "APPLIED"
    STALE_CONFLICT = "STALE_CONFLICT"
    DENIED = "DENIED"
    FAILED = "FAILED"


@dataclass(frozen=True)
class RelayMutationPrecondition:
    mission_id: str
    expected_state: MissionState
    expected_revision: str | None = None


@dataclass(frozen=True)
class RelayMutationResult:
    outcome: RelayMutationOutcome
    mission: dict | None
    detail: str


def apply_mission_mutation_precondition(
    conn, precondition: RelayMutationPrecondition, *, new_state: MissionState, evidence_ref: str | None = None,
) -> RelayMutationResult:
    """Typed, honest outcome for a governed mission-state mutation
    (pause/resume) attempted by a possibly-stale device. Never
    silently last-write-wins (spec section 15) -- see
    `mission_store.apply_mutation_with_precondition()` for the atomic
    mechanism (Phase 15.13.1: the precondition READ and the mutation
    WRITE now share the identical `SELECT ... FOR UPDATE` locked row,
    closing the earlier two-step get-then-transition race window).

    This function is NOT itself a Relay-authorized control boundary --
    it has no `session_id`/`authenticated_user_id` and performs no
    ownership/session-binding check, and -- deliberately, as the
    lower-level, security-agnostic primitive -- does NOT enforce Phase
    15.13.2's stronger "revision cannot be omitted when one durably
    exists" rule (`require_revision_if_present` defaults to `False`
    here). It exists as the composable primitive that
    `apply_relay_mission_mutation()` (below) uses as PART of its own
    larger atomic transaction. Do not expose this function directly as
    a Relay control action."""
    try:
        outcome_str, mission, detail = apply_mutation_with_precondition(
            conn, precondition.mission_id,
            expected_state=precondition.expected_state,
            expected_revision=precondition.expected_revision,
            new_state=new_state, evidence_ref=evidence_ref,
        )
    except MissionNotFoundError as e:
        return RelayMutationResult(RelayMutationOutcome.FAILED, None, str(e))
    except MissionStoreError as e:
        return RelayMutationResult(RelayMutationOutcome.FAILED, None, str(e))

    outcome = RelayMutationOutcome(outcome_str)
    return RelayMutationResult(outcome, mission, detail)


def apply_relay_mission_mutation(
    conn, *, session_id: str, authenticated_user_id: str,
    precondition: RelayMutationPrecondition, new_state: MissionState,
    evidence_ref: str | None = None, now_fn=_default_clock,
) -> RelayMutationResult:
    """THE actual Relay-authorized mutation control boundary (Phase
    15.13.2 closure: now genuinely ATOMIC end-to-end).

    Phase 15.13.1's version called `require_security_valid_session()`
    (whose own reads COMMIT internally) and only LATER, in a separate
    transaction, locked and mutated the mission row -- a real TOCTOU
    window: a concurrent session/device revocation could commit in
    between, and the mutation would still proceed using the earlier,
    now-stale security read.

    Here, ONE transaction establishes a single deterministic lock
    order -- Relay session -> device -> mission -- and holds every
    lock until a single final commit:

      1. `require_security_valid_session_locked()` locks the session
         row, then the bound device row, `FOR UPDATE`, and evaluates
         the EXACT SAME pure `evaluate_session_security()` rule every
         other Relay entrypoint uses (ownership, revocation, absolute
         expiry, inactivity, device revocation, device/mode
         compatibility) -- without committing.
      2. `session.mission_id == precondition.mission_id` is verified
         -- a mission ID alone is never proof of Relay authority.
      3. `_apply_mutation_with_precondition_locked()` locks the
         mission row `FOR UPDATE` and evaluates/applies the mutation,
         with `require_revision_if_present=True` -- the Relay-
         authoritative path cannot have its optimistic-concurrency
         check bypassed merely by omitting `expected_revision`.
      4. ONE commit releases all three locks together.

    Ordering guarantee this closes: if a concurrent revocation's
    UPDATE commits before this transaction acquires the session-row
    lock, this transaction's own re-read (after acquiring the lock)
    observes the revoked state and denies. If this transaction
    acquires the session-row lock FIRST (session still valid) and
    commits its mutation, a revocation that comes after is legal and
    has no bearing on the already-durably-applied mutation -- Postgres
    serializes the two transactions in whichever order they actually
    acquire/release the lock, and this function never uses information
    from a read older than that ordering.

    Any exception -- expected (`SessionSecurityInvalidError`,
    `RelayAccessDeniedError`, `RelayReconnectAccessDeniedError`) or
    genuinely unexpected -- rolls back before propagating, except
    `MissionNotFoundError`/`MissionStoreError`, which convert to a
    typed `FAILED` result (matching `apply_mission_mutation_precondition()`'s
    established convention) after rollback."""
    try:
        session, device = require_security_valid_session_locked(
            conn, session_id, authenticated_user_id=authenticated_user_id, now_fn=now_fn,
        )
        if session.mission_id != precondition.mission_id:
            raise RelayReconnectAccessDeniedError(
                f"relay session {session_id!r} is bound to mission {session.mission_id!r}, not "
                f"{precondition.mission_id!r} -- a mission ID alone is not proof of Relay authority"
            )
        with conn.cursor() as cur:
            outcome_str, mission_row, detail = _apply_mutation_with_precondition_locked(
                cur, precondition.mission_id,
                expected_state=precondition.expected_state,
                expected_revision=precondition.expected_revision,
                new_state=new_state, evidence_ref=evidence_ref,
                require_revision_if_present=True,
            )
    except (MissionNotFoundError, MissionStoreError) as e:
        conn.rollback()
        return RelayMutationResult(RelayMutationOutcome.FAILED, None, str(e))
    except Exception:
        conn.rollback()
        raise
    conn.commit()
    return RelayMutationResult(RelayMutationOutcome(outcome_str), mission_row, detail)


# ── Minimal edit/revision-conflict primitive (spec sections 27, 31) ──

class RevisionCurrency(Enum):
    CURRENT = "CURRENT"
    STALE_CONFLICT = "STALE_CONFLICT"


def _classify_revision_currency(expected_revision: str | None, actual_revision: str | None) -> RevisionCurrency:
    """Pure classification, independently unit-testable without a
    database. A genuinely absent revision on either side is never
    treated as a match by coincidence -- `None == None` would silently
    call an unrevisioned mission CURRENT for ANY caller, which is not
    an honest currentness claim, so an absent actual revision is
    always STALE_CONFLICT regardless of what the caller expected."""
    if actual_revision is None:
        return RevisionCurrency.STALE_CONFLICT
    if expected_revision == actual_revision:
        return RevisionCurrency.CURRENT
    return RevisionCurrency.STALE_CONFLICT


def check_revision_currency(
    conn, *, session_id: str, authenticated_user_id: str, mission_id: str,
    expected_revision: str | None, now_fn=_default_clock,
) -> RevisionCurrency:
    """The minimal Relay-bound edit-conflict primitive (spec section
    27): "a Relay-originating code/edit action based on revision A
    must not silently apply over revision B." No file merge UI, no
    new mutation path -- a read-only classification, security-session-
    bound exactly like every other Relay control boundary."""
    session, device = require_security_valid_session(
        conn, session_id, authenticated_user_id=authenticated_user_id, now_fn=now_fn,
    )
    if session.mission_id != mission_id:
        raise RelayReconnectAccessDeniedError(
            f"relay session {session_id!r} is bound to mission {session.mission_id!r}, not {mission_id!r}"
        )
    mission = get_mission(conn, mission_id)
    if mission is None:
        raise MissionNotFoundError(f"No such mission: {mission_id}")
    return _classify_revision_currency(expected_revision, mission.get("current_revision"))


# ── Checkpoint currentness (spec section 18) ─────────────────────────

class CheckpointCurrency(Enum):
    CURRENT = "CURRENT"
    STALE = "STALE"


def _classify_checkpoint_currency(checkpoint_revision: str | None, mission_revision: str | None) -> CheckpointCurrency:
    """Pure classification. Per spec section 18's own "at minimum ...
    where both revisions exist": when either revision is genuinely
    absent, currentness cannot be honestly verified, so this fails
    closed to STALE rather than fabricating a CURRENT claim."""
    if checkpoint_revision is None or mission_revision is None:
        return CheckpointCurrency.STALE
    if checkpoint_revision == mission_revision:
        return CheckpointCurrency.CURRENT
    return CheckpointCurrency.STALE


def check_checkpoint_currency(
    conn, *, session_id: str, authenticated_user_id: str, checkpoint_id: str, now_fn=_default_clock,
) -> CheckpointCurrency:
    """Determines whether a durable checkpoint is CURRENT for the
    Relay mission context, without touching checkpoint storage at all
    (no Phase 15.4 redesign -- `create_checkpoint()`'s append-only
    history is untouched). A STALE checkpoint remains fully present in
    history; this function only classifies whether it should be
    represented/promoted as the current continuation point -- it never
    deletes, rewrites, or reorders anything."""
    session, device = require_security_valid_session(
        conn, session_id, authenticated_user_id=authenticated_user_id, now_fn=now_fn,
    )
    checkpoint = get_checkpoint(conn, checkpoint_id)
    if checkpoint is None:
        raise CheckpointNotFoundError(f"No such checkpoint: {checkpoint_id}")
    if checkpoint.mission_id != session.mission_id:
        raise RelayReconnectAccessDeniedError(
            f"checkpoint {checkpoint_id!r} belongs to mission {checkpoint.mission_id!r}, "
            f"not relay session {session_id!r}'s mission {session.mission_id!r}"
        )
    mission = get_mission(conn, checkpoint.mission_id)
    if mission is None:
        raise MissionNotFoundError(f"No such mission: {checkpoint.mission_id}")
    return _classify_checkpoint_currency(checkpoint.current_revision, mission.get("current_revision"))


# ── Client-side cached-reconnect-view lifecycle (spec section 26) ───

@dataclass
class CachedRelayView:
    """A minimal, testable representation of a client's LOCAL view of
    the Relay reconnect lifecycle -- client-side bookkeeping only, no
    transport of any kind. This is the SERVICE-LAYER simulation the
    module docstring promises: it proves the state SEQUENCE a
    truthful client must follow, without claiming any real
    WebSocket/TLS/browser-retry behavior (spec section 28)."""
    connection_state: RelayConnectionState
    freshness: RelayFreshness
    last_good_result: RelayReconnectResult | None = None

    @classmethod
    def initial(cls) -> "CachedRelayView":
        return cls(connection_state=RelayConnectionState.OFFLINE, freshness=RelayFreshness.STALE)

    def mark_connection_lost(self) -> None:
        """A real or simulated transport signal that the connection
        dropped. The cached snapshot -- however recent -- immediately
        becomes STALE; it is never treated as CURRENT again until a
        fresh, successful server read succeeds."""
        self.connection_state = RelayConnectionState.OFFLINE
        self.freshness = RelayFreshness.STALE

    def begin_reconnecting(self) -> None:
        """Attempting to reconnect does not, by itself, make the
        cached data any more current -- freshness stays STALE until a
        real read actually succeeds."""
        self.connection_state = RelayConnectionState.RECONNECTING

    def apply_successful_reconnect(self, result: RelayReconnectResult) -> None:
        """Call ONLY after a real `reconnect_to_mission()` call has
        genuinely succeeded (that function itself only returns
        CONNECTED/CURRENT on success, and raises rather than returning
        a degraded result on failure -- see `record_failed_reconnect()`
        for the failure path)."""
        self.connection_state = result.connection_state
        self.freshness = result.freshness
        self.last_good_result = result

    def record_failed_reconnect(self) -> None:
        """A reconnect attempt failed (revoked/expired/idle-expired
        session, device/mode mismatch, or any other denial). The
        client stays OFFLINE with its previous cached snapshot still
        marked STALE -- never silently relabeled CURRENT."""
        self.connection_state = RelayConnectionState.OFFLINE
        self.freshness = RelayFreshness.STALE
