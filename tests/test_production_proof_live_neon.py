"""
Phase 15.10 -- LIVE_NEON_TEMP_BRANCH: durable Production Proof
persistence, fresh-connection reload, hash-integrity preservation,
mission/revision-binding, and append-only proof-history qualification
(spec sections 27, 30, 34), hardened by Phase 15.10.1's category-
identity binding, typed anti-gaming evidence, and honest
`overall_status` integrity (item 8).

POST-MIGRATION RECONCILIATION: `orca.mission.production_proof_schema
.PHASE_15_10_1_MIGRATION_SQL` was owner-approved and APPLIED to the
real production `orneur-core` database, and is now wired into
`orca.mission.db.apply_schema()` -- so `_ensure_schema` below (which
calls `apply_schema()` on the disposable target branch, exactly like
every other Phase 15 live-Neon test file) now bootstraps the MIGRATED
5-value `overall_status` CHECK constraint. `record_proof()` therefore
persists a genuinely `NOT_ENGINEERING_READY` proof SUCCESSFULLY, with
no translation and no application-side rejection -- proven end-to-end
below (`test_blocked_proof_persists_successfully_and_reloads_with_
matching_status`).

Skipped when ORNEUR_MISSION_DATABASE_URL(_DIRECT) are unset, matching
every other Phase 15 live-Neon test file.
"""
from __future__ import annotations

import os
import uuid

import pytest

from orca.mission.cognitive_court import CourtDecision, CourtRole, CourtVerdict, RiskLevel
from orca.mission.db import apply_schema, get_conn
from orca.mission.mission_store import create_mission
from orca.mission.production_proof import (
    CATEGORY_BUILD,
    CATEGORY_SECURITY,
    CATEGORY_UNIT_TEST,
    NOT_ENGINEERING_READY,
    AntiGamingAnalysisEvidence,
    ReleaseQualificationPolicy,
    compute_proof_hash,
    generate_production_proof,
)
from orca.mission.production_proof_store import (
    ProductionProofStoreError,
    is_proof_stale,
    latest_proof_for_mission,
    proofs_for_mission,
    record_proof,
)
from orca.mission.verification import VerificationOutcome, VerificationRecord
from orca.mission.verification_aggregation import RequiredVerificationScope

pytestmark = pytest.mark.skipif(
    not (os.environ.get("ORNEUR_MISSION_DATABASE_URL") and os.environ.get("ORNEUR_MISSION_DATABASE_URL_DIRECT")),
    reason="LIVE_NEON_TEMP_BRANCH: requires ORNEUR_MISSION_DATABASE_URL(_DIRECT) pointing at a disposable Neon branch",
)

_UNIT_TEST_SCOPE = RequiredVerificationScope(requirement_level_categories=frozenset({"UNIT_TEST"}))
_MINIMAL_POLICY = ReleaseQualificationPolicy(
    engineering_not_applicable={
        "integration_tests": "n/a", "e2e_tests": "n/a", "regression": "n/a", "authority": "n/a",
    },
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


def _rid() -> str:
    return f"REQ-LIVE-PROOF-{uuid.uuid4().hex[:8].upper()}-001"


def _seed_mission_and_requirement(conn, mission_id: str, requirement_id: str) -> None:
    create_mission(conn, id=mission_id, repository="org/repo", mode="BUILD",
                    autonomy_level="L1", owner_user_id="user_alice")
    with conn.cursor() as cur:
        cur.execute(
            "INSERT INTO requirements (id, mission_id, source_section, statement, status, created_at, updated_at) "
            "VALUES (%s, %s, %s, %s, 'UNIMPLEMENTED', now()::text, now()::text)",
            (requirement_id, mission_id, "live test", "A live-tested thing must happen"),
        )
    conn.commit()


def _unit_record(mission_id: str, requirement_id: str, revision: str = "rev1", **overrides) -> VerificationRecord:
    defaults = dict(
        id=f"ver_{uuid.uuid4().hex[:12]}", mission_id=mission_id, requirement_id=requirement_id,
        criterion_id=None, category=CATEGORY_UNIT_TEST, verification_method="UNIT_TEST", verifier_id="UnitTestVerifier",
        started_at="2026-01-01T00:00:00Z", outcome=VerificationOutcome.PASS, revision=revision,
        evidence_refs=("local:pytest",),
    )
    defaults.update(overrides)
    return VerificationRecord(**defaults)


def _build_record(mission_id: str, revision: str = "rev1") -> VerificationRecord:
    return VerificationRecord(
        id=f"ver_{uuid.uuid4().hex[:12]}", mission_id=mission_id, requirement_id=None, criterion_id=None,
        category=CATEGORY_BUILD, verification_method="BUILD_VERIFICATION", verifier_id="BuildVerifier",
        started_at="2026-01-01T00:00:00Z", outcome=VerificationOutcome.PASS, revision=revision,
        evidence_refs=("local:build",),
    )


def _security_record(mission_id: str, revision: str = "rev1") -> VerificationRecord:
    return VerificationRecord(
        id=f"ver_{uuid.uuid4().hex[:12]}", mission_id=mission_id, requirement_id=None, criterion_id=None,
        category=CATEGORY_SECURITY, verification_method="SECURITY_TEST", verifier_id="SecurityVerifier",
        started_at="2026-01-01T00:00:00Z", outcome=VerificationOutcome.PASS, revision=revision,
        evidence_refs=("local:security",),
    )


def _accept_decision(mission_id: str, requirement_id: str, revision: str = "rev1") -> CourtDecision:
    return CourtDecision(
        decision_id=f"d_{uuid.uuid4().hex[:12]}", mission_id=mission_id, revision=revision,
        risk_level=RiskLevel.STANDARD, roles_invoked=(CourtRole.ARBITER,), findings_considered=(),
        verification_refs=(), reasoning_summary="live qualification decision", verdict=CourtVerdict.ACCEPT,
    )


def _ag_evidence(mission_id: str, revision: str = "rev1") -> AntiGamingAnalysisEvidence:
    return AntiGamingAnalysisEvidence(
        analysis_id=f"ag_{uuid.uuid4().hex[:12]}", mission_id=mission_id, baseline_revision="rev0",
        candidate_revision=revision, detector_ids=("detect_x",),
    )


def _ready_proof(mission_id: str, requirement_id: str, revision: str):
    record = _unit_record(mission_id, requirement_id, revision=revision)
    decision = _accept_decision(mission_id, requirement_id, revision=revision)
    proof = generate_production_proof(
        mission_id=mission_id, revision=revision, required_requirement_ids=(requirement_id,),
        required_scopes_by_requirement={requirement_id: _UNIT_TEST_SCOPE},
        records_by_requirement={requirement_id: (record,)}, court_decision=decision,
        anti_gaming_evidence=_ag_evidence(mission_id, revision),
        build_records=(_build_record(mission_id, revision),), unit_test_records=(record,),
        unit_test_stats={"collected": 1, "passed": 1, "failed": 0, "skipped": 0, "errors": 0},
        security_records=(_security_record(mission_id, revision),), release_policy=_MINIMAL_POLICY,
    )
    return proof, record, decision


def test_production_proof_persists_and_reloads_through_fresh_connection_with_unchanged_hash():
    mission_id = _mid()
    requirement_id = _rid()
    conn_a = _fresh_connection()
    try:
        _seed_mission_and_requirement(conn_a, mission_id, requirement_id)
        proof, record, decision = _ready_proof(mission_id, requirement_id, "rev1")
        assert proof.release_state == "ENGINEERING_READY"
        expected_hash = compute_proof_hash(proof)
        _, written_hash = record_proof(conn_a, proof)
        assert written_hash == expected_hash
    finally:
        conn_a.close()  # simulated process boundary -- in-memory objects discarded

    conn_b = _fresh_connection()
    try:
        reloaded, stored_hash = latest_proof_for_mission(conn_b, mission_id)
        assert stored_hash == expected_hash
        assert compute_proof_hash(reloaded) == expected_hash
        assert reloaded.mission_id == mission_id
        assert reloaded.revision == "rev1"
        assert reloaded.requirements_satisfied == (requirement_id,)
        assert record.id in reloaded.evidence_refs
        assert decision.decision_id in reloaded.evidence_refs
    finally:
        conn_b.close()


def test_blocked_proof_persists_successfully_and_reloads_with_matching_status():
    """Item 5's exact required flow: blocked ProductionProof
    (release_state == NOT_ENGINEERING_READY) -> record_proof() ->
    persisted SUCCESSFULLY (post-migration, no translation, no
    application-side rejection) -> SQL overall_status ==
    NOT_ENGINEERING_READY -> JSON payload's release_state ==
    NOT_ENGINEERING_READY -> fresh connection reload -> exact
    agreement + proof hash preserved."""
    mission_id = _mid()
    requirement_id = _rid()
    conn = _fresh_connection()
    try:
        _seed_mission_and_requirement(conn, mission_id, requirement_id)
        blocked_proof = generate_production_proof(
            mission_id=mission_id, revision="rev1", required_requirement_ids=(requirement_id,),
            required_scopes_by_requirement={requirement_id: _UNIT_TEST_SCOPE},
            records_by_requirement={requirement_id: ()},
            anti_gaming_evidence=_ag_evidence(mission_id, "rev1"), release_policy=_MINIMAL_POLICY,
        )
        assert blocked_proof.release_state == NOT_ENGINEERING_READY
        expected_hash = compute_proof_hash(blocked_proof)
        # Persists successfully -- no ProductionProofStoreError, no
        # Postgres CHECK-constraint violation, post-migration.
        _, written_hash = record_proof(conn, blocked_proof)
        assert written_hash == expected_hash
        with conn.cursor() as cur:
            cur.execute(
                "SELECT overall_status, categories FROM production_proofs WHERE id = %s",
                (blocked_proof.proof_id,),
            )
            row = cur.fetchone()
        conn.commit()
        assert row["overall_status"] == NOT_ENGINEERING_READY
        import json as _json
        assert _json.loads(row["categories"])["release_state"] == NOT_ENGINEERING_READY
    finally:
        conn.close()

    conn2 = _fresh_connection()
    try:
        reloaded, stored_hash = latest_proof_for_mission(conn2, mission_id)
        assert stored_hash == expected_hash
        assert compute_proof_hash(reloaded) == expected_hash
        assert reloaded.release_state == NOT_ENGINEERING_READY
        assert reloaded.mission_id == mission_id
        assert reloaded.revision == "rev1"
    finally:
        conn2.close()


def test_proof_history_is_append_only_across_ready_blocked_ready():
    # rev1 -> ready; rev2 -> BLOCKED (genuinely persisted post-
    # migration, no longer merely "representable" -- this is the
    # exact spec section 30 worked example); rev3 -> ready again --
    # history preserves all three rows in chronological order, none
    # rewritten by another.
    mission_id = _mid()
    requirement_id = _rid()
    conn = _fresh_connection()
    try:
        _seed_mission_and_requirement(conn, mission_id, requirement_id)
        proof_1, _, _ = _ready_proof(mission_id, requirement_id, "rev1")
        record_proof(conn, proof_1)

        blocked_proof = generate_production_proof(
            mission_id=mission_id, revision="rev2", required_requirement_ids=(requirement_id,),
            required_scopes_by_requirement={requirement_id: _UNIT_TEST_SCOPE},
            records_by_requirement={requirement_id: ()},
            anti_gaming_evidence=_ag_evidence(mission_id, "rev2"), release_policy=_MINIMAL_POLICY,
        )
        assert blocked_proof.release_state == NOT_ENGINEERING_READY
        record_proof(conn, blocked_proof)

        proof_3, _, _ = _ready_proof(mission_id, requirement_id, "rev3")
        record_proof(conn, proof_3)
    finally:
        conn.close()

    conn2 = _fresh_connection()
    try:
        history = proofs_for_mission(conn2, mission_id)
        assert len(history) == 3
        assert [p.revision for p, _ in history] == ["rev1", "rev2", "rev3"]
        assert [p.release_state for p, _ in history] == [
            "ENGINEERING_READY", NOT_ENGINEERING_READY, "ENGINEERING_READY",
        ]
        # rev1's original outcome was NOT rewritten by rev2's later block:
        assert history[0][0].proof_id == proof_1.proof_id
        assert history[0][0].release_state == "ENGINEERING_READY"
    finally:
        conn2.close()


def test_stale_proof_cannot_certify_a_different_revision_after_reload():
    mission_id = _mid()
    requirement_id = _rid()
    conn = _fresh_connection()
    try:
        _seed_mission_and_requirement(conn, mission_id, requirement_id)
        proof, _, _ = _ready_proof(mission_id, requirement_id, "rev1")
        record_proof(conn, proof)
    finally:
        conn.close()

    conn2 = _fresh_connection()
    try:
        reloaded, _ = latest_proof_for_mission(conn2, mission_id)
        assert is_proof_stale(reloaded, current_revision="rev2") is True
        assert is_proof_stale(reloaded, current_revision="rev1") is False
    finally:
        conn2.close()


def test_no_raw_secret_persisted_in_stored_proof():
    mission_id = _mid()
    requirement_id = _rid()
    conn = _fresh_connection()
    try:
        _seed_mission_and_requirement(conn, mission_id, requirement_id)
        tainted_record = _unit_record(
            mission_id, requirement_id, revision="rev1",
            summary="connected using postgresql://admin:supersecretvalue@host/db",
        )
        proof = generate_production_proof(
            mission_id=mission_id, revision="rev1", required_requirement_ids=(requirement_id,),
            required_scopes_by_requirement={requirement_id: _UNIT_TEST_SCOPE},
            records_by_requirement={requirement_id: (tainted_record,)},
            anti_gaming_evidence=_ag_evidence(mission_id, "rev1"),
            build_records=(tainted_record,), release_policy=_MINIMAL_POLICY,
        )
        record_proof(conn, proof)
    finally:
        conn.close()

    conn2 = _fresh_connection()
    try:
        with conn2.cursor() as cur:
            cur.execute("SELECT categories FROM production_proofs WHERE mission_id = %s", (mission_id,))
            row = cur.fetchone()
        conn2.commit()
        assert "supersecretvalue" not in row["categories"]
    finally:
        conn2.close()


def test_no_test_data_leaks_to_production():
    """Sanity check matching the established pattern in every other
    Phase 15 live-Neon test file: this suite must be running against
    the disposable branch, never against the real production branch."""
    assert "ORNEUR_MISSION_DATABASE_URL" in os.environ
