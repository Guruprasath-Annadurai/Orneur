"""SQLite persistence in the product auth database. Not a second engine."""

from __future__ import annotations

import hashlib
import json
import sqlite3
from datetime import datetime, timezone

import orca.auth.db as auth_db

_SCHEMA = """
CREATE TABLE IF NOT EXISTS sovereign_missions (
    id TEXT PRIMARY KEY,
    owner_user_id TEXT NOT NULL,
    tenant_id TEXT NOT NULL,
    objective TEXT NOT NULL,
    state TEXT NOT NULL,
    cancel_requested INTEGER NOT NULL DEFAULT 0,
    revoked INTEGER NOT NULL DEFAULT 0,
    evidence_sha256 TEXT,
    created_at TEXT NOT NULL,
    updated_at TEXT NOT NULL
);
CREATE TABLE IF NOT EXISTS sovereign_steps (
    id TEXT PRIMARY KEY,
    mission_id TEXT NOT NULL,
    position INTEGER NOT NULL,
    tool TEXT NOT NULL,
    risk TEXT NOT NULL,
    arguments_json TEXT NOT NULL,
    approval_id TEXT,
    intent_json TEXT,
    effect_started INTEGER NOT NULL DEFAULT 0,
    outcome_json TEXT,
    UNIQUE (mission_id, position)
);
CREATE TABLE IF NOT EXISTS sovereign_approvals (
    id TEXT PRIMARY KEY,
    mission_id TEXT NOT NULL,
    step_id TEXT NOT NULL,
    user_id TEXT NOT NULL,
    tool TEXT NOT NULL,
    destination TEXT NOT NULL,
    expires_at TEXT NOT NULL,
    nonce TEXT NOT NULL,
    consumed_at TEXT
);
CREATE TABLE IF NOT EXISTS sovereign_evidence (
    id TEXT PRIMARY KEY,
    mission_id TEXT NOT NULL,
    step_id TEXT NOT NULL,
    owner_user_id TEXT NOT NULL,
    record_json TEXT NOT NULL,
    record_sha256 TEXT NOT NULL,
    created_at TEXT NOT NULL
);
"""


class StoreError(Exception):
    def __init__(self, code: str):
        self.code = code
        super().__init__(code)


def now_iso(now: datetime | None = None) -> str:
    clock = now or datetime.now(timezone.utc)
    if clock.tzinfo is None:
        raise StoreError("naive_clock")
    return clock.astimezone(timezone.utc).isoformat()


_READY: set[str] = set()


def connect() -> sqlite3.Connection:
    if auth_db.BACKEND != "sqlite":
        raise StoreError("sqlite_auth_required")
    auth_db.AUTH_DB.parent.mkdir(parents=True, exist_ok=True)
    conn = auth_db.get_conn()
    conn.isolation_level = None
    key = str(auth_db.AUTH_DB)
    if key not in _READY:
        conn.executescript(_SCHEMA)
        _READY.add(key)
    conn.execute("PRAGMA busy_timeout=5000")
    conn.execute("PRAGMA foreign_keys=ON")
    return conn


def ensure_schema() -> None:
    conn = connect()
    conn.close()


def canonical(payload: dict) -> str:
    return json.dumps(payload, sort_keys=True, separators=(",", ":"))


def digest(payload: dict) -> str:
    return hashlib.sha256(canonical(payload).encode()).hexdigest()


class Unit:
    def __init__(self):
        self.conn = connect()
        self.conn.execute("BEGIN IMMEDIATE")

    def commit(self) -> None:
        self.conn.execute("COMMIT")

    def rollback(self) -> None:
        try:
            self.conn.execute("ROLLBACK")
        except sqlite3.OperationalError:
            pass

    def close(self) -> None:
        self.conn.close()
