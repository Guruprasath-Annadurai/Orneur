"""
Phase 15.6.1 -- LIVE_NEON_TEMP_BRANCH: proves the VERIFIED container
sandbox does not bypass Phase 15.5 authority. Sandboxing and
authorization are orthogonal (spec section 7) -- a stronger execution
boundary must not become a second way to skip
`orca.mission.operation_store`/`orca.godmode`.

Skipped when ORNEUR_MISSION_DATABASE_URL(_DIRECT) are unset, matching
every other Phase 15 live-Neon test file. Additionally skipped when
Docker is unavailable on the runner.
"""
from __future__ import annotations

import os
import uuid

import pytest

from orca.mission.container_executor import ContainerCommandExecutor, is_docker_available
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
from orca.mission.sandbox_executor import ExecutionOutcome, ExecutionPath

pytestmark = [
    pytest.mark.skipif(
        not (os.environ.get("ORNEUR_MISSION_DATABASE_URL") and os.environ.get("ORNEUR_MISSION_DATABASE_URL_DIRECT")),
        reason="LIVE_NEON_TEMP_BRANCH: requires ORNEUR_MISSION_DATABASE_URL(_DIRECT) pointing at a disposable Neon branch",
    ),
    pytest.mark.skipif(not is_docker_available(), reason="Docker daemon unavailable on this runner"),
]

TENANT = "phase15-6-1-qualification-tenant"


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
    return f"ctropid_{uuid.uuid4().hex[:12]}"


def _key() -> str:
    return f"ctridem_{uuid.uuid4().hex[:12]}"


def _plan(tmp_path, command, **overrides) -> ExecutionPlan:
    defaults = dict(
        execution_id=f"ctrexec_{uuid.uuid4().hex[:12]}", mission_id=None, operation_id=None,
        mode="LAUNCH", tool="container_command",
        workspace_root=str(tmp_path), working_directory=str(tmp_path),
        command=tuple(command), environment_policy=frozenset(),
        network_policy=NetworkPolicy.DENIED,
        resource_policy=ResourcePolicy(cpu_seconds=5, memory_bytes=128 * 1024 * 1024, max_processes=32),
        timeout_seconds=20.0,
    )
    defaults.update(overrides)
    return ExecutionPlan(**defaults)


def test_authorized_container_execution_runs_via_real_authority(tmp_path):
    conn = _fresh_connection()
    try:
        op_id = _oid()
        op, created = request_operation(
            conn, id=op_id, idempotency_key=_key(), kind="run_tests",
            requested_by="user_alice", target="workspace", parameters={"mode": "LAUNCH", "sandbox": "container"},
        )
        assert created is True

        plan = _plan(tmp_path, ["python3", "-c", "print('container tests passed')"], operation_id=op_id)
        executor = ContainerCommandExecutor(plan=plan)

        authorize_operation(conn, op_id, tenant_id=TENANT, approved_by="user_bob", reason="run tests in verified sandbox")
        result = start_and_execute_operation(conn, op_id, executor)

        assert result["status"] == "SUCCEEDED"
        assert executor.last_result.execution_path == ExecutionPath.CONTAINER_SANDBOX.value
        assert "container tests passed" in executor.last_result.stdout
    finally:
        conn.close()


def test_container_sandbox_does_not_bypass_self_authorization_guard(tmp_path):
    # The stronger sandbox is not a second path around Phase 15.5's
    # authority guard -- self-authorization is rejected identically
    # regardless of which executor will eventually run the command.
    conn = _fresh_connection()
    try:
        op_id = _oid()
        request_operation(
            conn, id=op_id, idempotency_key=_key(), kind="deploy",
            requested_by="model_agent_alice", target="prod-svc", parameters={"mode": "LAUNCH", "sandbox": "container"},
        )
        with pytest.raises(SelfAuthorizationError):
            authorize_operation(
                conn, op_id, tenant_id=TENANT,
                approved_by="model_agent_alice",
                reason="self-claimed approval via container sandbox",
            )
        row = get_operation(conn, op_id)
        assert row["status"] == "REQUESTED"
    finally:
        conn.close()


def test_container_sandbox_cannot_start_without_authorization(tmp_path):
    conn = _fresh_connection()
    try:
        op_id = _oid()
        request_operation(
            conn, id=op_id, idempotency_key=_key(), kind="deploy",
            requested_by="user_alice", target="prod-svc", parameters={"mode": "LAUNCH", "sandbox": "container"},
        )
        plan = _plan(tmp_path, ["python3", "-c", "print('should not run')"], operation_id=op_id)
        executor = ContainerCommandExecutor(plan=plan)
        with pytest.raises(OperationStateError):
            start_and_execute_operation(conn, op_id, executor)
        assert executor.last_result is None
    finally:
        conn.close()


def test_container_execution_failure_never_yields_succeeded_operation(tmp_path):
    conn = _fresh_connection()
    try:
        op_id = _oid()
        request_operation(
            conn, id=op_id, idempotency_key=_key(), kind="run_tests",
            requested_by="user_alice", target="workspace", parameters={"mode": "BUILD", "sandbox": "container"},
        )
        plan = _plan(tmp_path, ["python3", "-c", "import sys; sys.exit(1)"], operation_id=op_id)
        executor = ContainerCommandExecutor(plan=plan)
        authorize_operation(conn, op_id, tenant_id=TENANT, approved_by="user_bob", reason="run failing tests in container")
        result = start_and_execute_operation(conn, op_id, executor)
        assert result["status"] == "FAILED"
        assert result["status"] != "SUCCEEDED"
    finally:
        conn.close()
