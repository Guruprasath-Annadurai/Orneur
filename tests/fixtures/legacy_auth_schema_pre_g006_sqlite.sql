-- Verbatim copy of orca/auth/db.py::_SCHEMA_SQLITE at the pre-G-006 commit (claude/p2-ui-design-spec). Used ONLY to test the upgrade path. Do not edit.

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
