"""Idempotency keys for /api/chat (Workstream B: safe retry).

A client that lost the connection can resend the SAME request with the SAME `Idempotency-Key` and get the SAME answer without a second model call or a second
quota charge. States: `begin()` -> "new" (caller proceeds), "done" (cached response returned), "in_progress" (another attempt holds the key -> 409),
"mismatch" (same key, different payload -> 422). Keys are scoped to the authenticated user and expire after 10 minutes. Only successful (200) JSON responses are
cached; failures release the key so a retry is a real retry.
"""
from __future__ import annotations

import hashlib
import json
import re
import time

from orca.auth.db import get_conn

TTL_SECONDS = 600
_KEY_RE = re.compile(r"^[A-Za-z0-9_\-]{8,128}$")


def valid_key(key: str | None) -> bool:
    return bool(key) and bool(_KEY_RE.match(key))


def request_hash(payload: dict) -> str:
    return hashlib.sha256(json.dumps(payload, sort_keys=True, separators=(",", ":"), default=str).encode()).hexdigest()


def _purge(conn, now: float) -> None:
    conn.execute("DELETE FROM idempotency_keys WHERE created_at < ?", (now - TTL_SECONDS,))


def begin(user_id: str, key: str, req_hash: str, now: float | None = None) -> tuple[str, dict | None]:
    now = time.time() if now is None else now
    with get_conn() as conn:
        _purge(conn, now)
        won = conn.execute(
            "INSERT INTO idempotency_keys (user_id, idem_key, request_hash, status, created_at) VALUES (?,?,?,?,?) ON CONFLICT DO NOTHING RETURNING idem_key",
            (user_id, key, req_hash, "in_progress", now),
        ).fetchone()
        if won:
            return "new", None
        row = conn.execute("SELECT request_hash, status, response FROM idempotency_keys WHERE user_id=? AND idem_key=?", (user_id, key)).fetchone()
    if row is None:                                   # expired between statements: let the caller retry as new
        return begin(user_id, key, req_hash, now)
    if row["request_hash"] != req_hash:
        return "mismatch", None
    if row["status"] == "done" and row["response"]:
        return "done", json.loads(row["response"])
    return "in_progress", None


def complete(user_id: str, key: str, response: dict) -> None:
    with get_conn() as conn:
        conn.execute("UPDATE idempotency_keys SET status='done', response=? WHERE user_id=? AND idem_key=?", (json.dumps(response, default=str), user_id, key))


def abort(user_id: str, key: str) -> None:
    with get_conn() as conn:
        conn.execute("DELETE FROM idempotency_keys WHERE user_id=? AND idem_key=? AND status='in_progress'", (user_id, key))
