"""
Phase 15.13 -- LIVE_NEON_TEMP_BRANCH: Reconnect + Idempotency
qualification against real Postgres.

Covers the canonical lost-response scenarios (spec sections 6-9), real
concurrent executor-race safety (section 10), two-device reconciliation
and same-key concurrency (sections 11-13), stale-authority and access-
control denial (sections 14, 26), the mission mutation-precondition
model for pause/resume (sections 15-17), reconnect strict read-onlyness
(section 4), and the secret-safety battery through reconciliation
summaries (section 23).

Skipped when ORNEUR_MISSION_DATABASE_URL(_DIRECT) are unset, matching
every other Phase 15 live-Neon test file.
"""
from __future__ import annotations

import os
import threading
import uuid
from datetime import datetime, timezone

import pytest

from orca.mission.db import apply_schema, get_conn
from orca.mission.mission_store import create_checkpoint, create_mission, get_checkpoint, get_mission, transition_mission
from orca.mission.executor import RecordingTestExecutor
from orca.mission.operation_store import (
    authorize_operation,
    request_operation,
    start_and_execute_operation,
)
from orca.mission.relay_reconnect import (
    CachedRelayView,
    CheckpointCurrency,
    RelayConnectionState,
    RelayFreshness,
    RelayMutationOutcome,
    RelayMutationPrecondition,
    RelayOperationTruth,
    RelayReconnectAccessDeniedError,
    RevisionCurrency,
    apply_mission_mutation_precondition,
    apply_relay_mission_mutation,
    check_checkpoint_currency,
    check_revision_currency,
    reconcile_operation,
    reconnect_to_mission,
)
from orca.mission.relay_security import (
    SessionSecurityInvalidError,
    create_relay_session,
    revoke_own_relay_session,
    touch_relay_session_securely,
)
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


def _seed_mission(conn, owner_user_id: str) -> str:
    mission_id = _mid()
    create_mission(
        conn, id=mission_id, repository="org/relay-reconnect-qual", branch="main", mode="BUILD",
        autonomy_level="L1", owner_user_id=owner_user_id, current_revision="rev1", workspace_id="ws_relay_reconnect",
    )
    return mission_id


def _advance_to_running(conn, mission_id: str) -> None:
    transition_mission(conn, mission_id, MissionState.PLANNING)
    transition_mission(conn, mission_id, MissionState.READY)
    transition_mission(conn, mission_id, MissionState.RUNNING)


def _seed_session(conn, owner_user_id: str, mission_id: str, *, mode=RelayMode.TRUSTED_DEVICE):
    device = register_device(conn, authenticated_user_id=owner_user_id, trust_level=DeviceTrustLevel.PUBLIC, name="dev")
    trust = DeviceTrustLevel.TRUSTED if mode is RelayMode.TRUSTED_DEVICE else DeviceTrustLevel.PUBLIC
    if trust is DeviceTrustLevel.TRUSTED:
        # register_device() unconditionally rejects TRUSTED -- use the low-level
        # test-only insertion path relay_security relies on internally is not
        # public, so exercise via PUBLIC device + PUBLIC_DEVICE mode instead
        # wherever TRUSTED is not the point of the test.
        mode = RelayMode.PUBLIC_DEVICE
    session = create_relay_session(conn, device_id=device.id, mission_id=mission_id, authenticated_user_id=owner_user_id, mode=mode)
    return device, session


# ── Canonical lost-response proof (spec sections 7, 26; THE core proof) ──

def test_lost_successful_response_reconnect_reports_confirmed_executor_count_still_one():
    owner = _uid()
    conn = _fresh_connection()
    try:
        mission_id = _seed_mission(conn, owner)
        device, session = _seed_session(conn, owner, mission_id)

        executor = RecordingTestExecutor()
        op_id = f"op_{uuid.uuid4().hex[:12]}"
        key = f"idem_{uuid.uuid4().hex[:12]}"
        op, created = request_operation(
            conn, id=op_id, idempotency_key=key, kind="deploy", requested_by=owner,
            mission_id=mission_id, target="prod", parameters={"version": "1.0"},
        )
        assert created is True
        approver = _uid()
        op, allowed = authorize_operation(conn, op_id, tenant_id="t1", approved_by=approver, reason="ok")
        assert allowed is True
        op = start_and_execute_operation(conn, op_id, executor)
        assert op["status"] == "SUCCEEDED"
        assert executor.call_count == 1

        # Simulate: the client never saw this response (connection dropped
        # before it arrived). A FRESH connection reconnects and reconciles.
        fresh_conn = _fresh_connection()
        try:
            result = reconnect_to_mission(fresh_conn, session_id=session.id, authenticated_user_id=owner)
            summaries = {s.operation_id: s for s in result.operations}
            assert summaries[op_id].truth is RelayOperationTruth.CONFIRMED
            assert summaries[op_id].status == "SUCCEEDED"
        finally:
            fresh_conn.close()

        # A deliberate retry of start_and_execute_operation() must NOT
        # recall the executor -- the exactly-once guarantee survives
        # reconnect/reconciliation.
        op_again = start_and_execute_operation(conn, op_id, executor)
        assert op_again["status"] == "SUCCEEDED"
        assert executor.call_count == 1
    finally:
        conn.close()


def test_lost_failure_response_reconnect_reports_failed_and_retry_does_not_reattempt():
    owner = _uid()
    conn = _fresh_connection()
    try:
        mission_id = _seed_mission(conn, owner)
        device, session = _seed_session(conn, owner, mission_id)

        executor = RecordingTestExecutor(fail_next=True)
        op_id = f"op_{uuid.uuid4().hex[:12]}"
        key = f"idem_{uuid.uuid4().hex[:12]}"
        request_operation(conn, id=op_id, idempotency_key=key, kind="deploy", requested_by=owner, mission_id=mission_id)
        authorize_operation(conn, op_id, tenant_id="t1", approved_by=_uid(), reason="ok")
        op = start_and_execute_operation(conn, op_id, executor)
        assert op["status"] == "FAILED"
        assert executor.call_count == 1

        summary = reconcile_operation(conn, session_id=session.id, authenticated_user_id=owner, operation_id=op_id)
        assert summary.truth is RelayOperationTruth.FAILED

        op_retry = start_and_execute_operation(conn, op_id, executor)
        assert op_retry["status"] == "FAILED"
        assert executor.call_count == 1  # never recalled
    finally:
        conn.close()


def test_started_with_lost_outcome_reconnect_reports_pending_never_confirmed_or_failed():
    """Simulates a crash boundary: STARTED was durably written, but the
    executor's own outcome write never landed (this test simply never
    calls start_and_execute_operation() to completion, mirroring a
    process that died between the two)."""
    owner = _uid()
    conn = _fresh_connection()
    try:
        mission_id = _seed_mission(conn, owner)
        device, session = _seed_session(conn, owner, mission_id)

        op_id = f"op_{uuid.uuid4().hex[:12]}"
        key = f"idem_{uuid.uuid4().hex[:12]}"
        request_operation(conn, id=op_id, idempotency_key=key, kind="deploy", requested_by=owner, mission_id=mission_id)
        authorize_operation(conn, op_id, tenant_id="t1", approved_by=_uid(), reason="ok")

        from orca.mission.operation_store import _write_operation_transition
        _write_operation_transition(conn, op_id, "STARTED")
        conn.commit()

        summary = reconcile_operation(conn, session_id=session.id, authenticated_user_id=owner, operation_id=op_id)
        assert summary.truth is RelayOperationTruth.PENDING
        assert summary.status == "STARTED"
    finally:
        conn.close()


# ── Real concurrent executor-race safety (spec section 10) ──────────

def test_concurrent_start_and_execute_from_two_real_connections_executes_exactly_once():
    owner = _uid()
    setup_conn = _fresh_connection()
    try:
        mission_id = _seed_mission(setup_conn, owner)
        op_id = f"op_{uuid.uuid4().hex[:12]}"
        key = f"idem_{uuid.uuid4().hex[:12]}"
        request_operation(setup_conn, id=op_id, idempotency_key=key, kind="deploy", requested_by=owner, mission_id=mission_id)
        authorize_operation(setup_conn, op_id, tenant_id="t1", approved_by=_uid(), reason="ok")
    finally:
        setup_conn.close()

    executor = RecordingTestExecutor()
    barrier = threading.Barrier(2)
    results = []

    def _worker():
        conn = _fresh_connection()
        try:
            barrier.wait(timeout=5)
            results.append(start_and_execute_operation(conn, op_id, executor))
        finally:
            conn.close()

    t1 = threading.Thread(target=_worker)
    t2 = threading.Thread(target=_worker)
    t1.start(); t2.start()
    t1.join(timeout=10); t2.join(timeout=10)

    assert len(results) == 2
    # The "losing" caller does NOT wait for the winner to finish
    # executing -- per start_and_execute_operation()'s own contract, it
    # observes whatever durable state exists at that instant (which may
    # still be STARTED, not yet SUCCEEDED) and returns immediately
    # without recalling the executor. Exactly-once is proven by
    # call_count, not by both in-thread results reading SUCCEEDED.
    assert all(r["status"] in ("STARTED", "SUCCEEDED") for r in results)
    assert executor.call_count == 1

    final_conn = _fresh_connection()
    try:
        from orca.mission.operation_store import get_operation
        final = get_operation(final_conn, op_id)
        assert final["status"] == "SUCCEEDED"
    finally:
        final_conn.close()


# ── Two-device reconciliation + same-key concurrency (sections 11-13) ──

def test_two_devices_observe_identical_durable_truth_neither_causes_reexecution():
    owner = _uid()
    conn = _fresh_connection()
    try:
        mission_id = _seed_mission(conn, owner)
        _, session_a = _seed_session(conn, owner, mission_id)
        _, session_b = _seed_session(conn, owner, mission_id)

        executor = RecordingTestExecutor()
        op_id = f"op_{uuid.uuid4().hex[:12]}"
        key = f"idem_{uuid.uuid4().hex[:12]}"
        request_operation(conn, id=op_id, idempotency_key=key, kind="deploy", requested_by=owner, mission_id=mission_id)
        authorize_operation(conn, op_id, tenant_id="t1", approved_by=_uid(), reason="ok")
        start_and_execute_operation(conn, op_id, executor)
        assert executor.call_count == 1

        sum_a = reconcile_operation(conn, session_id=session_a.id, authenticated_user_id=owner, operation_id=op_id)
        sum_b = reconcile_operation(conn, session_id=session_b.id, authenticated_user_id=owner, operation_id=op_id)
        assert sum_a.truth is sum_b.truth is RelayOperationTruth.CONFIRMED
        assert sum_a.status == sum_b.status == "SUCCEEDED"
        assert executor.call_count == 1
    finally:
        conn.close()


def test_two_connections_same_idempotency_key_concurrent_submission_produces_one_operation():
    owner = _uid()
    setup_conn = _fresh_connection()
    try:
        mission_id = _seed_mission(setup_conn, owner)
    finally:
        setup_conn.close()

    key = f"idem_{uuid.uuid4().hex[:12]}"
    barrier = threading.Barrier(2)
    outcomes = []

    def _worker(op_id):
        conn = _fresh_connection()
        try:
            barrier.wait(timeout=5)
            row, created = request_operation(
                conn, id=op_id, idempotency_key=key, kind="deploy", requested_by=owner,
                mission_id=mission_id, target="prod", parameters={"version": "1.0"},
            )
            outcomes.append((row["id"], created))
        finally:
            conn.close()

    t1 = threading.Thread(target=_worker, args=(f"op_{uuid.uuid4().hex[:12]}",))
    t2 = threading.Thread(target=_worker, args=(f"op_{uuid.uuid4().hex[:12]}",))
    t1.start(); t2.start()
    t1.join(timeout=10); t2.join(timeout=10)

    assert len(outcomes) == 2
    ids = {row_id for row_id, _created in outcomes}
    assert len(ids) == 1  # exactly one durable operation row, regardless of which caller "won"
    created_flags = [c for _id, c in outcomes]
    assert created_flags.count(True) == 1
    assert created_flags.count(False) == 1


# ── Access control: cross-user / cross-mission denial (sections 26, 33) ──

def test_cross_user_operation_lookup_is_denied():
    owner = _uid()
    other = _uid()
    conn = _fresh_connection()
    try:
        mission_id = _seed_mission(conn, owner)
        _, owner_session = _seed_session(conn, owner, mission_id)
        other_mission_id = _seed_mission(conn, other)
        _, other_session = _seed_session(conn, other, other_mission_id)

        op_id = f"op_{uuid.uuid4().hex[:12]}"
        request_operation(conn, id=op_id, idempotency_key=f"idem_{uuid.uuid4().hex[:12]}", kind="deploy", requested_by=owner, mission_id=mission_id)

        with pytest.raises(RelayReconnectAccessDeniedError):
            reconcile_operation(conn, session_id=other_session.id, authenticated_user_id=other, operation_id=op_id)
    finally:
        conn.close()


def test_cross_mission_operation_lookup_by_same_user_is_denied():
    owner = _uid()
    conn = _fresh_connection()
    try:
        mission_a = _seed_mission(conn, owner)
        mission_b = _seed_mission(conn, owner)
        _, session_b = _seed_session(conn, owner, mission_b)

        op_id = f"op_{uuid.uuid4().hex[:12]}"
        request_operation(conn, id=op_id, idempotency_key=f"idem_{uuid.uuid4().hex[:12]}", kind="deploy", requested_by=owner, mission_id=mission_a)

        with pytest.raises(RelayReconnectAccessDeniedError):
            reconcile_operation(conn, session_id=session_b.id, authenticated_user_id=owner, operation_id=op_id)
    finally:
        conn.close()


# ── Reconnect is strictly read-only (spec section 4) ─────────────────

def test_reconnect_never_mutates_operation_or_mission_state():
    owner = _uid()
    conn = _fresh_connection()
    try:
        mission_id = _seed_mission(conn, owner)
        device, session = _seed_session(conn, owner, mission_id)
        op_id = f"op_{uuid.uuid4().hex[:12]}"
        request_operation(conn, id=op_id, idempotency_key=f"idem_{uuid.uuid4().hex[:12]}", kind="deploy", requested_by=owner, mission_id=mission_id)

        mission_before = get_mission(conn, mission_id)
        from orca.mission.operation_store import get_operation
        op_before = get_operation(conn, op_id)

        result = reconnect_to_mission(conn, session_id=session.id, authenticated_user_id=owner)
        assert result.mission_id == mission_id

        mission_after = get_mission(conn, mission_id)
        op_after = get_operation(conn, op_id)
        assert mission_after["state"] == mission_before["state"]
        assert mission_after["updated_at"] == mission_before["updated_at"]
        assert op_after == op_before
    finally:
        conn.close()


# ── Mission mutation precondition (spec sections 15-17) ─────────────

def test_stale_pause_request_reports_stale_conflict_not_silent_overwrite():
    owner = _uid()
    conn = _fresh_connection()
    try:
        mission_id = _seed_mission(conn, owner)
        # mission starts in DRAFT; move it to RUNNING first via the real state machine
        from orca.mission.mission_store import transition_mission
        transition_mission(conn, mission_id, MissionState.PLANNING)
        transition_mission(conn, mission_id, MissionState.READY)
        transition_mission(conn, mission_id, MissionState.RUNNING)

        # A device believes the mission is still READY (stale view) and
        # tries to pause it.
        precondition = RelayMutationPrecondition(mission_id=mission_id, expected_state=MissionState.READY)
        result = apply_mission_mutation_precondition(conn, precondition, new_state=MissionState.PAUSED_USER)
        assert result.outcome is RelayMutationOutcome.STALE_CONFLICT
        assert get_mission(conn, mission_id)["state"] == MissionState.RUNNING.value
    finally:
        conn.close()


def test_simultaneous_identical_pause_requests_reconcile_safely():
    owner = _uid()
    conn = _fresh_connection()
    try:
        mission_id = _seed_mission(conn, owner)
        from orca.mission.mission_store import transition_mission
        transition_mission(conn, mission_id, MissionState.PLANNING)
        transition_mission(conn, mission_id, MissionState.READY)
        transition_mission(conn, mission_id, MissionState.RUNNING)

        precondition = RelayMutationPrecondition(mission_id=mission_id, expected_state=MissionState.RUNNING)
        first = apply_mission_mutation_precondition(conn, precondition, new_state=MissionState.PAUSED_USER)
        assert first.outcome is RelayMutationOutcome.APPLIED

        # A second, racing, identical PAUSE request against the SAME
        # (now stale) expectation reconciles as an idempotent no-op,
        # not a hard error.
        second = apply_mission_mutation_precondition(conn, precondition, new_state=MissionState.PAUSED_USER)
        assert second.outcome is RelayMutationOutcome.APPLIED
        assert get_mission(conn, mission_id)["state"] == MissionState.PAUSED_USER.value
    finally:
        conn.close()


def test_illegal_mutation_with_accurate_expectation_is_denied_not_stale():
    owner = _uid()
    conn = _fresh_connection()
    try:
        mission_id = _seed_mission(conn, owner)
        # mission is in DRAFT (its real, freshly-created state) -- caller's
        # expectation is accurate, but resuming a DRAFT mission is illegal.
        precondition = RelayMutationPrecondition(mission_id=mission_id, expected_state=MissionState.DRAFT)
        result = apply_mission_mutation_precondition(conn, precondition, new_state=MissionState.RUNNING)
        assert result.outcome is RelayMutationOutcome.DENIED
    finally:
        conn.close()


# ── Secret redaction in a real reconciliation round-trip (section 23) ──

def test_secret_battery_does_not_survive_into_reconciliation_summary():
    owner = _uid()
    conn = _fresh_connection()
    try:
        mission_id = _seed_mission(conn, owner)
        device, session = _seed_session(conn, owner, mission_id)

        class _LeakyExecutor:
            call_count = 0

            def execute(self, *, operation_id, kind, mission_id):
                self.call_count += 1
                return "connection succeeded via postgres://dbuser:S3cr3tPassw0rd@db.internal:5432/prod"

        op_id = f"op_{uuid.uuid4().hex[:12]}"
        request_operation(conn, id=op_id, idempotency_key=f"idem_{uuid.uuid4().hex[:12]}", kind="deploy", requested_by=owner, mission_id=mission_id)
        authorize_operation(conn, op_id, tenant_id="t1", approved_by=_uid(), reason="ok")
        start_and_execute_operation(conn, op_id, _LeakyExecutor())

        summary = reconcile_operation(conn, session_id=session.id, authenticated_user_id=owner, operation_id=op_id)
        assert "S3cr3tPassw0rd" not in (summary.result_ref or "")
    finally:
        conn.close()


# ═════════════════════════════════════════════════════════════════════
# Phase 15.13.1 -- Relay Mutation Atomicity + Reconnect-State Closure
# ═════════════════════════════════════════════════════════════════════

# ── Section 1: Relay mutation must require a security-valid session ──

def test_relay_mutation_for_a_different_mission_is_denied():
    owner = _uid()
    conn = _fresh_connection()
    try:
        mission_a = _seed_mission(conn, owner)
        mission_b = _seed_mission(conn, owner)
        _advance_to_running(conn, mission_a)
        _, session_bound_to_a = _seed_session(conn, owner, mission_a)

        precondition = RelayMutationPrecondition(mission_id=mission_b, expected_state=MissionState.RUNNING)
        with pytest.raises(RelayReconnectAccessDeniedError):
            apply_relay_mission_mutation(
                conn, session_id=session_bound_to_a.id, authenticated_user_id=owner,
                precondition=precondition, new_state=MissionState.PAUSED_USER,
            )
        # neither mission's durable state was touched
        assert get_mission(conn, mission_a)["state"] == MissionState.RUNNING.value
        assert get_mission(conn, mission_b)["state"] == MissionState.DRAFT.value
    finally:
        conn.close()


def test_relay_mutation_by_a_different_user_is_denied():
    owner = _uid()
    other = _uid()
    conn = _fresh_connection()
    try:
        mission = _seed_mission(conn, owner)
        _advance_to_running(conn, mission)
        other_mission = _seed_mission(conn, other)
        _, other_session = _seed_session(conn, other, other_mission)

        precondition = RelayMutationPrecondition(mission_id=mission, expected_state=MissionState.RUNNING)
        with pytest.raises(RelayReconnectAccessDeniedError):
            apply_relay_mission_mutation(
                conn, session_id=other_session.id, authenticated_user_id=other,
                precondition=precondition, new_state=MissionState.PAUSED_USER,
            )
        assert get_mission(conn, mission)["state"] == MissionState.RUNNING.value
    finally:
        conn.close()


def test_relay_mutation_with_revoked_session_is_denied():
    owner = _uid()
    conn = _fresh_connection()
    try:
        mission = _seed_mission(conn, owner)
        _advance_to_running(conn, mission)
        _, session = _seed_session(conn, owner, mission)
        revoke_own_relay_session(conn, session.id, authenticated_user_id=owner)

        precondition = RelayMutationPrecondition(mission_id=mission, expected_state=MissionState.RUNNING)
        with pytest.raises(SessionSecurityInvalidError):
            apply_relay_mission_mutation(
                conn, session_id=session.id, authenticated_user_id=owner,
                precondition=precondition, new_state=MissionState.PAUSED_USER,
            )
        assert get_mission(conn, mission)["state"] == MissionState.RUNNING.value
    finally:
        conn.close()


def test_relay_mutation_with_a_valid_session_and_matching_mission_succeeds():
    owner = _uid()
    conn = _fresh_connection()
    try:
        mission = _seed_mission(conn, owner)
        _advance_to_running(conn, mission)
        _, session = _seed_session(conn, owner, mission)

        precondition = RelayMutationPrecondition(mission_id=mission, expected_state=MissionState.RUNNING)
        result = apply_relay_mission_mutation(
            conn, session_id=session.id, authenticated_user_id=owner,
            precondition=precondition, new_state=MissionState.PAUSED_USER,
        )
        assert result.outcome is RelayMutationOutcome.APPLIED
        assert get_mission(conn, mission)["state"] == MissionState.PAUSED_USER.value
    finally:
        conn.close()


# ── Section 3: real concurrent stale-write race (atomic precondition) ──

def test_real_two_device_concurrent_mutation_race_is_atomic():
    """Two REAL Relay sessions (two devices) for the SAME user/mission
    race to pause the SAME mission from the SAME observed state,
    forced to genuine simultaneity via a threading.Barrier across two
    independent DB connections. Exactly one wins (APPLIED); the other,
    after acquiring the row lock, observes the ALREADY-CHANGED durable
    state and reports STALE_CONFLICT -- never applying a stale
    mutation. This proves the lock and the precondition check observe
    the SAME row version, not merely that the final state is correct
    (which sequential calls would also achieve)."""
    owner = _uid()
    setup_conn = _fresh_connection()
    try:
        mission_id = _seed_mission(setup_conn, owner)
        _advance_to_running(setup_conn, mission_id)
        device_a, session_a = _seed_session(setup_conn, owner, mission_id)
        device_b, session_b = _seed_session(setup_conn, owner, mission_id)
    finally:
        setup_conn.close()

    precondition = RelayMutationPrecondition(mission_id=mission_id, expected_state=MissionState.RUNNING)
    barrier = threading.Barrier(2)
    results = []
    errors = []

    def _worker(session_id):
        conn = _fresh_connection()
        try:
            barrier.wait(timeout=5)
            result = apply_relay_mission_mutation(
                conn, session_id=session_id, authenticated_user_id=owner,
                precondition=precondition, new_state=MissionState.PAUSED_USER,
            )
            results.append(result.outcome)
        except Exception as e:  # noqa: BLE001
            errors.append(e)
        finally:
            conn.close()

    t1 = threading.Thread(target=_worker, args=(session_a.id,))
    t2 = threading.Thread(target=_worker, args=(session_b.id,))
    t1.start(); t2.start()
    t1.join(timeout=15); t2.join(timeout=15)

    assert not errors, f"unexpected errors: {errors}"
    assert len(results) == 2
    assert sorted(o.value for o in results) == ["APPLIED", "STALE_CONFLICT"]

    final_conn = _fresh_connection()
    try:
        final = get_mission(final_conn, mission_id)
        assert final["state"] == MissionState.PAUSED_USER.value
    finally:
        final_conn.close()


# ── Section 4: precondition must include revision ────────────────────

def test_revision_matrix_same_state_same_revision_is_eligible():
    owner = _uid()
    conn = _fresh_connection()
    try:
        mission = _seed_mission(conn, owner)  # created with current_revision="rev1"
        _advance_to_running(conn, mission)
        _, session = _seed_session(conn, owner, mission)

        precondition = RelayMutationPrecondition(mission_id=mission, expected_state=MissionState.RUNNING, expected_revision="rev1")
        result = apply_relay_mission_mutation(
            conn, session_id=session.id, authenticated_user_id=owner,
            precondition=precondition, new_state=MissionState.PAUSED_USER,
        )
        assert result.outcome is RelayMutationOutcome.APPLIED
    finally:
        conn.close()


def test_revision_matrix_same_state_stale_revision_is_conflict():
    owner = _uid()
    conn = _fresh_connection()
    try:
        mission = _seed_mission(conn, owner)
        _advance_to_running(conn, mission)
        _, session = _seed_session(conn, owner, mission)

        precondition = RelayMutationPrecondition(mission_id=mission, expected_state=MissionState.RUNNING, expected_revision="rev0-stale")
        result = apply_relay_mission_mutation(
            conn, session_id=session.id, authenticated_user_id=owner,
            precondition=precondition, new_state=MissionState.PAUSED_USER,
        )
        assert result.outcome is RelayMutationOutcome.STALE_CONFLICT
        assert get_mission(conn, mission)["state"] == MissionState.RUNNING.value
    finally:
        conn.close()


def test_revision_matrix_different_state_same_revision_is_conflict():
    owner = _uid()
    conn = _fresh_connection()
    try:
        mission = _seed_mission(conn, owner)
        _advance_to_running(conn, mission)
        _, session = _seed_session(conn, owner, mission)

        precondition = RelayMutationPrecondition(mission_id=mission, expected_state=MissionState.READY, expected_revision="rev1")
        result = apply_relay_mission_mutation(
            conn, session_id=session.id, authenticated_user_id=owner,
            precondition=precondition, new_state=MissionState.PAUSED_USER,
        )
        assert result.outcome is RelayMutationOutcome.STALE_CONFLICT
        assert get_mission(conn, mission)["state"] == MissionState.RUNNING.value
    finally:
        conn.close()


def test_revision_matrix_both_stale_is_conflict():
    owner = _uid()
    conn = _fresh_connection()
    try:
        mission = _seed_mission(conn, owner)
        _advance_to_running(conn, mission)
        _, session = _seed_session(conn, owner, mission)

        precondition = RelayMutationPrecondition(mission_id=mission, expected_state=MissionState.READY, expected_revision="rev0-stale")
        result = apply_relay_mission_mutation(
            conn, session_id=session.id, authenticated_user_id=owner,
            precondition=precondition, new_state=MissionState.PAUSED_USER,
        )
        assert result.outcome is RelayMutationOutcome.STALE_CONFLICT
        assert get_mission(conn, mission)["state"] == MissionState.RUNNING.value
    finally:
        conn.close()


# ── Section 5: minimal edit-conflict primitive (check_revision_currency) ──

def test_check_revision_currency_matches_is_current():
    owner = _uid()
    conn = _fresh_connection()
    try:
        mission = _seed_mission(conn, owner)
        _, session = _seed_session(conn, owner, mission)
        result = check_revision_currency(
            conn, session_id=session.id, authenticated_user_id=owner, mission_id=mission, expected_revision="rev1",
        )
        assert result is RevisionCurrency.CURRENT
    finally:
        conn.close()


def test_check_revision_currency_mismatch_is_stale_conflict():
    owner = _uid()
    conn = _fresh_connection()
    try:
        mission = _seed_mission(conn, owner)
        _, session = _seed_session(conn, owner, mission)
        result = check_revision_currency(
            conn, session_id=session.id, authenticated_user_id=owner, mission_id=mission, expected_revision="rev0-stale",
        )
        assert result is RevisionCurrency.STALE_CONFLICT
    finally:
        conn.close()


def test_check_revision_currency_cross_mission_is_denied():
    owner = _uid()
    conn = _fresh_connection()
    try:
        mission_a = _seed_mission(conn, owner)
        mission_b = _seed_mission(conn, owner)
        _, session_bound_to_a = _seed_session(conn, owner, mission_a)
        with pytest.raises(RelayReconnectAccessDeniedError):
            check_revision_currency(
                conn, session_id=session_bound_to_a.id, authenticated_user_id=owner,
                mission_id=mission_b, expected_revision="rev1",
            )
    finally:
        conn.close()


# ── Section 6: checkpoint currentness ─────────────────────────────────

def test_checkpoint_matching_mission_revision_is_current():
    owner = _uid()
    conn = _fresh_connection()
    try:
        mission = _seed_mission(conn, owner)
        _, session = _seed_session(conn, owner, mission)
        checkpoint = create_checkpoint(
            conn, id=f"ckpt_{uuid.uuid4().hex[:12]}", mission_id=mission, mission_state=MissionState.DRAFT,
            repository="org/relay-reconnect-qual", current_revision="rev1",
        )
        result = check_checkpoint_currency(conn, session_id=session.id, authenticated_user_id=owner, checkpoint_id=checkpoint.id)
        assert result is CheckpointCurrency.CURRENT
    finally:
        conn.close()


def test_checkpoint_stale_after_mission_advances_but_history_preserved():
    owner = _uid()
    conn = _fresh_connection()
    try:
        mission = _seed_mission(conn, owner)
        _, session = _seed_session(conn, owner, mission)
        checkpoint = create_checkpoint(
            conn, id=f"ckpt_{uuid.uuid4().hex[:12]}", mission_id=mission, mission_state=MissionState.DRAFT,
            repository="org/relay-reconnect-qual", current_revision="rev1",
        )
        # Simulate the mission advancing to a new revision (test-only
        # direct write -- no mission_store function mutates
        # current_revision after creation, matching the established
        # "fabricate an adversarial row via raw SQL" pattern used
        # elsewhere in this test suite for device/mode-mismatch rows).
        with conn.cursor() as cur:
            cur.execute("UPDATE missions SET current_revision = %s WHERE id = %s", ("rev2", mission))
        conn.commit()

        result = check_checkpoint_currency(conn, session_id=session.id, authenticated_user_id=owner, checkpoint_id=checkpoint.id)
        assert result is CheckpointCurrency.STALE

        # the checkpoint itself is untouched -- still present, still rev1
        reloaded = get_checkpoint(conn, checkpoint.id)
        assert reloaded is not None
        assert reloaded.current_revision == "rev1"
    finally:
        conn.close()


def test_checkpoint_currency_cross_mission_is_denied():
    owner = _uid()
    conn = _fresh_connection()
    try:
        mission_a = _seed_mission(conn, owner)
        mission_b = _seed_mission(conn, owner)
        _, session_bound_to_b = _seed_session(conn, owner, mission_b)
        checkpoint = create_checkpoint(
            conn, id=f"ckpt_{uuid.uuid4().hex[:12]}", mission_id=mission_a, mission_state=MissionState.DRAFT,
            repository="org/relay-reconnect-qual", current_revision="rev1",
        )
        with pytest.raises(RelayReconnectAccessDeniedError):
            check_checkpoint_currency(conn, session_id=session_bound_to_b.id, authenticated_user_id=owner, checkpoint_id=checkpoint.id)
    finally:
        conn.close()


# ── Section 7: cancelled-mission stale-control proof ─────────────────

def test_stale_device_cannot_mutate_a_durably_cancelled_mission():
    owner = _uid()
    conn = _fresh_connection()
    try:
        mission = _seed_mission(conn, owner)
        _advance_to_running(conn, mission)
        _, stale_session = _seed_session(conn, owner, mission)

        # Device B (a separate, real, valid path -- not Relay-mediated
        # here, matching "durably transitions through a valid path")
        # cancels the mission.
        transition_mission(conn, mission, MissionState.CANCELLED)
        assert get_mission(conn, mission)["state"] == MissionState.CANCELLED.value

        # Device A, still holding its stale RUNNING precondition,
        # attempts to pause.
        precondition = RelayMutationPrecondition(mission_id=mission, expected_state=MissionState.RUNNING)
        result = apply_relay_mission_mutation(
            conn, session_id=stale_session.id, authenticated_user_id=owner,
            precondition=precondition, new_state=MissionState.PAUSED_USER,
        )
        assert result.outcome is RelayMutationOutcome.STALE_CONFLICT
        assert get_mission(conn, mission)["state"] == MissionState.CANCELLED.value

        # ...and cannot "resume" it either.
        resume_precondition = RelayMutationPrecondition(mission_id=mission, expected_state=MissionState.PAUSED_USER)
        resume_result = apply_relay_mission_mutation(
            conn, session_id=stale_session.id, authenticated_user_id=owner,
            precondition=resume_precondition, new_state=MissionState.RUNNING,
        )
        assert resume_result.outcome is RelayMutationOutcome.STALE_CONFLICT
        assert get_mission(conn, mission)["state"] == MissionState.CANCELLED.value

        # Reconnect observes CANCELLED as durable truth.
        reconnect_result = reconnect_to_mission(conn, session_id=stale_session.id, authenticated_user_id=owner)
        assert reconnect_result.snapshot.mission_state == MissionState.CANCELLED.value
    finally:
        conn.close()


# ── Section 8: operational network/freshness truth lifecycle ─────────

def test_network_truth_lifecycle_offline_reconnecting_connected():
    """Drives a REAL CachedRelayView through the canonical simulated
    flow using a REAL security-valid server read for the successful
    leg -- not enum membership alone."""
    owner = _uid()
    conn = _fresh_connection()
    try:
        mission = _seed_mission(conn, owner)
        _, session = _seed_session(conn, owner, mission)

        view = CachedRelayView.initial()
        assert view.connection_state is RelayConnectionState.OFFLINE
        assert view.freshness is RelayFreshness.STALE

        view.mark_connection_lost()
        assert view.connection_state is RelayConnectionState.OFFLINE
        assert view.freshness is RelayFreshness.STALE

        view.begin_reconnecting()
        assert view.connection_state is RelayConnectionState.RECONNECTING
        assert view.freshness is RelayFreshness.STALE

        result = reconnect_to_mission(conn, session_id=session.id, authenticated_user_id=owner)
        view.apply_successful_reconnect(result)
        assert view.connection_state is RelayConnectionState.CONNECTED
        assert view.freshness is RelayFreshness.CURRENT
    finally:
        conn.close()


def test_network_truth_lifecycle_failed_reconnect_stays_offline_and_stale():
    owner = _uid()
    conn = _fresh_connection()
    try:
        mission = _seed_mission(conn, owner)
        _, session = _seed_session(conn, owner, mission)
        revoke_own_relay_session(conn, session.id, authenticated_user_id=owner)

        view = CachedRelayView(connection_state=RelayConnectionState.CONNECTED, freshness=RelayFreshness.CURRENT)
        view.mark_connection_lost()
        view.begin_reconnecting()
        assert view.connection_state is RelayConnectionState.RECONNECTING

        try:
            reconnect_to_mission(conn, session_id=session.id, authenticated_user_id=owner)
            raised = False
        except SessionSecurityInvalidError:
            raised = True
        assert raised, "a revoked session must not produce a successful reconnect"
        view.record_failed_reconnect()

        # A failed reconnect must NEVER relabel the cached snapshot CURRENT.
        assert view.connection_state is RelayConnectionState.OFFLINE
        assert view.freshness is RelayFreshness.STALE
    finally:
        conn.close()
