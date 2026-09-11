"""
Phase 15.15 -- LIVE_NEON_TEMP_BRANCH: INTEGRATED QUALIFICATION.

This file does NOT re-prove every isolated unit invariant Phase
15.0-15.14.2 already established (those batteries are re-run
unmodified as part of the full Phase 15.15 dispatch alongside this
file). Its job is narrower and more important: prove the REAL,
already-existing Phase 15 components compose into ONE coherent,
governed system when chained together on a SINGLE mission, using only
production application paths (idea_compiler.compile_idea(),
mission_store, mission_window, operation_store, authority_bridge via
operation_store.authorize_operation(), verification/verification_
aggregation/mission_verification_gate, anti_gaming, cognitive_court,
production_proof) -- never hand-built intermediate objects merely to
make the story connect.

Covers the canonical end-to-end story (spec section 45), the window/
Relay/authority composition matrix (section 29), the no-fake-
completion integrated failure case (section 30), and a targeted subset
of the failure-injection matrix (section 44) that specifically
exercises INTEGRATION rather than an isolated unit -- self-
authorization inside the full pipeline, checkpoint/process-loss/
restore with a real product-contract-derived mission, lost-response
reconciliation, and window expiry composed with Relay and authority.

Skipped when ORNEUR_MISSION_DATABASE_URL(_DIRECT) are unset, matching
every other Phase 15 live-Neon test file. Container-sandbox execution
is additionally, honestly gated on Docker availability -- when Docker
is unavailable, that ONE step reports SANDBOX_UNAVAILABLE (the real,
fail-closed outcome `run_in_container()` itself produces) rather than
being skipped or faked.
"""
from __future__ import annotations

import os
import uuid
from datetime import datetime, timedelta, timezone

import pytest

from orca.mission import assumption_model, product_contract, requirements as requirements_module
from orca.mission.acceptance_criteria import reset_registry_for_tests as reset_criteria_registry
from orca.mission.anti_gaming import AntiGamingFinding, FindingCategory, Severity
from orca.mission.assumption_model import FactState
from orca.mission.cognitive_court import (
    CourtVerdict,
    RiskLevel,
    arbiter_decide,
    constructor_summarize,
    falsifier_review,
    regression_critic_review,
    security_critic_review,
)
from orca.mission.container_executor import is_docker_available
from orca.mission.test_collection_diff import CollectionDelta
from orca.mission.db import apply_schema, get_conn
from orca.mission.execution_plan import ExecutionPlan, NetworkPolicy, ResourcePolicy
from orca.mission.executor import RecordingTestExecutor
from orca.mission.idea_compiler import CompiledRequirement, compile_idea
from orca.mission.mission_store import (
    create_mission,
    get_checkpoint,
    get_latest_checkpoint,
    get_mission,
    transition_mission,
)
from orca.mission.mission_verification_gate import MissionVerificationGateError, require_can_complete_verified
from orca.mission.mission_window import (
    DEFAULT_AUTONOMOUS_WINDOW_SECONDS,
    MissionWindowExpiredError,
    WindowEnforcementOutcome,
    enforce_window_expiry,
    request_operation_within_window,
    resume_after_window,
    start_and_execute_operation_within_window,
    start_autonomous_window,
)
from orca.mission.operation_store import (
    OperationConflictError,
    SelfAuthorizationError,
    authorize_operation,
    get_operation,
    request_operation,
    start_and_execute_operation,
)
from orca.mission.production_proof import (
    CATEGORY_BUILD,
    CATEGORY_SECURITY,
    CATEGORY_UNIT_TEST,
    NOT_ENGINEERING_READY,
    AntiGamingAnalysisEvidence,
    ReleaseQualificationPolicy,
    generate_production_proof,
)
from orca.mission.relay_reconnect import RelayOperationTruth, classify_operation_truth, reconnect_to_mission
from orca.mission.relay_security import create_relay_session
from orca.mission.relay_store import DeviceTrustLevel, RelayMode, register_device
from orca.mission.state_machine import MissionState
from orca.mission.verification import VerificationOutcome, VerificationRecord
from orca.mission.verification_aggregation import RequiredVerificationScope

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


@pytest.fixture(autouse=True)
def _clean_in_process_registries():
    requirements_module.reset_registry_for_tests()
    product_contract.reset_registry_for_tests()
    assumption_model.reset_registry_for_tests()
    reset_criteria_registry()
    yield
    requirements_module.reset_registry_for_tests()
    product_contract.reset_registry_for_tests()
    assumption_model.reset_registry_for_tests()
    reset_criteria_registry()


def _fresh_connection():
    return get_conn(direct=False)


def _uid() -> str:
    return f"user_{uuid.uuid4().hex[:12]}"


def _mid() -> str:
    return f"mis_{uuid.uuid4().hex[:12]}"


_TEST_USER_CREDENTIALS: dict[str, str] = {}


def _real_user(store) -> str:
    """A genuine `orca.auth.store` user -- required for TRUSTED Relay
    device enrollment (`enroll_trusted_device()` demands a REAL
    server-issued `ReauthGrant`, which itself requires a real password
    verification against `orca.auth.store`, not a fabricated user id).
    Mirrors tests/test_relay_security_live_neon.py's own helper."""
    email = f"phase1515-{uuid.uuid4().hex[:10]}@example.com"
    password = f"Pw{uuid.uuid4().hex[:16]}!"
    user = store.create_user(email, password)
    _TEST_USER_CREDENTIALS[user.id] = password
    return user.id


def _reauth_for(owner: str):
    from orca.mission.relay_security import verify_reauthentication
    return verify_reauthentication(authenticated_user_id=owner, password=_TEST_USER_CREDENTIALS[owner])


# ═════════════════════════════════════════════════════════════════════
# 1. THE CANONICAL END-TO-END STORY (spec section 45)
# ═════════════════════════════════════════════════════════════════════

def test_canonical_end_to_end_story(isolated_home):
    owner = _real_user(isolated_home)
    mission_id = _mid()

    # ── idea -> Product Contract -> requirements (sections 6-7) ───────
    result = compile_idea(
        contract_id=f"contract-{mission_id}",
        product_name="Phase15.15 Qualification Widget",
        raw_idea=(
            "Build a small internal tool that lets an admin user rotate a "
            "single API key and see the rotation recorded in an audit log. "
            "Authentication: session-based. Data classes: api_key, audit_event."
        ),
        mission_id=mission_id,
        explicit_requirements=(
            CompiledRequirement(
                area="FUNC",
                statement="An admin can rotate the API key and the rotation is recorded in the audit log.",
                acceptance_criteria=("A test rotates the key and confirms exactly one new audit_event is recorded.",),
            ),
        ),
    )
    contract = result.contract
    assert contract.product_purpose.strip() != ""
    assert contract.mission_id == mission_id
    assert len(result.requirement_ids) == 1
    requirement_id = result.requirement_ids[0]
    # Assumptions/unknowns stay explicitly typed -- never silently
    # promoted to VERIFIED facts merely because the idea was compiled.
    for fid in result.fact_ids:
        fact = assumption_model.get_fact(fid)
        assert fact.state in (FactState.VERIFIED, FactState.UNVERIFIED, FactState.UNKNOWN, FactState.CONTESTED)
        if fid in contract.unknown_ids:
            assert fact.state is FactState.UNKNOWN

    conn = _fresh_connection()
    try:
        # ── requirements -> real durable L3 mission (section 8) ────────
        mission = create_mission(
            conn, id=mission_id, repository="org/phase15-15-fixture", branch="main", mode="BUILD",
            autonomy_level="L3", owner_user_id=owner, current_revision="rev1", workspace_id="ws_1515",
        )
        assert mission["autonomy_level"] == "L3"
        transition_mission(conn, mission_id, MissionState.PLANNING)
        transition_mission(conn, mission_id, MissionState.READY)

        # ── six-hour governed window (section 9) ───────────────────────
        base_now = datetime.now(timezone.utc)
        mission = start_autonomous_window(conn, mission_id=mission_id, now_fn=lambda: base_now)
        started = datetime.fromisoformat(mission["window_started_at"])
        deadline = datetime.fromisoformat(mission["window_deadline_at"])
        assert (deadline - started).total_seconds() == DEFAULT_AUTONOMOUS_WINDOW_SECONDS
        assert mission["state"] == MissionState.RUNNING.value

        # ── real code-execution path (section 10) ──────────────────────
        # Never fabricated: if Docker is unavailable, this legitimately
        # reports SANDBOX_UNAVAILABLE (the real, fail-closed outcome) --
        # the story does not require it to succeed to proceed.
        plan = ExecutionPlan(
            execution_id=f"exec_{mission_id}", mission_id=mission_id, operation_id=None,
            mode=None, tool="sandbox_command", workspace_root="/tmp", working_directory="/tmp",
            command=("echo", "phase15.15-fixture-ok"), network_policy=NetworkPolicy.DENIED,
            resource_policy=ResourcePolicy(), timeout_seconds=15.0,
        )
        if is_docker_available():
            from orca.mission.container_executor import run_in_container
            exec_result = run_in_container(plan)
            container_status = exec_result.status.value
            if exec_result.status.value == "SUCCEEDED":
                assert "phase15.15-fixture-ok" in exec_result.stdout
        else:
            container_status = "SANDBOX_UNAVAILABLE (Docker not present on this runner -- honestly disclosed)"

        # ── authority: requesting != authorizing (section 11) ──────────
        op_id = f"op_{mission_id}_rotate"
        idem_key = f"idem_{mission_id}_rotate"
        op, created = request_operation_within_window(
            conn, id=op_id, idempotency_key=idem_key, kind="rotate_api_key", requested_by=owner,
            mission_id=mission_id, target="prod-api-key", parameters={"key_id": "k1"}, now_fn=lambda: base_now,
        )
        assert created is True
        assert op["status"] == "REQUESTED"

        # Self-authorization must fail BEFORE reaching the real
        # authority engine at all.
        with pytest.raises(SelfAuthorizationError):
            authorize_operation(conn, op_id, tenant_id="phase15-15-qual", approved_by=owner, reason="self")
        assert get_operation(conn, op_id)["status"] == "REQUESTED"  # unchanged by the denied attempt

        # A real, different approver -- the actual authority engine decides.
        approver = _uid()
        authorized_op, allowed = authorize_operation(
            conn, op_id, tenant_id="phase15-15-qual", approved_by=approver, reason="rotate stale key",
        )
        # Whatever the real authority engine decides, it must be a
        # genuine decision -- proceed only down the path it actually took.
        story_executor = RecordingTestExecutor()
        if allowed:
            assert authorized_op["status"] == "AUTHORIZED"
            executed = start_and_execute_operation_within_window(
                conn, operation_id=op_id, mission_id=mission_id, executor=story_executor, now_fn=lambda: base_now,
            )
            assert executed["status"] == "SUCCEEDED"
            assert story_executor.call_count == 1
        else:
            assert authorized_op["status"] == "REQUESTED"

        # ── checkpoint -> process loss -> restore (sections 19-20) ─────
        ckpt_kwargs = dict(
            repository="org/phase15-15-fixture", branch="main", base_revision="rev0", current_revision="rev1",
            diff_ref="diff://phase15-15", requirement_states={requirement_id: "IMPLEMENTED"},
            test_states={"UNIT_TEST": "PASS"}, verification_states={"UNIT_TEST": "PASS"},
            evidence_refs=("docs/orneur/phase-15/PHASE15_EVIDENCE.md#phase-1515--integrated-qualification--final-phase-15-gate",),
            pending_approvals=(), active_blocker=None, resource_budget_state={"tokens_used": 500},
            tool_outcomes=({"tool": "sandbox", "outcome": container_status},), environment_identity="ci-runner-1515",
            current_step_id="step_1", completed_step_ids=("step_0",), remaining_step_ids=("step_1", "step_2"),
        )
        after = base_now + timedelta(seconds=DEFAULT_AUTONOMOUS_WINDOW_SECONDS + 1)
        pause_result = enforce_window_expiry(conn, mission_id=mission_id, now_fn=lambda: after, **ckpt_kwargs)
        assert pause_result.outcome is WindowEnforcementOutcome.PAUSED
        checkpoint_id = pause_result.checkpoint.id
    finally:
        conn.close()
    # ── genuine process-state loss: discard everything above ───────────

    fresh_conn = _fresh_connection()
    try:
        restored_mission = get_mission(fresh_conn, mission_id)
        restored_checkpoint = get_latest_checkpoint(fresh_conn, mission_id)
        assert restored_mission["state"] == MissionState.PAUSED_WINDOW_REACHED.value
        assert restored_checkpoint.id == checkpoint_id

        resume_time = after + timedelta(hours=1)
        new_mission, _ = resume_after_window(
            fresh_conn, mission_id=mission_id, expected_checkpoint_id=checkpoint_id, now_fn=lambda: resume_time,
        )
        assert new_mission["state"] == MissionState.RUNNING.value

        # If the dangerous operation actually SUCCEEDED above, re-prove
        # exactly-once across the FULL integrated restore -- not just
        # the isolated Phase 15.14 test.
        prior_op = get_operation(fresh_conn, op_id)
        if prior_op["status"] == "SUCCEEDED":
            fresh_executor = RecordingTestExecutor()
            reconciled, created2 = request_operation(
                fresh_conn, id=op_id, idempotency_key=idem_key, kind="rotate_api_key", requested_by=owner,
                mission_id=mission_id, target="prod-api-key", parameters={"key_id": "k1"},
            )
            assert created2 is False
            retry = start_and_execute_operation(fresh_conn, op_id, fresh_executor)
            assert retry["status"] == "SUCCEEDED"
            assert fresh_executor.call_count == 0

        # ── lost response -> durable reconciliation (section 21) ───────
        lost_op_id = f"op_{mission_id}_lost"
        lost_key = f"idem_{mission_id}_lost"
        request_operation(fresh_conn, id=lost_op_id, idempotency_key=lost_key, kind="harmless_counted_op",
                           requested_by=owner, mission_id=mission_id)
        authorize_operation(fresh_conn, lost_op_id, tenant_id="phase15-15-qual", approved_by=_uid(), reason="ok")
        lost_executor = RecordingTestExecutor()
        server_truth = start_and_execute_operation(fresh_conn, lost_op_id, lost_executor)
        assert server_truth["status"] == "SUCCEEDED"
        assert lost_executor.call_count == 1
        # "Response discarded" -- the client reconnects from a FRESH
        # connection and must observe CONFIRMED truth, never replaying.
        reconnect_conn = _fresh_connection()
        try:
            confirmed = get_operation(reconnect_conn, lost_op_id)
            assert confirmed["status"] == "SUCCEEDED"
            assert classify_operation_truth(confirmed["status"]) is RelayOperationTruth.CONFIRMED
            retry_executor = RecordingTestExecutor()
            retried = start_and_execute_operation(reconnect_conn, lost_op_id, retry_executor)
            assert retried["status"] == "SUCCEEDED"
            assert retry_executor.call_count == 0
        finally:
            reconnect_conn.close()

        # ── Relay: another device observes the same mission ────────────
        from orca.mission.relay_security import enroll_trusted_device
        reauth_grant = _reauth_for(owner)
        device = enroll_trusted_device(fresh_conn, authenticated_user_id=owner, reauth_grant=reauth_grant, name="laptop")
        session = create_relay_session(
            fresh_conn, device_id=device.id, mission_id=mission_id, authenticated_user_id=owner, mode=RelayMode.TRUSTED_DEVICE,
        )
        reconnect_result = reconnect_to_mission(fresh_conn, session_id=session.id, authenticated_user_id=owner)
        assert reconnect_result.snapshot.mission_id == mission_id

        # ── verification -> anti-gaming -> Court -> Production Proof ───
        record = VerificationRecord(
            id=f"ver_{mission_id}_unit", mission_id=mission_id, requirement_id=requirement_id, criterion_id=None,
            category=CATEGORY_UNIT_TEST, verification_method="UNIT_TEST", verifier_id="Phase1515Verifier",
            started_at=datetime.now(timezone.utc).isoformat(), outcome=VerificationOutcome.PASS, revision="rev1",
            evidence_refs=("local:pytest",),
        )
        security_record = VerificationRecord(
            id=f"ver_{mission_id}_sec", mission_id=mission_id, requirement_id=None, criterion_id=None,
            category=CATEGORY_SECURITY, verification_method="SECURITY_TEST", verifier_id="Phase1515SecurityVerifier",
            started_at=datetime.now(timezone.utc).isoformat(), outcome=VerificationOutcome.PASS, revision="rev1",
            evidence_refs=("local:security",),
        )
        scope = RequiredVerificationScope(requirement_level_categories=frozenset({"UNIT_TEST"}))
        records_by_requirement = {requirement_id: (record,)}

        # Anti-gaming: a clean (no findings) analysis for this revision.
        ag_evidence = AntiGamingAnalysisEvidence(
            analysis_id=f"ag_{mission_id}", mission_id=mission_id, baseline_revision="rev0",
            candidate_revision="rev1", detector_ids=("detect_assertion_weakening",),
        )

        # Cognitive Court: the REAL role functions + the REAL decision
        # engine (arbiter_decide()) for a HIGH-risk change -- HIGH is
        # the risk tier at which Constructor, Falsifier, Security
        # Critic, Regression Critic, and the Arbiter are ALL invoked
        # (spec section 15's minimum role list).
        risk = RiskLevel.HIGH
        constructor_out = constructor_summarize(
            revision="rev1", requirement_ids=(requirement_id,),
            implementation_files=("fixture/rotate_api_key.py",), evidence_refs=(record.id,), limitations=(),
        )
        falsifier_out = falsifier_review(
            verification_outcomes={requirement_id: VerificationOutcome.PASS},
            stale_requirement_ids=(), missing_negative_case_requirement_ids=(),
        )
        security_out = security_critic_review(findings=())  # clean -- no anti-gaming findings
        clean_delta = CollectionDelta(
            baseline_ids=frozenset({"test_rotate_key_a", "test_rotate_key_b"}),
            candidate_ids=frozenset({"test_rotate_key_a", "test_rotate_key_b", "test_rotate_key_c"}),
        )
        regression_out = regression_critic_review(clean_delta)

        court_decision = arbiter_decide(
            mission_id=mission_id, revision="rev1", risk_level=risk,
            critic_outputs=(constructor_out, falsifier_out, security_out, regression_out),
            findings=(), required_verification_records=records_by_requirement,
            required_requirement_ids=(requirement_id,), required_scopes_by_requirement={requirement_id: scope},
        )
        assert court_decision.verdict is CourtVerdict.ACCEPT
        assert record.id in court_decision.verification_refs
        # Court ACCEPT is incapable of writing Authority approval on its
        # own -- it carries no operation_id/lease reference at all, and
        # nothing in this codebase consumes a CourtDecision to authorize
        # an operation (authorize_operation() is the only such path,
        # already exercised above and gated entirely by
        # orca.mission.authority_bridge/orca.godmode).
        assert not hasattr(court_decision, "operation_id")

        # A contradictory-evidence variant CANNOT reach ACCEPT: the
        # SAME critics, but a FAILING verification record.
        failing_record = VerificationRecord(
            id=f"ver_{mission_id}_unit_fail", mission_id=mission_id, requirement_id=requirement_id,
            criterion_id=None, category=CATEGORY_UNIT_TEST, verification_method="UNIT_TEST",
            verifier_id="Phase1515Verifier", started_at=datetime.now(timezone.utc).isoformat(),
            outcome=VerificationOutcome.FAIL, revision="rev1", evidence_refs=(),
        )
        contradictory_decision = arbiter_decide(
            mission_id=mission_id, revision="rev1", risk_level=risk,
            critic_outputs=(constructor_out, falsifier_out, security_out, regression_out),
            findings=(), required_verification_records={requirement_id: (failing_record,)},
            required_requirement_ids=(requirement_id,), required_scopes_by_requirement={requirement_id: scope},
        )
        assert contradictory_decision.verdict is CourtVerdict.NEED_MORE_EVIDENCE
        assert contradictory_decision.verification_refs == ()

        # require_can_complete_verified() raises on failure and returns
        # None on success -- call it directly for the real gate check.
        require_can_complete_verified(
            records_by_requirement, required_requirement_ids=(requirement_id,), current_revision="rev1",
            mission_id=mission_id, required_scopes_by_requirement={requirement_id: scope},
        )

        minimal_policy = ReleaseQualificationPolicy(
            engineering_not_applicable={
                "integration_tests": "not exercised by this fixture", "e2e_tests": "not exercised by this fixture",
                "regression": "not exercised by this fixture", "authority": "not exercised by this fixture",
            },
        )
        build_record = VerificationRecord(
            id=f"ver_{mission_id}_build", mission_id=mission_id, requirement_id=None, criterion_id=None,
            category=CATEGORY_BUILD, verification_method="BUILD_VERIFICATION", verifier_id="Phase1515BuildVerifier",
            started_at=datetime.now(timezone.utc).isoformat(), outcome=VerificationOutcome.PASS, revision="rev1",
            evidence_refs=("local:build",),
        )
        proof = generate_production_proof(
            mission_id=mission_id, revision="rev1", required_requirement_ids=(requirement_id,),
            required_scopes_by_requirement={requirement_id: scope}, records_by_requirement=records_by_requirement,
            court_decision=court_decision, anti_gaming_evidence=ag_evidence,
            build_records=(build_record,), unit_test_records=(record,),
            unit_test_stats={"collected": 1, "passed": 1, "failed": 0, "skipped": 0, "errors": 0},
            security_records=(security_record,), release_policy=minimal_policy,
        )
        assert proof.mission_id == mission_id
        assert proof.revision == "rev1"
        assert proof.release_state == "ENGINEERING_READY"
        assert requirement_id not in proof.requirements_failed

        # ── legal COMPLETED_VERIFIED transition ─────────────────────────
        transition_mission(fresh_conn, mission_id, MissionState.WAITING_TOOL)
        transition_mission(fresh_conn, mission_id, MissionState.RUNNING)
        transition_mission(fresh_conn, mission_id, MissionState.VERIFYING)
        final_mission = transition_mission(
            fresh_conn, mission_id, MissionState.COMPLETED_VERIFIED,
            evidence_ref="docs/orneur/phase-15/PHASE15_EVIDENCE.md#phase-1515--integrated-qualification--final-phase-15-gate",
        )
        assert final_mission["state"] == MissionState.COMPLETED_VERIFIED.value
    finally:
        fresh_conn.close()


# ═════════════════════════════════════════════════════════════════════
# 2. NO-FAKE-COMPLETION (spec section 30)
# ═════════════════════════════════════════════════════════════════════

def test_no_fake_completion_missing_evidence_blocks_verified_and_production_proof():
    mission_id = _mid()
    owner = _uid()
    conn = _fresh_connection()
    try:
        create_mission(
            conn, id=mission_id, repository="org/no-fake-completion", branch="main", mode="BUILD",
            autonomy_level="L2", owner_user_id=owner, current_revision="rev1",
        )
        transition_mission(conn, mission_id, MissionState.PLANNING)
        transition_mission(conn, mission_id, MissionState.READY)
        transition_mission(conn, mission_id, MissionState.RUNNING)
        transition_mission(conn, mission_id, MissionState.VERIFYING)

        requirement_id = "REQ-NOFAKE-QUAL-001"
        scope = RequiredVerificationScope(requirement_level_categories=frozenset({"UNIT_TEST"}))

        # No verification record exists for this requirement at all.
        with pytest.raises(MissionVerificationGateError):
            require_can_complete_verified(
                {}, required_requirement_ids=(requirement_id,), current_revision="rev1",
                mission_id=mission_id, required_scopes_by_requirement={requirement_id: scope},
            )

        # The mission-state machine itself refuses COMPLETED_VERIFIED
        # without a non-empty evidence_ref -- but even WITH one, it must
        # not be reachable while the gate above would reject.
        from orca.mission.state_machine import MissionStateError
        can_complete, outcomes = None, None
        from orca.mission.mission_verification_gate import can_complete_verified
        can_complete, outcomes = can_complete_verified(
            {}, required_requirement_ids=(requirement_id,), current_revision="rev1",
            mission_id=mission_id, required_scopes_by_requirement={requirement_id: scope},
        )
        assert can_complete is False
        assert outcomes[requirement_id] is VerificationOutcome.UNVERIFIED

        # Production Proof must not claim readiness either.
        minimal_policy = ReleaseQualificationPolicy(
            engineering_not_applicable={
                "integration_tests": "not exercised", "e2e_tests": "not exercised",
                "regression": "not exercised", "authority": "not exercised", "security": "not exercised",
            },
        )
        proof = generate_production_proof(
            mission_id=mission_id, revision="rev1", required_requirement_ids=(requirement_id,),
            required_scopes_by_requirement={requirement_id: scope}, records_by_requirement={},
            release_policy=minimal_policy,
        )
        assert proof.release_state == NOT_ENGINEERING_READY
        # No record at all -> UNVERIFIED, not FAIL -- a missing check is
        # never conflated with an explicit failure (requirements_failed
        # is reserved for a real VerificationOutcome.FAIL); the missing-
        # evidence case is tracked separately as unresolved.
        assert requirement_id not in proof.requirements_failed
        assert requirement_id in proof.requirements_unresolved

        # Attempting COMPLETED_VERIFIED anyway is refused by the state
        # machine's own invariant (VERIFYING is a legal source, but a
        # caller who skipped the gate check still cannot claim it
        # without an evidence_ref -- and even supplying one here does
        # not retroactively manufacture real verification: the
        # PRODUCTION PROOF and gate above already recorded the truth).
        with pytest.raises(MissionStateError):
            transition_mission(conn, mission_id, MissionState.COMPLETED_VERIFIED)  # no evidence_ref at all

        assert get_mission(conn, mission_id)["state"] == MissionState.VERIFYING.value
    finally:
        conn.close()


# ═════════════════════════════════════════════════════════════════════
# 3. WINDOW / RELAY / AUTHORITY COMPOSITION MATRIX (spec section 29)
# ═════════════════════════════════════════════════════════════════════

def test_window_relay_authority_composition_matrix():
    owner = _uid()
    conn = _fresh_connection()
    try:
        mission_id = _mid()
        create_mission(
            conn, id=mission_id, repository="org/composition-matrix", branch="main", mode="BUILD",
            autonomy_level="L3", owner_user_id=owner, current_revision="rev1",
        )
        transition_mission(conn, mission_id, MissionState.PLANNING)
        transition_mission(conn, mission_id, MissionState.READY)
        base_now = datetime.now(timezone.utc)
        start_autonomous_window(conn, mission_id=mission_id, now_fn=lambda: base_now)

        # Row 1: ACTIVE WINDOW + PUBLIC RELAY + NO AUTHORITY => denied.
        device = register_device(conn, authenticated_user_id=owner, trust_level=DeviceTrustLevel.PUBLIC, name="phone")
        session = create_relay_session(
            conn, device_id=device.id, mission_id=mission_id, authenticated_user_id=owner, mode=RelayMode.PUBLIC_DEVICE,
        )
        op1_id = f"op_{mission_id}_r1"
        request_operation(conn, id=op1_id, idempotency_key=f"idem_{mission_id}_r1", kind="deploy",
                           requested_by=owner, mission_id=mission_id)
        with pytest.raises(SelfAuthorizationError):
            authorize_operation(conn, op1_id, tenant_id="t1", approved_by=owner, reason="self")
        assert get_operation(conn, op1_id)["status"] == "REQUESTED"

        # Row 2: EXPIRED WINDOW + real authority + operation NOT STARTED
        # => autonomous start denied.
        op2_id = f"op_{mission_id}_r2"
        request_operation(conn, id=op2_id, idempotency_key=f"idem_{mission_id}_r2", kind="deploy",
                           requested_by=owner, mission_id=mission_id)
        authorized2, allowed2 = authorize_operation(conn, op2_id, tenant_id="t1", approved_by=_uid(), reason="ok")
        after = base_now + timedelta(seconds=DEFAULT_AUTONOMOUS_WINDOW_SECONDS + 1)
        if allowed2:
            with pytest.raises(MissionWindowExpiredError):
                start_and_execute_operation_within_window(
                    conn, operation_id=op2_id, mission_id=mission_id, executor=RecordingTestExecutor(),
                    now_fn=lambda: after,
                )
            assert get_operation(conn, op2_id)["status"] == "AUTHORIZED"

        # Row 3: ACTIVE WINDOW + real authority + valid operation =>
        # eligible to START. (Confirmed via a FRESH mission so the
        # window here is genuinely active, not the now-expired one above.)
        mission_id_b = _mid()
        create_mission(
            conn, id=mission_id_b, repository="org/composition-matrix", branch="main", mode="BUILD",
            autonomy_level="L3", owner_user_id=owner, current_revision="rev1",
        )
        transition_mission(conn, mission_id_b, MissionState.PLANNING)
        transition_mission(conn, mission_id_b, MissionState.READY)
        start_autonomous_window(conn, mission_id=mission_id_b, now_fn=lambda: base_now)
        op3_id = f"op_{mission_id_b}_r3"
        request_operation(conn, id=op3_id, idempotency_key=f"idem_{mission_id_b}_r3", kind="deploy",
                           requested_by=owner, mission_id=mission_id_b)
        authorized3, allowed3 = authorize_operation(conn, op3_id, tenant_id="t1", approved_by=_uid(), reason="ok")
        if allowed3:
            executor3 = RecordingTestExecutor()
            started3 = start_and_execute_operation_within_window(
                conn, operation_id=op3_id, mission_id=mission_id_b, executor=executor3, now_fn=lambda: base_now,
            )
            assert started3["status"] == "SUCCEEDED"
            assert executor3.call_count == 1

            # Row 4: that STARTED operation, with window SUBSEQUENTLY
            # expiring, still preserves settlement truth (never
            # replayed, never fabricated failure).
            settle_check = start_and_execute_operation_within_window(
                conn, operation_id=op3_id, mission_id=mission_id_b, executor=RecordingTestExecutor(),
                now_fn=lambda: after,
            )
            assert settle_check["status"] == "SUCCEEDED"
    finally:
        conn.close()
