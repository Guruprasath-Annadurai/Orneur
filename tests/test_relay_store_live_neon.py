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
    _create_session_with_explicit_ttl,
    get_device,
    get_session,
    is_device_active,
    list_active_sessions,
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


_TEST_USER_CREDENTIALS: dict[str, tuple[str, str]] = {}


def _uid() -> str:
    """Creates a REAL, isolated auth-layer user (via `isolated_home`'s
    fresh SQLite backend, per this file's autouse `_use_isolated_auth_home`
    fixture below) and returns its real id -- so `owner` throughout this
    file is a genuine authenticated principal, not merely an arbitrary
    string, matching Phase 15.12's requirement that TRUSTED enrollment
    go through a real reauthentication against a real account. Email/
    password are kept in `_TEST_USER_CREDENTIALS` so `_reauth_for()` /
    `_register_trusted_device()` below can perform a REAL fresh
    reauthentication for this same user later in the same test."""
    from orca.auth.store import create_user

    email = f"relay-qual-{uuid.uuid4().hex[:10]}@example.com"
    password = f"Pw{uuid.uuid4().hex[:16]}!"
    user = create_user(email, password)
    _TEST_USER_CREDENTIALS[user.id] = (email, password)
    return user.id


def _reauth_for(owner: str, *, now_fn=None):
    """Returns a REAL server-issued `ReauthGrant` (15.12.1) -- never a
    client-fabricatable object. `authenticated_user_id` selects the
    account (no separate email parameter, 15.12.1 item 4: the account
    is looked up FROM the authenticated principal)."""
    from orca.mission.relay_security import verify_reauthentication

    _email, password = _TEST_USER_CREDENTIALS[owner]
    kwargs = {"authenticated_user_id": owner, "password": password}
    if now_fn is not None:
        kwargs["now_fn"] = now_fn
    return verify_reauthentication(**kwargs)


def _register_trusted_device(conn, owner: str, name: str | None = None, now_fn=None):
    """Test helper: performs a REAL fresh reauthentication (against the
    isolated real auth-layer account created by `_uid()`) and then
    enrolls a TRUSTED device through the real, enforced
    `orca.mission.relay_security.enroll_trusted_device()` path -- never
    a bypass of the Phase 15.12.1 enrollment boundary."""
    from orca.mission.relay_security import enroll_trusted_device

    reauth_kwargs = {}
    if now_fn is not None:
        reauth_kwargs["now_fn"] = now_fn
    grant = _reauth_for(owner, **reauth_kwargs)
    enroll_kwargs = {"authenticated_user_id": owner, "reauth_grant": grant, "name": name}
    if now_fn is not None:
        enroll_kwargs["now_fn"] = now_fn
    return enroll_trusted_device(conn, **enroll_kwargs)


@pytest.fixture(autouse=True)
def _use_isolated_auth_home(isolated_home):
    """Every test in this file that creates a real auth-layer user (via
    `_uid()`) does so against a fresh, isolated temp SQLite auth
    database -- never this developer's real `~/.orca/auth.db` -- per
    the project's own established `isolated_home` convention."""
    yield


def _rid() -> str:
    return f"REQ-RELAY-{uuid.uuid4().hex[:8].upper()}-001"


def _now_iso() -> str:
    return datetime.now(timezone.utc).isoformat()


def _seed_full_mission(conn, *, mission_id: str, owner_user_id: str, revision: str = "rev1", workspace_id: str | None = "ws_relay_qual") -> str:
    """Seeds a mission with representative durable state across every
    Relay governed-state domain (spec section 22): workspace,
    requirement, verification record (both requirement-scoped and
    mission-level test-category records), checkpoint, Production
    Proof, mission step, operation/approval/authority-decision,
    model/tool invocation. Returns the seeded requirement_id."""
    create_mission(
        conn, id=mission_id, repository="org/relay-qual-repo", branch="main", mode="BUILD",
        autonomy_level="L1", owner_user_id=owner_user_id, current_revision=revision,
        workspace_id=workspace_id,
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
        device = _register_trusted_device(conn, owner, name="Device A")
        session = _create_session_with_explicit_ttl(
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
# 15.11.1 item 4: assert EVERY material REQ-RELAY-STATE-001 domain
# individually -- workspace, repository, branch, revision, mission
# state, step state, requirement progress, test progress, verification
# state, Production Proof status, pending approvals, pending dangerous
# actions, checkpoints, model/agent activity, tool activity, authority
# context, secret safety -- never inferred merely from two snapshot
# objects comparing equal.

def test_second_device_continuity_asserts_every_governed_domain_individually():
    owner = _uid()
    mission_id = _mid()

    conn = _fresh_connection()
    try:
        requirement_id = _seed_full_mission(conn, mission_id=mission_id, owner_user_id=owner, workspace_id="ws_relay_qual_domains")
        device_a = _register_trusted_device(conn, owner, name="Device A")
        session_a = _create_session_with_explicit_ttl(
            conn, device_id=device_a.id, mission_id=mission_id, authenticated_user_id=owner,
            mode=RelayMode.TRUSTED_DEVICE, ttl_seconds=3600,
        )
        snapshot_a = build_relay_snapshot(conn, session_id=session_a.id, authenticated_user_id=owner)
    finally:
        conn.close()

    conn2 = _fresh_connection()
    try:
        device_b = register_device(conn2, authenticated_user_id=owner, trust_level=DeviceTrustLevel.PUBLIC, name="Device B")
        session_b = _create_session_with_explicit_ttl(
            conn2, device_id=device_b.id, mission_id=mission_id, authenticated_user_id=owner,
            mode=RelayMode.PUBLIC_DEVICE, ttl_seconds=3600,
        )
        snapshot_b = build_relay_snapshot(conn2, session_id=session_b.id, authenticated_user_id=owner)
    finally:
        conn2.close()

    assert device_a.id != device_b.id
    assert session_a.id != session_b.id

    # -- workspace --
    assert snapshot_a.workspace_id == "ws_relay_qual_domains"
    assert snapshot_a.workspace_id == snapshot_b.workspace_id == snapshot_a.mission.workspace_id == snapshot_b.mission.workspace_id

    # -- repository / branch / revision --
    assert snapshot_a.repository == snapshot_b.repository == "org/relay-qual-repo"
    assert snapshot_a.branch == snapshot_b.branch == "main"
    assert snapshot_a.current_revision == snapshot_b.current_revision == "rev1"

    # -- mission state --
    assert snapshot_a.mission_state == snapshot_b.mission_state
    assert snapshot_a.mission == snapshot_b.mission

    # -- step state --
    assert snapshot_a.step.current_step_id is not None
    assert snapshot_a.step == snapshot_b.step

    # -- requirement progress --
    assert len(snapshot_a.requirements) == 1
    assert snapshot_a.requirements[0].requirement_id == requirement_id
    assert snapshot_a.requirements == snapshot_b.requirements

    # -- verification state (per requirement+category, distinct from test progress) --
    assert len(snapshot_a.verifications) >= 1
    assert any(v.requirement_id == requirement_id and v.category == "UNIT_TEST" for v in snapshot_a.verifications)
    assert snapshot_a.verifications == snapshot_b.verifications

    # -- test progress (mission-level, current-revision-only, distinct domain) --
    assert len(snapshot_a.test_progress) >= 1
    assert any(t.category == "UNIT_TEST" and t.revision == "rev1" for t in snapshot_a.test_progress)
    assert snapshot_a.test_progress == snapshot_b.test_progress

    # -- Production Proof status --
    assert snapshot_a.production_proof.available is True
    assert snapshot_a.production_proof.revision == "rev1"
    assert snapshot_a.production_proof == snapshot_b.production_proof

    # -- pending approvals --
    assert len(snapshot_a.pending_approvals) == 1
    assert snapshot_a.pending_approvals[0].decision == "PENDING"
    assert snapshot_a.pending_approvals == snapshot_b.pending_approvals

    # -- pending dangerous actions (operations) --
    assert len(snapshot_a.pending_operations) == 1
    assert snapshot_a.pending_operations[0].status == "REQUESTED"
    assert snapshot_a.pending_operations == snapshot_b.pending_operations

    # -- checkpoints --
    assert snapshot_a.checkpoint.checkpoint_id is not None
    assert snapshot_a.checkpoint == snapshot_b.checkpoint

    # -- model/agent activity --
    assert len(snapshot_a.model_activity) == 1
    assert snapshot_a.model_activity == snapshot_b.model_activity

    # -- tool activity --
    assert len(snapshot_a.tool_activity) == 1
    assert snapshot_a.tool_activity == snapshot_b.tool_activity

    # -- authority context --
    assert len(snapshot_a.authority_context) == 1
    assert snapshot_a.authority_context == snapshot_b.authority_context

    # -- secret safety --
    for snap in (snapshot_a, snapshot_b):
        blob = json.dumps({
            "model_activity": [m.outcome_summary for m in snap.model_activity],
            "tool_activity": [t.outcome_summary for t in snap.tool_activity],
            "authority": [a.detail for a in snap.authority_context],
        })
        assert "BEGIN RSA PRIVATE KEY" not in blob
        assert "sk-" not in blob


def test_second_device_continuity_with_genuinely_absent_workspace():
    """workspace_id may legitimately be None -- the DOMAIN/FIELD must
    still exist and agree across both devices, never fabricated."""
    owner = _uid()
    mission_id = _mid()
    conn = _fresh_connection()
    try:
        _seed_full_mission(conn, mission_id=mission_id, owner_user_id=owner, workspace_id=None)
        device_a = _register_trusted_device(conn, owner)
        session_a = _create_session_with_explicit_ttl(
            conn, device_id=device_a.id, mission_id=mission_id, authenticated_user_id=owner,
            mode=RelayMode.TRUSTED_DEVICE, ttl_seconds=3600,
        )
        snapshot_a = build_relay_snapshot(conn, session_id=session_a.id, authenticated_user_id=owner)

        device_b = register_device(conn, authenticated_user_id=owner, trust_level=DeviceTrustLevel.PUBLIC)
        session_b = _create_session_with_explicit_ttl(
            conn, device_id=device_b.id, mission_id=mission_id, authenticated_user_id=owner,
            mode=RelayMode.PUBLIC_DEVICE, ttl_seconds=3600,
        )
        snapshot_b = build_relay_snapshot(conn, session_id=session_b.id, authenticated_user_id=owner)

        assert snapshot_a.workspace_id is None
        assert snapshot_a.workspace_id == snapshot_b.workspace_id == snapshot_a.mission.workspace_id
    finally:
        conn.close()


# ── IDOR / cross-user access (spec §25) ──────────────────────────────

def test_cross_user_device_access_denied():
    owner = _uid()
    other = _uid()
    conn = _fresh_connection()
    try:
        device = _register_trusted_device(conn, owner)
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
        device = _register_trusted_device(conn, owner)
        session = _create_session_with_explicit_ttl(
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
        attacker_device = _register_trusted_device(conn, attacker)
        with pytest.raises(RelayAccessDeniedError):
            _create_session_with_explicit_ttl(
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
        owner_device = _register_trusted_device(conn, owner)
        # `other` tries to use a device that isn't theirs at all.
        with pytest.raises(RelayAccessDeniedError):
            _create_session_with_explicit_ttl(
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
        device = _register_trusted_device(conn, owner)
        revoke_device(conn, device.id, authenticated_user_id=owner)
        assert not is_device_active(get_device(conn, device.id))
        with pytest.raises(DeviceRevokedError):
            _create_session_with_explicit_ttl(
                conn, device_id=device.id, mission_id=mission_id, authenticated_user_id=owner,
                mode=RelayMode.TRUSTED_DEVICE, ttl_seconds=3600,
            )
    finally:
        conn.close()


def test_revoked_device_cannot_be_touched_active_again():
    owner = _uid()
    conn = _fresh_connection()
    try:
        device = _register_trusted_device(conn, owner)
        revoke_device(conn, device.id, authenticated_user_id=owner)
        with pytest.raises(DeviceRevokedError):
            touch_device(conn, device.id, authenticated_user_id=owner)
    finally:
        conn.close()


def test_revoking_already_revoked_device_is_a_no_op_not_an_error():
    owner = _uid()
    conn = _fresh_connection()
    try:
        device = _register_trusted_device(conn, owner)
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
        device = _register_trusted_device(conn, owner)
        session = _create_session_with_explicit_ttl(
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
        device_a = _register_trusted_device(conn, owner)
        device_b = _register_trusted_device(conn, owner)
        session_a = _create_session_with_explicit_ttl(
            conn, device_id=device_a.id, mission_id=mission_id, authenticated_user_id=owner,
            mode=RelayMode.TRUSTED_DEVICE, ttl_seconds=3600,
        )
        session_b = _create_session_with_explicit_ttl(
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
        owner_device = _register_trusted_device(conn, owner)
        owner_session = _create_session_with_explicit_ttl(
            conn, device_id=owner_device.id, mission_id=mission_id, authenticated_user_id=owner,
            mode=RelayMode.TRUSTED_DEVICE, ttl_seconds=3600,
        )
        other_device = _register_trusted_device(conn, other)
        # `other` has no mission access, so give them a session on a mission they own instead,
        # then attempt to revoke owner's session as an "other" session -- must be denied.
        other_mission_id = _mid()
        _seed_full_mission(conn, mission_id=other_mission_id, owner_user_id=other)
        other_session = _create_session_with_explicit_ttl(
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
        devices = [_register_trusted_device(conn, owner) for _ in range(4)]
        sessions = [
            _create_session_with_explicit_ttl(
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
        device = _register_trusted_device(conn, owner)
        session = _create_session_with_explicit_ttl(
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
        device = _register_trusted_device(conn, owner)
        session = _create_session_with_explicit_ttl(
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
        device = _register_trusted_device(conn, owner)
        session = _create_session_with_explicit_ttl(
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

        device = _register_trusted_device(conn, owner)
        session = _create_session_with_explicit_ttl(
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
        device = _register_trusted_device(conn, owner)
        session = _create_session_with_explicit_ttl(
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


# ── Device registration binds to the authenticated principal (15.11.1 item 5) ──

def test_register_device_has_no_caller_controlled_ownership_override():
    """The public register_device() signature has no parameter through
    which a caller can name a DIFFERENT durable owner than
    `authenticated_user_id` -- attempting the old `user_id=` kwarg (or
    any other identity-naming kwarg) is a TypeError, not a silent
    ownership override."""
    import inspect
    sig = inspect.signature(register_device)
    assert "user_id" not in sig.parameters
    assert "owner_user_id" not in sig.parameters
    assert "authenticated_user_id" in sig.parameters


def test_registered_device_user_id_always_equals_authenticated_principal():
    owner = _uid()
    conn = _fresh_connection()
    try:
        device = _register_trusted_device(conn, owner)
        assert device.user_id == owner
        reloaded = get_device(conn, device.id)
        assert reloaded.user_id == owner
    finally:
        conn.close()


def test_attacker_cannot_create_device_durably_owned_by_victim():
    """An attacker who merely KNOWS a victim's user id cannot make
    register_device() durably attribute the new device to the victim
    -- the device is always owned by whichever `authenticated_user_id`
    the (trusted) caller passes, and there is no second parameter an
    attacker-controlled request body could smuggle a victim id into."""
    attacker = _uid()
    victim = _uid()
    conn = _fresh_connection()
    try:
        # The only identity register_device() will ever durably use is
        # the one explicit authenticated_user_id argument -- simulating
        # "attacker calls this as themselves" is exactly attacker's own id.
        device = _register_trusted_device(conn, attacker, name=f"pretend-owned-by-{victim}")
        assert device.user_id == attacker
        assert device.user_id != victim
    finally:
        conn.close()


# ── Dead-session guard for session-management actions (15.11.1 item 6) ──

def test_revoked_current_session_cannot_revoke_another():
    owner = _uid()
    mission_id = _mid()
    conn = _fresh_connection()
    try:
        _seed_full_mission(conn, mission_id=mission_id, owner_user_id=owner)
        device_a = _register_trusted_device(conn, owner)
        device_b = _register_trusted_device(conn, owner)
        session_a = _create_session_with_explicit_ttl(conn, device_id=device_a.id, mission_id=mission_id, authenticated_user_id=owner, mode=RelayMode.TRUSTED_DEVICE, ttl_seconds=3600)
        session_b = _create_session_with_explicit_ttl(conn, device_id=device_b.id, mission_id=mission_id, authenticated_user_id=owner, mode=RelayMode.TRUSTED_DEVICE, ttl_seconds=3600)

        revoke_session(conn, session_a.id, authenticated_user_id=owner, reason="dead current session")
        with pytest.raises(RelaySessionInvalidError) as exc_info:
            revoke_other_session(conn, current_session_id=session_a.id, target_session_id=session_b.id, authenticated_user_id=owner)
        assert exc_info.value.status is RelaySessionStatus.REVOKED
        assert session_status(get_session(conn, session_b.id)) is RelaySessionStatus.ACTIVE  # untouched
    finally:
        conn.close()


def test_expired_current_session_cannot_revoke_another():
    owner = _uid()
    mission_id = _mid()
    conn = _fresh_connection()
    try:
        _seed_full_mission(conn, mission_id=mission_id, owner_user_id=owner)
        device_a = _register_trusted_device(conn, owner)
        device_b = _register_trusted_device(conn, owner)
        session_a = _create_session_with_explicit_ttl(conn, device_id=device_a.id, mission_id=mission_id, authenticated_user_id=owner, mode=RelayMode.TRUSTED_DEVICE, ttl_seconds=1)
        session_b = _create_session_with_explicit_ttl(conn, device_id=device_b.id, mission_id=mission_id, authenticated_user_id=owner, mode=RelayMode.TRUSTED_DEVICE, ttl_seconds=3600)
        future = lambda: datetime.now(timezone.utc) + timedelta(days=1)  # noqa: E731

        with pytest.raises(RelaySessionInvalidError) as exc_info:
            revoke_other_session(conn, current_session_id=session_a.id, target_session_id=session_b.id, authenticated_user_id=owner, now_fn=future)
        assert exc_info.value.status is RelaySessionStatus.EXPIRED
        assert session_status(get_session(conn, session_b.id)) is RelaySessionStatus.ACTIVE
    finally:
        conn.close()


def test_revoked_current_device_cannot_revoke_another_session():
    owner = _uid()
    mission_id = _mid()
    conn = _fresh_connection()
    try:
        _seed_full_mission(conn, mission_id=mission_id, owner_user_id=owner)
        device_a = _register_trusted_device(conn, owner)
        device_b = _register_trusted_device(conn, owner)
        session_a = _create_session_with_explicit_ttl(conn, device_id=device_a.id, mission_id=mission_id, authenticated_user_id=owner, mode=RelayMode.TRUSTED_DEVICE, ttl_seconds=3600)
        session_b = _create_session_with_explicit_ttl(conn, device_id=device_b.id, mission_id=mission_id, authenticated_user_id=owner, mode=RelayMode.TRUSTED_DEVICE, ttl_seconds=3600)

        # Device A is revoked AFTER its session was created -- the session
        # itself is still unexpired/unrevoked, but its device is dead now.
        revoke_device(conn, device_a.id, authenticated_user_id=owner)
        with pytest.raises(DeviceRevokedError):
            revoke_other_session(conn, current_session_id=session_a.id, target_session_id=session_b.id, authenticated_user_id=owner)
        assert session_status(get_session(conn, session_b.id)) is RelaySessionStatus.ACTIVE
    finally:
        conn.close()


def test_active_session_context_legitimately_revokes_other_and_all_others():
    owner = _uid()
    mission_id = _mid()
    conn = _fresh_connection()
    try:
        _seed_full_mission(conn, mission_id=mission_id, owner_user_id=owner)
        devices = [_register_trusted_device(conn, owner) for _ in range(3)]
        sessions = [
            _create_session_with_explicit_ttl(conn, device_id=d.id, mission_id=mission_id, authenticated_user_id=owner, mode=RelayMode.TRUSTED_DEVICE, ttl_seconds=3600)
            for d in devices
        ]
        current, other1, other2 = sessions

        revoke_other_session(conn, current_session_id=current.id, target_session_id=other1.id, authenticated_user_id=owner)
        assert session_status(get_session(conn, other1.id)) is RelaySessionStatus.REVOKED
        assert session_status(get_session(conn, current.id)) is RelaySessionStatus.ACTIVE

        revoked = revoke_all_other_sessions(conn, current_session_id=current.id, authenticated_user_id=owner)
        assert {s.id for s in revoked} == {other2.id}  # other1 was already revoked, excluded by revoked_at IS NULL
        assert session_status(get_session(conn, current.id)) is RelaySessionStatus.ACTIVE
    finally:
        conn.close()


# ── Active-session list respects device revocation (15.11.1 item 7) ──

def test_list_active_sessions_excludes_session_on_later_revoked_device():
    owner = _uid()
    mission_id = _mid()
    conn = _fresh_connection()
    try:
        _seed_full_mission(conn, mission_id=mission_id, owner_user_id=owner)
        device = _register_trusted_device(conn, owner)
        session = _create_session_with_explicit_ttl(conn, device_id=device.id, mission_id=mission_id, authenticated_user_id=owner, mode=RelayMode.TRUSTED_DEVICE, ttl_seconds=3600)

        assert session.id in {s.id for s in list_active_sessions(conn, authenticated_user_id=owner)}

        revoke_device(conn, device.id, authenticated_user_id=owner)

        # The session row itself is still unexpired/unrevoked, but its
        # device is dead -- it must disappear from the active list.
        assert session.id not in {s.id for s in list_active_sessions(conn, authenticated_user_id=owner)}
        assert session.revoked_at is None  # the SESSION row itself was never touched

        with pytest.raises(DeviceRevokedError):
            build_relay_snapshot(conn, session_id=session.id, authenticated_user_id=owner)
    finally:
        conn.close()


# ── Pending operations must actually be pending (15.11.1 item 8) ────

def test_failed_operation_absent_from_pending_operations():
    owner = _uid()
    mission_id = _mid()
    conn = _fresh_connection()
    try:
        _seed_full_mission(conn, mission_id=mission_id, owner_user_id=owner)  # seeds 1 REQUESTED op
        now = _now_iso()
        with conn.cursor() as cur:
            cur.execute(
                "INSERT INTO operations (id, mission_id, idempotency_key, kind, status, requested_at, completed_at, requested_by) "
                "VALUES (%s, %s, %s, 'deploy', 'FAILED', %s, %s, %s)",
                (f"op_failed_{uuid.uuid4().hex[:8]}", mission_id, f"idem_failed_{uuid.uuid4().hex[:8]}", now, now, owner),
            )
        conn.commit()

        device = _register_trusted_device(conn, owner)
        session = _create_session_with_explicit_ttl(conn, device_id=device.id, mission_id=mission_id, authenticated_user_id=owner, mode=RelayMode.TRUSTED_DEVICE, ttl_seconds=3600)
        snapshot = build_relay_snapshot(conn, session_id=session.id, authenticated_user_id=owner)

        assert all(op.status != "FAILED" for op in snapshot.pending_operations)
        assert len(snapshot.pending_operations) == 1  # only the originally-seeded REQUESTED one
        assert snapshot.pending_operations[0].status == "REQUESTED"
    finally:
        conn.close()


# ── Production Proof freshness truthfulness (15.11.1 item 9) ────────

def test_production_proof_stale_is_unknown_not_current_when_revision_matches():
    """Revision equality alone must never be reported as CURRENT
    (`stale=False`) -- only as UNKNOWN (`stale=None`), since Relay
    cannot durably reconstruct the full stale-proof decision context."""
    owner = _uid()
    mission_id = _mid()
    conn = _fresh_connection()
    try:
        _seed_full_mission(conn, mission_id=mission_id, owner_user_id=owner, revision="rev1")
        device = _register_trusted_device(conn, owner)
        session = _create_session_with_explicit_ttl(conn, device_id=device.id, mission_id=mission_id, authenticated_user_id=owner, mode=RelayMode.TRUSTED_DEVICE, ttl_seconds=3600)
        snapshot = build_relay_snapshot(conn, session_id=session.id, authenticated_user_id=owner)

        assert snapshot.production_proof.revision == "rev1"  # matches mission.current_revision
        assert snapshot.production_proof.stale is None  # UNKNOWN, never False/CURRENT
    finally:
        conn.close()


def test_production_proof_stale_is_true_on_revision_mismatch():
    owner = _uid()
    mission_id = _mid()
    conn = _fresh_connection()
    try:
        requirement_id = _seed_full_mission(conn, mission_id=mission_id, owner_user_id=owner, revision="rev1")
        # Advance the mission's current_revision without a new proof.
        with conn.cursor() as cur:
            cur.execute("UPDATE missions SET current_revision = %s WHERE id = %s", ("rev2", mission_id))
        conn.commit()

        device = _register_trusted_device(conn, owner)
        session = _create_session_with_explicit_ttl(conn, device_id=device.id, mission_id=mission_id, authenticated_user_id=owner, mode=RelayMode.TRUSTED_DEVICE, ttl_seconds=3600)
        snapshot = build_relay_snapshot(conn, session_id=session.id, authenticated_user_id=owner)

        assert snapshot.production_proof.revision == "rev1"
        assert snapshot.current_revision == "rev2"
        assert snapshot.production_proof.stale is True
    finally:
        conn.close()


# ── Snapshot consistency (15.11.1 item 10) ───────────────────────────

def test_repeatable_read_isolation_prevents_mixed_snapshot_reads():
    """Proves the REPEATABLE READ mechanism `build_relay_snapshot()`
    relies on, directly: two reads inside the SAME transaction see the
    SAME data even though a DIFFERENT connection commits a change to
    that exact row in between -- a snapshot cannot be silently
    assembled from a mix of before/after database versions."""
    owner = _uid()
    mission_id = _mid()
    conn_reader = _fresh_connection()
    conn_writer = _fresh_connection()
    try:
        create_mission(
            conn_writer, id=mission_id, repository="org/consistency-repo", mode="BUILD",
            autonomy_level="L1", owner_user_id=owner, current_revision="rev1",
        )

        with conn_reader.cursor() as cur:
            cur.execute("SET TRANSACTION ISOLATION LEVEL REPEATABLE READ, READ ONLY")
            cur.execute("SELECT current_revision FROM missions WHERE id = %s", (mission_id,))
            first_read = cur.fetchone()["current_revision"]

            with conn_writer.cursor() as wcur:
                wcur.execute("UPDATE missions SET current_revision = %s WHERE id = %s", ("rev2", mission_id))
            conn_writer.commit()

            # Still inside the reader's ORIGINAL transaction:
            cur.execute("SELECT current_revision FROM missions WHERE id = %s", (mission_id,))
            second_read = cur.fetchone()["current_revision"]
        conn_reader.commit()

        assert first_read == second_read == "rev1"  # the concurrent write is invisible to this transaction

        with conn_reader.cursor() as cur:
            cur.execute("SELECT current_revision FROM missions WHERE id = %s", (mission_id,))
            after_commit_read = cur.fetchone()["current_revision"]
        conn_reader.commit()
        assert after_commit_read == "rev2"  # a FRESH transaction does see it
    finally:
        conn_reader.close()
        conn_writer.close()


def test_snapshot_names_its_own_consistency_basis():
    owner = _uid()
    mission_id = _mid()
    conn = _fresh_connection()
    try:
        _seed_full_mission(conn, mission_id=mission_id, owner_user_id=owner)
        device = _register_trusted_device(conn, owner)
        session = _create_session_with_explicit_ttl(conn, device_id=device.id, mission_id=mission_id, authenticated_user_id=owner, mode=RelayMode.TRUSTED_DEVICE, ttl_seconds=3600)
        snapshot = build_relay_snapshot(conn, session_id=session.id, authenticated_user_id=owner)
        assert "REPEATABLE READ" in snapshot.consistency_basis
        assert "READ ONLY" in snapshot.consistency_basis
    finally:
        conn.close()


# ── No hidden read side effect, re-proven after the consistency refactor (15.11.1 item 11) ──

def test_build_relay_snapshot_mutates_nothing_across_every_domain():
    owner = _uid()
    mission_id = _mid()
    conn = _fresh_connection()
    try:
        _seed_full_mission(conn, mission_id=mission_id, owner_user_id=owner)
        device = _register_trusted_device(conn, owner)
        session = _create_session_with_explicit_ttl(conn, device_id=device.id, mission_id=mission_id, authenticated_user_id=owner, mode=RelayMode.TRUSTED_DEVICE, ttl_seconds=3600)

        def _fingerprint():
            with conn.cursor() as cur:
                cur.execute("SELECT state, current_revision FROM missions WHERE id = %s", (mission_id,))
                mission_row = dict(cur.fetchone())
                cur.execute("SELECT status FROM operations WHERE mission_id = %s ORDER BY id", (mission_id,))
                op_statuses = [r["status"] for r in cur.fetchall()]
                cur.execute("SELECT decision FROM approvals WHERE mission_id = %s ORDER BY id", (mission_id,))
                approval_decisions = [r["decision"] for r in cur.fetchall()]
                cur.execute("SELECT count(*) AS c FROM checkpoints WHERE mission_id = %s", (mission_id,))
                checkpoint_count = cur.fetchone()["c"]
                cur.execute("SELECT count(*) AS c FROM verification_records WHERE mission_id = %s", (mission_id,))
                verification_count = cur.fetchone()["c"]
                cur.execute("SELECT count(*) AS c FROM production_proofs WHERE mission_id = %s", (mission_id,))
                proof_count = cur.fetchone()["c"]
            conn.commit()
            return (mission_row, op_statuses, approval_decisions, checkpoint_count, verification_count, proof_count)

        before_last_seen = get_session(conn, session.id).last_seen_at
        before = _fingerprint()
        build_relay_snapshot(conn, session_id=session.id, authenticated_user_id=owner)
        build_relay_snapshot(conn, session_id=session.id, authenticated_user_id=owner)
        after = _fingerprint()
        after_last_seen = get_session(conn, session.id).last_seen_at

        assert before == after
        assert before_last_seen == after_last_seen
    finally:
        conn.close()
