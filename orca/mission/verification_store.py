"""
Phase 15.8 -- durable VerificationRecord persistence, against the
`verification_records` table defined in
`orca/mission/verification_schema.py`.

Matches this repository's established raw-psycopg pattern
(`orca/mission/operation_store.py`, `mission_store.py`): explicit
`conn.commit()`/`conn.rollback()`, `%s` placeholders, `dict_row`
row factory (via `get_conn()`), no ORM.

Records are append-only: `record_verification()` always INSERTs a
new row (a fresh `id`); there is no `update_verification()` -- a
re-run of a check produces a NEW record, preserving history (spec
section 3, 24), never overwriting a prior FAIL with a later PASS.
"""
from __future__ import annotations

import json
from datetime import datetime, timezone

from orca.mission.verification import VerificationOutcome, VerificationRecord


def _now_iso() -> str:
    return datetime.now(timezone.utc).isoformat()


def record_verification(conn, record: VerificationRecord) -> VerificationRecord:
    """Persists `record` as a new row. Raises on a duplicate id
    (should never happen -- ids are generated fresh per call by
    convention) rather than silently overwriting history."""
    with conn.cursor() as cur:
        cur.execute(
            """
            INSERT INTO verification_records
                (id, mission_id, requirement_id, criterion_id, category, verification_method,
                 verifier_id, verifier_version, started_at, finished_at, outcome, revision,
                 summary, command_reference, evidence_refs, artifact_hash, environment_identity,
                 limitations, error_detail, not_applicable_reason, created_at)
            VALUES (%s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s)
            """,
            (
                record.id, record.mission_id, record.requirement_id, record.criterion_id,
                record.category, record.verification_method, record.verifier_id, record.verifier_version,
                record.started_at, record.finished_at, record.outcome.value, record.revision,
                record.summary, record.command_reference, json.dumps(list(record.evidence_refs)),
                record.artifact_hash, record.environment_identity, record.limitations,
                record.error_detail, record.not_applicable_reason, _now_iso(),
            ),
        )
    conn.commit()
    return record


def _row_to_record(row: dict) -> VerificationRecord:
    return VerificationRecord(
        id=row["id"], mission_id=row["mission_id"], requirement_id=row["requirement_id"],
        criterion_id=row["criterion_id"], category=row["category"],
        verification_method=row["verification_method"], verifier_id=row["verifier_id"],
        verifier_version=row["verifier_version"], started_at=row["started_at"],
        finished_at=row["finished_at"], outcome=VerificationOutcome(row["outcome"]),
        revision=row["revision"], summary=row["summary"], command_reference=row["command_reference"],
        evidence_refs=tuple(json.loads(row["evidence_refs"]) if row["evidence_refs"] else []),
        artifact_hash=row["artifact_hash"], environment_identity=row["environment_identity"],
        limitations=row["limitations"], error_detail=row["error_detail"],
        not_applicable_reason=row["not_applicable_reason"],
    )


def get_verification(conn, verification_id: str) -> VerificationRecord | None:
    with conn.cursor() as cur:
        cur.execute("SELECT * FROM verification_records WHERE id = %s", (verification_id,))
        row = cur.fetchone()
    conn.commit()
    return _row_to_record(dict(row)) if row else None


def verifications_for_requirement(conn, requirement_id: str) -> tuple[VerificationRecord, ...]:
    """Full history, oldest first -- a prior FAIL followed by a later
    PASS returns BOTH rows, never just the latest."""
    with conn.cursor() as cur:
        cur.execute(
            "SELECT * FROM verification_records WHERE requirement_id = %s ORDER BY created_at ASC",
            (requirement_id,),
        )
        rows = cur.fetchall()
    conn.commit()
    return tuple(_row_to_record(dict(r)) for r in rows)


def verifications_for_criterion(conn, criterion_id: str) -> tuple[VerificationRecord, ...]:
    with conn.cursor() as cur:
        cur.execute(
            "SELECT * FROM verification_records WHERE criterion_id = %s ORDER BY created_at ASC",
            (criterion_id,),
        )
        rows = cur.fetchall()
    conn.commit()
    return tuple(_row_to_record(dict(r)) for r in rows)


def latest_verification_for_criterion(conn, criterion_id: str) -> VerificationRecord | None:
    records = verifications_for_criterion(conn, criterion_id)
    return records[-1] if records else None
