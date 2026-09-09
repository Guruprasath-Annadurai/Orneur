"""
Phase 15.11 -- LIVE_NEON_TEMP_BRANCH: durable Relay device/session
core, authenticated-principal mission-access binding, session expiry/
revocation, and governed RelaySnapshot qualification against real
Postgres (spec sections 3-27).

Skipped when ORNEUR_MISSION_DATABASE_URL(_DIRECT) are unset, matching
every other Phase 15 live-Neon test file.
"""
from __future__ import annotations

import json
import os
import uuid
from datetime import datetime, timedelta, timezone

import pytest

from orca.mission.db import apply_schema, get_conn
from orca.mission.mission_store import create_checkpoint, create_mission
from orca.mission.production_proof import (
    CATEGORY_BUILD,
    CATEGORY_SECURITY,
    CATEGORY_UNIT_TEST,
    AntiGamingAnalysisEvidence,
    ReleaseQualificationPolicy,
    generate_production_proof,
)
from orca.mission.production_proof_store import record_proof
from orca.mission.relay_store import (
    DeviceNotFoundError,
    DeviceRevokedError,
    DeviceTrustLevel,
    RelayAccessDeniedError,
    RelayMode,
    RelaySessionInvalidError,
    RelaySessionNotFoundError,
    RelaySessionStatus,
    build_relay_snapshot,
    create_session,
    get_device,
    get_session,
    is_device_active,
    register_device,
    revoke_all_other_sessions,
    revoke_device,
    revoke_other_session,
    revoke_session,
    session_status,
    touch_device,
    touch_session,
)
from orca.mission.state_machine import MissionState
from orca.mission.verification import VerificationOutcome, VerificationRecord
from orca.mission.verification_aggregation import RequiredVerificationScope
from orca.mission.verification_store import record_verification

pytestmark = pytest.mark.skipif(
    not (os.environ.get("ORNEUR_MISSION_DATABASE_URL") and os.environ.get("ORNEUR_MISSION_DATABASE_URL_DIRECT")),
    reason="LIVE_NEON_TEMP_BRANCH: requires ORNEUR_MISSION_DATABASE_URL(_DIRECT) pointing at a disposable Neon branch",
)

_UNIT_TEST_SCOPE = RequiredVerificationScope(requirement_level_categories=frozenset({"UNIT_TEST"}))
_MINIMAL_POLICY = ReleaseQualificationPolicy(
    engineering_not_applicable={"integration_tests": "n/a", "e2e_tests": "n/a", "regression": "n/a", "authority": "n/a"},
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


def _mid() -> str:
    return f"mis_{uuid.uuid4().hex[:12]}"


def _uid() -> str:
    return f"user_{uuid.uuid4().hex[:8]}"


def _rid() -> str:
    return f"REQ-RELAY-{uuid.uuid4().hex[:8].upper()}-001"


def _now_iso() -> str:
    return datetime.now(timezone.utc).isoformat()


def _seed_full_mission(conn, *, mission_id: str, owner_user_id: str, revision: str = "rev1") -> str:
    """Seeds a mission with representative durable state across every
    Relay governed-state domain (spec section 22): requirement,
    verification record, checkpoint, Production Proof, mission step,
    operation/approval/authority-decision, model/tool invocation.
    Returns the seeded requirement_id."""
    create_mission(
        conn, id=mission_id, repository="org/relay-qual-repo", branch="main", mode="BUILD",
        autonomy_level="L1", owner_user_id=owner_user_id, current_revision=revision,
    )
    requirement_id = _rid()
    now = _now_iso()
    with conn.cursor() as cur:
        cur.execute(
            "INSERT INTO requirements (id, mission_id, source_section, statement, status, created_at, updated_at) "
            "VALUES (%s, %s, %s, %s, 'IMPLEMENTED', %s, %s)",
            (requirement_id, mission_id, "spec section 22", "Relay must synchronize this requirement", now, now),
        )
        step_id = f"step_{uuid.uuid4().hex[:8]}"
        cur.execute(
            "INSERT INTO mission_steps (id, mission_id, step_index, description, status, created_at) "
            "VALUES (%s, %s, 0, %s, 'RUNNING', %s)",
            (step_id, mission_id, "seeded relay-qual step", now),
        )
        op_id = f"op_{uuid.uuid4().hex[:8]}"
        cur.execute(
            "INSERT INTO operations (id, mission_id, idempotency_key, kind, status, requested_at, requested_by) "
            "VALUES (%s, %s, %s, 'deploy', 'REQUESTED', %s, %s)",
            (op_id, mission_id, f"idem_{uuid.uuid4().hex[:8]}", now, owner_user_id),
        )
        appr_id = f"appr_{uuid.uuid4().hex[:8]}"
        cur.execute(
            "INSERT INTO approvals (id, mission_id, operation_id, requested_at, decision) "
            "VALUES (%s, %s, %s, %s, 'PENDING')",
            (appr_id, mission_id, op_id, now),
        )
        authdec_id = f"authdec_{uuid.uuid4().hex[:8]}"
        cur.execute(
            "INSERT INTO authority_decisions (id, mission_id, operation_id, decision, decided_at, detail) "
            "VALUES (%s, %s, %s, 'ALLOW', %s, %s)",
            (authdec_id, mission_id, op_id, now, "authorized under relay-qual policy"),
        )
        model_id = f"minv_{uuid.uuid4().hex[:8]}"
        cur.execute(
            "INSERT INTO model_invocations (id, mission_id, provider, model, purpose, started_at, outcome_summary) "
            "VALUES (%s, %s, 'anthropic', 'claude', 'plan next step', %s, 'produced a plan')",
            (model_id, mission_id, now),
        )
        tool_id = f"tinv_{uuid.uuid4().hex[:8]}"
        cur.execute(
            "INSERT INTO tool_invocations (id, mission_id, tool_name, started_at, status, outcome_summary) "
            "VALUES (%s, %s, 'bash', %s, 'SUCCEEDED', 'ran tests successfully')",
            (tool_id, mission_id, now),
        )
    conn.commit()

    record = VerificationRecord(
        id=f"ver_{uuid.uuid4().hex[:12]}", mission_id=mission_id, requirement_id=requirement_id,
        criterion_id=None, category=CATEGORY_UNIT_TEST, verification_method="UNIT_TEST",
        verifier_id="RelayQualVerifier", started_at=now, outcome=VerificationOutcome.PASS,
        revision=revision, evidence_refs=("local:pytest",),
    )
    record_verification(conn, record)

    proof = generate_production_proof(
        mission_id=mission_id, revision=revision, required_requirement_ids=(requirement_id,),
        required_scopes_by_requirement={requirement_id: _UNIT_TEST_SCOPE},
        records_by_requirement={requirement_id: (record,)},
        anti_gaming_evidence=AntiGamingAnalysisEvidence(
            analysis_id=f"ag_{uuid.uuid4().hex[:8]}", mission_id=mission_id, baseline_revision="rev0",
            candidate_revision=revision, detector_ids=("detect_x",),
        ),
        build_records=(VerificationRecord(
            id=f"ver_{uuid.uuid4().hex[:12]}", mission_id=mission_id, requirement_id=None, criterion_id=None,
            category=CATEGORY_BUILD, verification_method="BUILD_VERIFICATION", verifier_id="BuildVerifier",
            started_at=now, outcome=VerificationOutcome.PASS, revision=revision, evidence_refs=("local:build",),
        ),),
        security_records=(VerificationRecord(
            id=f"ver_{uuid.uuid4().hex[:12]}", mission_id=mission_id, requirement_id=None, criterion_id=None,
            category=CATEGORY_SECURITY, verification_method="SECURITY_TEST", verifier_id="SecurityVerifier",
            started_at=now, outcome=VerificationOutcome.PASS, revision=revision, evidence_refs=("local:security",),
        ),),
        unit_test_records=(record,), unit_test_stats={"collected": 1, "passed": 1, "failed": 0, "skipped": 0, "errors": 0},
        release_policy=_MINIMAL_POLICY,
    )
    record_proof(conn, proof)

    create_checkpoint(
        conn, id=f"ckpt_{uuid.uuid4().hex[:8]}", mission_id=mission_id, mission_state=MissionState.RUNNING,
        repository="org/relay-qual-repo", current_revision=revision, current_step_id=step_id,
        completed_step_ids=(), remaining_step_ids=(step_id,), evidence_refs=(record.id,),
    )
    return requirement_id


# ── Device + session durability across a fresh connection (spec §23) ──

def test_device_and_session_durable_across_fresh_connection():
    owner = _uid()
    mission_id = _mid()

    conn = _fresh_connection()
    try:
        _seed_full_mission(conn, mission_id=mission_id, owner_user_id=owner)
        device = register_device(conn, user_id=owner, trust_level=DeviceTrustLevel.TRUSTED, name="Device A")
        session = create_session(
            conn, device_id=device.id, mission_id=mission_id, authenticated_user_id=owner,
            mode=RelayMode.TRUSTED_DEVICE, ttl_seconds=3600,
        )
    finally:
        conn.close()  # discard the connection -- simulates real process-state loss

    conn2 = _fresh_connection()
    try:
        reloaded_device = get_device(conn2, device.id)
        reloaded_session = get_session(conn2, session.id)
        assert reloaded_device == device
        assert reloaded_session == session
        assert is_device_active(reloaded_device)
        assert session_status(reloaded_session) is RelaySessionStatus.ACTIVE

        snapshot = build_relay_snapshot(conn2, session_id=session.id, authenticated_user_id=owner)
        assert snapshot.mission_id == mission_id
        assert snapshot.relay_session_id == session.id
        assert snapshot.device_id == device.id
    finally:
        conn2.close()


# ── Second-device continuity: REQ-RELAY-STATE-001 core proof (spec §22) ──

def test_second_device_continuity_same_mission_and_owner():
    owner = _uid()
    mission_id = _mid()

    conn = _fresh_connection()
    try:
        _seed_full_mission(conn, mission_id=mission_id, owner_user_id=owner)
        device_a = register_device(conn, user_id=owner, trust_level=DeviceTrustLevel.TRUSTED, name="Device A")
        session_a = create_session(
            conn, device_id=device_a.id, mission_id=mission_id, authenticated_user_id=owner,
            mode=RelayMode.TRUSTED_DEVICE, ttl_seconds=3600,
        )
        snapshot_a = build_relay_snapshot(conn, session_id=session_a.id, authenticated_user_id=owner)
    finally:
        conn.close()

    conn2 = _fresh_connection()
    try:
        device_b = register_device(conn2, user_id=owner, trust_level=DeviceTrustLevel.PUBLIC, name="Device B")
        session_b = create_session(
            conn2, device_id=device_b.id, mission_id=mission_id, authenticated_user_id=owner,
            mode=RelayMode.PUBLIC_DEVICE, ttl_seconds=3600,
        )
        snapshot_b = build_relay_snapshot(conn2, session_id=session_b.id, authenticated_user_id=owner)
    finally:
        conn2.close()

    assert device_a.id != device_b.id
    assert session_a.id != session_b.id

    assert snapshot_a.repository == snapshot_b.repository
    assert snapshot_a.branch == snapshot_b.branch
    assert snapshot_a.current_revision == snapshot_b.current_revision
    assert snapshot_a.mission_state == snapshot_b.mission_state
    assert snapshot_a.mission == snapshot_b.mission
    assert snapshot_a.step == snapshot_b.step
    assert snapshot_a.requirements == snapshot_b.requirements
    assert snapshot_a.verifications == snapshot_b.verifications
    assert snapshot_a.production_proof == snapshot_b.production_proof
    assert snapshot_a.checkpoint == snapshot_b.checkpoint
    assert len(snapshot_a.model_activity) == len(snapshot_b.model_activity) == 1
    assert len(snapshot_a.tool_activity) == len(snapshot_b.tool_activity) == 1
    assert len(snapshot_a.authority_context) == len(snapshot_b.authority_context) == 1
    assert len(snapshot_a.pending_approvals) == len(snapshot_b.pending_approvals) == 1
    assert len(snapshot_a.pending_operations) == len(snapshot_b.pending_operations) == 1

    # No raw secret in either device's payload.
    for snap in (snapshot_a, snapshot_b):
        blob = json.dumps({
            "model_activity": [m.outcome_summary for m in snap.model_activity],
            "tool_activity": [t.outcome_summary for t in snap.tool_activity],
            "authority": [a.detail for a in snap.authority_context],
        })
        assert "BEGIN RSA PRIVATE KEY" not in blob
        assert "sk-" not in blob


# ── IDOR / cross-user access (spec §25) ──────────────────────────────

def test_cross_user_device_access_denied():
    owner = _uid()
    other = _uid()
    conn = _fresh_connection()
    try:
        device = register_device(conn, user_id=owner, trust_level=DeviceTrustLevel.TRUSTED)
        with pytest.raises(RelayAccessDeniedError):
            touch_device(conn, device.id, authenticated_user_id=other)
    finally:
        conn.close()


def test_cross_user_session_access_denied():
    owner = _uid()
    other = _uid()
    mission_id = _mid()
    conn = _fresh_connection()
    try:
        _seed_full_mission(conn, mission_id=mission_id, owner_user_id=owner)
        device = register_device(conn, user_id=owner, trust_level=DeviceTrustLevel.TRUSTED)
        session = create_session(
            conn, device_id=device.id, mission_id=mission_id, authenticated_user_id=owner,
            mode=RelayMode.TRUSTED_DEVICE, ttl_seconds=3600,
        )
        with pytest.raises(RelayAccessDeniedError):
            build_relay_snapshot(conn, session_id=session.id, authenticated_user_id=other)
        with pytest.raises(RelayAccessDeniedError):
            touch_session(conn, session.id, authenticated_user_id=other)
        with pytest.raises(RelayAccessDeniedError):
            revoke_session(conn, session.id, authenticated_user_id=other)
    finally:
        conn.close()


def test_cross_user_mission_session_creation_denied():
    owner = _uid()
    attacker = _uid()
    mission_id = _mid()
    conn = _fresh_connection()
    try:
        _seed_full_mission(conn, mission_id=mission_id, owner_user_id=owner)
        attacker_device = register_device(conn, user_id=attacker, trust_level=DeviceTrustLevel.TRUSTED)
        with pytest.raises(RelayAccessDeniedError):
            create_session(
                conn, device_id=attacker_device.id, mission_id=mission_id, authenticated_user_id=attacker,
                mode=RelayMode.TRUSTED_DEVICE, ttl_seconds=3600,
            )
    finally:
        conn.close()


def test_device_paired_with_wrong_user_cannot_create_session():
    owner = _uid()
    other = _uid()
    mission_id = _mid()
    conn = _fresh_connection()
    try:
        _seed_full_mission(conn, mission_id=mission_id, owner_user_id=owner)
        owner_device = register_device(conn, user_id=owner, trust_level=DeviceTrustLevel.TRUSTED)
        # `other` tries to use a device that isn't theirs at all.
        with pytest.raises(RelayAccessDeniedError):
            create_session(
                conn, device_id=owner_device.id, mission_id=mission_id, authenticated_user_id=other,
                mode=RelayMode.TRUSTED_DEVICE, ttl_seconds=3600,
            )
    finally:
        conn.close()


# ── Device revocation (spec §3, §24) ──────────────────────────────────

def test_revoked_device_cannot_create_new_session():
    owner = _uid()
    mission_id = _mid()
    conn = _fresh_connection()
    try:
        _seed_full_mission(conn, mission_id=mission_id, owner_user_id=owner)
        device = register_device(conn, user_id=owner, trust_level=DeviceTrustLevel.TRUSTED)
        revoke_device(conn, device.id, authenticated_user_id=owner)
        assert not is_device_active(get_device(conn, device.id))
        with pytest.raises(DeviceRevokedError):
            create_session(
                conn, device_id=device.id, mission_id=mission_id, authenticated_user_id=owner,
                mode=RelayMode.TRUSTED_DEVICE, ttl_seconds=3600,
            )
    finally:
        conn.close()


def test_revoked_device_cannot_be_touched_active_again():
    owner = _uid()
    conn = _fresh_connection()
    try:
        device = register_device(conn, user_id=owner, trust_level=DeviceTrustLevel.TRUSTED)
        revoke_device(conn, device.id, authenticated_user_id=owner)
        with pytest.raises(DeviceRevokedError):
            touch_device(conn, device.id, authenticated_user_id=owner)
    finally:
        conn.close()


def test_revoking_already_revoked_device_is_a_no_op_not_an_error():
    owner = _uid()
    conn = _fresh_connection()
    try:
        device = register_device(conn, user_id=owner, trust_level=DeviceTrustLevel.TRUSTED)
        first = revoke_device(conn, device.id, authenticated_user_id=owner)
        second = revoke_device(conn, device.id, authenticated_user_id=owner)
        assert first.revoked_at == second.revoked_at
    finally:
        conn.close()


# ── Session revocation foundation (spec §6, §24) ─────────────────────

def test_revoke_other_session_rejects_targeting_current_session():
    owner = _uid()
    mission_id = _mid()
    conn = _fresh_connection()
    try:
        _seed_full_mission(conn, mission_id=mission_id, owner_user_id=owner)
        device = register_device(conn, user_id=owner, trust_level=DeviceTrustLevel.TRUSTED)
        session = create_session(
            conn, device_id=device.id, mission_id=mission_id, authenticated_user_id=owner,
            mode=RelayMode.TRUSTED_DEVICE, ttl_seconds=3600,
        )
        with pytest.raises(Exception):
            revoke_other_session(
                conn, current_session_id=session.id, target_session_id=session.id, authenticated_user_id=owner,
            )
        assert session_status(get_session(conn, session.id)) is RelaySessionStatus.ACTIVE
    finally:
        conn.close()


def test_revoke_other_session_leaves_current_valid_and_revokes_target():
    owner = _uid()
    mission_id = _mid()
    conn = _fresh_connection()
    try:
        _seed_full_mission(conn, mission_id=mission_id, owner_user_id=owner)
        device_a = register_device(conn, user_id=owner, trust_level=DeviceTrustLevel.TRUSTED)
        device_b = register_device(conn, user_id=owner, trust_level=DeviceTrustLevel.TRUSTED)
        session_a = create_session(
            conn, device_id=device_a.id, mission_id=mission_id, authenticated_user_id=owner,
            mode=RelayMode.TRUSTED_DEVICE, ttl_seconds=3600,
        )
        session_b = create_session(
            conn, device_id=device_b.id, mission_id=mission_id, authenticated_user_id=owner,
            mode=RelayMode.TRUSTED_DEVICE, ttl_seconds=3600,
        )
        revoke_other_session(conn, current_session_id=session_a.id, target_session_id=session_b.id, authenticated_user_id=owner)

        assert session_status(get_session(conn, session_a.id)) is RelaySessionStatus.ACTIVE
        assert session_status(get_session(conn, session_b.id)) is RelaySessionStatus.REVOKED
        with pytest.raises(RelaySessionInvalidError):
            build_relay_snapshot(conn, session_id=session_b.id, authenticated_user_id=owner)
        # Revoking session remains valid and can still produce a snapshot.
        build_relay_snapshot(conn, session_id=session_a.id, authenticated_user_id=owner)
    finally:
        conn.close()


def test_revoke_other_session_cross_user_denied():
    owner = _uid()
    other = _uid()
    mission_id = _mid()
    conn = _fresh_connection()
    try:
        _seed_full_mission(conn, mission_id=mission_id, owner_user_id=owner)
        owner_device = register_device(conn, user_id=owner, trust_level=DeviceTrustLevel.TRUSTED)
        owner_session = create_session(
            conn, device_id=owner_device.id, mission_id=mission_id, authenticated_user_id=owner,
            mode=RelayMode.TRUSTED_DEVICE, ttl_seconds=3600,
        )
        other_device = register_device(conn, user_id=other, trust_level=DeviceTrustLevel.TRUSTED)
        # `other` has no mission access, so give them a session on a mission they own instead,
        # then attempt to revoke owner's session as an "other" session -- must be denied.
        other_mission_id = _mid()
        _seed_full_mission(conn, mission_id=other_mission_id, owner_user_id=other)
        other_session = create_session(
            conn, device_id=other_device.id, mission_id=other_mission_id, authenticated_user_id=other,
            mode=RelayMode.TRUSTED_DEVICE, ttl_seconds=3600,
        )
        with pytest.raises(RelayAccessDeniedError):
            revoke_other_session(
                conn, current_session_id=other_session.id, target_session_id=owner_session.id, authenticated_user_id=other,
            )
        assert session_status(get_session(conn, owner_session.id)) is RelaySessionStatus.ACTIVE
    finally:
        conn.close()


def test_revoke_all_other_sessions_is_atomic_and_preserves_current():
    owner = _uid()
    mission_id = _mid()
    conn = _fresh_connection()
    try:
        _seed_full_mission(conn, mission_id=mission_id, owner_user_id=owner)
        devices = [register_device(conn, user_id=owner, trust_level=DeviceTrustLevel.TRUSTED) for _ in range(4)]
        sessions = [
            create_session(
                conn, device_id=d.id, mission_id=mission_id, authenticated_user_id=owner,
                mode=RelayMode.TRUSTED_DEVICE, ttl_seconds=3600,
            )
            for d in devices
        ]
        current = sessions[0]
        revoked = revoke_all_other_sessions(conn, current_session_id=current.id, authenticated_user_id=owner)

        assert {s.id for s in revoked} == {s.id for s in sessions[1:]}
        assert session_status(get_session(conn, current.id)) is RelaySessionStatus.ACTIVE
        for s in sessions[1:]:
            assert session_status(get_session(conn, s.id)) is RelaySessionStatus.REVOKED
    finally:
        conn.close()


def test_revoked_session_cannot_be_revived_via_touch():
    owner = _uid()
    mission_id = _mid()
    conn = _fresh_connection()
    try:
        _seed_full_mission(conn, mission_id=mission_id, owner_user_id=owner)
        device = register_device(conn, user_id=owner, trust_level=DeviceTrustLevel.TRUSTED)
        session = create_session(
            conn, device_id=device.id, mission_id=mission_id, authenticated_user_id=owner,
            mode=RelayMode.TRUSTED_DEVICE, ttl_seconds=3600,
        )
        revoke_session(conn, session.id, authenticated_user_id=owner, reason="test revoke")
        with pytest.raises(RelaySessionInvalidError) as exc_info:
            touch_session(conn, session.id, authenticated_user_id=owner)
        assert exc_info.value.status is RelaySessionStatus.REVOKED
    finally:
        conn.close()


# ── Expiry with an injected clock -- no real sleeps (spec §5, §27) ───

def test_expired_session_cannot_be_touched_or_produce_snapshot():
    owner = _uid()
    mission_id = _mid()
    conn = _fresh_connection()
    try:
        _seed_full_mission(conn, mission_id=mission_id, owner_user_id=owner)
        device = register_device(conn, user_id=owner, trust_level=DeviceTrustLevel.TRUSTED)
        session = create_session(
            conn, device_id=device.id, mission_id=mission_id, authenticated_user_id=owner,
            mode=RelayMode.TRUSTED_DEVICE, ttl_seconds=1,
        )
        future = lambda: datetime.now(timezone.utc) + timedelta(days=1)  # noqa: E731

        with pytest.raises(RelaySessionInvalidError) as exc_info:
            touch_session(conn, session.id, authenticated_user_id=owner, now_fn=future)
        assert exc_info.value.status is RelaySessionStatus.EXPIRED

        with pytest.raises(RelaySessionInvalidError) as exc_info2:
            build_relay_snapshot(conn, session_id=session.id, authenticated_user_id=owner, now_fn=future)
        assert exc_info2.value.status is RelaySessionStatus.EXPIRED
    finally:
        conn.close()


# ── No side effect on read (spec §21) ─────────────────────────────────

def test_build_relay_snapshot_does_not_touch_last_seen_at():
    owner = _uid()
    mission_id = _mid()
    conn = _fresh_connection()
    try:
        _seed_full_mission(conn, mission_id=mission_id, owner_user_id=owner)
        device = register_device(conn, user_id=owner, trust_level=DeviceTrustLevel.TRUSTED)
        session = create_session(
            conn, device_id=device.id, mission_id=mission_id, authenticated_user_id=owner,
            mode=RelayMode.TRUSTED_DEVICE, ttl_seconds=3600,
        )
        before = get_session(conn, session.id).last_seen_at
        build_relay_snapshot(conn, session_id=session.id, authenticated_user_id=owner)
        build_relay_snapshot(conn, session_id=session.id, authenticated_user_id=owner)
        after = get_session(conn, session.id).last_seen_at
        assert before == after
    finally:
        conn.close()


# ── Raw secret prohibition, end to end against real Postgres (spec §19) ──

def test_snapshot_contains_no_raw_secrets_from_seeded_adversarial_fields():
    owner = _uid()
    mission_id = _mid()
    conn = _fresh_connection()
    try:
        requirement_id = _seed_full_mission(conn, mission_id=mission_id, owner_user_id=owner)
        now = _now_iso()
        with conn.cursor() as cur:
            cur.execute(
                "UPDATE model_invocations SET outcome_summary = %s WHERE mission_id = %s",
                ("leaked credential: postgres://admin:sup3rs3cret@db.internal:5432/prod", mission_id),
            )
            cur.execute(
                "UPDATE tool_invocations SET outcome_summary = %s WHERE mission_id = %s",
                ("Authorization: Bearer abcdefghijklmnopqrstuvwx1234567890", mission_id),
            )
            cur.execute(
                "UPDATE authority_decisions SET detail = %s WHERE mission_id = %s",
                ("api_key: sk-abcdefghijklmnopqrstuvwxyz123456", mission_id),
            )
            cur.execute(
                "UPDATE checkpoints SET active_blocker = %s WHERE mission_id = %s",
                ("-----BEGIN RSA PRIVATE KEY-----\nMIIBogIBAAKCAQ==\n-----END RSA PRIVATE KEY-----", mission_id),
            )
            cur.execute(
                "UPDATE approvals SET reason = %s WHERE mission_id = %s",
                ("password=Tr0ub4dor&3-actually-long-enough-to-match", mission_id),
            )
        conn.commit()

        device = register_device(conn, user_id=owner, trust_level=DeviceTrustLevel.TRUSTED)
        session = create_session(
            conn, device_id=device.id, mission_id=mission_id, authenticated_user_id=owner,
            mode=RelayMode.TRUSTED_DEVICE, ttl_seconds=3600,
        )
        snapshot = build_relay_snapshot(conn, session_id=session.id, authenticated_user_id=owner)

        blob = json.dumps({
            "model": [m.outcome_summary for m in snapshot.model_activity],
            "tool": [t.outcome_summary for t in snapshot.tool_activity],
            "authority": [a.detail for a in snapshot.authority_context],
            "checkpoint_blocker": snapshot.checkpoint.active_blocker,
            "approval_reason": [a.reason for a in snapshot.pending_approvals],
        })
        assert "sup3rs3cret" not in blob
        assert "Bearer abcdefghijklmnopqrstuvwx1234567890" not in blob
        assert "sk-abcdefghijklmnopqrstuvwxyz123456" not in blob
        assert "BEGIN RSA PRIVATE KEY" not in blob
        assert "Tr0ub4dor" not in blob
        assert "[REDACTED]" in blob
    finally:
        conn.close()


def test_missing_domains_are_absent_not_fabricated():
    """A mission with NO production proof, NO checkpoint, and NO
    pending approvals/operations must report those domains as
    genuinely absent -- never a fabricated ENGINEERING_READY / fake
    checkpoint (spec section 32.15)."""
    owner = _uid()
    mission_id = _mid()
    conn = _fresh_connection()
    try:
        create_mission(conn, id=mission_id, repository="org/bare-repo", mode="BUILD", autonomy_level="L1", owner_user_id=owner)
        device = register_device(conn, user_id=owner, trust_level=DeviceTrustLevel.TRUSTED)
        session = create_session(
            conn, device_id=device.id, mission_id=mission_id, authenticated_user_id=owner,
            mode=RelayMode.TRUSTED_DEVICE, ttl_seconds=3600,
        )
        snapshot = build_relay_snapshot(conn, session_id=session.id, authenticated_user_id=owner)
        assert snapshot.production_proof.available is False
        assert snapshot.production_proof.release_state is None
        assert snapshot.checkpoint.checkpoint_id is None
        assert snapshot.pending_approvals == ()
        assert snapshot.pending_operations == ()
        assert snapshot.requirements == ()
        assert snapshot.step.current_step_id is None
        assert snapshot.step.integrity_warning is None
    finally:
        conn.close()


def test_relay_session_not_found_and_device_not_found_raise():
    owner = _uid()
    conn = _fresh_connection()
    try:
        with pytest.raises(RelaySessionNotFoundError):
            build_relay_snapshot(conn, session_id="rlysess_doesnotexist", authenticated_user_id=owner)
        with pytest.raises(DeviceNotFoundError):
            touch_device(conn, "dev_doesnotexist", authenticated_user_id=owner)
    finally:
        conn.close()
