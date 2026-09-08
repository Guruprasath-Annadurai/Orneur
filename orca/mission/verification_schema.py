"""
Phase 15.8 -- schema extension for durable VerificationRecord storage.

Inspected first (spec section 25): the existing `evidence` table
(Phase 15.2) has no `outcome`, `verifier_id`, `revision`, or
`criterion_id` columns -- nowhere NEAR enough shape to satisfy this
phase's own PASS conditions (revision-bound stale-evidence detection,
non-vacuous history, criterion-level linkage). A genuinely new table
is required; this is NOT reached for casually -- see the module
docstring in `orca/mission/verification.py` for why the shape is
what it is.

Per the explicit instruction ("write migration as code; validate on
disposable Neon branch; test it; STOP; request explicit owner
approval before production. No autonomous new production migration."):
this SQL was validated against a disposable Neon branch (see
PHASE15_EVIDENCE.md's Phase 15.8 section), then held back from
`orca/mission/db.py`'s `apply_schema()` until the owner explicitly
approved production application. That approval was received and the
migration was APPLIED to production (see
PHASE15_EVIDENCE.md's Phase 15.8 production-schema-reconciliation
section for the exact migration_id and post-application verification)
-- `apply_schema()` now includes `PHASE_15_8_MIGRATION_SQL` alongside
`PHASE_15_5_MIGRATION_SQL`, exactly like Phase 15.2/15.5's own
precedent, so new/fresh databases can reproduce the approved schema
from code.
"""
from __future__ import annotations

PHASE_15_8_MIGRATION_SQL = """
CREATE TABLE IF NOT EXISTS verification_records (
    id                    TEXT PRIMARY KEY,
    mission_id            TEXT REFERENCES missions(id),
    requirement_id        TEXT REFERENCES requirements(id),
    criterion_id          TEXT,
    category              TEXT NOT NULL,
    verification_method   TEXT NOT NULL,
    verifier_id           TEXT NOT NULL,
    verifier_version      TEXT,
    started_at            TEXT NOT NULL,
    finished_at           TEXT,
    outcome               TEXT NOT NULL CHECK (outcome IN (
                               'PASS', 'FAIL', 'UNVERIFIED', 'NOT_APPLICABLE',
                               'ERROR', 'CANCELLED', 'TIMED_OUT'
                           )),
    revision              TEXT,
    summary                TEXT,
    command_reference       TEXT,
    evidence_refs            TEXT,   -- JSON array, never a raw secret value
    artifact_hash             TEXT,
    environment_identity       TEXT,
    limitations                 TEXT,
    error_detail                 TEXT,
    not_applicable_reason         TEXT,
    created_at                     TEXT NOT NULL
);
CREATE INDEX IF NOT EXISTS ix_verification_records_mission ON verification_records(mission_id);
CREATE INDEX IF NOT EXISTS ix_verification_records_requirement ON verification_records(requirement_id);
CREATE INDEX IF NOT EXISTS ix_verification_records_criterion ON verification_records(criterion_id);
CREATE INDEX IF NOT EXISTS ix_verification_records_revision ON verification_records(requirement_id, revision);

ALTER TABLE evidence ADD COLUMN IF NOT EXISTS verification_id TEXT REFERENCES verification_records(id);
ALTER TABLE evidence ADD COLUMN IF NOT EXISTS revision TEXT;
"""
