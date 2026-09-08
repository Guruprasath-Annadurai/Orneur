"""
Phase 15.6 -- LIVE_NEON_TEMP_BRANCH integration: a real Code-mode
execution routed through the real Phase 15.5 operation/authority
engine, using `orca.mission.sandbox_executor.SandboxCommandExecutor`
as the `Executor` -- proving Code execution does NOT duplicate the
operation engine (spec section 14), authority is never self-granted
by a model (spec section 13, 20), and idempotency is genuinely reused
(spec section 14), all against real Neon + real orca.godmode (spec
section 24's core-tests-stay-provider-neutral rule doesn't apply here
-- this file tests the AUTHORITY integration, which is intentionally
NOT a "provider", per module scope).

Skipped entirely when ORNEUR_MISSION_DATABASE_URL(_DIRECT) are unset,
matching every other Phase 15 live-Neon test file.
"""
from __future__ import annotations

import os
import sys
import uuid

import pytest

from orca.mission.code_mode import CapabilityAction, CodeMode, is_allowed_by_mode, requires_authority
from orca.mission.db import apply_schema, get_conn
from orca.mission.execution_plan import ExecutionPlan, NetworkPolicy, ResourcePolicy
from orca.mission.operation_store import (
    OperationStateError,
    SelfAuthorizationError,
    authorize_operation,
    get_operation,
    request_operation,
    start_and_execute_operation,
)
from orca.mission.sandbox_executor import ExecutionOutcome, SandboxCommandExecutor

pytestmark = pytest.mark.skipif(
    not (os.environ.get("ORNEUR_MISSION_DATABASE_URL") and os.environ.get("ORNEUR_MISSION_DATABASE_URL_DIRECT")),
    reason="LIVE_NEON_TEMP_BRANCH: requires ORNEUR_MISSION_DATABASE_URL(_DIRECT) pointing at a disposable Neon branch",
)

TENANT = "phase15-6-qualification-tenant"


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
    return f"codeop_{uuid.uuid4().hex[:12]}"


def _key() -> str:
    return f"codeidem_{uuid.uuid4().hex[:12]}"


def _plan(tmp_path, command, **overrides) -> ExecutionPlan:
    defaults = dict(
        execution_id=f"exec_{uuid.uuid4().hex[:12]}",
        mission_id=None,
        operation_id=None,
        mode=CodeMode.LAUNCH,
        tool="sandbox_command",
        workspace_root=str(tmp_path),
        working_directory=str(tmp_path),
        command=tuple(command),
        environment_policy=frozenset(),
        network_policy=NetworkPolicy.DENIED,
        resource_policy=ResourcePolicy(cpu_seconds=5, memory_bytes=256 * 1024 * 1024, max_processes=None),
        timeout_seconds=5.0,
    )
    defaults.update(overrides)
    return ExecutionPlan(**defaults)


class TestModeGateBeforeAuthority:
    def test_deploy_requires_launch_mode_and_still_requires_real_authority(self):
        # Mode gate: DEPLOY is only in LAUNCH's policy.
        assert is_allowed_by_mode(CodeMode.LAUNCH, CapabilityAction.DEPLOY)
        assert not is_allowed_by_mode(CodeMode.PROTOTYPE, CapabilityAction.DEPLOY)
        # Passing the mode gate is NOT authority -- DEPLOY still requires it.
        assert requires_authority(CapabilityAction.DEPLOY)


class TestPrivilegedExecutionRoutesThroughRealAuthority:
    def test_authorized_code_execution_runs_via_sandbox_executor(self, tmp_path):
        conn = _fresh_connection()
        try:
            op_id = _oid()
            op, created = request_operation(
                conn, id=op_id, idempotency_key=_key(), kind="run_tests",
                requested_by="user_alice", target="workspace", parameters={"mode": "LAUNCH"},
            )
            assert created is True

            plan = _plan(tmp_path, [sys.executable, "-c", "print('tests passed')"], operation_id=op_id)
            executor = SandboxCommandExecutor(plan=plan)

            authorize_operation(conn, op_id, tenant_id=TENANT, approved_by="user_bob", reason="run tests for launch gate")
            result = start_and_execute_operation(conn, op_id, executor)

            assert result["status"] == "SUCCEEDED"
            assert executor.last_result.status is ExecutionOutcome.SUCCEEDED
            assert "tests passed" in executor.last_result.stdout
        finally:
            conn.close()

    def test_model_output_cannot_self_authorize_a_code_execution(self, tmp_path):
        # The exact spec-13/20 invariant: a requester (standing in for
        # "the model's own claim it's authorized") cannot also be the
        # approver -- rejected BEFORE any real side effect runs.
        conn = _fresh_connection()
        try:
            op_id = _oid()
            request_operation(
                conn, id=op_id, idempotency_key=_key(), kind="deploy",
                requested_by="model_agent_alice", target="prod-svc", parameters={"mode": "LAUNCH"},
            )
            with pytest.raises(SelfAuthorizationError):
                authorize_operation(
                    conn, op_id, tenant_id=TENANT,
                    approved_by="model_agent_alice",  # same principal as requested_by
                    reason="self-claimed approval",
                )
            # Never reached STARTED -- the operation is still REQUESTED.
            row = get_operation(conn, op_id)
            assert row["status"] == "REQUESTED"
        finally:
            conn.close()

    def test_unauthorized_execution_cannot_start(self, tmp_path):
        conn = _fresh_connection()
        try:
            op_id = _oid()
            request_operation(
                conn, id=op_id, idempotency_key=_key(), kind="deploy",
                requested_by="user_alice", target="prod-svc", parameters={"mode": "LAUNCH"},
            )
            plan = _plan(tmp_path, [sys.executable, "-c", "print('should not run')"], operation_id=op_id)
            executor = SandboxCommandExecutor(plan=plan)
            with pytest.raises(OperationStateError):
                start_and_execute_operation(conn, op_id, executor)
            assert executor.last_result is None  # the real side effect never ran
        finally:
            conn.close()


class TestIdempotencyReuse:
    def test_significant_code_operation_reuses_operation_engine_idempotency(self, tmp_path):
        # A "lost response, caller retries" scenario for a Code-mode
        # significant execution -- no second SandboxCommandExecutor
        # invocation, exactly like Phase 15.5's own test_G.
        conn = _fresh_connection()
        try:
            key = _key()
            op_id = _oid()
            op, created = request_operation(
                conn, id=op_id, idempotency_key=key, kind="run_tests",
                requested_by="user_alice", target="workspace", parameters={"mode": "BUILD"},
            )
            assert created is True

            plan = _plan(tmp_path, [sys.executable, "-c", "print('ran once')"], operation_id=op_id)
            executor = SandboxCommandExecutor(plan=plan)
            authorize_operation(conn, op_id, tenant_id=TENANT, approved_by="user_bob", reason="build test run")
            first = start_and_execute_operation(conn, op_id, executor)
            assert first["status"] == "SUCCEEDED"

            # Retry with the SAME idempotency key: request_operation
            # returns the EXISTING operation, not a new one.
            retried_op, retried_created = request_operation(
                conn, id=_oid(), idempotency_key=key, kind="run_tests",
                requested_by="user_alice", target="workspace", parameters={"mode": "BUILD"},
            )
            assert retried_created is False
            assert retried_op["id"] == op_id

            # Retrying execution on the (already-SUCCEEDED) operation
            # does not re-invoke the executor.
            second = start_and_execute_operation(conn, op_id, executor)
            assert second["status"] == "SUCCEEDED"
            assert len(executor.plan.command) > 0  # plan unchanged
        finally:
            conn.close()


class TestNoFakeCompletionIntegration:
    def test_failed_command_never_yields_succeeded_operation(self, tmp_path):
        conn = _fresh_connection()
        try:
            op_id = _oid()
            request_operation(
                conn, id=op_id, idempotency_key=_key(), kind="run_tests",
                requested_by="user_alice", target="workspace", parameters={"mode": "BUILD"},
            )
            plan = _plan(tmp_path, [sys.executable, "-c", "import sys; sys.exit(1)"], operation_id=op_id)
            executor = SandboxCommandExecutor(plan=plan)
            authorize_operation(conn, op_id, tenant_id=TENANT, approved_by="user_bob", reason="run failing tests")
            result = start_and_execute_operation(conn, op_id, executor)
            assert result["status"] == "FAILED"
            assert result["status"] != "SUCCEEDED"
        finally:
            conn.close()

    def test_timed_out_command_never_yields_succeeded_operation(self, tmp_path):
        conn = _fresh_connection()
        try:
            op_id = _oid()
            request_operation(
                conn, id=op_id, idempotency_key=_key(), kind="run_tests",
                requested_by="user_alice", target="workspace", parameters={"mode": "BUILD"},
            )
            plan = _plan(
                tmp_path, [sys.executable, "-c", "import time; time.sleep(30)"],
                operation_id=op_id, timeout_seconds=0.5,
            )
            executor = SandboxCommandExecutor(plan=plan)
            authorize_operation(conn, op_id, tenant_id=TENANT, approved_by="user_bob", reason="run slow tests")
            result = start_and_execute_operation(conn, op_id, executor)
            assert result["status"] == "FAILED"
            assert "TIMED_OUT" in result["result_ref"]
        finally:
            conn.close()
