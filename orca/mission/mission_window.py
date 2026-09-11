"""
Phase 15.14 / 15.14.1 -- Six-Hour Mission Governance + Autonomous-Window
Bypass, Atomic Admission, and Secret-Safe Checkpoint Closure.

The six-hour autonomous mission window is a LIMIT on autonomous work,
never a GRANT of authority, never a compute budget, and never a
reason to fabricate completion:

    THE SIX-HOUR WINDOW LIMITS AUTONOMOUS WORK.
    IT DOES NOT GRANT AUTHORITY.
    IT DOES NOT RESET IDEMPOTENCY.
    IT DOES NOT MEAN SIX HOURS OF COMPUTE BUDGET.

This module is a THIN layer composed entirely on top of already-proven
machinery -- it does not build a second mission-state machine, a
second checkpoint system, or a second operation ledger:

  * `orca.mission.mission_store.checkpoint_and_pause()` (Phase 15.4)
    remains THE single atomic transition-plus-checkpoint primitive.
    `enforce_window_expiry()` below calls it unmodified.
  * `orca.mission.mission_store.resume_mission()` remains the module-
    level reference implementation for a standalone PAUSED_* ->
    RUNNING transition; `resume_after_window()` below composes the
    SAME `state_machine.transition()` validation inline so it can
    share ONE transaction/lock with the fresh-window write (Phase
    15.14.1 item 12) rather than committing separately.
  * `orca.mission.operation_store.request_operation()` and
    `start_and_execute_operation()` remain completely UNMODIFIED for
    every non-autonomous caller. Phase 15.14.1 items 5/7 add thin,
    ADDITIVE, window-gated wrappers -- `request_operation_within_
    window()` and `start_and_execute_operation_within_window()` --
    that compose the mission-row lock with the operation ledger's own
    primitives (`_write_operation_transition()`, `_execute_and_
    settle()`) rather than duplicating their logic.
  * Relay-visible secret redaction reuses
    `orca.mission.production_proof.redact_secrets()` -- the SAME
    primitive `orca.mission.relay_store._sanitize()` already uses --
    applied here at CHECKPOINT WRITE TIME (item 11), not only at
    Relay-display time.

Phase 15.14.1 (owner audit) closed the following gaps found in the
originally-accepted Phase 15.14 implementation:

  1. `start_autonomous_window()` could silently renew an EXPIRED
     window, bypassing the explicit PAUSED_WINDOW_REACHED -> resume
     boundary. Closed: a direct call now DENIES renewal of an expired
     window; only `resume_after_window()` (reachable only after
     durable PAUSED_WINDOW_REACHED + checkpoint validation) may start
     a genuinely new post-expiry window, via the private `_begin_
     window_locked()` helper's `allow_post_expiry_renewal` flag -- not
     a public caller-supplied boolean.
  2. Window duration is now sourced from `get_mission_window_policy()`
     (a trusted SERVER policy), never a public caller-supplied
     integer. Tests inject a policy only via the underscore-prefixed,
     internal `_policy` seam.
  3. NOT_STARTED (an L3/L4 mission with no window ever begun) no
     longer admits new autonomous work.
  4. PAUSED_USER and BLOCKED now explicitly deny new autonomous work,
     regardless of how much of a window's timestamp range remains.
  5/6. AUTHORIZED-but-not-yet-STARTED operations can no longer START
     after window expiry (`start_and_execute_operation_within_
     window()`); already-STARTED work still settles exactly once,
     never replayed.
  7/8/9. New-operation admission and the AUTHORIZED->STARTED boundary
     are now atomic with window/state eligibility -- both hold the
     SAME mission-row `FOR UPDATE` lock `enforce_window_expiry()`
     uses, so whichever transaction commits first durably wins.
  10. Idempotency-key retry bypass is now MISSION-BOUND: a key that
      belongs to a different mission never confers eligibility here.
  11. Checkpoint content is sanitized BEFORE the INSERT, not only at
      Relay-read time.
  12/13. `resume_after_window()` and `enforce_window_expiry()` now
      hold ONE mission-row lock across their entire decision + write,
      rather than deciding from an earlier, separately-committed read.
"""
from __future__ import annotations

import uuid
from dataclasses import dataclass
from datetime import datetime, timedelta, timezone
from enum import Enum

from orca.mission.mission_store import (
    Checkpoint,
    MissionNotFoundError,
    MissionStoreError,
    checkpoint_and_pause,
    get_latest_checkpoint,
    get_mission,
)
from orca.mission.production_proof import redact_secrets
from orca.mission.state_machine import TERMINAL_STATES, MissionState, MissionStateError, transition

DEFAULT_AUTONOMOUS_WINDOW_SECONDS = 6 * 60 * 60

# The six-hour window governs only autonomous-mission autonomy levels.
# L0 (ADVISE)/L1 (EDIT)/L2 (EXECUTE) never become six-hour autonomous
# workers merely because this module exists (spec section 8 item 2).
_AUTONOMOUS_LEVELS = frozenset({"L3", "L4"})

# States in which the mission is genuinely doing (or waiting on) work
# under an active window -- the window keeps counting through all of
# these; none of them resets the deadline (spec section 3/7).
_ACTIVE_WINDOW_STATES = frozenset({
    MissionState.RUNNING,
    MissionState.WAITING_TOOL,
    MissionState.WAITING_EXTERNAL_EVENT,
    MissionState.WAITING_APPROVAL,
    MissionState.VERIFYING,
    MissionState.COURT_REVIEW,
})

# States a window may legitimately BEGIN from directly: READY (the
# mission's first ever autonomous start) or RUNNING (a window being
# established on a mission that is already running). A post-expiry
# RENEWAL via resume_after_window() is handled separately -- see
# `_begin_window_locked()`'s `allow_post_expiry_renewal`.
_WINDOW_STARTABLE_STATES = frozenset({MissionState.READY, MissionState.RUNNING})


def _default_clock() -> datetime:
    return datetime.now(timezone.utc)


def _parse_iso(value: str) -> datetime:
    dt = datetime.fromisoformat(value)
    if dt.tzinfo is None:
        dt = dt.replace(tzinfo=timezone.utc)
    return dt


class MissionWindowError(Exception):
    """Base class for mission-window errors."""


class MissionWindowExpiredError(MissionWindowError):
    """Raised when a genuinely NEW admission (a new idempotency key, or
    an AUTHORIZED operation's START) is attempted while the mission's
    autonomous window does not admit new work."""


class WindowRenewalDeniedError(MissionWindowError):
    """Phase 15.14.1 item 1: raised by `start_autonomous_window()` when
    the mission's PRIOR window has already expired -- a direct call
    may never renew it. A new window may begin only via the explicit
    `PAUSED_WINDOW_REACHED -> resume_after_window()` path."""


# ── Typed window status/decision model (spec section 1) ─────────────

class MissionWindowStatus(Enum):
    NOT_STARTED = "NOT_STARTED"
    ACTIVE = "ACTIVE"
    EXPIRED = "EXPIRED"
    PAUSED = "PAUSED"
    BLOCKED = "BLOCKED"
    TERMINAL = "TERMINAL"
    NOT_APPLICABLE = "NOT_APPLICABLE"
    INVALID = "INVALID"


class MissionWindowDecision(Enum):
    ALLOW_NEW_WORK = "ALLOW_NEW_WORK"
    DENY_NOT_ELIGIBLE = "DENY_NOT_ELIGIBLE"


class WindowEnforcementOutcome(Enum):
    PAUSED = "PAUSED"
    ALREADY_PAUSED = "ALREADY_PAUSED"
    NOT_YET_EXPIRED = "NOT_YET_EXPIRED"
    TERMINAL = "TERMINAL"
    NO_ACTION = "NO_ACTION"


@dataclass(frozen=True)
class WindowEnforcementResult:
    outcome: WindowEnforcementOutcome
    mission: dict
    checkpoint: Checkpoint | None


# ── Server-controlled window duration policy (item 2) ────────────────

@dataclass(frozen=True)
class MissionWindowPolicy:
    """Trusted SERVER policy for autonomous window duration. V1: a
    fixed 21,600s (6h) for both L3 and L4 -- no real per-organization
    policy source exists yet, so none is invented. Production
    authoritative code always obtains duration via
    `get_mission_window_policy()`; a caller can never supply an
    arbitrary duration directly."""
    durations_by_level: dict[str, int]

    def duration_seconds(self, autonomy_level: str) -> int:
        try:
            return self.durations_by_level[autonomy_level]
        except KeyError:
            raise MissionWindowError(
                f"no window-duration policy configured for autonomy_level {autonomy_level!r}"
            )


_DEFAULT_WINDOW_POLICY = MissionWindowPolicy(
    durations_by_level={"L3": DEFAULT_AUTONOMOUS_WINDOW_SECONDS, "L4": DEFAULT_AUTONOMOUS_WINDOW_SECONDS},
)


def get_mission_window_policy() -> MissionWindowPolicy:
    """THE trusted server policy source for window duration. Returns
    the fixed V1 policy (21,600s for both L3 and L4). A future phase
    may replace this with a real trusted-organization-configuration
    lookup; every production authoritative call site goes through this
    function rather than accepting a duration from a caller."""
    return _DEFAULT_WINDOW_POLICY


# ── Pure window-status evaluation (spec section 6, hardened 15.14.1) ─

def evaluate_mission_window(mission: dict, *, now: datetime) -> MissionWindowStatus:
    """Derives window status ENTIRELY from durable mission state --
    never from an in-process timer. Order matters: autonomy-level
    applicability is checked first (L0-L2 are NOT_APPLICABLE
    regardless of any timestamps that happen to be present), then
    mission-state governance that is STRONGER than the window
    dimension (terminal, window-paused, user-paused, blocked -- Phase
    15.14.1 item 4: a still-in-range deadline never overrides these),
    and only then are the timestamps themselves evaluated. Malformed
    or partial timestamp state fails closed to INVALID -- never
    reinterpreted as a fresh six-hour window."""
    autonomy_level = mission.get("autonomy_level")
    if autonomy_level not in _AUTONOMOUS_LEVELS:
        return MissionWindowStatus.NOT_APPLICABLE

    state = MissionState(mission["state"])
    if state in TERMINAL_STATES:
        return MissionWindowStatus.TERMINAL
    if state is MissionState.PAUSED_WINDOW_REACHED:
        return MissionWindowStatus.PAUSED
    if state is MissionState.PAUSED_USER:
        return MissionWindowStatus.PAUSED
    if state is MissionState.BLOCKED:
        return MissionWindowStatus.BLOCKED

    started = mission.get("window_started_at")
    deadline = mission.get("window_deadline_at")
    if started is None and deadline is None:
        return MissionWindowStatus.NOT_STARTED
    if started is None or deadline is None:
        return MissionWindowStatus.INVALID

    try:
        started_dt = _parse_iso(started)
        deadline_dt = _parse_iso(deadline)
    except (ValueError, TypeError):
        return MissionWindowStatus.INVALID
    if deadline_dt <= started_dt:
        return MissionWindowStatus.INVALID

    if now >= deadline_dt:
        return MissionWindowStatus.EXPIRED
    return MissionWindowStatus.ACTIVE


# The single eligibility set for "may admit NEW autonomous work" --
# reused by every atomic admission boundary below so the definition of
# "eligible" cannot drift between call sites (item 3/4).
_WORK_ADMITTING_STATUSES = frozenset({MissionWindowStatus.NOT_APPLICABLE, MissionWindowStatus.ACTIVE})


# ── Starting an autonomous window (items 1-2) ────────────────────────

def _begin_window_locked(
    cur, mission_row: dict, *, now_dt: datetime, policy: MissionWindowPolicy,
    allow_post_expiry_renewal: bool,
) -> dict:
    """Internal, non-public core: assumes the mission row is ALREADY
    locked `FOR UPDATE` by the caller in an open transaction. Writes
    `window_started_at`/`window_deadline_at` (and READY->RUNNING where
    applicable) using the SAME cursor/transaction.

    `allow_post_expiry_renewal` is True ONLY when called from
    `resume_after_window()`, which reaches this AFTER already
    validating (under the SAME lock) that the mission is genuinely
    `PAUSED_WINDOW_REACHED` with a matching checkpoint, and has ALREADY
    written the `PAUSED_WINDOW_REACHED -> RUNNING` transition. There is
    no public parameter that lets an ordinary `start_autonomous_
    window()` caller set this (item 1)."""
    mission_id = mission_row["id"]
    autonomy_level = mission_row.get("autonomy_level")
    if autonomy_level not in _AUTONOMOUS_LEVELS:
        raise MissionWindowError(
            f"mission {mission_id!r} has autonomy_level {autonomy_level!r} -- the "
            f"six-hour autonomous window applies only to L3/L4"
        )

    existing_started = mission_row.get("window_started_at")
    existing_deadline = mission_row.get("window_deadline_at")
    if existing_started is not None and existing_deadline is not None:
        try:
            still_active = _parse_iso(existing_deadline) > now_dt
        except (ValueError, TypeError):
            still_active = False
        if still_active:
            return mission_row  # idempotent, unchanged -- never extended
        if not allow_post_expiry_renewal:
            raise WindowRenewalDeniedError(
                f"mission {mission_id!r}'s prior autonomous window already expired at "
                f"{existing_deadline!r} -- a direct start_autonomous_window() call may not "
                f"renew it; a new window may begin only via the explicit "
                f"PAUSED_WINDOW_REACHED -> resume_after_window() path"
            )

    if not allow_post_expiry_renewal:
        current_state = MissionState(mission_row["state"])
        if current_state not in _WINDOW_STARTABLE_STATES:
            raise MissionWindowError(
                f"mission {mission_id!r} is in state {current_state.value!r}, which does "
                f"not permit beginning an autonomous window (must be READY or RUNNING)"
            )
    else:
        current_state = MissionState(mission_row["state"])

    window_seconds = policy.duration_seconds(autonomy_level)
    now_iso = now_dt.isoformat()
    deadline_iso = (now_dt + timedelta(seconds=window_seconds)).isoformat()
    cur.execute(
        "UPDATE missions SET window_started_at = %s, window_deadline_at = %s, updated_at = %s WHERE id = %s",
        (now_iso, deadline_iso, now_iso, mission_id),
    )

    mission_row = dict(mission_row)
    if current_state is MissionState.READY:
        validated_new = transition(current_state, MissionState.RUNNING, evidence_ref=None)
        cur.execute(
            "UPDATE missions SET state = %s, updated_at = %s WHERE id = %s AND state = %s",
            (validated_new.value, now_iso, mission_id, current_state.value),
        )
        mission_row["state"] = validated_new.value

    mission_row["window_started_at"] = now_iso
    mission_row["window_deadline_at"] = deadline_iso
    mission_row["updated_at"] = now_iso
    return mission_row


def start_autonomous_window(
    conn, *, mission_id: str, now_fn=_default_clock, _policy: MissionWindowPolicy | None = None,
) -> dict:
    """THE authoritative, production-facing window-start entrypoint.

    Server-controlled duration only: duration comes from
    `get_mission_window_policy()` (item 2). `_policy` is an
    underscore-prefixed, INTERNAL/TEST-ONLY seam -- no production call
    site ever passes it, and it accepts a full trusted `MissionWindowPolicy`
    object, never a bare caller-supplied integer.

    Idempotent, not extending: a STILL-ACTIVE existing window is
    returned unchanged. An EXPIRED prior window is NOT renewable by
    this direct call (item 1) -- it raises `WindowRenewalDeniedError`
    and writes nothing; only the explicit `resume_after_window()` path
    may start a genuinely new post-expiry window."""
    policy = _policy or get_mission_window_policy()
    now_dt = now_fn()
    try:
        with conn.cursor() as cur:
            cur.execute("SELECT * FROM missions WHERE id = %s FOR UPDATE", (mission_id,))
            row = cur.fetchone()
            if row is None:
                raise MissionNotFoundError(f"No such mission: {mission_id}")
            mission_row = dict(row)
            _begin_window_locked(
                cur, mission_row, now_dt=now_dt, policy=policy, allow_post_expiry_renewal=False,
            )
    except Exception:
        conn.rollback()
        raise
    conn.commit()
    return get_mission(conn, mission_id)  # type: ignore[return-value]


# ── The discretionary-new-work admission gate (advisory / non-atomic) ─

def require_new_autonomous_work_allowed(
    conn, *, mission_id: str, now_fn=_default_clock,
) -> MissionWindowDecision:
    """An ADVISORY, non-atomic status check -- useful for a caller that
    only needs a yes/no answer and does not itself need to admit new
    durable work atomically with that answer. `ALLOW_NEW_WORK` for
    NOT_APPLICABLE (L0-L2) and ACTIVE only; `DENY_NOT_ELIGIBLE` for
    NOT_STARTED, EXPIRED, PAUSED (user or window), BLOCKED, TERMINAL,
    and INVALID alike (items 3/4: none of these may admit new
    discretionary work).

    NOT used by the AUTHORITATIVE atomic admission boundaries below
    (`request_operation_within_window()`, `start_and_execute_
    operation_within_window()`) -- those perform their OWN eligibility
    read under the SAME mission-row lock they use for the write, to
    close the TOCTOU window a separate read-then-write here would
    otherwise leave open (item 7)."""
    mission = get_mission(conn, mission_id)
    if mission is None:
        raise MissionNotFoundError(f"No such mission: {mission_id}")
    status = evaluate_mission_window(mission, now=now_fn())
    if status in _WORK_ADMITTING_STATUSES:
        return MissionWindowDecision.ALLOW_NEW_WORK
    return MissionWindowDecision.DENY_NOT_ELIGIBLE


def _admit_new_operation_locked(
    cur, *, id: str, idempotency_key: str, kind: str, requested_by: str, mission_id: str,
    target: str = "", parameters: dict | None = None,
) -> tuple[dict, bool]:
    """Transaction-composable: inserts a genuinely NEW REQUESTED
    operation using the SAME `INSERT ... ON CONFLICT (idempotency_key)
    DO NOTHING` shape `orca.mission.operation_store.request_operation()`
    uses, on the caller's ALREADY-OPEN cursor/transaction -- so it can
    be composed with the mission-row lock and window/state eligibility
    check above it in ONE atomic admission boundary (item 7). Does not
    commit. `request_operation()` itself remains completely unmodified
    and is still what every non-autonomous caller uses."""
    from orca.mission.operation_store import OperationConflictError, compute_fingerprint

    fingerprint = compute_fingerprint(kind=kind, target=target, parameters=parameters)
    now = datetime.now(timezone.utc).isoformat()
    cur.execute(
        """
        INSERT INTO operations
            (id, mission_id, idempotency_key, kind, status, requested_at,
             parameters_fingerprint, requested_by)
        VALUES (%s, %s, %s, %s, 'REQUESTED', %s, %s, %s)
        ON CONFLICT (idempotency_key) DO NOTHING
        RETURNING id
        """,
        (id, mission_id, idempotency_key, kind, now, fingerprint, requested_by),
    )
    inserted = cur.fetchone()
    if inserted is not None:
        cur.execute("SELECT * FROM operations WHERE id = %s", (id,))
        return dict(cur.fetchone()), True

    cur.execute("SELECT * FROM operations WHERE idempotency_key = %s", (idempotency_key,))
    existing_row = cur.fetchone()
    assert existing_row is not None
    existing = dict(existing_row)
    if existing["parameters_fingerprint"] != fingerprint:
        raise OperationConflictError(
            f"idempotency_key {idempotency_key!r} was already used with different operation "
            f"parameters (existing fingerprint {existing['parameters_fingerprint']!r}, "
            f"this request's fingerprint {fingerprint!r})."
        )
    return existing, False


def request_operation_within_window(
    conn, *, id: str, idempotency_key: str, kind: str, requested_by: str, mission_id: str,
    target: str = "", parameters: dict | None = None, now_fn=_default_clock,
) -> tuple[dict, bool]:
    """THE atomic autonomous-admission boundary for genuinely NEW
    discretionary work (item 7). Locks the mission row `FOR UPDATE`
    FIRST, and performs the ENTIRE decision -- idempotency-key lookup,
    mission-bound retry-bypass check (item 10), window/state
    eligibility, and the REQUESTED insert itself -- inside that SAME
    transaction/lock, closing the gap a separate read-then-write would
    otherwise leave for a concurrent `enforce_window_expiry()` or user
    pause to race into (item 8).

    Idempotency-key retry-bypass is MISSION-BOUND (item 10): an
    existing operation is treated as "already-admitted work for THIS
    request" ONLY if it belongs to the SAME `mission_id`. A key that
    belongs to a DIFFERENT mission confers no eligibility here -- it is
    a genuine conflict, not a legitimate retry, and this mission's OWN
    window/state governs regardless of the foreign mission's state."""
    from orca.mission.operation_store import OperationConflictError

    try:
        with conn.cursor() as cur:
            cur.execute("SELECT * FROM missions WHERE id = %s FOR UPDATE", (mission_id,))
            mrow = cur.fetchone()
            if mrow is None:
                raise MissionNotFoundError(f"No such mission: {mission_id}")
            mission_row = dict(mrow)

            cur.execute("SELECT * FROM operations WHERE idempotency_key = %s", (idempotency_key,))
            existing_row = cur.fetchone()
            existing = dict(existing_row) if existing_row else None

            if existing is not None and existing["mission_id"] == mission_id:
                # Same-mission retry/reconciliation of already-admitted
                # work -- never blocked by window expiry.
                conn.commit()
                return existing, False

            status = evaluate_mission_window(mission_row, now=now_fn())
            if status not in _WORK_ADMITTING_STATUSES:
                raise MissionWindowExpiredError(
                    f"mission {mission_id!r} does not admit new discretionary work "
                    f"(window status={status.value}); idempotency_key={idempotency_key!r} "
                    f"was never previously requested for THIS mission"
                )

            if existing is not None:
                # Eligible mission, but the key belongs to a DIFFERENT
                # mission -- a genuine conflict, not this mission's own
                # retry (item 10).
                raise OperationConflictError(
                    f"idempotency_key {idempotency_key!r} already belongs to mission "
                    f"{existing['mission_id']!r}, not {mission_id!r}"
                )

            operation, created = _admit_new_operation_locked(
                cur, id=id, idempotency_key=idempotency_key, kind=kind, requested_by=requested_by,
                mission_id=mission_id, target=target, parameters=parameters,
            )
    except Exception:
        conn.rollback()
        raise
    conn.commit()
    return operation, created


def start_and_execute_operation_within_window(
    conn, *, operation_id: str, mission_id: str, executor, now_fn=_default_clock,
) -> dict:
    """THE atomic autonomous-mission wrapper around `orca.mission.
    operation_store.start_and_execute_operation()` (items 5/6/9). An
    AUTHORIZED operation may transition to STARTED (and have its
    executor invoked) ONLY while the mission's window admits new work
    AT THE SAME SERIALIZATION POINT `enforce_window_expiry()` uses --
    both lock the SAME `missions` row `FOR UPDATE`, so whichever
    transaction commits first durably wins.

    If the window does NOT admit new work, the operation is left
    EXACTLY as it was (AUTHORIZED, never STARTED) and the executor is
    NEVER invoked -- `operations.status` is not touched at all in the
    deny path, so `start_and_execute_operation()`'s own generic
    semantics (used by every non-autonomous caller) are completely
    unmodified.

    An operation that is already STARTED/SUCCEEDED/FAILED/CANCELLED at
    call time is reconciliation-only (item 6): it is never re-gated by
    the window, and its executor is never re-invoked -- exactly as
    `start_and_execute_operation()` itself already guarantees."""
    from orca.mission.operation_store import (
        OperationNotFoundError,
        OperationStateError,
        _NO_EXECUTOR_RECALL_STATES,
        _execute_and_settle,
        _write_operation_transition,
        get_operation,
    )

    already_settled = False
    try:
        with conn.cursor() as cur:
            cur.execute("SELECT * FROM missions WHERE id = %s FOR UPDATE", (mission_id,))
            mrow = cur.fetchone()
            if mrow is None:
                raise MissionNotFoundError(f"No such mission: {mission_id}")
            mission_row = dict(mrow)

            cur.execute("SELECT status, mission_id FROM operations WHERE id = %s", (operation_id,))
            orow = cur.fetchone()
            if orow is None:
                raise OperationNotFoundError(f"No such operation: {operation_id}")
            if orow["mission_id"] != mission_id:
                raise OperationStateError(
                    f"operation {operation_id!r} belongs to mission {orow['mission_id']!r}, "
                    f"not {mission_id!r}"
                )
            op_status = orow["status"]

            if op_status in _NO_EXECUTOR_RECALL_STATES:
                already_settled = True
            else:
                if op_status != "AUTHORIZED":
                    raise OperationStateError(f"cannot start operation {operation_id} in status {op_status}")
                status = evaluate_mission_window(mission_row, now=now_fn())
                if status not in _WORK_ADMITTING_STATUSES:
                    raise MissionWindowExpiredError(
                        f"mission {mission_id!r}'s autonomous window does not admit starting "
                        f"operation {operation_id!r} (window status={status.value}); it remains "
                        f"AUTHORIZED and the executor was never invoked"
                    )
                # Written under the SAME mission-row lock enforce_window_
                # expiry() also takes -- whichever transaction commits
                # first durably wins (item 9).
                _write_operation_transition(conn, operation_id, "STARTED")
    except Exception:
        conn.rollback()
        raise
    conn.commit()

    if already_settled:
        return get_operation(conn, operation_id)  # type: ignore[return-value]
    return _execute_and_settle(conn, operation_id, executor)


# ── Atomic expiry: checkpoint + pause (items 11, 13) ─────────────────

def _sanitize_checkpoint_value(value):
    """Recursively redacts every string reachable from `value` via
    `orca.mission.production_proof.redact_secrets()`, applied BEFORE
    the checkpoint row is ever inserted (item 11: raw secrets must
    never enter the durable checkpoint, not merely be redacted later
    at Relay-display time). Mirrors the same walk `orca.mission.
    relay_store._sanitize()` already uses for Relay snapshots -- reuses
    the same underlying `redact_secrets()` primitive rather than
    inventing a second sanitizer."""
    if isinstance(value, str):
        return redact_secrets(value) or ""
    if isinstance(value, dict):
        return {k: _sanitize_checkpoint_value(v) for k, v in value.items()}
    if isinstance(value, tuple):
        return tuple(_sanitize_checkpoint_value(v) for v in value)
    if isinstance(value, list):
        return [_sanitize_checkpoint_value(v) for v in value]
    return value


def _sanitize_checkpoint_kwargs(checkpoint_kwargs: dict) -> dict:
    return {k: _sanitize_checkpoint_value(v) for k, v in checkpoint_kwargs.items()}


def enforce_window_expiry(
    conn, *, mission_id: str, now_fn=_default_clock, **checkpoint_kwargs,
) -> WindowEnforcementResult:
    """The atomic window-expiry boundary. Holds ONE mission-row `FOR
    UPDATE` lock across the ENTIRE decision (state re-read, deadline
    re-read, eligibility) AND the write (item 13) -- the deadline/state
    used to decide EXPIRED is re-read HERE, under the lock, not from an
    earlier unlocked snapshot. `checkpoint_and_pause()` below is called
    WITHOUT an intervening commit, so its own internal row (re-)lock is
    an instant re-acquisition of the lock THIS transaction already
    holds (Postgres row locks are held per-TRANSACTION, not per-
    cursor) -- not a second, separately-racing lock. `checkpoint_and_
    pause()` itself is reused completely unmodified.

    `**checkpoint_kwargs` are the real, caller-supplied mission state,
    sanitized via `_sanitize_checkpoint_kwargs()` BEFORE being passed
    through (item 11) -- nothing is fabricated here to make fields
    look populated, and no raw secret value is ever written to the
    `checkpoints` table.

    Convergence for repeated/concurrent enforcement (spec sections
    23-24) still comes from `checkpoint_and_pause()`'s own
    `_write_transition()` row lock plus the canonical state machine's
    transition table: PAUSED_WINDOW_REACHED has no outgoing transition
    back to itself, so a second (sequential OR concurrent-losing)
    attempt to re-pause an already-window-paused mission raises
    `MissionStateError`, caught here and reported as `ALREADY_PAUSED`
    with the REAL existing checkpoint."""
    sanitized_kwargs = _sanitize_checkpoint_kwargs(checkpoint_kwargs)

    try:
        with conn.cursor() as cur:
            cur.execute("SELECT * FROM missions WHERE id = %s FOR UPDATE", (mission_id,))
            row = cur.fetchone()
            if row is None:
                raise MissionNotFoundError(f"No such mission: {mission_id}")
            mission_row = dict(row)
            current_state = MissionState(mission_row["state"])

            early_outcome: WindowEnforcementOutcome | None = None
            if current_state is MissionState.PAUSED_WINDOW_REACHED:
                early_outcome = WindowEnforcementOutcome.ALREADY_PAUSED
            elif current_state in TERMINAL_STATES:
                early_outcome = WindowEnforcementOutcome.TERMINAL
            elif current_state is MissionState.PAUSED_USER:
                # A user-requested pause is a stronger, distinct
                # stopping condition -- expiry enforcement never
                # overwrites it.
                early_outcome = WindowEnforcementOutcome.NO_ACTION
            elif current_state is MissionState.BLOCKED:
                # BLOCKED is never bypassed by window expiry -- a
                # blocked mission is already prevented from doing new
                # autonomous work by the stronger blocking condition.
                early_outcome = WindowEnforcementOutcome.NO_ACTION
            else:
                status = evaluate_mission_window(mission_row, now=now_fn())
                if status is not MissionWindowStatus.EXPIRED:
                    early_outcome = WindowEnforcementOutcome.NOT_YET_EXPIRED
                elif current_state not in _ACTIVE_WINDOW_STATES:
                    early_outcome = WindowEnforcementOutcome.NO_ACTION

            proceed = early_outcome is None
    except Exception:
        conn.rollback()
        raise

    if not proceed:
        conn.commit()  # releases the lock; nothing was written
        if early_outcome is WindowEnforcementOutcome.ALREADY_PAUSED:
            return WindowEnforcementResult(early_outcome, mission_row, get_latest_checkpoint(conn, mission_id))
        return WindowEnforcementResult(early_outcome, mission_row, None)  # type: ignore[arg-type]

    # Still holding the SAME open transaction/lock acquired above.
    checkpoint_id = f"ckpt_window_{mission_id}_{uuid.uuid4().hex[:12]}"
    try:
        updated_mission, checkpoint = checkpoint_and_pause(
            conn, mission_id, pause_state=MissionState.PAUSED_WINDOW_REACHED,
            checkpoint_id=checkpoint_id, **sanitized_kwargs,
        )
    except MissionStateError:
        # A genuine race was lost -- re-read and report truthfully
        # rather than erroring the caller. checkpoint_and_pause() has
        # already rolled back its own attempted write.
        current = get_mission(conn, mission_id)
        assert current is not None
        current_state2 = MissionState(current["state"])
        if current_state2 is MissionState.PAUSED_WINDOW_REACHED:
            return WindowEnforcementResult(
                WindowEnforcementOutcome.ALREADY_PAUSED, current, get_latest_checkpoint(conn, mission_id),
            )
        if current_state2 in TERMINAL_STATES:
            return WindowEnforcementResult(WindowEnforcementOutcome.TERMINAL, current, None)
        return WindowEnforcementResult(WindowEnforcementOutcome.NO_ACTION, current, None)

    return WindowEnforcementResult(WindowEnforcementOutcome.PAUSED, updated_mission, checkpoint)


# ── Resuming after PAUSED_WINDOW_REACHED (items 12, 17, 27) ─────────

def resume_after_window(
    conn, *, mission_id: str, expected_checkpoint_id: str, now_fn=_default_clock,
    _policy: MissionWindowPolicy | None = None,
) -> tuple[dict, Checkpoint]:
    """The governed resume path. Requires an EXPLICIT caller action
    (never automatic). Holds ONE mission-row lock across mission-state
    validation, checkpoint-match validation, the `PAUSED_WINDOW_REACHED
    -> RUNNING` transition write, AND the fresh window-start write
    (item 12) -- on ANY failure, the whole transaction rolls back: the
    mission remains `PAUSED_WINDOW_REACHED`, the old checkpoint remains
    authoritative, and there is no partial `RUNNING`-without-a-window
    state.

    Confirms the mission is genuinely `PAUSED_WINDOW_REACHED` and that
    `expected_checkpoint_id` matches the mission's REAL latest
    checkpoint -- a stale or wrong checkpoint reference is rejected.
    Starts a genuinely NEW, server-controlled window via `_begin_
    window_locked(..., allow_post_expiry_renewal=True)` -- the ONLY
    place that flag is ever set to True, and only after the state/
    checkpoint validation above has already succeeded under this SAME
    lock. This does not reset any other governance dimension -- no
    authority is minted, no approval is granted, no failure/blocker
    history is cleared, nothing about the operation ledger is touched;
    only the mission's own state and window timestamps change."""
    policy = _policy or get_mission_window_policy()
    now_dt = now_fn()

    try:
        with conn.cursor() as cur:
            cur.execute("SELECT * FROM missions WHERE id = %s FOR UPDATE", (mission_id,))
            row = cur.fetchone()
            if row is None:
                raise MissionNotFoundError(f"No such mission: {mission_id}")
            mission_row = dict(row)
            current_state = MissionState(mission_row["state"])
            if current_state is not MissionState.PAUSED_WINDOW_REACHED:
                raise MissionWindowError(
                    f"mission {mission_id!r} is in state {current_state.value!r}, not "
                    f"PAUSED_WINDOW_REACHED -- cannot resume_after_window()"
                )

            cur.execute(
                "SELECT * FROM checkpoints WHERE mission_id = %s ORDER BY created_at DESC LIMIT 1",
                (mission_id,),
            )
            ckpt_row = cur.fetchone()
            checkpoint = Checkpoint.from_row(dict(ckpt_row)) if ckpt_row else None
            if checkpoint is None or checkpoint.id != expected_checkpoint_id:
                raise MissionWindowError(
                    f"expected checkpoint {expected_checkpoint_id!r} does not match the "
                    f"mission's actual latest checkpoint "
                    f"({checkpoint.id if checkpoint else None!r}) -- refusing a stale/"
                    f"wrong-checkpoint resume"
                )

            validated_new = transition(current_state, MissionState.RUNNING, evidence_ref=None)
            now_iso = now_dt.isoformat()
            cur.execute(
                "UPDATE missions SET state = %s, updated_at = %s WHERE id = %s AND state = %s",
                (validated_new.value, now_iso, mission_id, current_state.value),
            )
            if cur.rowcount != 1:
                raise MissionStoreError(
                    f"Mission {mission_id} state changed unexpectedly during resume_after_window() "
                    f"(expected {current_state.value}); the row lock was not held for the full "
                    f"transaction."
                )
            mission_row["state"] = validated_new.value
            mission_row["updated_at"] = now_iso

            _begin_window_locked(
                cur, mission_row, now_dt=now_dt, policy=policy, allow_post_expiry_renewal=True,
            )
    except Exception:
        conn.rollback()
        raise
    conn.commit()
    new_mission = get_mission(conn, mission_id)
    assert new_mission is not None
    return new_mission, checkpoint
