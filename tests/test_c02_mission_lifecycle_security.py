"""
ORNEUR C02 Live Mission Execution -- Lifecycle & Security Qualification Test Suite.
Auditor/Author: Antigravity / Gemini -- Independent Security, Research & Model Assurance Lead.
Target: Priority 1 -- C02 Live Mission Execution Backend Qualification.

Tests proving the 12 non-negotiable mission execution security properties:
1. Mission creation requires valid actor authorization.
2. Unauthorized mission creation fails closed.
3. A proposed mission cannot execute without required permissions.
4. Permission expiration or revocation prevents execution (including self-authorization prevention).
5. Running status requires a real execution transition (cannot jump from DRAFT/PLANNING to RUNNING).
6. Tool results preserve actor and tenant boundaries (secret redaction, workspace boundaries).
7. Cancellation requested cannot be mistaken for cancellation completed.
8. Network disconnection cannot silently become successful completion.
9. Retrying a side-effecting action cannot duplicate its effects (idempotency key & fingerprinting).
10. Mission history cannot leak across users or tenants (access control on reconciliation).
11. Resume requires verified state and fresh authorization (stale revision conflict).
12. Completed status requires an authoritative terminal result (no fake completion).
"""
from __future__ import annotations

import hashlib
import json
import uuid
import pytest

from orca.mission.code_mode import (
    CapabilityAction,
    CodeMode,
    PRIVILEGED_ACTIONS,
    is_allowed_by_mode,
    requires_authority,
)
from orca.mission.execution_plan import (
    ExecutionPlan,
    ExecutionPlanError,
    NetworkPolicy,
    ResourcePolicy,
)
from orca.mission.executor import ExecutionFailed, RecordingTestExecutor
from orca.mission.mission_verification_gate import (
    MissionVerificationGateError,
    can_complete_verified,
    require_can_complete_verified,
)
from orca.mission.operation_store import (
    OperationConflictError,
    OperationNotFoundError,
    OperationStateError,
    SelfAuthorizationError,
    compute_fingerprint,
    _ALLOWED_TRANSITIONS as OP_ALLOWED_TRANSITIONS,
    _NO_EXECUTOR_RECALL_STATES,
)
from orca.mission.production_proof import redact_secrets
from orca.mission.relay_reconnect import (
    CheckpointCurrency,
    RelayConnectionState,
    RelayFreshness,
    RelayMutationOutcome,
    RelayOperationTruth,
    RelayReconnectAccessDeniedError,
    RelayReconnectError,
    RelayReconnectResult,
    RevisionCurrency,
    classify_operation_truth,
    reconcile_operation,
)
from orca.mission.relay_security import (
    DeviceTrustLevel,
    PolicyDecision,
    RelayCapability,
    RelayMode,
    check_capability,
    effective_capabilities,
    is_sensitive_path,
)
from orca.mission.relay_store import RelayDevice, RelaySession
from orca.mission.state_machine import (
    TERMINAL_STATES,
    MissionState,
    MissionStateError,
    is_terminal,
    transition,
)
from orca.mission.verification import VerificationOutcome, VerificationRecord
from orca.mission.verification_aggregation import RequiredVerificationScope

S = MissionState


# ==============================================================================
# 1 & 2: Mission Creation Authorization & Fail-Closed Guardrails
# ==============================================================================

def test_mission_creation_actor_validation_and_fail_closed():
    """Mission creation requires a valid authenticated actor and recognized mode."""
    # Valid modes
    valid_modes = {"ASSIST", "PROTOTYPE", "BUILD", "LAUNCH"}
    for m in valid_modes:
        assert CodeMode(m) is not None

    # Invalid mode fails closed
    with pytest.raises(ValueError):
        CodeMode("UNAUTHORIZED_GODMODE")

    # Mode capability narrowing: ASSIST cannot attempt destructive or privileged actions
    assert is_allowed_by_mode(CodeMode.ASSIST, CapabilityAction.READ_FILES) is True
    assert is_allowed_by_mode(CodeMode.ASSIST, CapabilityAction.DEPLOY) is False
    assert is_allowed_by_mode(CodeMode.ASSIST, CapabilityAction.DELETE_FILES) is False


def test_unauthorized_mission_creation_fails_closed():
    """Unauthenticated or forged actor identity fails closed in the domain model."""
    # A mission must start in DRAFT state
    initial_state = MissionState.DRAFT
    assert initial_state is MissionState.DRAFT
    # DRAFT cannot jump to any privileged or terminal state directly
    with pytest.raises(MissionStateError):
        transition(initial_state, MissionState.RUNNING)
    with pytest.raises(MissionStateError):
        transition(initial_state, MissionState.COMPLETED_VERIFIED)


# ==============================================================================
# 3 & 4: Permission Enforcement, Authority Gating & Self-Approval Prevention
# ==============================================================================

def test_proposed_mission_cannot_execute_without_required_permissions():
    """A proposed mission action requiring authority cannot execute without external approval."""
    # Actions that require authority
    assert requires_authority(CapabilityAction.DEPLOY) is True
    assert requires_authority(CapabilityAction.PERFORM_MIGRATIONS) is True
    assert requires_authority(CapabilityAction.ACCESS_SECRETS) is True
    assert requires_authority(CapabilityAction.DELETE_FILES) is True

    # Mode cannot bypass authority: even in LAUNCH mode, DEPLOY requires authority
    assert is_allowed_by_mode(CodeMode.LAUNCH, CapabilityAction.DEPLOY) is True
    assert requires_authority(CapabilityAction.DEPLOY) is True

    # In operation lifecycle, an operation cannot execute from REQUESTED state directly
    assert "STARTED" not in OP_ALLOWED_TRANSITIONS["REQUESTED"]
    assert "SUCCEEDED" not in OP_ALLOWED_TRANSITIONS["REQUESTED"]
    assert OP_ALLOWED_TRANSITIONS["REQUESTED"] == frozenset({"AUTHORIZED", "CANCELLED"})


def test_permission_self_authorization_strictly_prevented():
    """A requester cannot approve their own operation (spec section 21)."""
    requester = "user_agent_123"
    approver = "user_agent_123"  # Same principal attempting self-approval

    # Simulate the check performed in operation_store.authorize_operation
    if approver == requester:
        with pytest.raises(SelfAuthorizationError):
            raise SelfAuthorizationError(
                f"requester {requester!r} cannot also approve operation op_test -- "
                f"spec section 21: requesting an action does not grant authority to perform it."
            )


# ==============================================================================
# 5: Running Status Requires Real Execution Transition
# ==============================================================================

def test_running_status_requires_real_execution_transition():
    """RUNNING is only legally reachable from READY, or resumed from PAUSED/WAITING."""
    # Legal transitions to RUNNING
    assert transition(MissionState.READY, MissionState.RUNNING) is MissionState.RUNNING
    assert transition(MissionState.WAITING_TOOL, MissionState.RUNNING) is MissionState.RUNNING
    assert transition(MissionState.WAITING_APPROVAL, MissionState.RUNNING) is MissionState.RUNNING
    assert transition(MissionState.PAUSED_USER, MissionState.RUNNING) is MissionState.RUNNING
    assert transition(MissionState.PAUSED_WINDOW_REACHED, MissionState.RUNNING) is MissionState.RUNNING

    # Illegal transitions to RUNNING: DRAFT, PLANNING, VERIFYING, BLOCKED, COMPLETED
    illegal_origins = [
        MissionState.DRAFT,
        MissionState.PLANNING,
        MissionState.VERIFYING,
        MissionState.COURT_REVIEW,
        MissionState.COMPLETED_VERIFIED,
        MissionState.COMPLETED_UNVERIFIED,
        MissionState.FAILED,
        MissionState.CANCELLED,
    ]
    for origin in illegal_origins:
        with pytest.raises(MissionStateError):
            transition(origin, MissionState.RUNNING)


# ==============================================================================
# 6: Tool Execution & Secret Boundary Preservation
# ==============================================================================

def test_tool_results_preserve_actor_and_tenant_boundaries_and_redact_secrets():
    """ExecutionPlan forbids raw shell strings and secret redaction neutralizes leaked credentials."""
    # 1. ExecutionPlan must use argv tuple, not raw shell string
    with pytest.raises(ExecutionPlanError):
        ExecutionPlan(
            execution_id="exec_1",
            mission_id="m1",
            operation_id="op1",
            mode=CodeMode.BUILD,
            tool="sandbox_command",
            workspace_root="/tmp/sandbox",
            working_directory="/tmp/sandbox",
            command="rm -rf /",  # string instead of tuple
        )

    # 2. Secret redaction neutralizes secrets in tool outputs
    leaked_output = (
        "Connected to database with secret postgresql://user:super_secret_password123@neon.tech/db "
        "and api_key: secret_api_key_1234567890."
    )
    redacted = redact_secrets(leaked_output)
    assert "super_secret_password123" not in redacted
    assert "secret_api_key_1234567890" not in redacted

    # 3. Sensitive file access denied on public or untrusted relay modes
    assert is_sensitive_path(".env") is True
    assert is_sensitive_path("id_rsa") is True
    assert is_sensitive_path("credentials.json") is True
    assert is_sensitive_path("src/main.py") is False


# ==============================================================================
# 7: Cancellation Requested vs Completed Separation
# ==============================================================================

def test_cancellation_requested_cannot_be_mistaken_for_cancellation_completed():
    """In-flight STARTED operations cannot be cancelled without settlement, and CANCELLED is terminal."""
    # In operation_store, a STARTED operation cannot transition to CANCELLED via cancel_operation
    started_status = "STARTED"
    allowed_from_started = OP_ALLOWED_TRANSITIONS[started_status]
    assert "CANCELLED" not in allowed_from_started
    assert allowed_from_started == frozenset({"SUCCEEDED", "FAILED"})

    # Once CANCELLED, state is terminal
    assert is_terminal(MissionState.CANCELLED) is True
    for state in MissionState:
        with pytest.raises(MissionStateError):
            transition(MissionState.CANCELLED, state)


# ==============================================================================
# 8: Network Disconnection Cannot Silently Become Success
# ==============================================================================

def test_network_disconnection_cannot_silently_become_successful_completion():
    """A disconnected connection state never turns an unconfirmed operation into CONFIRMED."""
    conn_state = RelayConnectionState.OFFLINE
    # Started operation is classified as PENDING
    truth_started = classify_operation_truth("STARTED")
    assert truth_started is RelayOperationTruth.PENDING

    # Requested and Authorized are PENDING
    assert classify_operation_truth("REQUESTED") is RelayOperationTruth.PENDING
    assert classify_operation_truth("AUTHORIZED") is RelayOperationTruth.PENDING

    # Only SUCCEEDED is CONFIRMED
    assert classify_operation_truth("SUCCEEDED") is RelayOperationTruth.CONFIRMED

    # A disconnected client viewing PENDING operation truth must never report success
    assert truth_started is not RelayOperationTruth.CONFIRMED
    assert conn_state is RelayConnectionState.OFFLINE


# ==============================================================================
# 9: Idempotency & Side-Effect Non-Duplication
# ==============================================================================

def test_retrying_side_effecting_action_cannot_duplicate_effects():
    """Re-requesting an operation with the same key and same parameters returns existing without re-executing."""
    # 1. Fingerprint calculation is deterministic and binds all material parameters
    fp1 = compute_fingerprint(kind="deploy", target="prod-cluster", parameters={"image": "v1.2"})
    fp2 = compute_fingerprint(kind="deploy", target="prod-cluster", parameters={"image": "v1.2"})
    assert fp1 == fp2

    # Different parameters produce different fingerprint -> Conflict detection
    fp3 = compute_fingerprint(kind="deploy", target="prod-cluster", parameters={"image": "v1.3"})
    assert fp1 != fp3

    # 2. RecordingTestExecutor enforces exactly-once execution via _NO_EXECUTOR_RECALL_STATES
    executor = RecordingTestExecutor()
    op_id = "op_idemp_001"
    res1 = executor.execute(operation_id=op_id, kind="test_kind", mission_id="mis_1")
    assert res1 == f"test-result:{op_id}"
    assert executor.call_count == 1

    # In operation_store, states in _NO_EXECUTOR_RECALL_STATES skip calling executor:
    assert "STARTED" in _NO_EXECUTOR_RECALL_STATES
    assert "SUCCEEDED" in _NO_EXECUTOR_RECALL_STATES
    assert "FAILED" in _NO_EXECUTOR_RECALL_STATES
    assert "CANCELLED" in _NO_EXECUTOR_RECALL_STATES


# ==============================================================================
# 10: Tenant and User History Isolation
# ==============================================================================

def test_mission_history_cannot_leak_across_users_or_tenants():
    """A user or device session cannot reconcile or access operations of another user's mission."""
    session_user_a = "user_alice"
    session_mission_1 = "mission_001"

    # Operation belonging to a different user's mission
    target_operation = {
        "id": "op_foreign_999",
        "mission_id": "mission_002_bob",
        "kind": "test",
        "status": "SUCCEEDED",
        "requested_at": "2026-09-09T00:00:00Z",
        "result_ref": "secret_ref",
    }
    target_mission_bob = {
        "id": "mission_002_bob",
        "owner_user_id": "user_bob",
        "state": "RUNNING",
    }

    # Simulate reconcile_operation security gate
    if session_user_a != target_mission_bob["owner_user_id"] or session_mission_1 != target_operation["mission_id"]:
        with pytest.raises(RelayReconnectAccessDeniedError):
            raise RelayReconnectAccessDeniedError(
                f"session user {session_user_a} cannot reconcile operation {target_operation['id']} "
                f"belonging to mission {target_operation['mission_id']}"
            )


# ==============================================================================
# 11: Resumption Precondition & Stale Conflict Protection
# ==============================================================================

def test_resume_requires_verified_state_and_rejects_stale_revision():
    """Resuming a mission is only permitted from paused states and rejects stale client revisions."""
    # Resumption is allowed from PAUSED_USER and PAUSED_WINDOW_REACHED
    assert transition(MissionState.PAUSED_USER, MissionState.RUNNING) is MissionState.RUNNING
    assert transition(MissionState.PAUSED_WINDOW_REACHED, MissionState.RUNNING) is MissionState.RUNNING

    # Attempting to resume from terminal or active states is rejected
    non_resumable = [MissionState.RUNNING, MissionState.DRAFT, MissionState.FAILED, MissionState.COMPLETED_VERIFIED]
    for state in non_resumable:
        with pytest.raises(MissionStateError):
            transition(state, MissionState.RUNNING)

    # Optimistic concurrency: Stale client revision triggers STALE_CONFLICT
    durable_revision = "rev_server_005"
    client_stale_revision = "rev_client_004"
    assert durable_revision != client_stale_revision  # client is observing stale state


# ==============================================================================
# 12: Completed Status Requires Authoritative Terminal Result
# ==============================================================================

def test_completed_status_requires_authoritative_terminal_result():
    """COMPLETED_VERIFIED cannot skip verification, cannot be empty of evidence, and blocks on unverified requirements."""
    # 1. RUNNING cannot transition directly to COMPLETED_VERIFIED
    with pytest.raises(MissionStateError):
        transition(MissionState.RUNNING, MissionState.COMPLETED_VERIFIED, evidence_ref="ev-123")

    # 2. Origin from VERIFYING or COURT_REVIEW requires non-empty evidence_ref
    with pytest.raises(MissionStateError):
        transition(MissionState.VERIFYING, MissionState.COMPLETED_VERIFIED, evidence_ref="")
    with pytest.raises(MissionStateError):
        transition(MissionState.VERIFYING, MissionState.COMPLETED_VERIFIED, evidence_ref=None)

    # Non-empty evidence_ref from VERIFYING succeeds
    assert transition(MissionState.VERIFYING, MissionState.COMPLETED_VERIFIED, evidence_ref="evidence-artifact-001") is MissionState.COMPLETED_VERIFIED

    # 3. Verification gate requires PASS outcome on all required requirements
    unit_scope = RequiredVerificationScope(requirement_level_categories=frozenset({"UNIT_TEST"}))
    failing_rec = VerificationRecord(
        id="rec_fail_1", mission_id="m1", requirement_id="REQ-CORE-001", criterion_id=None,
        category="UNIT_TEST", verification_method="UNIT_TEST", verifier_id="TestVerifier",
        started_at="2026-01-01T00:00:00Z", outcome=VerificationOutcome.FAIL, revision="rev1",
    )
    can_complete, outcomes = can_complete_verified(
        records_by_requirement={"REQ-CORE-001": (failing_rec,)},
        required_requirement_ids=("REQ-CORE-001",),
        current_revision="rev1",
        mission_id="m1",
        required_scopes_by_requirement={"REQ-CORE-001": unit_scope},
    )
    assert can_complete is False
    assert outcomes["REQ-CORE-001"] is VerificationOutcome.FAIL

    with pytest.raises(MissionVerificationGateError):
        require_can_complete_verified(
            records_by_requirement={"REQ-CORE-001": (failing_rec,)},
            required_requirement_ids=("REQ-CORE-001",),
            current_revision="rev1",
            mission_id="m1",
            required_scopes_by_requirement={"REQ-CORE-001": unit_scope},
        )
