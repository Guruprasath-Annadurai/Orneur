"""
Phase 15.10.1 -- PRODUCTION SCHEMA MIGRATION. Owner-approved and
APPLIED to the real production `orneur-core` database this closure
(post-migration reconciliation). Now wired into
`orca.mission.db.apply_schema()` (idempotent -- `DROP CONSTRAINT IF
EXISTS` + re-`ADD CONSTRAINT`, safe to re-run) so fresh/disposable
databases reproduce the same, now-approved schema from code, matching
this project's established migration convention
(`PHASE_15_5_MIGRATION_SQL`, `PHASE_15_8_MIGRATION_SQL`).

Closed the integrity defect in `production_proofs.overall_status`'s
Phase 15.2 CHECK constraint (`orca/mission/schema.py`), which only
allowed `'ENGINEERING_READY', 'SUBMISSION_READY', 'RELEASE_CANDIDATE',
'PUBLISHED'` -- there was no value for a BLOCKED proof
(`NOT_ENGINEERING_READY`), so the original Phase 15.10
`production_proof_store.py` silently mapped a blocked proof's durable
row to `'ENGINEERING_READY'`. This module defines the additive
migration that widens the constraint to also allow
`'NOT_ENGINEERING_READY'`, preserving every existing row (the new
constraint is a strict superset of the old one -- no existing value
became invalid).

VALIDATED on two disposable Neon branches before application (fresh-
schema creation, old-schema -> new-schema migration, idempotent
re-run, existing-row preservation, blocked-state insert, invalid-
status rejection), then APPLIED to the real production `orneur-core`
database with explicit owner approval, then RE-VERIFIED directly
against production (constraint now reads exactly the 5 intended
values; row count unchanged, 0 rows both before and after -- no
qualification data was ever inserted into production) -- see
PHASE15_EVIDENCE.md's "PHASE 15.10.1" and "PHASE 15.10.1 POST-
MIGRATION RECONCILIATION" sections for the exact commands and results.
"""
from __future__ import annotations

PHASE_15_10_1_MIGRATION_SQL = """
ALTER TABLE production_proofs DROP CONSTRAINT IF EXISTS production_proofs_overall_status_check;
ALTER TABLE production_proofs ADD CONSTRAINT production_proofs_overall_status_check
    CHECK (overall_status IN (
        'NOT_ENGINEERING_READY', 'ENGINEERING_READY', 'SUBMISSION_READY', 'RELEASE_CANDIDATE', 'PUBLISHED'
    ));
"""


def apply_migration_15_10_1(conn) -> None:
    """Applies `PHASE_15_10_1_MIGRATION_SQL` against an already-open
    connection. Idempotent (DROP CONSTRAINT IF EXISTS, then re-ADD)
    -- safe to call more than once. Callers are responsible for
    committing (or using a `with conn:` block), matching this
    project's existing psycopg usage pattern. NEVER call this against
    a production connection without explicit, current owner approval
    for THIS specific migration."""
    with conn.cursor() as cur:
        cur.execute(PHASE_15_10_1_MIGRATION_SQL)
