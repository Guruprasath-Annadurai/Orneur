"""
Phase 15.2 -- connection layer for the Mission Engine's Neon Postgres
database. Deliberately separate from `orca.auth.db` (Supabase-backed,
Phase 14 identity/tenant data) -- this is a different database
instance entirely (Neon project orneur-core, little-boat-61470844),
per spec section 9.

Two connection strings, two purposes (spec section 9 -- "Application
traffic should use the normal pooled database URL. Schema migrations/
admin operations should use the direct/unpooled connection."):

  ORNEUR_MISSION_DATABASE_URL         -- pooled, application traffic
  ORNEUR_MISSION_DATABASE_URL_DIRECT  -- direct/unpooled, schema-only

Neither is read, logged, or embedded anywhere except passed straight
to psycopg.connect() -- never printed (spec section 13/34: no secret
values in logs, evidence, or committed files).
"""
from __future__ import annotations

from orca.config import orneur_env
from orca.mission.schema import PHASE_15_5_MIGRATION_SQL, SCHEMA_SQL
from orca.mission.verification_schema import PHASE_15_8_MIGRATION_SQL


class MissionDatabaseConfigError(Exception):
    """Raised when the required Neon connection strings are not configured."""


def _pooled_dsn() -> str:
    dsn = orneur_env("MISSION_DATABASE_URL")
    if not dsn:
        raise MissionDatabaseConfigError(
            "ORNEUR_MISSION_DATABASE_URL is not set -- the Mission Engine's pooled "
            "application connection to Neon (orneur-core) is required for any "
            "runtime read/write."
        )
    return dsn


def _direct_dsn() -> str:
    dsn = orneur_env("MISSION_DATABASE_URL_DIRECT")
    if not dsn:
        raise MissionDatabaseConfigError(
            "ORNEUR_MISSION_DATABASE_URL_DIRECT is not set -- schema/admin "
            "operations against Neon (orneur-core) require the direct/unpooled "
            "connection, per spec section 9. Do not fall back to the pooled URL "
            "for schema changes."
        )
    return dsn


def get_conn(*, direct: bool = False):
    """Returns a live psycopg connection. `direct=True` selects the
    unpooled connection (schema/admin operations only) -- callers
    doing ordinary mission/checkpoint/operation reads and writes must
    leave this False (the default) and use the pooled connection."""
    import psycopg
    from psycopg.rows import dict_row

    dsn = _direct_dsn() if direct else _pooled_dsn()
    return psycopg.connect(dsn, row_factory=dict_row, autocommit=False)


def apply_schema(conn) -> None:
    """Applies SCHEMA_SQL (idempotent -- every statement is CREATE
    TABLE/INDEX IF NOT EXISTS) plus every subsequent schema-evolution
    migration (also idempotent -- ADD COLUMN IF NOT EXISTS, matching
    orca/auth/db.py's own established pattern) against an already-open
    connection. Callers are responsible for committing (or using a
    `with conn:` block, matching this project's existing psycopg usage
    pattern)."""
    with conn.cursor() as cur:
        cur.execute(SCHEMA_SQL)
        cur.execute(PHASE_15_5_MIGRATION_SQL)
        cur.execute(PHASE_15_8_MIGRATION_SQL)


def list_existing_tables(conn) -> set[str]:
    """Returns the set of table names actually present in the public
    schema of whatever database `conn` is connected to -- used to
    verify a migration created exactly what was expected, not merely
    that CREATE TABLE didn't raise."""
    with conn.cursor() as cur:
        cur.execute(
            "SELECT table_name FROM information_schema.tables WHERE table_schema = 'public'"
        )
        rows = cur.fetchall()
    return {row["table_name"] for row in rows}
