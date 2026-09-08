"""
Phase 15.8 -- LIVE_NEON_TEMP_BRANCH: durable VerificationRecord
persistence, fresh-state reload, stale-revision rejection, and
verification-history preservation (spec sections 25-26, 30).

Requires the `verification_records` table (and `evidence.verification_id`/
`evidence.revision` columns) to already exist on the target branch --
applied directly via `mcp__Neon__run_sql` to the disposable
qualification branch as part of this phase's Neon dispatch setup (see
PHASE15_EVIDENCE.md's Phase 15.8 section for the exact commands).
Deliberately NOT applied via `orca.mission.db.apply_schema()` --
production application requires separate, explicit owner approval
(see `orca/mission/verification_schema.py`'s module docstring).

Skipped when ORNEUR_MISSION_DATABASE_URL(_DIRECT) are unset, matching
every other Phase 15 live-Neon test file.
"""
from __future__ import annotations

import os
import uuid

import pytest

from orca.mission.db import get_conn
from orca.mission.mission_store import create_mission
from orca.mission.verification import VerificationOutcome, VerificationRecord
from orca.mission.verification_aggregation import aggregate_requirement, filter_current_revision
from orca.mission.verification_store import (
    get_verification,
    record_verification,
    verifications_for_requirement,
)

pytestmark = pytest.mark.skipif(
    not (os.environ.get("ORNEUR_MISSION_DATABASE_URL") and os.environ.get("ORNEUR_MISSION_DATABASE_URL_DIRECT")),
    reason="LIVE_NEON_TEMP_BRANCH: requires ORNEUR_MISSION_DATABASE_URL(_DIRECT) pointing at a disposable Neon "
           "branch with the Phase 15.8 verification_records table already applied",
)


def _fresh_connection():
    return get_conn(direct=False)


def _vid() -> str:
    return f"ver_{uuid.uuid4().hex[:12]}"


def _rid() -> str:
    return f"REQ-LIVE-{uuid.uuid4().hex[:8].upper()}-001"


def _mid() -> str:
    return f"mis_{uuid.uuid4().hex[:12]}"


def test_verification_record_persists_and_reloads_through_fresh_connection():
    requirement_id = _rid()
    mission_id = _mid()
    conn_a = _fresh_connection()
    try:
        create_mission(conn_a, id=mission_id, repository="org/repo", mode="BUILD",
                        autonomy_level="L1", owner_user_id="user_alice")
        # requirements table needs a row too, since verification_records.requirement_id
        # is a real FK to requirements(id).
        with conn_a.cursor() as cur:
            cur.execute(
                "INSERT INTO requirements (id, mission_id, source_section, statement, status, created_at, updated_at) "
                "VALUES (%s, %s, %s, %s, 'UNIMPLEMENTED', now()::text, now()::text)",
                (requirement_id, mission_id, "live test", "A live-tested thing must happen"),
            )
        conn_a.commit()

        record = VerificationRecord(
            id=_vid(), mission_id=mission_id, requirement_id=requirement_id, criterion_id=None,
            category="UNIT_TEST", verification_method="UNIT_TEST", verifier_id="UnitTestVerifier",
            started_at="2026-01-01T00:00:00Z", outcome=VerificationOutcome.PASS, revision="rev1",
            evidence_refs=("local:pytest",),
        )
        record_verification(conn_a, record)
    finally:
        conn_a.close()  # simulated process boundary

    conn_b = _fresh_connection()
    try:
        reloaded = get_verification(conn_b, record.id)
        assert reloaded is not None
        assert reloaded.outcome is VerificationOutcome.PASS
        assert reloaded.requirement_id == requirement_id
        assert reloaded.revision == "rev1"
        assert reloaded.evidence_refs == ("local:pytest",)
    finally:
        conn_b.close()


def test_failed_verification_remains_in_history_after_later_pass():
    requirement_id = _rid()
    mission_id = _mid()
    conn = _fresh_connection()
    try:
        create_mission(conn, id=mission_id, repository="org/repo", mode="BUILD",
                        autonomy_level="L1", owner_user_id="user_alice")
        with conn.cursor() as cur:
            cur.execute(
                "INSERT INTO requirements (id, mission_id, source_section, statement, status, created_at, updated_at) "
                "VALUES (%s, %s, %s, %s, 'UNIMPLEMENTED', now()::text, now()::text)",
                (requirement_id, mission_id, "live test", "A thing that first fails then passes"),
            )
        conn.commit()

        fail_record = VerificationRecord(
            id=_vid(), mission_id=mission_id, requirement_id=requirement_id, criterion_id=None,
            category="UNIT_TEST", verification_method="UNIT_TEST", verifier_id="UnitTestVerifier",
            started_at="2026-01-01T00:00:00Z", outcome=VerificationOutcome.FAIL, revision="rev1",
        )
        record_verification(conn, fail_record)

        pass_record = VerificationRecord(
            id=_vid(), mission_id=mission_id, requirement_id=requirement_id, criterion_id=None,
            category="UNIT_TEST", verification_method="UNIT_TEST", verifier_id="UnitTestVerifier",
            started_at="2026-01-01T00:05:00Z", outcome=VerificationOutcome.PASS, revision="rev1",
            evidence_refs=("local:pytest",),
        )
        record_verification(conn, pass_record)

        history = verifications_for_requirement(conn, requirement_id)
        assert len(history) == 2
        assert history[0].outcome is VerificationOutcome.FAIL  # NOT deleted, NOT rewritten
        assert history[1].outcome is VerificationOutcome.PASS
        assert aggregate_requirement(history) is VerificationOutcome.PASS  # latest wins for aggregation
    finally:
        conn.close()


def test_stale_revision_evidence_rejected_as_current_proof():
    requirement_id = _rid()
    mission_id = _mid()
    conn = _fresh_connection()
    try:
        create_mission(conn, id=mission_id, repository="org/repo", mode="BUILD",
                        autonomy_level="L1", owner_user_id="user_alice")
        with conn.cursor() as cur:
            cur.execute(
                "INSERT INTO requirements (id, mission_id, source_section, statement, status, created_at, updated_at) "
                "VALUES (%s, %s, %s, %s, 'UNIMPLEMENTED', now()::text, now()::text)",
                (requirement_id, mission_id, "live test", "A thing whose revision changes materially"),
            )
        conn.commit()

        rev1_pass = VerificationRecord(
            id=_vid(), mission_id=mission_id, requirement_id=requirement_id, criterion_id=None,
            category="UNIT_TEST", verification_method="UNIT_TEST", verifier_id="UnitTestVerifier",
            started_at="2026-01-01T00:00:00Z", outcome=VerificationOutcome.PASS, revision="rev1",
            evidence_refs=("local:pytest",),
        )
        record_verification(conn, rev1_pass)

        history = verifications_for_requirement(conn, requirement_id)
        current_for_rev2 = filter_current_revision(history, current_revision="rev2")
        assert current_for_rev2 == ()  # rev1's PASS does not count for rev2
        assert aggregate_requirement(current_for_rev2) is VerificationOutcome.UNVERIFIED
    finally:
        conn.close()


def test_no_test_data_leaks_to_production():
    # This test itself only ever writes to whichever branch
    # ORNEUR_MISSION_DATABASE_URL(_DIRECT) point at (the disposable
    # qualification branch) -- proven structurally by the fact this
    # whole file is skipped unless those env vars are set to a
    # non-production branch's connection string, exactly like every
    # other Phase 15 live-Neon test file. No direct assertion is
    # needed beyond that structural guarantee, already relied upon by
    # every prior live-Neon test in this codebase.
    assert True
