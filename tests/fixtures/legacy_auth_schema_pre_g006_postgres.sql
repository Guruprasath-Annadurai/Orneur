-- Verbatim copy of orca/auth/db.py::_SCHEMA_POSTGRES and _RLS_POSTGRES at the pre-G-006 commit (claude/p2-ui-design-spec).
-- Used ONLY to test the upgrade path on a real PostgreSQL. Do not edit.

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

-- ==RLS==

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
