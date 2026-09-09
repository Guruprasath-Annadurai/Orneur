"""
Phase 15.10.1 -- PENDING PRODUCTION SCHEMA MIGRATION. NOT applied to
production. NOT wired into `orca.mission.db.apply_schema()`.

Closes the integrity defect in `production_proofs.overall_status`'s
Phase 15.2 CHECK constraint (`orca/mission/schema.py`), which only
allows `'ENGINEERING_READY', 'SUBMISSION_READY', 'RELEASE_CANDIDATE',
'PUBLISHED'` -- there is no value for a BLOCKED proof
(`NOT_ENGINEERING_READY`), so the original Phase 15.10
`production_proof_store.py` silently mapped a blocked proof's durable
row to `'ENGINEERING_READY'`. This module defines the additive
migration that widens the constraint to also allow
`'NOT_ENGINEERING_READY'`, preserving every existing row (the new
constraint is a strict superset of the old one -- no existing value
becomes invalid).

VALIDATED on a disposable Neon branch this closure (fresh-schema
creation, old-schema -> new-schema migration, idempotent re-run,
existing-row preservation, blocked-state insert, invalid-status
rejection -- see PHASE15_EVIDENCE.md's "PHASE 15.10.1" section for the
exact commands and results). NOT applied to the real production
branch. Applying this to production requires the owner to explicitly
approve it and either call `apply_migration_15_10_1()` (or run the SQL
directly) against the real `orneur-core` project -- this module does
not do so on its own, and is not imported by `apply_schema()`.
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
