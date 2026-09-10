"""
Phase 15.14 -- Six-Hour Mission Governance.

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
    `enforce_window_expiry()` below calls it unmodified -- the
    convergence guarantee for repeated/concurrent expiry enforcement
    (spec sections 23-24) comes entirely from that function's own
    `_write_transition()` row lock and the canonical state machine's
    transition table, not from any new locking or ID scheme here.
  * `orca.mission.mission_store.resume_mission()` (Phase 15.4) remains
    the only code path that ever writes a PAUSED_* -> RUNNING
    transition. `resume_after_window()` calls it, then starts a NEW
    window -- it never fabricates a resumed state directly.
  * `orca.mission.operation_store.request_operation()` (Phase 15.5) is
    completely unmodified. `request_operation_within_window()` is a
    thin, ADDITIVE wrapper: it gates only genuinely NEW idempotency
    keys, and lets an existing key's retry/reconciliation through
    unconditionally (spec section 11/12: settling already-admitted
    work is never blocked by window expiry).
  * Relay-visible secret redaction reuses
    `orca.mission.relay_store._sanitize()` (via `build_relay_snapshot()`/
    `reconnect_to_mission()`) unmodified -- no new sanitizer is written.

One minimal, explicitly-authorized state-machine adjustment was made
in `orca.mission.state_machine`: `COURT_REVIEW -> PAUSED_WINDOW_REACHED`
was added (spec section 7 item 7) so a mission genuinely in Court
Review when the window expires can still be safely checkpointed and
paused, rather than being stuck unable to honor its own deadline.
"""
from __future__ import annotations

import uuid
from dataclasses import dataclass
from datetime import datetime, timedelta, timezone
from enum import Enum

from orca.mission.mission_store import (
    Checkpoint,
    MissionNotFoundError,
    checkpoint_and_pause,
    get_latest_checkpoint,
    get_mission,
    resume_mission,
)
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

# States a window may legitimately BEGIN from: READY (the mission's
# first ever autonomous start) or RUNNING (a window being established
# on a mission that is already running -- e.g. the first real call to
# start_autonomous_window() for a pre-existing L3/L4 mission).
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
    """Raised by `request_operation_within_window()` when a genuinely
    NEW idempotency key is requested after the mission's autonomous
    window has expired."""


# ── Typed window status/decision model (spec section 1) ─────────────

class MissionWindowStatus(Enum):
    NOT_STARTED = "NOT_STARTED"
    ACTIVE = "ACTIVE"
    EXPIRED = "EXPIRED"
    PAUSED = "PAUSED"
    TERMINAL = "TERMINAL"
    NOT_APPLICABLE = "NOT_APPLICABLE"
    INVALID = "INVALID"


class MissionWindowDecision(Enum):
    ALLOW_NEW_WORK = "ALLOW_NEW_WORK"
    DENY_WINDOW_EXPIRED = "DENY_WINDOW_EXPIRED"


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


# ── Pure window-status evaluation (spec section 6) ───────────────────

def evaluate_mission_window(mission: dict, *, now: datetime) -> MissionWindowStatus:
    """Derives window status ENTIRELY from durable mission state --
    never from an in-process timer. Order matters: autonomy-level
    applicability is checked first (L0-L2 are NOT_APPLICABLE
    regardless of any timestamps that happen to be present), then
    terminal/paused mission state (a terminal or already-window-paused
    mission reports that fact regardless of remaining window time),
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


# ── Starting an autonomous window (spec sections 4-5) ────────────────

def start_autonomous_window(
    conn, *, mission_id: str, now_fn=_default_clock,
    window_seconds: int = DEFAULT_AUTONOMOUS_WINDOW_SECONDS,
) -> dict:
    """THE authoritative window-start entrypoint. Server-controlled
    duration only -- `window_seconds` is a trusted SERVER policy
    parameter (defaulting to `DEFAULT_AUTONOMOUS_WINDOW_SECONDS`),
    never accepted from a client/user request in any real call site;
    a caller cannot supply `started_at`/`deadline_at` directly at all.

    Locks the mission row `FOR UPDATE`, verifies autonomy level is
    L3/L4, verifies the mission is in a state that may legitimately
    begin a window, and -- ONLY if no window has been started yet --
    sets `window_started_at`/`window_deadline_at` from the server
    clock and transitions READY -> RUNNING where applicable, all in
    one transaction with one commit.

    Idempotent, not extending: if the mission ALREADY has a window
    (`window_started_at`/`window_deadline_at` both already set), this
    returns the EXISTING, UNCHANGED window -- a second `start()` call
    never resets the deadline to `now + window_seconds` again (spec
    section 4 explicitly allows either "return unchanged" or "reject";
    this module chooses the idempotent-return form)."""
    try:
        with conn.cursor() as cur:
            cur.execute("SELECT * FROM missions WHERE id = %s FOR UPDATE", (mission_id,))
            row = cur.fetchone()
            if row is None:
                raise MissionNotFoundError(f"No such mission: {mission_id}")
            mission_row = dict(row)

            autonomy_level = mission_row.get("autonomy_level")
            if autonomy_level not in _AUTONOMOUS_LEVELS:
                raise MissionWindowError(
                    f"mission {mission_id!r} has autonomy_level {autonomy_level!r} -- the "
                    f"six-hour autonomous window applies only to L3/L4"
                )

            if mission_row.get("window_started_at") is not None and mission_row.get("window_deadline_at") is not None:
                conn.commit()
                return mission_row

            current_state = MissionState(mission_row["state"])
            if current_state not in _WINDOW_STARTABLE_STATES:
                raise MissionWindowError(
                    f"mission {mission_id!r} is in state {current_state.value!r}, which does "
                    f"not permit beginning an autonomous window (must be READY or RUNNING)"
                )

            now_dt = now_fn()
            now_iso = now_dt.isoformat()
            deadline_iso = (now_dt + timedelta(seconds=window_seconds)).isoformat()
            cur.execute(
                "UPDATE missions SET window_started_at = %s, window_deadline_at = %s, updated_at = %s WHERE id = %s",
                (now_iso, deadline_iso, now_iso, mission_id),
            )

            if current_state is MissionState.READY:
                validated_new = transition(current_state, MissionState.RUNNING, evidence_ref=None)
                cur.execute(
                    "UPDATE missions SET state = %s, updated_at = %s WHERE id = %s AND state = %s",
                    (validated_new.value, now_iso, mission_id, current_state.value),
                )
    except Exception:
        conn.rollback()
        raise
    conn.commit()
    return get_mission(conn, mission_id)  # type: ignore[return-value]


# ── The discretionary-new-work admission gate (spec section 9) ───────

def require_new_autonomous_work_allowed(
    conn, *, mission_id: str, now_fn=_default_clock,
) -> MissionWindowDecision:
    """THE single authoritative gate for whether NEW discretionary
    autonomous work may begin. `ALLOW_NEW_WORK` for NOT_APPLICABLE
    (L0-L2 -- the window imposes no restriction on them at all),
    ACTIVE, and NOT_STARTED (no window opened yet -- this gate's job
    is purely "has the window been exceeded", not "has authority been
    granted"; see WINDOW / AUTHORITY SEPARATION). `DENY_WINDOW_EXPIRED`
    for EXPIRED, PAUSED, TERMINAL, and INVALID (fail closed) alike --
    none of those states may admit new discretionary work."""
    mission = get_mission(conn, mission_id)
    if mission is None:
        raise MissionNotFoundError(f"No such mission: {mission_id}")
    status = evaluate_mission_window(mission, now=now_fn())
    if status in (MissionWindowStatus.NOT_APPLICABLE, MissionWindowStatus.ACTIVE, MissionWindowStatus.NOT_STARTED):
        return MissionWindowDecision.ALLOW_NEW_WORK
    return MissionWindowDecision.DENY_WINDOW_EXPIRED


def request_operation_within_window(
    conn, *, id: str, idempotency_key: str, kind: str, requested_by: str, mission_id: str,
    target: str = "", parameters: dict | None = None, now_fn=_default_clock,
) -> tuple[dict, bool]:
    """The ONLY currently-existing production-facing "start new
    discretionary work" entrypoint in this codebase is
    `orca.mission.operation_store.request_operation()` -- there is no
    mission-step-creation API, no model/tool-task-start API, and no
    deployment-start API independent of it (verified by inspection;
    none is fabricated here). This wrapper gates EXACTLY that
    entrypoint, and ONLY for a genuinely NEW idempotency key: if the
    key already exists (a retry/reconciliation of already-admitted
    work), the window gate is bypassed entirely and the call proceeds
    -- settling already-started atomic work is never blocked by window
    expiry (spec sections 11-13). `request_operation()` itself is
    imported and called completely unmodified."""
    from orca.mission.operation_store import get_operation_by_idempotency_key, request_operation

    existing = get_operation_by_idempotency_key(conn, idempotency_key)
    if existing is None:
        decision = require_new_autonomous_work_allowed(conn, mission_id=mission_id, now_fn=now_fn)
        if decision is MissionWindowDecision.DENY_WINDOW_EXPIRED:
            raise MissionWindowExpiredError(
                f"mission {mission_id!r}'s autonomous window does not permit new discretionary "
                f"work -- idempotency_key={idempotency_key!r} was never previously requested"
            )
    return request_operation(
        conn, id=id, idempotency_key=idempotency_key, kind=kind, requested_by=requested_by,
        mission_id=mission_id, target=target, parameters=parameters,
    )


# ── Atomic expiry: checkpoint + pause (spec sections 14-16, 23-26) ──

def enforce_window_expiry(
    conn, *, mission_id: str, now_fn=_default_clock, **checkpoint_kwargs,
) -> WindowEnforcementResult:
    """The atomic window-expiry boundary. Reuses
    `mission_store.checkpoint_and_pause()` UNMODIFIED for the actual
    atomic transition-plus-checkpoint write -- this function's own job
    is purely to decide WHETHER that call should be attempted, and to
    interpret its outcome (including a lost race) truthfully.

    `**checkpoint_kwargs` are passed straight through to
    `checkpoint_and_pause()` -- exactly the real, caller-supplied
    mission state (repository, branch, revisions, requirement/test/
    verification states, evidence, blockers, etc.); nothing is
    fabricated here to make fields look populated.

    Convergence for repeated/concurrent enforcement (spec sections
    23-24) comes entirely from `checkpoint_and_pause()`'s own
    `_write_transition()` row lock plus the canonical state machine's
    transition table: PAUSED_WINDOW_REACHED has no outgoing transition
    back to itself, so a second (sequential OR concurrent-losing)
    attempt to re-pause an already-window-paused mission raises
    `MissionStateError`, caught here and reported as `ALREADY_PAUSED`
    with the REAL existing checkpoint -- never a second checkpoint, never
    a corrupted state. The same mechanism protects PAUSED_USER and every
    terminal state from being overwritten (neither has
    PAUSED_WINDOW_REACHED in its own outgoing transition set)."""
    mission = get_mission(conn, mission_id)
    if mission is None:
        raise MissionNotFoundError(f"No such mission: {mission_id}")

    current_state = MissionState(mission["state"])

    if current_state is MissionState.PAUSED_WINDOW_REACHED:
        return WindowEnforcementResult(
            WindowEnforcementOutcome.ALREADY_PAUSED, mission, get_latest_checkpoint(conn, mission_id),
        )
    if current_state in TERMINAL_STATES:
        return WindowEnforcementResult(WindowEnforcementOutcome.TERMINAL, mission, None)
    if current_state is MissionState.PAUSED_USER:
        # A user-requested pause is a stronger, distinct stopping
        # condition (spec section 8) -- expiry enforcement never
        # overwrites it.
        return WindowEnforcementResult(WindowEnforcementOutcome.NO_ACTION, mission, None)
    if current_state is MissionState.BLOCKED:
        # BLOCKED is never bypassed by window expiry (spec section 26)
        # -- a blocked mission is already prevented from doing new
        # autonomous work by the stronger blocking condition.
        return WindowEnforcementResult(WindowEnforcementOutcome.NO_ACTION, mission, None)

    status = evaluate_mission_window(mission, now=now_fn())
    if status is not MissionWindowStatus.EXPIRED:
        return WindowEnforcementResult(WindowEnforcementOutcome.NOT_YET_EXPIRED, mission, None)

    if current_state not in _ACTIVE_WINDOW_STATES:
        return WindowEnforcementResult(WindowEnforcementOutcome.NO_ACTION, mission, None)

    checkpoint_id = f"ckpt_window_{mission_id}_{uuid.uuid4().hex[:12]}"
    try:
        updated_mission, checkpoint = checkpoint_and_pause(
            conn, mission_id, pause_state=MissionState.PAUSED_WINDOW_REACHED,
            checkpoint_id=checkpoint_id, **checkpoint_kwargs,
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


# ── Resuming after PAUSED_WINDOW_REACHED (spec sections 17, 27) ─────

def resume_after_window(
    conn, *, mission_id: str, expected_checkpoint_id: str, now_fn=_default_clock,
    window_seconds: int = DEFAULT_AUTONOMOUS_WINDOW_SECONDS,
) -> tuple[dict, Checkpoint]:
    """The governed resume path. Requires an EXPLICIT caller action
    (never automatic -- spec section 17: "Do NOT automatically
    resume"). Confirms the mission is genuinely PAUSED_WINDOW_REACHED
    and that `expected_checkpoint_id` matches the mission's REAL
    latest checkpoint -- a stale or wrong checkpoint reference is
    rejected, never silently accepted. Resumes via the existing,
    unmodified `resume_mission()` (PAUSED_WINDOW_REACHED -> RUNNING,
    the only code path that ever writes that transition), then starts
    a genuinely NEW, server-controlled window via
    `start_autonomous_window()` -- `new_started_at` is the resume-time
    server clock, never the old deadline, never extended from the old
    window. This does not reset any other governance dimension (spec
    section 27) -- no authority is minted, no approval is granted, no
    failure/blocker history is cleared, nothing about the operation
    ledger is touched; only the mission's own state and window
    timestamps change, via the existing primitives."""
    mission = get_mission(conn, mission_id)
    if mission is None:
        raise MissionNotFoundError(f"No such mission: {mission_id}")
    if mission["state"] != MissionState.PAUSED_WINDOW_REACHED.value:
        raise MissionWindowError(
            f"mission {mission_id!r} is in state {mission['state']!r}, not "
            f"PAUSED_WINDOW_REACHED -- cannot resume_after_window()"
        )

    checkpoint = get_latest_checkpoint(conn, mission_id)
    if checkpoint is None or checkpoint.id != expected_checkpoint_id:
        raise MissionWindowError(
            f"expected checkpoint {expected_checkpoint_id!r} does not match the mission's "
            f"actual latest checkpoint ({checkpoint.id if checkpoint else None!r}) -- "
            f"refusing a stale/wrong-checkpoint resume"
        )

    resume_mission(conn, mission_id, evidence_ref=None)
    new_window_mission = start_autonomous_window(
        conn, mission_id=mission_id, now_fn=now_fn, window_seconds=window_seconds,
    )
    return new_window_mission, checkpoint
