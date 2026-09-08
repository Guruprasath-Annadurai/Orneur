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
this SQL is validated against a disposable Neon branch (see
PHASE15_EVIDENCE.md's Phase 15.8 section for the exact
migration_id/branch used) but is NOT applied to production by this
module or by any code path in this phase. `apply_schema()` in
`orca/mission/db.py` is NOT updated to include this migration --
deliberately, so a normal qualification dispatch against production-
cloned branches does not silently apply it either. Production
application requires a separate, explicit owner-approved migration
turn, exactly like Phase 15.2/15.5's own precedent.
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
