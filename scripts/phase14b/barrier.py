"""
Phase 14B distributed qualification -- a real, staging-only, namespaced
cross-host synchronization barrier.

This is deliberately NOT arbitrary sleep-based timing (spec explicitly
forbids that as the primary mechanism). Two actors running on genuinely
different hosts (Northflank Host A, GitHub Actions Host B) rendezvous
through a small table in the CORE Supabase database, gated entirely by
`run_id` so concurrent qualification runs (or a stale run from an
earlier attempt) can never interfere with each other. The barrier table
is qualification-only -- it is never read by any real ORNEUR
authorization path -- and every row is deleted by `cleanup()` at the
end of a run, so no barrier state survives a qualification run.

Uses `ORNEUR_DATABASE_URL` directly (the core Supabase database) via
psycopg, since this is test-harness infrastructure, not ORNEUR's own
authorization code.
"""
from __future__ import annotations

import os
import time

import psycopg

_SCHEMA = """
CREATE TABLE IF NOT EXISTS phase14b_qualification_barrier (
    run_id TEXT NOT NULL,
    actor TEXT NOT NULL,
    state TEXT NOT NULL,
    payload TEXT,
    created_at TIMESTAMPTZ NOT NULL DEFAULT now(),
    PRIMARY KEY (run_id, actor)
)
"""


def _connect() -> psycopg.Connection:
    dsn = os.environ["ORNEUR_DATABASE_URL"]
    return psycopg.connect(dsn, connect_timeout=10)


def _ensure_schema(conn: psycopg.Connection) -> None:
    with conn.cursor() as cur:
        cur.execute(_SCHEMA)
    conn.commit()


def announce_ready(run_id: str, actor: str, payload: str = "") -> None:
    """Actor announces it has reached the rendezvous point."""
    with _connect() as conn:
        _ensure_schema(conn)
        with conn.cursor() as cur:
            cur.execute(
                """
                INSERT INTO phase14b_qualification_barrier (run_id, actor, state, payload)
                VALUES (%s, %s, 'READY', %s)
                ON CONFLICT (run_id, actor) DO UPDATE SET state = 'READY', payload = %s, created_at = now()
                """,
                (run_id, actor, payload, payload),
            )
        conn.commit()


def wait_for_both(run_id: str, actors: tuple[str, str], timeout_s: float = 60.0, poll_s: float = 0.25) -> bool:
    """Blocks until both named actors have announced READY for this
    run_id, or returns False on timeout. This is the actual
    synchronization primitive -- polling a shared durable table, not a
    fixed sleep -- so the release is driven by real cross-host state,
    not a guessed delay."""
    deadline = time.monotonic() + timeout_s
    with _connect() as conn:
        _ensure_schema(conn)
        while time.monotonic() < deadline:
            with conn.cursor() as cur:
                cur.execute(
                    "SELECT actor FROM phase14b_qualification_barrier WHERE run_id = %s AND state = 'READY'",
                    (run_id,),
                )
                ready = {row[0] for row in cur.fetchall()}
            if set(actors).issubset(ready):
                return True
            time.sleep(poll_s)
    return False


def cleanup(run_id: str) -> None:
    """Deletes this run's barrier rows only -- qualification-only
    table, safe to delete; never touches any real ORNEUR authority/
    audit table."""
    with _connect() as conn:
        _ensure_schema(conn)
        with conn.cursor() as cur:
            cur.execute("DELETE FROM phase14b_qualification_barrier WHERE run_id = %s", (run_id,))
        conn.commit()
