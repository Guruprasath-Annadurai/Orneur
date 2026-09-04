"""
Database backend for Orca auth — users, sessions, usage, API keys.

Dual-backend by design:
  - Default (no ORCA_DATABASE_URL set): SQLite at ~/.orca/auth.db. This is
    the actual product for most Orca users — a single local install with
    zero setup. Nothing changes for them.
  - Production mode (ORCA_DATABASE_URL set, e.g. postgresql://...): Postgres.
    Needed once you're running multiple API instances behind a load balancer —
    SQLite's file lock doesn't work across processes/machines.

Call sites (orca/audit.py, orca/auth/store.py, orca/auth/apikeys.py) use
get_conn() and never touch sqlite3/psycopg directly, so backend selection
here is transparent to the rest of the codebase. The _PGConnAdapter class
below exists to make a psycopg connection quack like a sqlite3.Connection —
same execute()/executescript()/fetchone()/fetchall()/dict-row/context-manager
surface — so no other file needs to change.
"""
from __future__ import annotations

import os
import re
import sqlite3
from pathlib import Path

from orca.config import ORCA_HOME, orneur_env

AUTH_DB = ORCA_HOME / "auth.db"

# Phase 14A.4: defense-in-depth against the exact "silent per-host
# fallback" hazard Phase 14A.3 closed for the Godmode authority and
# security-root backends -- this module is a THIRD backend selection
# with the same shape (env-var-gated Postgres vs. local-file SQLite),
# and it must not be the one place that hazard was left open. This
# check duplicates `orca.godmode.deployment_profile.validate_deployment_config()`'s
# own core-db requirement (that function is the primary, earlier-
# running gate at `orca/serve/api.py`'s import time) -- kept here too
# so any OTHER entry point that imports `orca.auth.db` directly (a CLI
# tool, a script, a future service) without ever importing
# `orca.serve.api` still cannot silently fall back to SQLite while
# ORNEUR_DEPLOYMENT_PROFILE=DISTRIBUTED is set.
try:
    from orca.godmode.deployment_profile import is_distributed as _is_distributed
    _DISTRIBUTED = _is_distributed()
except Exception:
    # deployment_profile itself raises DeploymentConfigError for an
    # UNKNOWN profile value -- let that propagate as-is (it is already
    # a clear, secret-free error) rather than masking it here.
    raise

if _DISTRIBUTED and not orneur_env("DATABASE_URL"):
    raise RuntimeError(
        "DISTRIBUTED profile requires an explicitly configured shared core application database "
        "(set ORNEUR_DATABASE_URL) -- local per-host auth/session/audit storage is not valid in "
        "DISTRIBUTED mode."
    )

BACKEND = "postgres" if orneur_env("DATABASE_URL") else "sqlite"

_PLACEHOLDER_RE = re.compile(r"\?")

_SCHEMA_SQLITE = """
CREATE TABLE IF NOT EXISTS users (
    id                  TEXT PRIMARY KEY,
    email               TEXT UNIQUE NOT NULL,
    name                TEXT NOT NULL DEFAULT '',
    password_hash       TEXT NOT NULL,
    tier                TEXT NOT NULL DEFAULT 'free',
    role                TEXT NOT NULL DEFAULT 'member',
    created_at          TEXT NOT NULL,
    verified            INTEGER NOT NULL DEFAULT 0,
    stripe_customer_id  TEXT,
    totp_secret         TEXT,
    totp_enabled        INTEGER NOT NULL DEFAULT 0,
    signup_seq          INTEGER
);

-- Single-row atomic counter for global signup order — used to gate the
-- "first 100 users get Novus free" cohort. A dedicated counter (not
-- COUNT(*) or the users.id UUID) because it must be assigned atomically
-- via UPDATE...RETURNING under concurrent signups; SQLite's single-writer
-- semantics and Postgres's row lock on UPDATE both make this race-safe.
CREATE TABLE IF NOT EXISTS signup_counter (
    id       INTEGER PRIMARY KEY,
    next_seq INTEGER NOT NULL DEFAULT 1
);
INSERT INTO signup_counter (id, next_seq) VALUES (1, 1) ON CONFLICT(id) DO NOTHING;

CREATE TABLE IF NOT EXISTS usage_daily (
    user_id    TEXT NOT NULL,
    date       TEXT NOT NULL,
    messages   INTEGER NOT NULL DEFAULT 0,
    ultra_runs INTEGER NOT NULL DEFAULT 0,
    PRIMARY KEY (user_id, date)
);

CREATE TABLE IF NOT EXISTS user_sessions (
    user_id    TEXT NOT NULL,
    session_id TEXT NOT NULL,
    created_at TEXT NOT NULL,
    PRIMARY KEY (user_id, session_id)
);

-- Enterprise/Team management — one organization per owning account. Seat
-- limits are tied to the owner's tier (free/pro/enterprise), NOT a separate
-- Stripe seat-billing product — a real scoping limit, not an oversight.
-- See orca/auth/org_store.py SEAT_LIMITS for the actual numbers.
CREATE TABLE IF NOT EXISTS organizations (
    id            TEXT PRIMARY KEY,
    name          TEXT NOT NULL,
    owner_user_id TEXT NOT NULL,
    created_at    TEXT NOT NULL
);
CREATE TABLE IF NOT EXISTS org_members (
    id            TEXT PRIMARY KEY,
    org_id        TEXT NOT NULL,
    user_id       TEXT,
    invited_email TEXT NOT NULL,
    role          TEXT NOT NULL DEFAULT 'member',
    status        TEXT NOT NULL DEFAULT 'invited',
    invite_token  TEXT,
    invited_at    TEXT NOT NULL,
    joined_at     TEXT
);

-- Privacy/compliance tables — see orca/auth/privacy.py. One row per
-- (user, purpose); consent_audit_log is append-only (enforced by trigger
-- below, not just convention) so a consent change can't be silently
-- rewritten after the fact.
CREATE TABLE IF NOT EXISTS privacy_consents (
    id          TEXT PRIMARY KEY,
    user_id     TEXT NOT NULL,
    purpose     TEXT NOT NULL,
    granted     INTEGER NOT NULL DEFAULT 0,
    legal_basis TEXT NOT NULL DEFAULT 'consent',
    version     TEXT NOT NULL DEFAULT '1.0',
    source      TEXT NOT NULL DEFAULT 'web',
    granted_at  TEXT,
    revoked_at  TEXT,
    updated_at  TEXT NOT NULL,
    UNIQUE (user_id, purpose)
);

CREATE TABLE IF NOT EXISTS consent_audit_log (
    id             TEXT PRIMARY KEY,
    user_id        TEXT NOT NULL,
    purpose        TEXT NOT NULL,
    action         TEXT NOT NULL,
    previous_state INTEGER,
    new_state      INTEGER NOT NULL,
    created_at     TEXT NOT NULL
);

-- SQLite triggers can't be dropped by IF NOT EXISTS on CREATE alone across
-- repeated init_db() runs the same way tables can — these two use
-- CREATE TRIGGER IF NOT EXISTS explicitly so re-running init_db() is safe.
CREATE TRIGGER IF NOT EXISTS trg_consent_audit_no_update
BEFORE UPDATE ON consent_audit_log
BEGIN
    SELECT RAISE(ABORT, 'consent_audit_log is append-only');
END;

CREATE TRIGGER IF NOT EXISTS trg_consent_audit_no_delete
BEFORE DELETE ON consent_audit_log
BEGIN
    SELECT RAISE(ABORT, 'consent_audit_log is append-only');
END;

CREATE TABLE IF NOT EXISTS data_export_requests (
    id              TEXT PRIMARY KEY,
    user_id         TEXT NOT NULL,
    status          TEXT NOT NULL DEFAULT 'pending',
    requested_at    TEXT NOT NULL,
    completed_at    TEXT,
    file_path       TEXT,
    error_message   TEXT
);

-- Structured incident log — deliberately generic (not India/CERT-In-specific
-- like the pattern this was adapted from), since Orca hasn't committed to a
-- specific jurisdiction's breach-notification regime. Immutable once
-- created: a breach record you can edit after the fact isn't evidence of
-- anything. Only DELETE is blocked (not UPDATE) because status/remediation
-- fields legitimately need to be updated as an incident is worked; the
-- historical fact that it was opened must not be erasable.
CREATE TABLE IF NOT EXISTS security_breach_log (
    id                TEXT PRIMARY KEY,
    title             TEXT NOT NULL,
    severity          TEXT NOT NULL DEFAULT 'medium',
    breach_type       TEXT NOT NULL,
    affected_user_ids TEXT,
    affected_count    INTEGER,
    data_categories   TEXT,
    description       TEXT NOT NULL,
    discovered_at     TEXT NOT NULL,
    contained_at      TEXT,
    users_notified    INTEGER NOT NULL DEFAULT 0,
    users_notified_at TEXT,
    status            TEXT NOT NULL DEFAULT 'open',
    remediation_steps TEXT,
    reported_by       TEXT NOT NULL,
    created_at        TEXT NOT NULL,
    updated_at        TEXT NOT NULL
);

CREATE TRIGGER IF NOT EXISTS trg_breach_log_no_delete
BEFORE DELETE ON security_breach_log
BEGIN
    SELECT RAISE(ABORT, 'security_breach_log entries cannot be deleted');
END;
"""

# Postgres gets the full audit_log hash-chain schema from day one — there's
# no "legacy pre-chain" Postgres install to migrate, unlike SQLite where
# existing local users may have an old-schema audit_log table.
_SCHEMA_POSTGRES = """
CREATE TABLE IF NOT EXISTS users (
    id            TEXT PRIMARY KEY,
    email               TEXT UNIQUE NOT NULL,
    name                TEXT NOT NULL DEFAULT '',
    password_hash       TEXT NOT NULL,
    tier                TEXT NOT NULL DEFAULT 'free',
    role                TEXT NOT NULL DEFAULT 'member',
    created_at          TEXT NOT NULL,
    verified            INTEGER NOT NULL DEFAULT 0,
    stripe_customer_id  TEXT,
    totp_secret         TEXT,
    totp_enabled        INTEGER NOT NULL DEFAULT 0,
    signup_seq          INTEGER
);
CREATE INDEX IF NOT EXISTS ix_users_stripe_customer ON users(stripe_customer_id);

-- See _SCHEMA_SQLITE for the rationale — same atomic-counter pattern here.
CREATE TABLE IF NOT EXISTS signup_counter (
    id       INTEGER PRIMARY KEY,
    next_seq INTEGER NOT NULL DEFAULT 1
);
INSERT INTO signup_counter (id, next_seq) VALUES (1, 1) ON CONFLICT (id) DO NOTHING;

CREATE TABLE IF NOT EXISTS usage_daily (
    user_id    TEXT NOT NULL,
    date       TEXT NOT NULL,
    messages   INTEGER NOT NULL DEFAULT 0,
    ultra_runs INTEGER NOT NULL DEFAULT 0,
    PRIMARY KEY (user_id, date)
);

CREATE TABLE IF NOT EXISTS user_sessions (
    user_id    TEXT NOT NULL,
    session_id TEXT NOT NULL,
    created_at TEXT NOT NULL,
    PRIMARY KEY (user_id, session_id)
);

-- See _SCHEMA_SQLITE for the rationale.
CREATE TABLE IF NOT EXISTS organizations (
    id            TEXT PRIMARY KEY,
    name          TEXT NOT NULL,
    owner_user_id TEXT NOT NULL,
    created_at    TEXT NOT NULL
);
CREATE TABLE IF NOT EXISTS org_members (
    id            TEXT PRIMARY KEY,
    org_id        TEXT NOT NULL,
    user_id       TEXT,
    invited_email TEXT NOT NULL,
    role          TEXT NOT NULL DEFAULT 'member',
    status        TEXT NOT NULL DEFAULT 'invited',
    invite_token  TEXT,
    invited_at    TEXT NOT NULL,
    joined_at     TEXT
);

CREATE TABLE IF NOT EXISTS audit_log (
    id          TEXT PRIMARY KEY,
    seq         BIGINT,
    user_id     TEXT,
    event       TEXT NOT NULL,
    detail      TEXT,
    ip          TEXT,
    created_at  DOUBLE PRECISION NOT NULL,
    prev_hash   TEXT NOT NULL,
    entry_hash  TEXT NOT NULL,
    signature   TEXT NOT NULL
);
CREATE INDEX IF NOT EXISTS ix_audit_user  ON audit_log(user_id);
CREATE INDEX IF NOT EXISTS ix_audit_event ON audit_log(event);
CREATE INDEX IF NOT EXISTS ix_audit_ts    ON audit_log(created_at);
CREATE INDEX IF NOT EXISTS ix_audit_seq   ON audit_log(seq);

-- See _SCHEMA_SQLITE for the rationale on these three tables.
CREATE TABLE IF NOT EXISTS privacy_consents (
    id          TEXT PRIMARY KEY,
    user_id     TEXT NOT NULL,
    purpose     TEXT NOT NULL,
    granted     INTEGER NOT NULL DEFAULT 0,
    legal_basis TEXT NOT NULL DEFAULT 'consent',
    version     TEXT NOT NULL DEFAULT '1.0',
    source      TEXT NOT NULL DEFAULT 'web',
    granted_at  TEXT,
    revoked_at  TEXT,
    updated_at  TEXT NOT NULL,
    UNIQUE (user_id, purpose)
);

CREATE TABLE IF NOT EXISTS consent_audit_log (
    id             TEXT PRIMARY KEY,
    user_id        TEXT NOT NULL,
    purpose        TEXT NOT NULL,
    action         TEXT NOT NULL,
    previous_state INTEGER,
    new_state      INTEGER NOT NULL,
    created_at     TEXT NOT NULL
);

CREATE TABLE IF NOT EXISTS data_export_requests (
    id              TEXT PRIMARY KEY,
    user_id         TEXT NOT NULL,
    status          TEXT NOT NULL DEFAULT 'pending',
    requested_at    TEXT NOT NULL,
    completed_at    TEXT,
    file_path       TEXT,
    error_message   TEXT
);

CREATE TABLE IF NOT EXISTS security_breach_log (
    id                TEXT PRIMARY KEY,
    title             TEXT NOT NULL,
    severity          TEXT NOT NULL DEFAULT 'medium',
    breach_type       TEXT NOT NULL,
    affected_user_ids TEXT,
    affected_count    INTEGER,
    data_categories   TEXT,
    description       TEXT NOT NULL,
    discovered_at     TEXT NOT NULL,
    contained_at      TEXT,
    users_notified    INTEGER NOT NULL DEFAULT 0,
    users_notified_at TEXT,
    status            TEXT NOT NULL DEFAULT 'open',
    remediation_steps TEXT,
    reported_by       TEXT NOT NULL,
    created_at        TEXT NOT NULL,
    updated_at        TEXT NOT NULL
);

-- Postgres-only append-only enforcement — SQLite's equivalent is the two
-- BEFORE triggers in _SCHEMA_SQLITE. rule-based, not trigger-based, since
-- that's the simpler idiom for "block a whole command" in Postgres.
CREATE OR REPLACE RULE consent_audit_no_update AS ON UPDATE TO consent_audit_log DO INSTEAD NOTHING;
CREATE OR REPLACE RULE consent_audit_no_delete AS ON DELETE TO consent_audit_log DO INSTEAD NOTHING;
CREATE OR REPLACE RULE breach_log_no_delete AS ON DELETE TO security_breach_log DO INSTEAD NOTHING;
"""

# ─────────────────────────────────────────────────────────────────────────────
#  Row-level security (Postgres only — SQLite has no RLS concept, and Orca's
#  SQLite mode is documented above as a single local install, not a
#  multi-tenant deployment). Defense-in-depth: every user-scoped query in
#  orca/auth/store.py already filters by user_id/uid at the application
#  layer — this is a DB-level backstop so a query that forgets that filter
#  fails closed (returns nothing) instead of leaking another user's rows.
#
#  Deliberately NOT wired into every call site yet — see
#  set_user_context()/set_service_context() below. Existing store.py code
#  runs as the Postgres role's default privileges, which this migration
#  does not change, so nothing breaks by adding these policies; they only
#  take effect for connections that actually call set_user_context() first.
#  Treat this as the schema-level foundation, not a claim that every code
#  path has adopted it yet.
# ─────────────────────────────────────────────────────────────────────────────
_RLS_POSTGRES = """
CREATE SCHEMA IF NOT EXISTS orca_security;

CREATE OR REPLACE FUNCTION orca_security.current_uid()
RETURNS TEXT LANGUAGE sql STABLE AS $$
  SELECT NULLIF(current_setting('app.current_user_id', true), '')
$$;

CREATE OR REPLACE FUNCTION orca_security.current_role_name()
RETURNS TEXT LANGUAGE sql STABLE AS $$
  SELECT COALESCE(NULLIF(current_setting('app.current_role', true), ''), 'user')
$$;

CREATE OR REPLACE FUNCTION orca_security.is_service()
RETURNS BOOLEAN LANGUAGE sql STABLE AS $$
  SELECT orca_security.current_role_name() IN ('service', 'admin', 'migration')
$$;

CREATE OR REPLACE FUNCTION orca_security.set_user_context(p_uid TEXT)
RETURNS void LANGUAGE plpgsql AS $$
BEGIN
  PERFORM set_config('app.current_user_id', p_uid, true);
  PERFORM set_config('app.current_role',    'user', true);
END;
$$;

CREATE OR REPLACE FUNCTION orca_security.set_service_context()
RETURNS void LANGUAGE plpgsql AS $$
BEGIN
  PERFORM set_config('app.current_user_id', '',        true);
  PERFORM set_config('app.current_role',    'service', true);
END;
$$;

ALTER TABLE users ENABLE ROW LEVEL SECURITY;
ALTER TABLE users FORCE ROW LEVEL SECURITY;
DROP POLICY IF EXISTS users_service_all ON users;
CREATE POLICY users_service_all ON users USING (orca_security.is_service());
DROP POLICY IF EXISTS users_self ON users;
CREATE POLICY users_self ON users USING (id = orca_security.current_uid());

ALTER TABLE usage_daily ENABLE ROW LEVEL SECURITY;
ALTER TABLE usage_daily FORCE ROW LEVEL SECURITY;
DROP POLICY IF EXISTS usage_daily_service_all ON usage_daily;
CREATE POLICY usage_daily_service_all ON usage_daily USING (orca_security.is_service());
DROP POLICY IF EXISTS usage_daily_owner ON usage_daily;
CREATE POLICY usage_daily_owner ON usage_daily USING (user_id = orca_security.current_uid());

ALTER TABLE privacy_consents ENABLE ROW LEVEL SECURITY;
ALTER TABLE privacy_consents FORCE ROW LEVEL SECURITY;
DROP POLICY IF EXISTS privacy_consents_service_all ON privacy_consents;
CREATE POLICY privacy_consents_service_all ON privacy_consents USING (orca_security.is_service());
DROP POLICY IF EXISTS privacy_consents_owner ON privacy_consents;
CREATE POLICY privacy_consents_owner ON privacy_consents USING (user_id = orca_security.current_uid());

ALTER TABLE data_export_requests ENABLE ROW LEVEL SECURITY;
ALTER TABLE data_export_requests FORCE ROW LEVEL SECURITY;
DROP POLICY IF EXISTS data_export_service_all ON data_export_requests;
CREATE POLICY data_export_service_all ON data_export_requests USING (orca_security.is_service());
DROP POLICY IF EXISTS data_export_owner ON data_export_requests;
CREATE POLICY data_export_owner ON data_export_requests USING (user_id = orca_security.current_uid());
"""
# api_keys is NOT created here — orca/auth/apikeys.py owns that table's
# schema (it has its own _ensure_table() with REAL timestamp columns and a
# `revoked` flag this module must not shadow). session_titles and doc_registry
# stay as flat JSON files for now — out of scope for this migration pass.


class _PGCursorAdapter:
    """Wraps a psycopg cursor so callers can use it exactly like a sqlite3 cursor."""

    def __init__(self, cur):
        self._cur = cur

    def fetchone(self):
        return self._cur.fetchone()

    def fetchall(self):
        return self._cur.fetchall()

    @property
    def rowcount(self):
        return self._cur.rowcount


class _PGConnAdapter:
    """
    Makes a psycopg connection quack like sqlite3.Connection:
      - execute(sql, params) with '?' placeholders (translated to '%s')
      - executescript(sql) for multi-statement DDL blocks
      - dict-row access (row["col"]) via psycopg's dict_row factory
      - context-manager commit-on-success / rollback-on-exception

    Deliberately does NOT close the underlying connection on __exit__ —
    this matches the existing sqlite3 usage pattern in this codebase (every
    call site does `with get_conn() as conn:` and relies on commit-only
    semantics, never calling conn.close()). Not fixing that pattern here;
    out of scope for this migration.
    """

    def __init__(self, pg_conn):
        self._conn = pg_conn

    def execute(self, sql: str, params=()):
        sql = _PLACEHOLDER_RE.sub("%s", sql)
        cur = self._conn.cursor()
        cur.execute(sql, params)
        return _PGCursorAdapter(cur)

    def executescript(self, script: str) -> None:
        cur = self._conn.cursor()
        for stmt in filter(None, (s.strip() for s in script.split(";"))):
            cur.execute(stmt)

    def execute_sql_block(self, script: str) -> None:
        """
        Sends `script` to Postgres as a single multi-statement string,
        unlike executescript() which splits on ';' — that split breaks any
        script containing a $$ ... $$ function body with semicolons inside
        it (e.g. the RLS policy setup in _RLS_POSTGRES). Postgres's simple
        query protocol accepts multiple ;-separated statements in one string
        natively, so this only works for static DDL with no parameters —
        never use this for anything taking user input.
        """
        cur = self._conn.cursor()
        cur.execute(script)

    def __enter__(self):
        return self

    def __exit__(self, exc_type, exc, tb):
        if exc_type is None:
            self._conn.commit()
        else:
            self._conn.rollback()
        return False  # never suppress exceptions


def _get_postgres_conn() -> _PGConnAdapter:
    import psycopg
    from psycopg.rows import dict_row

    dsn = orneur_env("DATABASE_URL")
    conn = psycopg.connect(dsn, row_factory=dict_row, autocommit=False)
    return _PGConnAdapter(conn)


def _get_sqlite_conn() -> sqlite3.Connection:
    AUTH_DB.parent.mkdir(parents=True, exist_ok=True)
    conn = sqlite3.connect(str(AUTH_DB), check_same_thread=False)
    conn.row_factory = sqlite3.Row
    conn.execute("PRAGMA journal_mode=WAL")
    conn.execute("PRAGMA foreign_keys=ON")
    return conn


def get_conn():
    """Returns a sqlite3.Connection or a _PGConnAdapter, selected by ORCA_DATABASE_URL."""
    if BACKEND == "postgres":
        return _get_postgres_conn()
    return _get_sqlite_conn()


def init_db() -> None:
    if BACKEND == "postgres":
        with get_conn() as conn:
            # CREATE TABLE IF NOT EXISTS is NOT safe under concurrent creation
            # on Postgres — multiple instances racing to create the same table
            # at startup can hit a catalog-level UniqueViolation
            # (pg_type_typname_nsp_index) even with IF NOT EXISTS, because the
            # check-then-create isn't atomic across transactions. Every API
            # replica runs this at import time, so without serializing it here,
            # a simultaneous multi-instance rollout crashes on boot. Same
            # advisory-lock pattern as the audit chain writer: first instance
            # through does the real work, the rest block, then see the schema
            # already exists once they get the lock.
            conn.execute("SELECT pg_advisory_xact_lock(hashtext('orca_schema_init'))")
            conn.executescript(_SCHEMA_POSTGRES)
            # A Postgres deployment created BEFORE a given column existed in
            # _SCHEMA_POSTGRES needs its own migration too — "fresh installs
            # get every column" only covers installs created after this line
            # was added. Postgres supports ADD COLUMN IF NOT EXISTS natively,
            # no try/except dance needed like the SQLite branch below.
            conn.execute("ALTER TABLE users ADD COLUMN IF NOT EXISTS stripe_customer_id TEXT")
            conn.execute("CREATE INDEX IF NOT EXISTS ix_users_stripe_customer ON users(stripe_customer_id)")
            conn.execute("ALTER TABLE users ADD COLUMN IF NOT EXISTS totp_secret TEXT")
            conn.execute("ALTER TABLE users ADD COLUMN IF NOT EXISTS totp_enabled INTEGER NOT NULL DEFAULT 0")
            conn.execute("ALTER TABLE users ADD COLUMN IF NOT EXISTS signup_seq INTEGER")
            # Contains $$ ... $$ function bodies with semicolons inside them —
            # must go through execute_sql_block(), not executescript(), which
            # would break on the naive ';' split (see its docstring).
            conn.execute_sql_block(_RLS_POSTGRES)
        return

    with get_conn() as conn:
        conn.executescript(_SCHEMA_SQLITE)
        # Migrations for existing SQLite installs only — a fresh Postgres
        # schema above already has every column (as of its own creation date —
        # columns added after that still need the ALTER above).
        for stmt in [
            "ALTER TABLE users ADD COLUMN role TEXT NOT NULL DEFAULT 'member'",
            "ALTER TABLE users ADD COLUMN stripe_customer_id TEXT",
            "ALTER TABLE users ADD COLUMN totp_secret TEXT",
            "ALTER TABLE users ADD COLUMN totp_enabled INTEGER NOT NULL DEFAULT 0",
            "ALTER TABLE users ADD COLUMN signup_seq INTEGER",
        ]:
            try:
                conn.execute(stmt)
            except Exception:
                pass  # column already exists


init_db()
