"""
Phase 15.5 -- LIVE_NEON_TEMP_BRANCH integration tests for
orca.mission.operation_store, covering spec section 16's required
scenarios A-M against real Neon Postgres AND real orca.godmode
authority (whatever backend ORNEUR_GODMODE_DATABASE_URL selects in
the running environment -- Supabase-backed in CI, matching how every
other Phase 15.5 authority decision in this codebase is made; SQLite
locally when unset). No mocked database, no mocked authority engine.

Skipped entirely when ORNEUR_MISSION_DATABASE_URL(_DIRECT) are unset,
matching tests/test_mission_store_live_neon.py's pattern.
"""
from __future__ import annotations

import os
import uuid

import pytest

from orca.mission.db import apply_schema, get_conn
from orca.mission.executor import ExecutionFailed, RecordingTestExecutor
from orca.mission.operation_store import (
    OperationConflictError,
    OperationNotFoundError,
    OperationStateError,
    SelfAuthorizationError,
    authorize_operation,
    cancel_operation,
    get_operation,
    request_operation,
    start_and_execute_operation,
)

pytestmark = pytest.mark.skipif(
    not (os.environ.get("ORNEUR_MISSION_DATABASE_URL") and os.environ.get("ORNEUR_MISSION_DATABASE_URL_DIRECT")),
    reason="LIVE_NEON_TEMP_BRANCH: requires ORNEUR_MISSION_DATABASE_URL(_DIRECT) pointing at a disposable Neon branch",
)

TENANT = "phase15-5-qualification-tenant"


def _fresh_connection():
    return get_conn(direct=False)


@pytest.fixture(scope="module", autouse=True)
def _ensure_schema():
    conn = get_conn(direct=True)
    try:
        apply_schema(conn)
        conn.commit()
    finally:
        conn.close()


def _oid() -> str:
    return f"op_{uuid.uuid4().hex[:12]}"


def _key() -> str:
    return f"idem_{uuid.uuid4().hex[:12]}"


def _request(conn, *, id=None, idempotency_key=None, kind="deploy", requested_by="user_alice", target="svc-a", parameters=None):
    return request_operation(
        conn, id=id or _oid(), idempotency_key=idempotency_key or _key(),
        kind=kind, requested_by=requested_by, target=target, parameters=parameters or {"version": "1.0.0"},
    )


class TestRequestAndIdempotency:
    def test_A_request_creates_real_row(self):
        conn = _fresh_connection()
        try:
            op, was_new = _request(conn)
            assert was_new is True
            assert op["status"] == "REQUESTED"
            assert op["parameters_fingerprint"]
        finally:
            conn.close()

    def test_B_idempotent_retry_same_key_returns_existing_operation(self):
        conn = _fresh_connection()
        try:
            key = _key()
            op1, new1 = _request(conn, idempotency_key=key, parameters={"version": "1.0.0"})
            op2, new2 = _request(conn, idempotency_key=key, parameters={"version": "1.0.0"})
            assert new1 is True
            assert new2 is False
            assert op1["id"] == op2["id"]
        finally:
            conn.close()

    def test_C_same_key_different_parameters_conflict(self):
        conn = _fresh_connection()
        try:
            key = _key()
            _request(conn, idempotency_key=key, parameters={"version": "1.0.0"})
            with pytest.raises(OperationConflictError):
                _request(conn, idempotency_key=key, parameters={"version": "2.0.0"})
        finally:
            conn.close()

    def test_M_database_unique_backstop_still_enforced(self):
        """Even bypassing request_operation() entirely, a raw duplicate
        INSERT on idempotency_key is rejected by the database itself."""
        conn = _fresh_connection()
        try:
            key = _key()
            op, _ = _request(conn, idempotency_key=key)
            with conn.cursor() as cur:
                with pytest.raises(Exception):
                    cur.execute(
                        "INSERT INTO operations (id, idempotency_key, kind, status, requested_at, requested_by) "
                        "VALUES (%s, %s, 'deploy', 'REQUESTED', %s, 'user_alice')",
                        (_oid(), key, op["requested_at"]),
                    )
            conn.rollback()
        finally:
            conn.close()


class TestSelfAuthorizationGuard:
    def test_D_requester_cannot_approve_own_operation(self):
        conn = _fresh_connection()
        try:
            op, _ = _request(conn, requested_by="user_alice")
            with pytest.raises(SelfAuthorizationError):
                authorize_operation(conn, op["id"], tenant_id=TENANT, approved_by="user_alice", reason="self-approval attempt")
            assert get_operation(conn, op["id"])["status"] == "REQUESTED"  # unchanged
        finally:
            conn.close()


class TestApprovalAndExecution:
    def test_E_valid_external_approval_authorizes(self):
        conn = _fresh_connection()
        try:
            op, _ = _request(conn, requested_by="user_alice")
            authorized_op, allowed = authorize_operation(conn, op["id"], tenant_id=TENANT, approved_by="user_bob", reason="qualification")
            assert allowed is True
            assert authorized_op["status"] == "AUTHORIZED"
        finally:
            conn.close()

    def test_F_authorized_operation_starts_and_succeeds(self):
        conn = _fresh_connection()
        try:
            op, _ = _request(conn, requested_by="user_alice")
            authorize_operation(conn, op["id"], tenant_id=TENANT, approved_by="user_bob", reason="qualification")
            executor = RecordingTestExecutor()
            result = start_and_execute_operation(conn, op["id"], executor)
            assert result["status"] == "SUCCEEDED"
            assert result["result_ref"] == f"test-result:{op['id']}"
            assert executor.call_count == 1
        finally:
            conn.close()

    def test_execution_failure_recorded_as_failed_not_generic(self):
        conn = _fresh_connection()
        try:
            op, _ = _request(conn, requested_by="user_alice")
            authorize_operation(conn, op["id"], tenant_id=TENANT, approved_by="user_bob", reason="qualification")
            executor = RecordingTestExecutor(fail_next=True)
            result = start_and_execute_operation(conn, op["id"], executor)
            assert result["status"] == "FAILED"
            assert "deliberate test failure" in result["result_ref"]
        finally:
            conn.close()

    def test_cannot_start_unauthorized_operation(self):
        conn = _fresh_connection()
        try:
            op, _ = _request(conn, requested_by="user_alice")
            executor = RecordingTestExecutor()
            with pytest.raises(OperationStateError):
                start_and_execute_operation(conn, op["id"], executor)
            assert executor.call_count == 0
        finally:
            conn.close()


class TestLostResponseAndProcessLoss:
    def test_G_retry_after_success_no_duplicate_side_effect(self):
        conn_a = _fresh_connection()
        op_id = None
        try:
            op, _ = _request(conn_a, requested_by="user_alice")
            op_id = op["id"]
            authorize_operation(conn_a, op_id, tenant_id=TENANT, approved_by="user_bob", reason="q")
            executor = RecordingTestExecutor()
            first = start_and_execute_operation(conn_a, op_id, executor)
            assert first["status"] == "SUCCEEDED"
            assert executor.call_count == 1

            # "Lost response, caller retries" -- same executor instance
            # would be a fresh one in reality, but reusing it here lets
            # us assert call_count didn't increase.
            second = start_and_execute_operation(conn_a, op_id, executor)
            assert second["status"] == "SUCCEEDED"
            assert second["result_ref"] == first["result_ref"]
            assert executor.call_count == 1  # NOT called again
        finally:
            conn_a.close()

    def test_H_process_loss_fresh_connection_reconstructs_exact_state(self):
        conn_a = _fresh_connection()
        op_id = None
        try:
            op, _ = _request(conn_a, requested_by="user_alice")
            op_id = op["id"]
            authorize_operation(conn_a, op_id, tenant_id=TENANT, approved_by="user_bob", reason="q")
        finally:
            conn_a.close()  # simulated process loss

        conn_b = _fresh_connection()
        try:
            reloaded = get_operation(conn_b, op_id)
            assert reloaded["status"] == "AUTHORIZED"
            executor = RecordingTestExecutor()
            result = start_and_execute_operation(conn_b, op_id, executor)
            assert result["status"] == "SUCCEEDED"
            assert executor.call_count == 1
        finally:
            conn_b.close()

        conn_c = _fresh_connection()
        try:
            final = get_operation(conn_c, op_id)
            assert final["status"] == "SUCCEEDED"
        finally:
            conn_c.close()


class TestApprovalBindingAndReuse:
    def test_I_authorizing_operation_a_does_not_affect_operation_b(self):
        conn = _fresh_connection()
        try:
            op_a, _ = _request(conn, requested_by="user_alice")
            op_b, _ = _request(conn, requested_by="user_alice")
            authorize_operation(conn, op_a["id"], tenant_id=TENANT, approved_by="user_bob", reason="q")
            assert get_operation(conn, op_a["id"])["status"] == "AUTHORIZED"
            assert get_operation(conn, op_b["id"])["status"] == "REQUESTED"  # untouched
        finally:
            conn.close()

    def test_J_cannot_reauthorize_already_authorized_operation(self):
        conn = _fresh_connection()
        try:
            op, _ = _request(conn, requested_by="user_alice")
            authorize_operation(conn, op["id"], tenant_id=TENANT, approved_by="user_bob", reason="q")
            with pytest.raises(OperationStateError):
                authorize_operation(conn, op["id"], tenant_id=TENANT, approved_by="user_carol", reason="second attempt")
        finally:
            conn.close()

    def test_authorize_missing_operation_raises(self):
        conn = _fresh_connection()
        try:
            with pytest.raises(OperationNotFoundError):
                authorize_operation(conn, "op_does_not_exist_xyz", tenant_id=TENANT, approved_by="user_bob", reason="q")
        finally:
            conn.close()


class TestCancellation:
    def test_K_cancelled_requested_operation_never_executes(self):
        conn = _fresh_connection()
        try:
            op, _ = _request(conn, requested_by="user_alice")
            cancelled = cancel_operation(conn, op["id"])
            assert cancelled["status"] == "CANCELLED"
            executor = RecordingTestExecutor()
            with pytest.raises(OperationStateError):
                authorize_operation(conn, op["id"], tenant_id=TENANT, approved_by="user_bob", reason="too late")
            # start_and_execute_operation treats an already-terminal
            # operation as a graceful idempotent no-op (same as
            # SUCCEEDED/FAILED) rather than raising -- consistent with
            # test_cancelled_authorized_operation_never_executes below.
            result = start_and_execute_operation(conn, op["id"], executor)
            assert result["status"] == "CANCELLED"
            assert executor.call_count == 0
        finally:
            conn.close()

    def test_cancelled_authorized_operation_never_executes(self):
        conn = _fresh_connection()
        try:
            op, _ = _request(conn, requested_by="user_alice")
            authorize_operation(conn, op["id"], tenant_id=TENANT, approved_by="user_bob", reason="q")
            cancel_operation(conn, op["id"])
            executor = RecordingTestExecutor()
            result = start_and_execute_operation(conn, op["id"], executor)
            assert result["status"] == "CANCELLED"  # returned as-is, not re-started
            assert executor.call_count == 0
        finally:
            conn.close()

    def test_terminal_operation_cannot_be_cancelled(self):
        conn = _fresh_connection()
        try:
            op, _ = _request(conn, requested_by="user_alice")
            authorize_operation(conn, op["id"], tenant_id=TENANT, approved_by="user_bob", reason="q")
            start_and_execute_operation(conn, op["id"], RecordingTestExecutor())
            with pytest.raises(OperationStateError):
                cancel_operation(conn, op["id"])
            assert get_operation(conn, op["id"])["status"] == "SUCCEEDED"  # unchanged
        finally:
            conn.close()


class TestConcurrency:
    def test_L_concurrent_execution_calls_executor_exactly_once(self):
        import threading

        conn_setup = _fresh_connection()
        op_id = None
        try:
            op, _ = _request(conn_setup, requested_by="user_alice")
            op_id = op["id"]
            authorize_operation(conn_setup, op_id, tenant_id=TENANT, approved_by="user_bob", reason="q")
        finally:
            conn_setup.close()

        executor = RecordingTestExecutor()
        results: list[dict] = []
        errors: list[Exception] = []

        def _worker():
            conn = _fresh_connection()
            try:
                result = start_and_execute_operation(conn, op_id, executor)
                results.append(result)
            except Exception as e:  # noqa: BLE001
                errors.append(e)
            finally:
                conn.close()

        threads = [threading.Thread(target=_worker) for _ in range(4)]
        for t in threads:
            t.start()
        for t in threads:
            t.join(timeout=20)

        assert executor.call_count == 1, f"executor invoked {executor.call_count} times, expected exactly 1"
        assert not errors, f"unexpected errors: {errors}"
        conn_check = _fresh_connection()
        try:
            final = get_operation(conn_check, op_id)
            assert final["status"] == "SUCCEEDED"
        finally:
            conn_check.close()

    def test_concurrent_requests_same_idempotency_key_one_operation_wins(self):
        import threading

        key = _key()
        created_ids: list[str] = []
        errors: list[Exception] = []

        def _worker():
            conn = _fresh_connection()
            try:
                op, _ = request_operation(
                    conn, id=_oid(), idempotency_key=key, kind="deploy",
                    requested_by="user_alice", target="svc-a", parameters={"version": "1.0.0"},
                )
                created_ids.append(op["id"])
            except Exception as e:  # noqa: BLE001
                errors.append(e)
            finally:
                conn.close()

        threads = [threading.Thread(target=_worker) for _ in range(5)]
        for t in threads:
            t.start()
        for t in threads:
            t.join(timeout=20)

        assert not errors, f"unexpected errors (all should have converged, not raised): {errors}"
        assert len(set(created_ids)) == 1, f"expected exactly one winning operation id, got {set(created_ids)}"
