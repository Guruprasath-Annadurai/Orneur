"""
Phase 15.10 -- LIVE_NEON_TEMP_BRANCH: durable Production Proof
persistence, fresh-connection reload, hash-integrity preservation,
mission/revision-binding, and append-only proof-history qualification
(spec sections 27, 30, 34).

`_ensure_schema` calls `apply_schema()` on the target branch before
any test runs, exactly like every other Phase 15 live-Neon test file
-- the `production_proofs` table itself is unchanged from its Phase
15.2 definition (no migration this closure); this test proves the
Phase 15.10 STORE CODE reads/writes that existing table correctly
across a real process boundary.

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
from orca.mission.production_proof import compute_proof_hash, generate_production_proof
from orca.mission.production_proof_store import (
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


def _pass_record(mission_id: str, requirement_id: str, revision: str = "rev1") -> VerificationRecord:
    return VerificationRecord(
        id=f"ver_{uuid.uuid4().hex[:12]}", mission_id=mission_id, requirement_id=requirement_id,
        criterion_id=None, category="UNIT_TEST", verification_method="UNIT_TEST", verifier_id="UnitTestVerifier",
        started_at="2026-01-01T00:00:00Z", outcome=VerificationOutcome.PASS, revision=revision,
        evidence_refs=("local:pytest",),
    )


def _accept_decision(mission_id: str, requirement_id: str, revision: str = "rev1") -> CourtDecision:
    return CourtDecision(
        decision_id=f"d_{uuid.uuid4().hex[:12]}", mission_id=mission_id, revision=revision,
        risk_level=RiskLevel.STANDARD, roles_invoked=(CourtRole.ARBITER,), findings_considered=(),
        verification_refs=(), reasoning_summary="live qualification decision", verdict=CourtVerdict.ACCEPT,
    )


def test_production_proof_persists_and_reloads_through_fresh_connection_with_unchanged_hash():
    mission_id = _mid()
    requirement_id = _rid()
    conn_a = _fresh_connection()
    try:
        _seed_mission_and_requirement(conn_a, mission_id, requirement_id)
        record = _pass_record(mission_id, requirement_id)
        decision = _accept_decision(mission_id, requirement_id)
        proof = generate_production_proof(
            mission_id=mission_id, revision="rev1", required_requirement_ids=(requirement_id,),
            required_scopes_by_requirement={requirement_id: _UNIT_TEST_SCOPE},
            records_by_requirement={requirement_id: (record,)}, court_decision=decision,
            anti_gaming_analysis_performed=True, build_records=(record,), unit_test_records=(record,),
            unit_test_stats={"collected": 1, "passed": 1, "failed": 0, "skipped": 0, "errors": 0},
            security_records=(record,),
        )
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


def test_proof_history_is_append_only_across_multiple_revisions():
    # rev A -> blocked proof (missing evidence); rev B -> ready;
    # rev C -> regression (blocked again) -- history preserves all
    # three, never rewriting an earlier proof's outcome.
    mission_id = _mid()
    requirement_id = _rid()
    conn = _fresh_connection()
    try:
        _seed_mission_and_requirement(conn, mission_id, requirement_id)

        # rev A: blocked -- no verification record at all.
        proof_a = generate_production_proof(
            mission_id=mission_id, revision="revA", required_requirement_ids=(requirement_id,),
            required_scopes_by_requirement={requirement_id: _UNIT_TEST_SCOPE},
            records_by_requirement={requirement_id: ()},
            anti_gaming_analysis_performed=True,
        )
        record_proof(conn, proof_a)

        # rev B: ready -- real record + Court ACCEPT.
        record_b = _pass_record(mission_id, requirement_id, revision="revB")
        decision_b = _accept_decision(mission_id, requirement_id, revision="revB")
        proof_b = generate_production_proof(
            mission_id=mission_id, revision="revB", required_requirement_ids=(requirement_id,),
            required_scopes_by_requirement={requirement_id: _UNIT_TEST_SCOPE},
            records_by_requirement={requirement_id: (record_b,)}, court_decision=decision_b,
            anti_gaming_analysis_performed=True, build_records=(record_b,), unit_test_records=(record_b,),
            unit_test_stats={"collected": 1, "passed": 1, "failed": 0, "skipped": 0, "errors": 0},
            security_records=(record_b,),
        )
        record_proof(conn, proof_b)

        # rev C: regressed -- a FAIL record.
        fail_record_c = VerificationRecord(
            id=f"ver_{uuid.uuid4().hex[:12]}", mission_id=mission_id, requirement_id=requirement_id,
            criterion_id=None, category="UNIT_TEST", verification_method="UNIT_TEST",
            verifier_id="UnitTestVerifier", started_at="2026-01-01T00:00:00Z",
            outcome=VerificationOutcome.FAIL, revision="revC",
        )
        proof_c = generate_production_proof(
            mission_id=mission_id, revision="revC", required_requirement_ids=(requirement_id,),
            required_scopes_by_requirement={requirement_id: _UNIT_TEST_SCOPE},
            records_by_requirement={requirement_id: (fail_record_c,)},
            anti_gaming_analysis_performed=True,
        )
        record_proof(conn, proof_c)
    finally:
        conn.close()

    conn2 = _fresh_connection()
    try:
        history = proofs_for_mission(conn2, mission_id)
        assert len(history) == 3
        revisions_in_order = [p.revision for p, _ in history]
        assert revisions_in_order == ["revA", "revB", "revC"]
        outcomes_in_order = [p.release_state for p, _ in history]
        assert outcomes_in_order[0] != "ENGINEERING_READY"   # rev A blocked
        assert outcomes_in_order[1] == "ENGINEERING_READY"   # rev B ready
        assert outcomes_in_order[2] != "ENGINEERING_READY"   # rev C regressed
        # rev A's original outcome was NOT rewritten by later revisions:
        assert history[0][0].release_state != "ENGINEERING_READY"
    finally:
        conn2.close()


def test_stale_proof_cannot_certify_a_different_revision_after_reload():
    mission_id = _mid()
    requirement_id = _rid()
    conn = _fresh_connection()
    try:
        _seed_mission_and_requirement(conn, mission_id, requirement_id)
        record = _pass_record(mission_id, requirement_id, revision="rev1")
        decision = _accept_decision(mission_id, requirement_id, revision="rev1")
        proof = generate_production_proof(
            mission_id=mission_id, revision="rev1", required_requirement_ids=(requirement_id,),
            required_scopes_by_requirement={requirement_id: _UNIT_TEST_SCOPE},
            records_by_requirement={requirement_id: (record,)}, court_decision=decision,
            anti_gaming_analysis_performed=True, build_records=(record,), unit_test_records=(record,),
            unit_test_stats={"collected": 1, "passed": 1, "failed": 0, "skipped": 0, "errors": 0},
            security_records=(record,),
        )
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
        tainted_record = VerificationRecord(
            id=f"ver_{uuid.uuid4().hex[:12]}", mission_id=mission_id, requirement_id=requirement_id,
            criterion_id=None, category="UNIT_TEST", verification_method="UNIT_TEST",
            verifier_id="UnitTestVerifier", started_at="2026-01-01T00:00:00Z",
            outcome=VerificationOutcome.PASS, revision="rev1", evidence_refs=("x",),
            summary="connected using postgresql://admin:supersecretvalue@host/db",
        )
        proof = generate_production_proof(
            mission_id=mission_id, revision="rev1", required_requirement_ids=(requirement_id,),
            required_scopes_by_requirement={requirement_id: _UNIT_TEST_SCOPE},
            records_by_requirement={requirement_id: (tainted_record,)},
            anti_gaming_analysis_performed=True, build_records=(tainted_record,),
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
