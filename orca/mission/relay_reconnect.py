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
    MissionNotFoundError,
    MissionStateError,
    MissionStoreError,
    get_mission,
    resume_mission,
    transition_mission,
)
from orca.mission.operation_store import get_operation, list_operations_for_mission
from orca.mission.production_proof import redact_secrets
from orca.mission.relay_security import (
    RelayAccessDeniedError,
    RelaySnapshot,
    SessionSecurityInvalidError,
    _default_clock,
    build_security_valid_relay_snapshot,
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


@dataclass(frozen=True)
class RelayMutationResult:
    outcome: RelayMutationOutcome
    mission: dict | None
    detail: str


def _resolve_new_state(new_state: MissionState) -> callable:
    if new_state is MissionState.RUNNING:
        return lambda conn, mission_id, evidence_ref: resume_mission(conn, mission_id, evidence_ref=evidence_ref)
    return lambda conn, mission_id, evidence_ref: transition_mission(
        conn, mission_id, new_state, evidence_ref=evidence_ref,
    )


def apply_mission_mutation_precondition(
    conn, precondition: RelayMutationPrecondition, *, new_state: MissionState, evidence_ref: str | None = None,
) -> RelayMutationResult:
    """Typed, honest outcome for a governed mission-state mutation
    (pause/resume/cancel) attempted by a possibly-stale reconnecting
    device. Never silently last-write-wins (spec section 15):

      * If the mission is ALREADY in `new_state` (a second, identical,
        racing request), reports APPLIED as an idempotent no-op --
        this is the "simultaneous identical PAUSE requests reconcile
        safely" requirement (spec section 16) -- without attempting a
        redundant write.
      * If the mission's actual current state does not match what the
        caller expected AND is not yet the target, reports
        STALE_CONFLICT -- the caller's view of mission state was
        out of date; it did not durably corrupt anything.
      * If the caller's expected state was accurate but the mutation
        is illegal per the canonical state machine (e.g. attempting to
        resume a durably CANCELLED mission), reports DENIED.
      * Any other failure (e.g. mission not found) reports FAILED.

    Uses `mission_store`'s existing `SELECT ... FOR UPDATE` row locking
    for the actual write -- no additive revision/version column is
    introduced (spec section 31: prefer no migration)."""
    try:
        mission = get_mission(conn, precondition.mission_id)
    except MissionStoreError as e:
        return RelayMutationResult(RelayMutationOutcome.FAILED, None, str(e))
    if mission is None:
        return RelayMutationResult(
            RelayMutationOutcome.FAILED, None, f"no such mission: {precondition.mission_id}",
        )

    actual_state = MissionState(mission["state"])
    if actual_state is new_state:
        return RelayMutationResult(
            RelayMutationOutcome.APPLIED, mission,
            "mission already in target state -- idempotent no-op, no duplicate write issued",
        )
    if actual_state is not precondition.expected_state:
        return RelayMutationResult(
            RelayMutationOutcome.STALE_CONFLICT, mission,
            f"caller expected {precondition.expected_state.value}, mission is actually {actual_state.value}",
        )

    apply_fn = _resolve_new_state(new_state)
    try:
        updated = apply_fn(conn, precondition.mission_id, evidence_ref)
    except MissionNotFoundError as e:
        return RelayMutationResult(RelayMutationOutcome.FAILED, None, str(e))
    except (MissionStateError, MissionStoreError) as e:
        return RelayMutationResult(RelayMutationOutcome.DENIED, mission, str(e))
    return RelayMutationResult(RelayMutationOutcome.APPLIED, updated, "mutation applied")
