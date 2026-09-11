"""
Phase 15.14 -- LIVE_NEON_TEMP_BRANCH: Six-Hour Mission Governance
qualification against real Postgres.

Covers items A-V of the Phase 15.14 live-Neon qualification matrix:
default window duration, exact boundary behavior, process-loss
durability, waiting-state counting, Relay-reconnect non-reset,
discretionary-work gating before/after expiry, window/authority
separation, already-started atomic work crossing the deadline,
STARTED/unknown truthfulness, atomic expiry checkpoint+pause,
full-state checkpoint preservation, exact resume with a new window,
already-SUCCEEDED operation non-rerun (REQ-CKPT-RESTORE-002's exact
acceptance proof), idempotent/concurrent expiry enforcement, the
user-pause-vs-expiry and terminal-vs-expiry races, BLOCKED precedence,
and secret-safe checkpoint content.

Skipped when ORNEUR_MISSION_DATABASE_URL(_DIRECT) are unset, matching
every other Phase 15 live-Neon test file.
"""
from __future__ import annotations

import os
import threading
import time
import uuid
from datetime import datetime, timedelta, timezone

import pytest

from orca.mission.db import apply_schema, get_conn
from orca.mission.executor import RecordingTestExecutor
from orca.mission.mission_store import (
    MissionStateError,
    create_mission,
    get_checkpoint,
    get_latest_checkpoint,
    get_mission,
    transition_mission,
)
from orca.mission.mission_window import (
    DEFAULT_AUTONOMOUS_WINDOW_SECONDS,
    MissionWindowDecision,
    MissionWindowError,
    MissionWindowExpiredError,
    MissionWindowPolicy,
    MissionWindowStatus,
    WindowEnforcementOutcome,
    WindowRenewalDeniedError,
    enforce_window_expiry,
    evaluate_mission_window,
    request_operation_within_window,
    require_new_autonomous_work_allowed,
    resume_after_window,
    start_and_execute_operation_within_window,
    start_autonomous_window,
)
from orca.mission.operation_store import (
    OperationConflictError,
    OperationStateError,
    authorize_operation,
    get_operation,
    request_operation,
    start_and_execute_operation,
)
from orca.mission.relay_reconnect import RelayOperationTruth, classify_operation_truth, reconnect_to_mission
from orca.mission.relay_security import create_relay_session
from orca.mission.relay_store import DeviceTrustLevel, RelayMode, register_device
from orca.mission.state_machine import MissionState

pytestmark = pytest.mark.skipif(
    not (os.environ.get("ORNEUR_MISSION_DATABASE_URL") and os.environ.get("ORNEUR_MISSION_DATABASE_URL_DIRECT")),
    reason="LIVE_NEON_TEMP_BRANCH: requires ORNEUR_MISSION_DATABASE_URL(_DIRECT) pointing at a disposable Neon branch",
)


@pytest.fixture(scope="module", autouse=True)
def _ensure_schema():
    conn = get_conn(direct=True)
    try:
        apply_schema(conn)
        conn.commit()
    finally:
        conn.close()


def _fresh_connection():
    return get_conn(direct=False)


def _uid() -> str:
    return f"user_{uuid.uuid4().hex[:12]}"


def _mid() -> str:
    return f"mis_{uuid.uuid4().hex[:12]}"


def _seed_l3_mission(conn, owner_user_id: str, *, state: MissionState = MissionState.READY) -> str:
    mission_id = _mid()
    create_mission(
        conn, id=mission_id, repository="org/window-qual", branch="main", mode="BUILD",
        autonomy_level="L3", owner_user_id=owner_user_id, current_revision="rev1", workspace_id="ws_window",
    )
    if state is MissionState.PLANNING:
        transition_mission(conn, mission_id, MissionState.PLANNING)
    elif state is MissionState.READY:
        transition_mission(conn, mission_id, MissionState.PLANNING)
        transition_mission(conn, mission_id, MissionState.READY)
    return mission_id


def _seed_session(conn, owner_user_id: str, mission_id: str, *, now_fn=None):
    """`now_fn`, when given, seeds the DEVICE and SESSION using THAT
    same simulated clock -- so a session "created" at a later
    simulated instant (e.g. a device reconnecting hours into a mission
    window) is itself still fresh/valid AT that instant, rather than
    colliding with its own short-lived PUBLIC_DEVICE TTL/inactivity
    policy (a completely separate concept from the mission window)."""
    kwargs = {"now_fn": now_fn} if now_fn is not None else {}
    device = register_device(conn, authenticated_user_id=owner_user_id, trust_level=DeviceTrustLevel.PUBLIC, name="dev", **kwargs)
    session = create_relay_session(conn, device_id=device.id, mission_id=mission_id, authenticated_user_id=owner_user_id, mode=RelayMode.PUBLIC_DEVICE, **kwargs)
    return device, session


def _wait_until_blocked_on_lock(inspect_conn, *, timeout=8.0) -> bool:
    deadline = time.monotonic() + timeout
    while time.monotonic() < deadline:
        with inspect_conn.cursor() as cur:
            cur.execute("SELECT count(*) AS c FROM pg_stat_activity WHERE wait_event_type = 'Lock'")
            row = cur.fetchone()
        inspect_conn.commit()
        if row["c"] > 0:
            return True
        time.sleep(0.1)
    return False


_CKPT_KWARGS = dict(
    repository="org/window-qual", branch="main", base_revision="rev0", current_revision="rev1",
    diff_ref="diff://abc123", requirement_states={"REQ-X-001": "IMPLEMENTED"},
    test_states={"UNIT_TEST": "PASS"}, verification_states={"UNIT_TEST": "PASS"},
    evidence_refs=("docs/evidence.md#x",), pending_approvals=(), active_blocker=None,
    resource_budget_state={"tokens_used": 1000}, tool_outcomes=({"tool": "pytest", "outcome": "pass"},),
    environment_identity="runner-ci-1", current_step_id="step_2",
    completed_step_ids=("step_0", "step_1"), remaining_step_ids=("step_2", "step_3"),
)


# ── A. Default window duration ────────────────────────────────────────

def test_default_window_start_is_exactly_six_hours():
    owner = _uid()
    conn = _fresh_connection()
    try:
        mission_id = _seed_l3_mission(conn, owner)
        base_now = datetime.now(timezone.utc)
        mission = start_autonomous_window(conn, mission_id=mission_id, now_fn=lambda: base_now)
        started = datetime.fromisoformat(mission["window_started_at"])
        deadline = datetime.fromisoformat(mission["window_deadline_at"])
        assert (deadline - started).total_seconds() == DEFAULT_AUTONOMOUS_WINDOW_SECONDS
        assert mission["state"] == MissionState.RUNNING.value
    finally:
        conn.close()


def test_repeated_start_does_not_extend_the_deadline():
    owner = _uid()
    conn = _fresh_connection()
    try:
        mission_id = _seed_l3_mission(conn, owner)
        base_now = datetime.now(timezone.utc)
        first = start_autonomous_window(conn, mission_id=mission_id, now_fn=lambda: base_now)
        later = base_now + timedelta(hours=2)
        second = start_autonomous_window(conn, mission_id=mission_id, now_fn=lambda: later)
        assert second["window_started_at"] == first["window_started_at"]
        assert second["window_deadline_at"] == first["window_deadline_at"]
    finally:
        conn.close()


def test_l0_l2_mission_cannot_start_an_autonomous_window():
    from orca.mission.mission_window import MissionWindowError
    owner = _uid()
    conn = _fresh_connection()
    try:
        mission_id = _mid()
        create_mission(
            conn, id=mission_id, repository="org/window-qual", branch="main", mode="BUILD",
            autonomy_level="L1", owner_user_id=owner, current_revision="rev1", workspace_id="ws_window",
        )
        with pytest.raises(MissionWindowError):
            start_autonomous_window(conn, mission_id=mission_id)
    finally:
        conn.close()


# ── C. Durable start / process-loss recovery ──────────────────────────

def test_window_deadline_survives_fresh_connection():
    owner = _uid()
    setup_conn = _fresh_connection()
    try:
        mission_id = _seed_l3_mission(setup_conn, owner)
        base_now = datetime.now(timezone.utc)
        mission = start_autonomous_window(setup_conn, mission_id=mission_id, now_fn=lambda: base_now)
        started, deadline = mission["window_started_at"], mission["window_deadline_at"]
    finally:
        setup_conn.close()

    fresh_conn = _fresh_connection()
    try:
        reloaded = get_mission(fresh_conn, mission_id)
        assert reloaded["window_started_at"] == started
        assert reloaded["window_deadline_at"] == deadline
        assert reloaded["state"] == MissionState.RUNNING.value
        assert reloaded["current_revision"] == "rev1"
    finally:
        fresh_conn.close()


# ── B. Exact boundary (live, wired through evaluate + gate) ──────────

def test_boundary_active_then_expired_live():
    owner = _uid()
    conn = _fresh_connection()
    try:
        mission_id = _seed_l3_mission(conn, owner)
        base_now = datetime.now(timezone.utc)
        start_autonomous_window(conn, mission_id=mission_id, now_fn=lambda: base_now)
        mission = get_mission(conn, mission_id)
        deadline = datetime.fromisoformat(mission["window_deadline_at"])

        just_before = deadline - timedelta(milliseconds=1)
        assert evaluate_mission_window(mission, now=just_before).value == "ACTIVE"
        assert require_new_autonomous_work_allowed(conn, mission_id=mission_id, now_fn=lambda: just_before) is MissionWindowDecision.ALLOW_NEW_WORK

        assert evaluate_mission_window(mission, now=deadline).value == "EXPIRED"
        assert require_new_autonomous_work_allowed(conn, mission_id=mission_id, now_fn=lambda: deadline) is MissionWindowDecision.DENY_NOT_ELIGIBLE

        past = deadline + timedelta(milliseconds=1)
        assert evaluate_mission_window(mission, now=past).value == "EXPIRED"
    finally:
        conn.close()


# ── D. Waiting-state time still counts ────────────────────────────────

def test_waiting_state_transitions_do_not_reset_deadline():
    owner = _uid()
    conn = _fresh_connection()
    try:
        mission_id = _seed_l3_mission(conn, owner)
        base_now = datetime.now(timezone.utc)
        started_mission = start_autonomous_window(conn, mission_id=mission_id, now_fn=lambda: base_now)
        deadline_before = started_mission["window_deadline_at"]

        transition_mission(conn, mission_id, MissionState.WAITING_TOOL)
        transition_mission(conn, mission_id, MissionState.RUNNING)
        transition_mission(conn, mission_id, MissionState.WAITING_APPROVAL)
        transition_mission(conn, mission_id, MissionState.RUNNING)
        transition_mission(conn, mission_id, MissionState.VERIFYING)

        after = get_mission(conn, mission_id)
        assert after["window_deadline_at"] == deadline_before
    finally:
        conn.close()


def test_court_review_window_expiry_transitions_safely():
    """The minimal Phase 15.14 state-machine adjustment: a mission
    genuinely in COURT_REVIEW when the window expires can still be
    checkpointed and paused."""
    owner = _uid()
    conn = _fresh_connection()
    try:
        mission_id = _seed_l3_mission(conn, owner)
        base_now = datetime.now(timezone.utc)
        start_autonomous_window(conn, mission_id=mission_id, now_fn=lambda: base_now)
        transition_mission(conn, mission_id, MissionState.VERIFYING)
        transition_mission(conn, mission_id, MissionState.COURT_REVIEW)

        expired_now = base_now + timedelta(seconds=DEFAULT_AUTONOMOUS_WINDOW_SECONDS + 1)
        result = enforce_window_expiry(conn, mission_id=mission_id, now_fn=lambda: expired_now, **_CKPT_KWARGS)
        assert result.outcome is WindowEnforcementOutcome.PAUSED
        assert result.mission["state"] == MissionState.PAUSED_WINDOW_REACHED.value
    finally:
        conn.close()


# ── E. Relay reconnect does not reset deadline ────────────────────────

def test_relay_reconnect_does_not_reset_window_deadline():
    owner = _uid()
    conn = _fresh_connection()
    try:
        mission_id = _seed_l3_mission(conn, owner)
        base_now = datetime.now(timezone.utc)
        mission = start_autonomous_window(conn, mission_id=mission_id, now_fn=lambda: base_now)
        deadline_before = mission["window_deadline_at"]

        later = base_now + timedelta(hours=5)
        _, session = _seed_session(conn, owner, mission_id, now_fn=lambda: later)
        reconnect_to_mission(conn, session_id=session.id, authenticated_user_id=owner, now_fn=lambda: later)

        after = get_mission(conn, mission_id)
        assert after["window_deadline_at"] == deadline_before
    finally:
        conn.close()


# ── F/G. Discretionary work gate before/after deadline ────────────────

def test_new_discretionary_work_allowed_before_deadline():
    owner = _uid()
    conn = _fresh_connection()
    try:
        mission_id = _seed_l3_mission(conn, owner)
        base_now = datetime.now(timezone.utc)
        start_autonomous_window(conn, mission_id=mission_id, now_fn=lambda: base_now)

        before = base_now + timedelta(hours=1)
        from orca.mission.mission_window import request_operation_within_window
        op, created = request_operation_within_window(
            conn, id=f"op_{uuid.uuid4().hex[:12]}", idempotency_key=f"idem_{uuid.uuid4().hex[:12]}",
            kind="deploy", requested_by=owner, mission_id=mission_id, now_fn=lambda: before,
        )
        assert created is True
        assert op["status"] == "REQUESTED"
    finally:
        conn.close()


def test_new_discretionary_work_denied_after_deadline():
    owner = _uid()
    conn = _fresh_connection()
    try:
        mission_id = _seed_l3_mission(conn, owner)
        base_now = datetime.now(timezone.utc)
        start_autonomous_window(conn, mission_id=mission_id, now_fn=lambda: base_now)

        after = base_now + timedelta(seconds=DEFAULT_AUTONOMOUS_WINDOW_SECONDS + 1)
        from orca.mission.mission_window import request_operation_within_window
        with pytest.raises(MissionWindowExpiredError):
            request_operation_within_window(
                conn, id=f"op_{uuid.uuid4().hex[:12]}", idempotency_key=f"idem_{uuid.uuid4().hex[:12]}",
                kind="deploy", requested_by=owner, mission_id=mission_id, now_fn=lambda: after,
            )
    finally:
        conn.close()


def test_retry_of_existing_idempotency_key_bypasses_window_gate():
    """Settling already-admitted work is never blocked by window
    expiry -- only genuinely NEW keys are gated."""
    owner = _uid()
    conn = _fresh_connection()
    try:
        mission_id = _seed_l3_mission(conn, owner)
        base_now = datetime.now(timezone.utc)
        start_autonomous_window(conn, mission_id=mission_id, now_fn=lambda: base_now)

        before = base_now + timedelta(hours=1)
        key = f"idem_{uuid.uuid4().hex[:12]}"
        op_id = f"op_{uuid.uuid4().hex[:12]}"
        from orca.mission.mission_window import request_operation_within_window
        op1, created1 = request_operation_within_window(
            conn, id=op_id, idempotency_key=key, kind="deploy", requested_by=owner,
            mission_id=mission_id, now_fn=lambda: before,
        )
        assert created1 is True

        after = base_now + timedelta(seconds=DEFAULT_AUTONOMOUS_WINDOW_SECONDS + 1)
        op2, created2 = request_operation_within_window(
            conn, id=op_id, idempotency_key=key, kind="deploy", requested_by=owner,
            mission_id=mission_id, now_fn=lambda: after,
        )
        assert created2 is False
        assert op2["id"] == op1["id"]
    finally:
        conn.close()


# ── H/I. Window/authority separation ───────────────────────────────────

def test_window_allow_does_not_bypass_authority_self_authorization_guard():
    from orca.mission.operation_store import SelfAuthorizationError
    owner = _uid()
    conn = _fresh_connection()
    try:
        mission_id = _seed_l3_mission(conn, owner)
        base_now = datetime.now(timezone.utc)
        start_autonomous_window(conn, mission_id=mission_id, now_fn=lambda: base_now)

        from orca.mission.mission_window import request_operation_within_window
        op, _ = request_operation_within_window(
            conn, id=f"op_{uuid.uuid4().hex[:12]}", idempotency_key=f"idem_{uuid.uuid4().hex[:12]}",
            kind="deploy", requested_by=owner, mission_id=mission_id, now_fn=lambda: base_now,
        )
        # Window ALLOW got us here -- authority is a SEPARATE
        # question, and a self-authorization attempt still fails.
        with pytest.raises(SelfAuthorizationError):
            authorize_operation(conn, op["id"], tenant_id="t1", approved_by=owner, reason="self")
    finally:
        conn.close()


def test_authority_allow_does_not_override_expired_window_new_work_prohibition():
    owner = _uid()
    conn = _fresh_connection()
    try:
        mission_id = _seed_l3_mission(conn, owner)
        base_now = datetime.now(timezone.utc)
        start_autonomous_window(conn, mission_id=mission_id, now_fn=lambda: base_now)

        # A genuinely NEW operation, that WOULD be perfectly
        # authorizable (different approver), is still denied purely
        # by window expiry -- authority is never even reached.
        after = base_now + timedelta(seconds=DEFAULT_AUTONOMOUS_WINDOW_SECONDS + 1)
        from orca.mission.mission_window import request_operation_within_window
        with pytest.raises(MissionWindowExpiredError):
            request_operation_within_window(
                conn, id=f"op_{uuid.uuid4().hex[:12]}", idempotency_key=f"idem_{uuid.uuid4().hex[:12]}",
                kind="deploy", requested_by=owner, mission_id=mission_id, now_fn=lambda: after,
            )
    finally:
        conn.close()


# ── J/K. Already-started atomic work crossing the deadline ────────────

def test_already_started_operation_crossing_deadline_settles_exactly_once():
    owner = _uid()
    conn = _fresh_connection()
    try:
        mission_id = _seed_l3_mission(conn, owner)
        base_now = datetime.now(timezone.utc)
        start_autonomous_window(conn, mission_id=mission_id, now_fn=lambda: base_now)

        before_deadline = base_now + timedelta(hours=5, minutes=59)
        key = f"idem_{uuid.uuid4().hex[:12]}"
        op_id = f"op_{uuid.uuid4().hex[:12]}"
        op, created = request_operation(
            conn, id=op_id, idempotency_key=key, kind="deploy", requested_by=owner, mission_id=mission_id,
        )
        assert created is True
        authorize_operation(conn, op_id, tenant_id="t1", approved_by=_uid(), reason="ok")

        executor = RecordingTestExecutor()
        op = start_and_execute_operation(conn, op_id, executor)
        assert op["status"] == "SUCCEEDED"
        assert executor.call_count == 1

        # Clock now advances past the deadline -- the ALREADY-SUCCEEDED
        # operation must not be re-executed, and no NEW discretionary
        # work may start.
        after_deadline = base_now + timedelta(seconds=DEFAULT_AUTONOMOUS_WINDOW_SECONDS + 1)
        op_retry = start_and_execute_operation(conn, op_id, executor)
        assert op_retry["status"] == "SUCCEEDED"
        assert executor.call_count == 1

        decision = require_new_autonomous_work_allowed(conn, mission_id=mission_id, now_fn=lambda: after_deadline)
        assert decision is MissionWindowDecision.DENY_NOT_ELIGIBLE
    finally:
        conn.close()


def test_started_unknown_operation_at_deadline_remains_pending_never_replayed():
    owner = _uid()
    conn = _fresh_connection()
    try:
        mission_id = _seed_l3_mission(conn, owner)
        base_now = datetime.now(timezone.utc)
        start_autonomous_window(conn, mission_id=mission_id, now_fn=lambda: base_now)

        op_id = f"op_{uuid.uuid4().hex[:12]}"
        request_operation(conn, id=op_id, idempotency_key=f"idem_{uuid.uuid4().hex[:12]}", kind="deploy", requested_by=owner, mission_id=mission_id)
        authorize_operation(conn, op_id, tenant_id="t1", approved_by=_uid(), reason="ok")

        from orca.mission.operation_store import _write_operation_transition
        _write_operation_transition(conn, op_id, "STARTED")
        conn.commit()

        after_deadline = base_now + timedelta(seconds=DEFAULT_AUTONOMOUS_WINDOW_SECONDS + 1)
        op = get_operation(conn, op_id)
        assert classify_operation_truth(op["status"]) is RelayOperationTruth.PENDING

        decision = require_new_autonomous_work_allowed(conn, mission_id=mission_id, now_fn=lambda: after_deadline)
        assert decision is MissionWindowDecision.DENY_NOT_ELIGIBLE

        # Enforcing window expiry checkpoints/pauses the MISSION but
        # never touches the operation's own durable truth.
        result = enforce_window_expiry(conn, mission_id=mission_id, now_fn=lambda: after_deadline, **_CKPT_KWARGS)
        assert result.outcome is WindowEnforcementOutcome.PAUSED
        op_after = get_operation(conn, op_id)
        assert op_after["status"] == "STARTED"
        assert classify_operation_truth(op_after["status"]) is RelayOperationTruth.PENDING
    finally:
        conn.close()


# ── L/M. Expiry checkpoint + pause atomicity, full-state preservation ──

def test_enforce_window_expiry_atomic_pause_and_checkpoint():
    owner = _uid()
    conn = _fresh_connection()
    try:
        mission_id = _seed_l3_mission(conn, owner)
        base_now = datetime.now(timezone.utc)
        start_autonomous_window(conn, mission_id=mission_id, now_fn=lambda: base_now)

        after = base_now + timedelta(seconds=DEFAULT_AUTONOMOUS_WINDOW_SECONDS + 1)
        result = enforce_window_expiry(conn, mission_id=mission_id, now_fn=lambda: after, **_CKPT_KWARGS)
        assert result.outcome is WindowEnforcementOutcome.PAUSED
        assert result.mission["state"] == MissionState.PAUSED_WINDOW_REACHED.value
        assert result.checkpoint is not None
        assert result.checkpoint.mission_state == MissionState.PAUSED_WINDOW_REACHED.value

        reloaded_mission = get_mission(conn, mission_id)
        reloaded_checkpoint = get_checkpoint(conn, result.checkpoint.id)
        assert reloaded_mission["state"] == MissionState.PAUSED_WINDOW_REACHED.value
        assert reloaded_checkpoint is not None
    finally:
        conn.close()


def test_window_checkpoint_preserves_full_mission_state():
    owner = _uid()
    conn = _fresh_connection()
    try:
        mission_id = _seed_l3_mission(conn, owner)
        base_now = datetime.now(timezone.utc)
        start_autonomous_window(conn, mission_id=mission_id, now_fn=lambda: base_now)

        after = base_now + timedelta(seconds=DEFAULT_AUTONOMOUS_WINDOW_SECONDS + 1)
        result = enforce_window_expiry(conn, mission_id=mission_id, now_fn=lambda: after, **_CKPT_KWARGS)
        ckpt = result.checkpoint
        assert ckpt.repository == _CKPT_KWARGS["repository"]
        assert ckpt.branch == _CKPT_KWARGS["branch"]
        assert ckpt.base_revision == _CKPT_KWARGS["base_revision"]
        assert ckpt.current_revision == _CKPT_KWARGS["current_revision"]
        assert ckpt.diff_ref == _CKPT_KWARGS["diff_ref"]
        assert ckpt.requirement_states == _CKPT_KWARGS["requirement_states"]
        assert ckpt.test_states == _CKPT_KWARGS["test_states"]
        assert ckpt.verification_states == _CKPT_KWARGS["verification_states"]
        assert ckpt.evidence_refs == _CKPT_KWARGS["evidence_refs"]
        assert ckpt.active_blocker == _CKPT_KWARGS["active_blocker"]
        assert ckpt.resource_budget_state == _CKPT_KWARGS["resource_budget_state"]
        assert ckpt.tool_outcomes == _CKPT_KWARGS["tool_outcomes"]
        assert ckpt.environment_identity == _CKPT_KWARGS["environment_identity"]
        assert ckpt.current_step_id == _CKPT_KWARGS["current_step_id"]
        assert ckpt.completed_step_ids == _CKPT_KWARGS["completed_step_ids"]
        assert ckpt.remaining_step_ids == _CKPT_KWARGS["remaining_step_ids"]
    finally:
        conn.close()


# ── U. Secret-safe checkpoint (Relay-visible) ─────────────────────────

def test_window_checkpoint_is_secret_safe_through_relay():
    owner = _uid()
    conn = _fresh_connection()
    try:
        mission_id = _seed_l3_mission(conn, owner)
        base_now = datetime.now(timezone.utc)
        start_autonomous_window(conn, mission_id=mission_id, now_fn=lambda: base_now)

        leaky_kwargs = dict(_CKPT_KWARGS)
        leaky_kwargs["diff_ref"] = "postgres://dbuser:S3cr3tPassw0rd@db.internal:5432/prod"
        leaky_kwargs["active_blocker"] = "Bearer sk-abcdefghijklmnopqrstuvwxyz1234567890ABCD blocked deploy"

        after = base_now + timedelta(seconds=DEFAULT_AUTONOMOUS_WINDOW_SECONDS + 1)
        enforce_window_expiry(conn, mission_id=mission_id, now_fn=lambda: after, **leaky_kwargs)

        # A device/session created AROUND the reconnect time (fresh,
        # valid at that instant) -- proves checkpoint secret-safety
        # through Relay, independent of the unrelated Relay-session
        # TTL/inactivity policy.
        _, session = _seed_session(conn, owner, mission_id, now_fn=lambda: after)
        reconnect_result = reconnect_to_mission(conn, session_id=session.id, authenticated_user_id=owner, now_fn=lambda: after)
        summary = reconnect_result.snapshot.checkpoint
        assert "S3cr3tPassw0rd" not in (summary.diff_ref or "")
        assert "sk-abcdefghijklmnopqrstuvwxyz1234567890" not in (summary.active_blocker or "")
    finally:
        conn.close()


# ── N/O/P. Resume, new window, SUCCEEDED-operation non-rerun ─────────

def test_resume_after_window_creates_a_new_server_controlled_window():
    owner = _uid()
    conn = _fresh_connection()
    try:
        mission_id = _seed_l3_mission(conn, owner)
        base_now = datetime.now(timezone.utc)
        start_autonomous_window(conn, mission_id=mission_id, now_fn=lambda: base_now)

        after = base_now + timedelta(seconds=DEFAULT_AUTONOMOUS_WINDOW_SECONDS + 1)
        result = enforce_window_expiry(conn, mission_id=mission_id, now_fn=lambda: after, **_CKPT_KWARGS)
        assert result.outcome is WindowEnforcementOutcome.PAUSED

        resume_time = after + timedelta(hours=1)
        new_mission, checkpoint = resume_after_window(
            conn, mission_id=mission_id, expected_checkpoint_id=result.checkpoint.id, now_fn=lambda: resume_time,
        )
        assert new_mission["state"] == MissionState.RUNNING.value
        assert new_mission["window_started_at"] == resume_time.isoformat()
        expected_deadline = resume_time + timedelta(seconds=DEFAULT_AUTONOMOUS_WINDOW_SECONDS)
        assert new_mission["window_deadline_at"] == expected_deadline.isoformat()
        # The OLD deadline is gone -- this is a genuinely new window,
        # not the old one extended.
        assert new_mission["window_deadline_at"] != result.mission["window_deadline_at"]
    finally:
        conn.close()


def test_resume_after_window_rejects_wrong_checkpoint():
    from orca.mission.mission_window import MissionWindowError
    owner = _uid()
    conn = _fresh_connection()
    try:
        mission_id = _seed_l3_mission(conn, owner)
        base_now = datetime.now(timezone.utc)
        start_autonomous_window(conn, mission_id=mission_id, now_fn=lambda: base_now)
        after = base_now + timedelta(seconds=DEFAULT_AUTONOMOUS_WINDOW_SECONDS + 1)
        enforce_window_expiry(conn, mission_id=mission_id, now_fn=lambda: after, **_CKPT_KWARGS)

        with pytest.raises(MissionWindowError):
            resume_after_window(conn, mission_id=mission_id, expected_checkpoint_id="ckpt_does_not_exist")

        # mission remains paused -- the bad resume attempt changed nothing
        assert get_mission(conn, mission_id)["state"] == MissionState.PAUSED_WINDOW_REACHED.value
    finally:
        conn.close()


def test_req_ckpt_restore_002_exact_acceptance_proof():
    """THE canonical Phase 15.14 proof closing REQ-CKPT-RESTORE-002:
    mission running under a real window -> operation O with
    idempotency key K -> O becomes SUCCEEDED, executor count 1 ->
    more mission work remains -> window expires -> real checkpoint +
    PAUSED_WINDOW_REACHED -> discard process state -> fresh-connection
    restore -> explicit resume -> the SAME logical operation K is
    reconciled/re-requested -> existing O is returned, never
    re-executed -> executor count STILL 1 -> remaining mission work
    (a second, real operation) can still proceed under the NEW window."""
    owner = _uid()
    setup_conn = _fresh_connection()
    try:
        mission_id = _seed_l3_mission(setup_conn, owner)
        base_now = datetime.now(timezone.utc)
        start_autonomous_window(setup_conn, mission_id=mission_id, now_fn=lambda: base_now)

        key = f"idem_{uuid.uuid4().hex[:12]}"
        op_id = f"op_{uuid.uuid4().hex[:12]}"
        request_operation(setup_conn, id=op_id, idempotency_key=key, kind="deploy", requested_by=owner, mission_id=mission_id, target="prod", parameters={"v": "1"})
        authorize_operation(setup_conn, op_id, tenant_id="t1", approved_by=_uid(), reason="ok")
        executor = RecordingTestExecutor()
        op = start_and_execute_operation(setup_conn, op_id, executor)
        assert op["status"] == "SUCCEEDED"
        assert executor.call_count == 1

        after = base_now + timedelta(seconds=DEFAULT_AUTONOMOUS_WINDOW_SECONDS + 1)
        pause_result = enforce_window_expiry(setup_conn, mission_id=mission_id, now_fn=lambda: after, **_CKPT_KWARGS)
        assert pause_result.outcome is WindowEnforcementOutcome.PAUSED
        checkpoint_id = pause_result.checkpoint.id
    finally:
        setup_conn.close()
    # PROCESS-STATE LOSS: setup_conn, executor's Python object, everything above is discarded/unreferenced now.

    fresh_conn = _fresh_connection()
    try:
        restored_mission = get_mission(fresh_conn, mission_id)
        restored_checkpoint = get_latest_checkpoint(fresh_conn, mission_id)
        assert restored_mission["state"] == MissionState.PAUSED_WINDOW_REACHED.value
        assert restored_checkpoint.id == checkpoint_id

        resume_time = after + timedelta(hours=1)
        new_mission, _ = resume_after_window(fresh_conn, mission_id=mission_id, expected_checkpoint_id=checkpoint_id, now_fn=lambda: resume_time)
        assert new_mission["state"] == MissionState.RUNNING.value

        # The SAME logical operation is reconciled -- a fresh executor
        # object (simulating a fresh process) attempts the SAME key.
        fresh_executor = RecordingTestExecutor()
        reconciled_op, created = request_operation(
            fresh_conn, id=op_id, idempotency_key=key, kind="deploy", requested_by=owner,
            mission_id=mission_id, target="prod", parameters={"v": "1"},
        )
        assert created is False
        assert reconciled_op["status"] == "SUCCEEDED"
        retry_result = start_and_execute_operation(fresh_conn, op_id, fresh_executor)
        assert retry_result["status"] == "SUCCEEDED"
        assert fresh_executor.call_count == 0  # never invoked -- already SUCCEEDED

        # Remaining mission work continues under the NEW window: a
        # genuinely different operation may be requested.
        from orca.mission.mission_window import request_operation_within_window
        new_op, new_created = request_operation_within_window(
            fresh_conn, id=f"op_{uuid.uuid4().hex[:12]}", idempotency_key=f"idem_{uuid.uuid4().hex[:12]}",
            kind="verify", requested_by=owner, mission_id=mission_id, now_fn=lambda: resume_time,
        )
        assert new_created is True
    finally:
        fresh_conn.close()


# ── Q/R. Idempotent + concurrent expiry enforcement ───────────────────

def test_double_expiry_enforcement_is_idempotent():
    owner = _uid()
    conn = _fresh_connection()
    try:
        mission_id = _seed_l3_mission(conn, owner)
        base_now = datetime.now(timezone.utc)
        start_autonomous_window(conn, mission_id=mission_id, now_fn=lambda: base_now)
        after = base_now + timedelta(seconds=DEFAULT_AUTONOMOUS_WINDOW_SECONDS + 1)

        first = enforce_window_expiry(conn, mission_id=mission_id, now_fn=lambda: after, **_CKPT_KWARGS)
        assert first.outcome is WindowEnforcementOutcome.PAUSED

        second = enforce_window_expiry(conn, mission_id=mission_id, now_fn=lambda: after, **_CKPT_KWARGS)
        assert second.outcome is WindowEnforcementOutcome.ALREADY_PAUSED
        assert second.checkpoint.id == first.checkpoint.id  # no checkpoint spam

        # Exactly one checkpoint exists for this mission's window pause.
        with conn.cursor() as cur:
            cur.execute("SELECT count(*) AS c FROM checkpoints WHERE mission_id = %s", (mission_id,))
            count = cur.fetchone()["c"]
        conn.commit()
        assert count == 1
    finally:
        conn.close()


def test_concurrent_expiry_enforcers_converge_to_one_pause():
    owner = _uid()
    setup_conn = _fresh_connection()
    try:
        mission_id = _seed_l3_mission(setup_conn, owner)
        base_now = datetime.now(timezone.utc)
        start_autonomous_window(setup_conn, mission_id=mission_id, now_fn=lambda: base_now)
    finally:
        setup_conn.close()

    after = base_now + timedelta(seconds=DEFAULT_AUTONOMOUS_WINDOW_SECONDS + 1)
    barrier = threading.Barrier(2)
    results = []
    errors = []

    def _worker():
        conn = _fresh_connection()
        try:
            barrier.wait(timeout=5)
            results.append(enforce_window_expiry(conn, mission_id=mission_id, now_fn=lambda: after, **_CKPT_KWARGS).outcome)
        except Exception as e:  # noqa: BLE001
            errors.append(e)
        finally:
            conn.close()

    t1 = threading.Thread(target=_worker, daemon=True)
    t2 = threading.Thread(target=_worker, daemon=True)
    t1.start(); t2.start()
    t1.join(timeout=15); t2.join(timeout=15)

    assert not errors, f"unexpected errors: {errors}"
    assert len(results) == 2
    assert sorted(o.value for o in results) == ["ALREADY_PAUSED", "PAUSED"]

    final_conn = _fresh_connection()
    try:
        assert get_mission(final_conn, mission_id)["state"] == MissionState.PAUSED_WINDOW_REACHED.value
        with final_conn.cursor() as cur:
            cur.execute("SELECT count(*) AS c FROM checkpoints WHERE mission_id = %s", (mission_id,))
            count = cur.fetchone()["c"]
        final_conn.commit()
        assert count == 1
    finally:
        final_conn.close()


# ── S. User-pause vs expiry race ──────────────────────────────────────

def test_user_pause_vs_expiry_race_converges_without_corruption():
    from orca.mission.mission_store import checkpoint_and_pause

    owner = _uid()
    setup_conn = _fresh_connection()
    try:
        mission_id = _seed_l3_mission(setup_conn, owner)
        base_now = datetime.now(timezone.utc)
        start_autonomous_window(setup_conn, mission_id=mission_id, now_fn=lambda: base_now)
    finally:
        setup_conn.close()

    after = base_now + timedelta(seconds=DEFAULT_AUTONOMOUS_WINDOW_SECONDS + 1)
    barrier = threading.Barrier(2)
    outcomes = {}
    errors = []

    def _user_pause():
        conn = _fresh_connection()
        try:
            barrier.wait(timeout=5)
            try:
                checkpoint_and_pause(
                    conn, mission_id, pause_state=MissionState.PAUSED_USER,
                    checkpoint_id=f"ckpt_user_{uuid.uuid4().hex[:12]}", **_CKPT_KWARGS,
                )
                outcomes["user"] = "APPLIED"
            except MissionStateError:
                outcomes["user"] = "LOST"
        except Exception as e:  # noqa: BLE001
            errors.append(e)
        finally:
            conn.close()

    def _window_expiry():
        conn = _fresh_connection()
        try:
            barrier.wait(timeout=5)
            result = enforce_window_expiry(conn, mission_id=mission_id, now_fn=lambda: after, **_CKPT_KWARGS)
            outcomes["window"] = result.outcome.value
        except Exception as e:  # noqa: BLE001
            errors.append(e)
        finally:
            conn.close()

    t1 = threading.Thread(target=_user_pause, daemon=True)
    t2 = threading.Thread(target=_window_expiry, daemon=True)
    t1.start(); t2.start()
    t1.join(timeout=15); t2.join(timeout=15)

    assert not errors, f"unexpected errors: {errors}"
    final_conn = _fresh_connection()
    try:
        final_state = get_mission(final_conn, mission_id)["state"]
        assert final_state in (MissionState.PAUSED_USER.value, MissionState.PAUSED_WINDOW_REACHED.value)
        # Exactly one checkpoint won -- never both, never neither.
        with final_conn.cursor() as cur:
            cur.execute("SELECT count(*) AS c FROM checkpoints WHERE mission_id = %s", (mission_id,))
            count = cur.fetchone()["c"]
        final_conn.commit()
        assert count == 1
        # Whichever won, the OTHER reports a non-corrupting outcome.
        if final_state == MissionState.PAUSED_USER.value:
            assert outcomes["window"] in ("ALREADY_PAUSED", "NO_ACTION", "TERMINAL")
        else:
            assert outcomes["user"] == "LOST"
    finally:
        final_conn.close()


# ── T. Terminal-completion vs expiry ───────────────────────────────────

def test_terminal_completion_before_expiry_enforcement_wins():
    owner = _uid()
    conn = _fresh_connection()
    try:
        mission_id = _seed_l3_mission(conn, owner)
        base_now = datetime.now(timezone.utc)
        start_autonomous_window(conn, mission_id=mission_id, now_fn=lambda: base_now)
        transition_mission(conn, mission_id, MissionState.WAITING_TOOL)
        transition_mission(conn, mission_id, MissionState.RUNNING)
        transition_mission(conn, mission_id, MissionState.FAILED)

        after = base_now + timedelta(seconds=DEFAULT_AUTONOMOUS_WINDOW_SECONDS + 1)
        result = enforce_window_expiry(conn, mission_id=mission_id, now_fn=lambda: after, **_CKPT_KWARGS)
        assert result.outcome is WindowEnforcementOutcome.TERMINAL
        assert get_mission(conn, mission_id)["state"] == MissionState.FAILED.value
    finally:
        conn.close()


# ── BLOCKED precedence ─────────────────────────────────────────────────

def test_blocked_state_is_never_bypassed_by_window_expiry():
    owner = _uid()
    conn = _fresh_connection()
    try:
        mission_id = _seed_l3_mission(conn, owner)
        base_now = datetime.now(timezone.utc)
        start_autonomous_window(conn, mission_id=mission_id, now_fn=lambda: base_now)
        transition_mission(conn, mission_id, MissionState.BLOCKED)

        after = base_now + timedelta(seconds=DEFAULT_AUTONOMOUS_WINDOW_SECONDS + 1)
        result = enforce_window_expiry(conn, mission_id=mission_id, now_fn=lambda: after, **_CKPT_KWARGS)
        assert result.outcome is WindowEnforcementOutcome.NO_ACTION
        assert get_mission(conn, mission_id)["state"] == MissionState.BLOCKED.value
    finally:
        conn.close()


# ═════════════════════════════════════════════════════════════════════
# PHASE 15.14.1 -- Autonomous-Window Bypass, Atomic Admission, and
# Secret-Safe Checkpoint Closure (owner audit).
# ═════════════════════════════════════════════════════════════════════

# ── Item 1: an expired window is not renewable by a direct start() ────

def test_direct_start_after_expired_window_is_denied():
    owner = _uid()
    conn = _fresh_connection()
    try:
        mission_id = _seed_l3_mission(conn, owner)
        base_now = datetime.now(timezone.utc)
        start_autonomous_window(conn, mission_id=mission_id, now_fn=lambda: base_now)
        original = get_mission(conn, mission_id)

        after = base_now + timedelta(seconds=DEFAULT_AUTONOMOUS_WINDOW_SECONDS + 1)
        with pytest.raises(WindowRenewalDeniedError):
            start_autonomous_window(conn, mission_id=mission_id, now_fn=lambda: after)

        reloaded = get_mission(conn, mission_id)
        assert reloaded["window_started_at"] == original["window_started_at"]
        assert reloaded["window_deadline_at"] == original["window_deadline_at"]
        assert reloaded["state"] == MissionState.RUNNING.value  # no second allocation, no state churn
    finally:
        conn.close()


# ── Item 2: server-controlled window duration, no caller override ─────

def test_start_autonomous_window_has_no_public_duration_parameter():
    import inspect
    sig = inspect.signature(start_autonomous_window)
    assert "window_seconds" not in sig.parameters
    assert "_policy" in sig.parameters  # internal/test-only seam only


def test_default_policy_is_21600_for_l3_and_l4():
    from orca.mission.mission_window import get_mission_window_policy
    policy = get_mission_window_policy()
    assert policy.duration_seconds("L3") == 21600
    assert policy.duration_seconds("L4") == 21600


def test_test_only_policy_seam_does_not_leak_into_other_calls():
    owner = _uid()
    conn = _fresh_connection()
    try:
        mission_id = _seed_l3_mission(conn, owner)
        base_now = datetime.now(timezone.utc)
        tiny_policy = MissionWindowPolicy(durations_by_level={"L3": 1, "L4": 1})
        mission = start_autonomous_window(conn, mission_id=mission_id, now_fn=lambda: base_now, _policy=tiny_policy)
        started = datetime.fromisoformat(mission["window_started_at"])
        deadline = datetime.fromisoformat(mission["window_deadline_at"])
        assert (deadline - started).total_seconds() == 1

        mission_id_2 = _seed_l3_mission(conn, owner)
        mission2 = start_autonomous_window(conn, mission_id=mission_id_2, now_fn=lambda: base_now)
        started2 = datetime.fromisoformat(mission2["window_started_at"])
        deadline2 = datetime.fromisoformat(mission2["window_deadline_at"])
        assert (deadline2 - started2).total_seconds() == DEFAULT_AUTONOMOUS_WINDOW_SECONDS
    finally:
        conn.close()


# ── Item 3: NOT_STARTED L3/L4 must not admit autonomous work ──────────

def test_not_started_l3_mission_cannot_request_autonomous_work():
    owner = _uid()
    conn = _fresh_connection()
    try:
        mission_id = _seed_l3_mission(conn, owner)  # READY, no window started
        assert get_mission(conn, mission_id)["window_started_at"] is None

        with pytest.raises(MissionWindowExpiredError):
            request_operation_within_window(
                conn, id=f"op_{uuid.uuid4().hex[:12]}", idempotency_key=f"idem_{uuid.uuid4().hex[:12]}",
                kind="deploy", requested_by=owner, mission_id=mission_id,
            )
        with conn.cursor() as cur:
            cur.execute("SELECT count(*) AS c FROM operations WHERE mission_id = %s", (mission_id,))
            count = cur.fetchone()["c"]
        conn.commit()
        assert count == 0

        base_now = datetime.now(timezone.utc)
        start_autonomous_window(conn, mission_id=mission_id, now_fn=lambda: base_now)
        op, created = request_operation_within_window(
            conn, id=f"op_{uuid.uuid4().hex[:12]}", idempotency_key=f"idem_{uuid.uuid4().hex[:12]}",
            kind="deploy", requested_by=owner, mission_id=mission_id, now_fn=lambda: base_now,
        )
        assert created is True
    finally:
        conn.close()


# ── Item 4: PAUSED_USER and BLOCKED must deny new autonomous work ─────

def test_paused_user_cannot_admit_new_operation():
    from orca.mission.mission_store import checkpoint_and_pause
    owner = _uid()
    conn = _fresh_connection()
    try:
        mission_id = _seed_l3_mission(conn, owner)
        base_now = datetime.now(timezone.utc)
        start_autonomous_window(conn, mission_id=mission_id, now_fn=lambda: base_now)
        checkpoint_and_pause(
            conn, mission_id, pause_state=MissionState.PAUSED_USER,
            checkpoint_id=f"ckpt_user_{uuid.uuid4().hex[:12]}", **_CKPT_KWARGS,
        )

        with pytest.raises(MissionWindowExpiredError):
            request_operation_within_window(
                conn, id=f"op_{uuid.uuid4().hex[:12]}", idempotency_key=f"idem_{uuid.uuid4().hex[:12]}",
                kind="deploy", requested_by=owner, mission_id=mission_id, now_fn=lambda: base_now,
            )
        with conn.cursor() as cur:
            cur.execute("SELECT count(*) AS c FROM operations WHERE mission_id = %s", (mission_id,))
            count = cur.fetchone()["c"]
        conn.commit()
        assert count == 0
    finally:
        conn.close()


def test_blocked_cannot_admit_new_operation():
    owner = _uid()
    conn = _fresh_connection()
    try:
        mission_id = _seed_l3_mission(conn, owner)
        base_now = datetime.now(timezone.utc)
        start_autonomous_window(conn, mission_id=mission_id, now_fn=lambda: base_now)
        transition_mission(conn, mission_id, MissionState.BLOCKED)

        with pytest.raises(MissionWindowExpiredError):
            request_operation_within_window(
                conn, id=f"op_{uuid.uuid4().hex[:12]}", idempotency_key=f"idem_{uuid.uuid4().hex[:12]}",
                kind="deploy", requested_by=owner, mission_id=mission_id, now_fn=lambda: base_now,
            )
        with conn.cursor() as cur:
            cur.execute("SELECT count(*) AS c FROM operations WHERE mission_id = %s", (mission_id,))
            count = cur.fetchone()["c"]
        conn.commit()
        assert count == 0
    finally:
        conn.close()


# ── Items 5/6/7/8: AUTHORIZED-but-not-STARTED cannot start after ──────
# expiry; executor never invoked; explicit resume makes it eligible
# again; already-STARTED work still settles without replay.

def test_authorized_operation_cannot_start_after_expiry_then_resume_makes_it_eligible():
    owner = _uid()
    conn = _fresh_connection()
    try:
        mission_id = _seed_l3_mission(conn, owner)
        base_now = datetime.now(timezone.utc)
        start_autonomous_window(conn, mission_id=mission_id, now_fn=lambda: base_now)

        op_id = f"op_{uuid.uuid4().hex[:12]}"
        request_operation(conn, id=op_id, idempotency_key=f"idem_{uuid.uuid4().hex[:12]}", kind="deploy", requested_by=owner, mission_id=mission_id)
        authorize_operation(conn, op_id, tenant_id="t1", approved_by=_uid(), reason="ok")
        assert get_operation(conn, op_id)["status"] == "AUTHORIZED"

        after = base_now + timedelta(seconds=DEFAULT_AUTONOMOUS_WINDOW_SECONDS + 1)
        executor = RecordingTestExecutor()
        with pytest.raises(MissionWindowExpiredError):
            start_and_execute_operation_within_window(
                conn, operation_id=op_id, mission_id=mission_id, executor=executor, now_fn=lambda: after,
            )
        assert get_operation(conn, op_id)["status"] == "AUTHORIZED"
        assert executor.call_count == 0

        result = enforce_window_expiry(conn, mission_id=mission_id, now_fn=lambda: after, **_CKPT_KWARGS)
        assert result.outcome is WindowEnforcementOutcome.PAUSED
        resume_time = after + timedelta(hours=1)
        resume_after_window(conn, mission_id=mission_id, expected_checkpoint_id=result.checkpoint.id, now_fn=lambda: resume_time)

        retry_executor = RecordingTestExecutor()
        started = start_and_execute_operation_within_window(
            conn, operation_id=op_id, mission_id=mission_id, executor=retry_executor, now_fn=lambda: resume_time,
        )
        assert started["status"] == "SUCCEEDED"
        assert retry_executor.call_count == 1
    finally:
        conn.close()


def test_already_started_operation_settles_via_within_window_wrapper_without_replay():
    owner = _uid()
    conn = _fresh_connection()
    try:
        mission_id = _seed_l3_mission(conn, owner)
        base_now = datetime.now(timezone.utc)
        start_autonomous_window(conn, mission_id=mission_id, now_fn=lambda: base_now)

        op_id = f"op_{uuid.uuid4().hex[:12]}"
        request_operation(conn, id=op_id, idempotency_key=f"idem_{uuid.uuid4().hex[:12]}", kind="deploy", requested_by=owner, mission_id=mission_id)
        authorize_operation(conn, op_id, tenant_id="t1", approved_by=_uid(), reason="ok")

        executor = RecordingTestExecutor()
        started = start_and_execute_operation_within_window(
            conn, operation_id=op_id, mission_id=mission_id, executor=executor, now_fn=lambda: base_now,
        )
        assert started["status"] == "SUCCEEDED"
        assert executor.call_count == 1

        after = base_now + timedelta(seconds=DEFAULT_AUTONOMOUS_WINDOW_SECONDS + 1)
        retry_executor = RecordingTestExecutor()
        retried = start_and_execute_operation_within_window(
            conn, operation_id=op_id, mission_id=mission_id, executor=retry_executor, now_fn=lambda: after,
        )
        assert retried["status"] == "SUCCEEDED"
        assert retry_executor.call_count == 0  # settlement-only, never replayed
    finally:
        conn.close()


# ── Item 10: idempotency retry-bypass is mission-bound ────────────────

def test_cross_mission_idempotency_key_does_not_bypass_a_mission_own_window():
    owner = _uid()
    conn = _fresh_connection()
    try:
        mission_a = _seed_l3_mission(conn, owner)
        mission_b = _seed_l3_mission(conn, owner)
        base_now = datetime.now(timezone.utc)
        start_autonomous_window(conn, mission_id=mission_a, now_fn=lambda: base_now)
        start_autonomous_window(conn, mission_id=mission_b, now_fn=lambda: base_now)

        shared_key = f"idem_{uuid.uuid4().hex[:12]}"
        op_a, created_a = request_operation_within_window(
            conn, id=f"op_{uuid.uuid4().hex[:12]}", idempotency_key=shared_key, kind="deploy",
            requested_by=owner, mission_id=mission_a, now_fn=lambda: base_now,
        )
        assert created_a is True
        assert op_a["mission_id"] == mission_a

        after = base_now + timedelta(seconds=DEFAULT_AUTONOMOUS_WINDOW_SECONDS + 1)
        with pytest.raises(MissionWindowExpiredError):
            request_operation_within_window(
                conn, id=f"op_{uuid.uuid4().hex[:12]}", idempotency_key=shared_key, kind="deploy",
                requested_by=owner, mission_id=mission_b, now_fn=lambda: after,
            )

        mission_c = _seed_l3_mission(conn, owner)
        start_autonomous_window(conn, mission_id=mission_c, now_fn=lambda: base_now)
        with pytest.raises(OperationConflictError):
            request_operation_within_window(
                conn, id=f"op_{uuid.uuid4().hex[:12]}", idempotency_key=shared_key, kind="deploy",
                requested_by=owner, mission_id=mission_c, now_fn=lambda: base_now,
            )

        with conn.cursor() as cur:
            cur.execute("SELECT count(*) AS c FROM operations WHERE idempotency_key = %s", (shared_key,))
            count = cur.fetchone()["c"]
        conn.commit()
        assert count == 1  # only mission A's original operation exists
    finally:
        conn.close()


# ── Item 11: raw secrets must never enter the durable checkpoint ──────

def test_raw_secrets_absent_from_checkpoint_row_at_rest_and_via_relay():
    owner = _uid()
    conn = _fresh_connection()
    try:
        mission_id = _seed_l3_mission(conn, owner)
        base_now = datetime.now(timezone.utc)
        start_autonomous_window(conn, mission_id=mission_id, now_fn=lambda: base_now)

        leaky_kwargs = dict(_CKPT_KWARGS)
        leaky_kwargs["diff_ref"] = "postgres://dbuser:S3cr3tPassw0rd@db.internal:5432/prod"
        leaky_kwargs["active_blocker"] = "Bearer sk-abcdefghijklmnopqrstuvwxyz1234567890ABCD blocked deploy"
        leaky_kwargs["requirement_states"] = {"REQ-X-001": "token=ghp_abcdefghijklmnopqrstuvwxyz0123456789"}
        leaky_kwargs["tool_outcomes"] = ({"tool": "curl", "outcome": "Authorization Bearer sk-zzzzzzzzzzzzzzzzzzzzzzzzzzzzzzzzzzzzzzzz"},)
        leaky_kwargs["environment_identity"] = "runner password=abcdEFGH1234567890abcdEFGH1234567890abcd"

        after = base_now + timedelta(seconds=DEFAULT_AUTONOMOUS_WINDOW_SECONDS + 1)
        result = enforce_window_expiry(conn, mission_id=mission_id, now_fn=lambda: after, **leaky_kwargs)
        assert result.outcome is WindowEnforcementOutcome.PAUSED

        # AT-REST: query the checkpoints TABLE DIRECTLY.
        with conn.cursor() as cur:
            cur.execute("SELECT * FROM checkpoints WHERE id = %s", (result.checkpoint.id,))
            row = dict(cur.fetchone())
        conn.commit()
        raw_text = str(row)
        assert "S3cr3tPassw0rd" not in raw_text
        assert "sk-abcdefghijklmnopqrstuvwxyz1234567890" not in raw_text
        assert "ghp_abcdefghijklmnopqrstuvwxyz0123456789" not in raw_text
        assert "sk-zzzzzzzzzzzzzzzzzzzzzzzzzzzzzzzzzzzzzzzz" not in raw_text
        assert "abcdEFGH1234567890abcdEFGH1234567890abcd" not in raw_text

        # RELAY: still clean.
        _, session = _seed_session(conn, owner, mission_id, now_fn=lambda: after)
        reconnect_result = reconnect_to_mission(conn, session_id=session.id, authenticated_user_id=owner, now_fn=lambda: after)
        summary = reconnect_result.snapshot.checkpoint
        assert "S3cr3tPassw0rd" not in (summary.diff_ref or "")
        assert "sk-abcdefghijklmnopqrstuvwxyz1234567890" not in (summary.active_blocker or "")
    finally:
        conn.close()


# ── Item 12: resume state + fresh window must be transactionally ──────
# coherent.

def test_resume_after_window_rolls_back_atomically_on_failure(monkeypatch):
    owner = _uid()
    conn = _fresh_connection()
    try:
        mission_id = _seed_l3_mission(conn, owner)
        base_now = datetime.now(timezone.utc)
        start_autonomous_window(conn, mission_id=mission_id, now_fn=lambda: base_now)
        after = base_now + timedelta(seconds=DEFAULT_AUTONOMOUS_WINDOW_SECONDS + 1)
        result = enforce_window_expiry(conn, mission_id=mission_id, now_fn=lambda: after, **_CKPT_KWARGS)
        assert result.outcome is WindowEnforcementOutcome.PAUSED
        checkpoint_id = result.checkpoint.id

        import orca.mission.mission_window as mw
        original = mw._begin_window_locked

        def _boom(*a, **k):
            raise RuntimeError("simulated failure between RUNNING transition and window write")

        monkeypatch.setattr(mw, "_begin_window_locked", _boom)
        resume_time = after + timedelta(hours=1)
        with pytest.raises(RuntimeError):
            resume_after_window(conn, mission_id=mission_id, expected_checkpoint_id=checkpoint_id, now_fn=lambda: resume_time)
        monkeypatch.setattr(mw, "_begin_window_locked", original)

        reloaded = get_mission(conn, mission_id)
        assert reloaded["state"] == MissionState.PAUSED_WINDOW_REACHED.value
        latest = get_latest_checkpoint(conn, mission_id)
        assert latest.id == checkpoint_id
    finally:
        conn.close()

    # A SECOND, independent connection can immediately resume -- proving
    # no lock was leaked by the failed attempt.
    conn2 = _fresh_connection()
    try:
        resume_time2 = after + timedelta(hours=2)
        new_mission, ckpt = resume_after_window(conn2, mission_id=mission_id, expected_checkpoint_id=checkpoint_id, now_fn=lambda: resume_time2)
        assert new_mission["state"] == MissionState.RUNNING.value
    finally:
        conn2.close()


# ── Item 13/15#15: enforce_window_expiry() holds ONE lock for its ─────
# ENTIRE decision + write.

def test_enforce_window_expiry_holds_one_lock_for_decision_and_write():
    owner = _uid()
    setup_conn = _fresh_connection()
    try:
        mission_id = _seed_l3_mission(setup_conn, owner)
        base_now = datetime.now(timezone.utc)
        start_autonomous_window(setup_conn, mission_id=mission_id, now_fn=lambda: base_now)
    finally:
        setup_conn.close()

    after = base_now + timedelta(seconds=DEFAULT_AUTONOMOUS_WINDOW_SECONDS + 1)
    hold_event = threading.Event()
    release_event = threading.Event()

    def _raw_lock_holder():
        conn = _fresh_connection()
        try:
            with conn.cursor() as cur:
                cur.execute("SELECT * FROM missions WHERE id = %s FOR UPDATE", (mission_id,))
                cur.fetchone()
            hold_event.set()
            release_event.wait(timeout=10)
        finally:
            conn.rollback()
            conn.close()

    holder = threading.Thread(target=_raw_lock_holder, daemon=True)
    holder.start()
    assert hold_event.wait(timeout=5)

    result_box = {}

    def _expiry_attempt():
        conn = _fresh_connection()
        try:
            result_box["result"] = enforce_window_expiry(conn, mission_id=mission_id, now_fn=lambda: after, **_CKPT_KWARGS)
        finally:
            conn.close()

    attempt_thread = threading.Thread(target=_expiry_attempt, daemon=True)
    attempt_thread.start()

    inspect_conn = _fresh_connection()
    try:
        assert _wait_until_blocked_on_lock(inspect_conn), "enforce_window_expiry() did not genuinely block on the mission row lock"
    finally:
        inspect_conn.close()

    release_event.set()
    holder.join(timeout=10)
    attempt_thread.join(timeout=10)

    assert result_box["result"].outcome is WindowEnforcementOutcome.PAUSED
    final_conn = _fresh_connection()
    try:
        assert get_mission(final_conn, mission_id)["state"] == MissionState.PAUSED_WINDOW_REACHED.value
    finally:
        final_conn.close()


# ── Item 8/9: real admission-vs-expiry and START-vs-expiry races ──────

def test_admission_vs_expiry_race_expiry_commits_first_denies_admission():
    from orca.mission.mission_store import checkpoint_and_pause

    owner = _uid()
    setup_conn = _fresh_connection()
    try:
        mission_id = _seed_l3_mission(setup_conn, owner)
        base_now = datetime.now(timezone.utc)
        start_autonomous_window(setup_conn, mission_id=mission_id, now_fn=lambda: base_now)
    finally:
        setup_conn.close()

    after = base_now + timedelta(seconds=DEFAULT_AUTONOMOUS_WINDOW_SECONDS + 1)
    hold_event = threading.Event()
    holder_conn = _fresh_connection()

    def _hold():
        with holder_conn.cursor() as cur:
            cur.execute("SELECT * FROM missions WHERE id = %s FOR UPDATE", (mission_id,))
            cur.fetchone()
        hold_event.set()

    holder_thread = threading.Thread(target=_hold, daemon=True)
    holder_thread.start()
    assert hold_event.wait(timeout=5)
    holder_thread.join(timeout=5)

    result_box = {}
    errors = []

    def _admission_attempt():
        conn = _fresh_connection()
        try:
            request_operation_within_window(
                conn, id=f"op_{uuid.uuid4().hex[:12]}", idempotency_key=f"idem_{uuid.uuid4().hex[:12]}",
                kind="deploy", requested_by=owner, mission_id=mission_id, now_fn=lambda: after,
            )
        except MissionWindowExpiredError:
            result_box["denied"] = True
        except Exception as e:  # noqa: BLE001
            errors.append(e)
        finally:
            conn.close()

    attempt_thread = threading.Thread(target=_admission_attempt, daemon=True)
    attempt_thread.start()

    inspect_conn = _fresh_connection()
    try:
        assert _wait_until_blocked_on_lock(inspect_conn)
    finally:
        inspect_conn.close()

    # Still holding the lock via holder_conn's open transaction:
    # perform the REAL pause+checkpoint write -- exactly what
    # enforce_window_expiry() itself does, with deterministic timing.
    checkpoint_and_pause(
        holder_conn, mission_id, pause_state=MissionState.PAUSED_WINDOW_REACHED,
        checkpoint_id=f"ckpt_race_{uuid.uuid4().hex[:12]}", **_CKPT_KWARGS,
    )
    holder_conn.close()

    attempt_thread.join(timeout=10)
    assert not errors, f"unexpected errors: {errors}"
    assert result_box.get("denied") is True

    final_conn = _fresh_connection()
    try:
        assert get_mission(final_conn, mission_id)["state"] == MissionState.PAUSED_WINDOW_REACHED.value
        with final_conn.cursor() as cur:
            cur.execute("SELECT count(*) AS c FROM operations WHERE mission_id = %s", (mission_id,))
            count = cur.fetchone()["c"]
        final_conn.commit()
        assert count == 0
    finally:
        final_conn.close()


def test_admission_vs_expiry_race_admission_commits_first_survives_later_expiry():
    owner = _uid()
    setup_conn = _fresh_connection()
    try:
        mission_id = _seed_l3_mission(setup_conn, owner)
        base_now = datetime.now(timezone.utc)
        start_autonomous_window(setup_conn, mission_id=mission_id, now_fn=lambda: base_now)
    finally:
        setup_conn.close()

    hold_event = threading.Event()
    holder_conn = _fresh_connection()

    def _hold():
        with holder_conn.cursor() as cur:
            cur.execute("SELECT * FROM missions WHERE id = %s FOR UPDATE", (mission_id,))
            cur.fetchone()
        hold_event.set()

    holder_thread = threading.Thread(target=_hold, daemon=True)
    holder_thread.start()
    assert hold_event.wait(timeout=5)
    holder_thread.join(timeout=5)

    after = base_now + timedelta(seconds=DEFAULT_AUTONOMOUS_WINDOW_SECONDS + 1)
    result_box = {}
    errors = []

    def _expiry_attempt():
        conn = _fresh_connection()
        try:
            result_box["result"] = enforce_window_expiry(conn, mission_id=mission_id, now_fn=lambda: after, **_CKPT_KWARGS)
        except Exception as e:  # noqa: BLE001
            errors.append(e)
        finally:
            conn.close()

    attempt_thread = threading.Thread(target=_expiry_attempt, daemon=True)
    attempt_thread.start()

    inspect_conn = _fresh_connection()
    try:
        assert _wait_until_blocked_on_lock(inspect_conn)
    finally:
        inspect_conn.close()

    # Still holding the lock: commit a REAL REQUESTED operation --
    # representing admission having durably won the race while the
    # window was genuinely still active.
    op_id = f"op_{uuid.uuid4().hex[:12]}"
    request_operation(holder_conn, id=op_id, idempotency_key=f"idem_{uuid.uuid4().hex[:12]}", kind="deploy", requested_by=owner, mission_id=mission_id)
    holder_conn.close()

    attempt_thread.join(timeout=10)
    assert not errors, f"unexpected errors: {errors}"
    assert result_box["result"].outcome is WindowEnforcementOutcome.PAUSED

    final_conn = _fresh_connection()
    try:
        op = get_operation(final_conn, op_id)
        assert op["status"] == "REQUESTED"
        assert get_mission(final_conn, mission_id)["state"] == MissionState.PAUSED_WINDOW_REACHED.value
    finally:
        final_conn.close()


def test_start_vs_expiry_race_expiry_commits_first_denies_start():
    from orca.mission.mission_store import checkpoint_and_pause

    owner = _uid()
    setup_conn = _fresh_connection()
    try:
        mission_id = _seed_l3_mission(setup_conn, owner)
        base_now = datetime.now(timezone.utc)
        start_autonomous_window(setup_conn, mission_id=mission_id, now_fn=lambda: base_now)
        op_id = f"op_{uuid.uuid4().hex[:12]}"
        request_operation(setup_conn, id=op_id, idempotency_key=f"idem_{uuid.uuid4().hex[:12]}", kind="deploy", requested_by=owner, mission_id=mission_id)
        authorize_operation(setup_conn, op_id, tenant_id="t1", approved_by=_uid(), reason="ok")
    finally:
        setup_conn.close()

    after = base_now + timedelta(seconds=DEFAULT_AUTONOMOUS_WINDOW_SECONDS + 1)
    hold_event = threading.Event()
    holder_conn = _fresh_connection()

    def _hold():
        with holder_conn.cursor() as cur:
            cur.execute("SELECT * FROM missions WHERE id = %s FOR UPDATE", (mission_id,))
            cur.fetchone()
        hold_event.set()

    holder_thread = threading.Thread(target=_hold, daemon=True)
    holder_thread.start()
    assert hold_event.wait(timeout=5)
    holder_thread.join(timeout=5)

    result_box = {}
    errors = []
    executor = RecordingTestExecutor()

    def _start_attempt():
        conn = _fresh_connection()
        try:
            start_and_execute_operation_within_window(
                conn, operation_id=op_id, mission_id=mission_id, executor=executor, now_fn=lambda: after,
            )
        except MissionWindowExpiredError:
            result_box["denied"] = True
        except Exception as e:  # noqa: BLE001
            errors.append(e)
        finally:
            conn.close()

    attempt_thread = threading.Thread(target=_start_attempt, daemon=True)
    attempt_thread.start()

    inspect_conn = _fresh_connection()
    try:
        assert _wait_until_blocked_on_lock(inspect_conn)
    finally:
        inspect_conn.close()

    checkpoint_and_pause(
        holder_conn, mission_id, pause_state=MissionState.PAUSED_WINDOW_REACHED,
        checkpoint_id=f"ckpt_race_{uuid.uuid4().hex[:12]}", **_CKPT_KWARGS,
    )
    holder_conn.close()

    attempt_thread.join(timeout=10)
    assert not errors, f"unexpected errors: {errors}"
    assert result_box.get("denied") is True
    assert executor.call_count == 0

    final_conn = _fresh_connection()
    try:
        assert get_operation(final_conn, op_id)["status"] == "AUTHORIZED"
        assert get_mission(final_conn, mission_id)["state"] == MissionState.PAUSED_WINDOW_REACHED.value
    finally:
        final_conn.close()


def test_start_vs_expiry_race_start_commits_first_settles_exactly_once():
    owner = _uid()
    setup_conn = _fresh_connection()
    try:
        mission_id = _seed_l3_mission(setup_conn, owner)
        base_now = datetime.now(timezone.utc)
        start_autonomous_window(setup_conn, mission_id=mission_id, now_fn=lambda: base_now)
        op_id = f"op_{uuid.uuid4().hex[:12]}"
        request_operation(setup_conn, id=op_id, idempotency_key=f"idem_{uuid.uuid4().hex[:12]}", kind="deploy", requested_by=owner, mission_id=mission_id)
        authorize_operation(setup_conn, op_id, tenant_id="t1", approved_by=_uid(), reason="ok")
    finally:
        setup_conn.close()

    hold_event = threading.Event()
    holder_conn = _fresh_connection()

    def _hold():
        with holder_conn.cursor() as cur:
            cur.execute("SELECT * FROM missions WHERE id = %s FOR UPDATE", (mission_id,))
            cur.fetchone()
        hold_event.set()

    holder_thread = threading.Thread(target=_hold, daemon=True)
    holder_thread.start()
    assert hold_event.wait(timeout=5)
    holder_thread.join(timeout=5)

    after = base_now + timedelta(seconds=DEFAULT_AUTONOMOUS_WINDOW_SECONDS + 1)
    result_box = {}
    errors = []

    def _expiry_attempt():
        conn = _fresh_connection()
        try:
            result_box["result"] = enforce_window_expiry(conn, mission_id=mission_id, now_fn=lambda: after, **_CKPT_KWARGS)
        except Exception as e:  # noqa: BLE001
            errors.append(e)
        finally:
            conn.close()

    attempt_thread = threading.Thread(target=_expiry_attempt, daemon=True)
    attempt_thread.start()

    inspect_conn = _fresh_connection()
    try:
        assert _wait_until_blocked_on_lock(inspect_conn)
    finally:
        inspect_conn.close()

    # Still holding the lock (holder_conn's open transaction): the REAL
    # start boundary wins the race, while the window is genuinely
    # ACTIVE (now_fn = base_now, before the deadline) -- durably
    # STARTS and immediately SETTLES the operation exactly once.
    holder_executor = RecordingTestExecutor()
    settled = start_and_execute_operation_within_window(
        holder_conn, operation_id=op_id, mission_id=mission_id, executor=holder_executor, now_fn=lambda: base_now,
    )
    assert settled["status"] == "SUCCEEDED"
    assert holder_executor.call_count == 1
    holder_conn.close()

    attempt_thread.join(timeout=10)
    assert not errors, f"unexpected errors: {errors}"
    assert result_box["result"].outcome is WindowEnforcementOutcome.PAUSED

    final_conn = _fresh_connection()
    try:
        assert get_operation(final_conn, op_id)["status"] == "SUCCEEDED"
        assert get_mission(final_conn, mission_id)["state"] == MissionState.PAUSED_WINDOW_REACHED.value
    finally:
        final_conn.close()

    # Never replayed by a further settlement attempt.
    settle_conn = _fresh_connection()
    try:
        executor2 = RecordingTestExecutor()
        retried = start_and_execute_operation_within_window(
            settle_conn, operation_id=op_id, mission_id=mission_id, executor=executor2, now_fn=lambda: after,
        )
        assert retried["status"] == "SUCCEEDED"
        assert executor2.call_count == 0
    finally:
        settle_conn.close()
