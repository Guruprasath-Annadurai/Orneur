"""L02-03: authoritative outcome of a client request ("did my message go through?").

A browser can lose its connection at any instant of a turn - before the server saw the request, while the model is generating, during the commit, or after the
commit but before the acknowledgement. The connection state says nothing about which. This module keeps one durable record per request (the ``Idempotency-Key``,
scoped to the signed-in user) in the same database as the transcript, so the answer comes from the same transaction that decides what the transcript contains.

States (``view()["state"]``):
  admitted          the server accepted the request; generation has not started
  running           generation / commit in progress, and the worker that owns the turn is still alive
  cancel_requested  the user pressed Stop; the running turn has not yet confirmed
  cancelled         CONFIRMED: the turn stopped and nothing was committed
  committed         the turn is in the transcript (message ids returned)
  not_committed     nothing was committed (provider failure, refusal, abstention, client disconnect, worker lost) - ``reason`` says which
  superseded        another worker took the conversation over; nothing from this request was committed
  unknown           the server has no record: it never saw the request or refused it before admission. Nothing was committed. Retrying is safe.
  outcome_unknown   (HTTP 503 only) the authoritative store could not be read right now. NOT a statement about the turn. Ask again.

``committed`` is written by ``conversations.commit_turn`` inside the commit transaction. Every other terminal state is a compare-and-set from a non-terminal state,
so a terminal state never changes and a commit can never be contradicted. A non-terminal record whose turn authority has expired or been replaced can no longer
commit (``commit_turn`` re-validates fence, epoch and expiry in its transaction), so the reader resolves it to ``not_committed`` / ``superseded`` and records that.
"""
from __future__ import annotations

import time

from orca.serve import conversations

TERMINAL = ("committed", "not_committed", "cancelled", "superseded")
RETENTION_S = 24 * 3600
ABANDON_GRACE_S = 2.0
READ_TIMEOUT_S = 3.0


def _now() -> float:
    return time.time()


def begin(user_id: str, key: str, session_id: str | None = None, request_hash: str | None = None) -> dict:
    """Record admission (idempotent). Returns the current record - a pre-existing terminal record means the request was already decided."""
    now = _now()
    conn = conversations._turns_conn()
    try:
        with conn:
            conn.execute("DELETE FROM turn_requests WHERE updated_at < ?", (now - RETENTION_S,))
            conn.execute(
                "INSERT INTO turn_requests (user_id, request_key, session_id, state, request_hash, created_at, updated_at) VALUES (?,?,?,?,?,?,?) ON CONFLICT DO NOTHING",
                (user_id, key, session_id, "admitted", request_hash, now, now),
            )
            return dict(conn.execute("SELECT * FROM turn_requests WHERE user_id=? AND request_key=?", (user_id, key)).fetchone())
    finally:
        conn.close()


def reopen(user_id: str, key: str, session_id: str | None = None, request_hash: str | None = None) -> None:
    """A client retry of a request whose previous attempt ended WITHOUT committing: same key, new attempt. (A committed record is never reopened.)"""
    now = _now()
    _update("UPDATE turn_requests SET state='admitted', reason=NULL, session_id=COALESCE(?, session_id), request_hash=COALESCE(?, request_hash), fence_token=NULL, epoch=NULL, cancel_requested=0, updated_at=? "
            "WHERE user_id=? AND request_key=? AND state IN ('not_committed','cancelled','superseded')", (session_id, request_hash, now, user_id, key))


def _update(sql: str, args: tuple) -> bool:
    conn = conversations._turns_conn()
    try:
        with conn:
            return (conn.execute(sql, args).rowcount or 0) == 1
    finally:
        conn.close()


def attach(user_id: str, key: str, session_id: str) -> None:
    _update("UPDATE turn_requests SET session_id=?, updated_at=? WHERE user_id=? AND request_key=? AND state NOT IN ('committed','not_committed','cancelled','superseded')",
            (session_id, _now(), user_id, key))


def mark_running(user_id: str, key: str, session_id: str, fence: str, epoch: int) -> None:
    _update("UPDATE turn_requests SET state='running', session_id=?, fence_token=?, epoch=?, updated_at=? "
            "WHERE user_id=? AND request_key=? AND state IN ('admitted','running')", (session_id, fence, int(epoch or 0), _now(), user_id, key))


def finish(user_id: str, key: str, state: str, reason: str | None = None) -> bool:
    """Compare-and-set to a terminal state from a non-terminal one. Returns False when the record was already terminal (e.g. committed)."""
    assert state in TERMINAL and state != "committed"
    return _update("UPDATE turn_requests SET state=?, reason=?, updated_at=? WHERE user_id=? AND request_key=? "
                   "AND state NOT IN ('committed','not_committed','cancelled','superseded')", (state, (reason or "")[:80] or None, _now(), user_id, key))


def request_cancel(user_id: str, key: str, session_id: str | None = None) -> dict:
    """The user pressed Stop. A running turn is asked to stop (it confirms by ending); a request the server has not seen yet is closed in advance so that a
    late-arriving request with the same key is refused instead of generating."""
    now = _now()
    conn = conversations._turns_conn()
    try:
        with conn:
            row = conn.execute("SELECT state FROM turn_requests WHERE user_id=? AND request_key=?", (user_id, key)).fetchone()
            if row is None:
                conn.execute("INSERT INTO turn_requests (user_id, request_key, session_id, state, reason, cancel_requested, created_at, updated_at) VALUES (?,?,?,?,?,?,?,?)",
                             (user_id, key, session_id, "cancelled", "cancelled_before_admission", 1, now, now))
            elif row["state"] not in TERMINAL:
                conn.execute("UPDATE turn_requests SET cancel_requested=1, updated_at=? WHERE user_id=? AND request_key=?", (now, user_id, key))
    finally:
        conn.close()
    return view(user_id, key) or {"state": "unknown"}


def cancel_requested(user_id: str, key: str) -> bool:
    try:
        conn = conversations._turns_conn()
        try:
            row = conn.execute("SELECT cancel_requested, state FROM turn_requests WHERE user_id=? AND request_key=?", (user_id, key)).fetchone()
        finally:
            conn.close()
        return bool(row and row["cancel_requested"] and row["state"] not in TERMINAL)
    except Exception:
        return False


def _authority_alive(conn, session_id, fence, epoch) -> str:
    """'alive' | 'superseded' | 'lost' for the turn authority this request ran under."""
    if not session_id or not fence:
        return "lost"
    row = conn.execute("SELECT fence_token, epoch, expires_at FROM session_authority WHERE session_id=?", (session_id,)).fetchone()
    if row is None:
        return "lost"
    if row["fence_token"] == fence and int(row["epoch"]) == int(epoch or 0):
        return "alive" if float(row["expires_at"]) > _now() - ABANDON_GRACE_S else "lost"
    return "superseded" if int(row["epoch"]) > int(epoch or 0) or row["fence_token"] != fence else "lost"


def view(user_id: str, key: str) -> dict | None:
    """The authoritative record, or None if the server has none. Raises if the store cannot be read within ``READ_TIMEOUT_S`` (the caller reports ``outcome_unknown``
    instead of making the client wait behind a slow commit)."""
    conn = conversations._turns_conn(timeout=READ_TIMEOUT_S)
    try:
        row = conn.execute("SELECT * FROM turn_requests WHERE user_id=? AND request_key=?", (user_id, key)).fetchone()
        if row is None:
            return None
        state, reason = row["state"], row["reason"]
        if state not in TERMINAL:
            liveness = _authority_alive(conn, row["session_id"], row["fence_token"], row["epoch"]) if state == "running" else (
                "alive" if _now() - float(row["updated_at"]) < 120 else "lost")
            if liveness != "alive":
                # The owning worker can no longer commit (authority expired or replaced): resolve and record it. CAS from the exact state we read.
                resolved = "superseded" if liveness == "superseded" else "not_committed"
                why = "superseded_by_another_worker" if liveness == "superseded" else ("cancelled_worker_lost" if row["cancel_requested"] else "worker_lost")
                if row["cancel_requested"] and resolved == "not_committed":
                    resolved, why = "cancelled", "worker_lost_after_cancel"
                with conn:
                    cur = conn.execute("UPDATE turn_requests SET state=?, reason=?, updated_at=? WHERE user_id=? AND request_key=? AND state=?",
                                       (resolved, why, _now(), user_id, key, state))
                if (cur.rowcount or 0) != 1:                                       # someone else (possibly the commit) decided first: read the truth
                    row = conn.execute("SELECT * FROM turn_requests WHERE user_id=? AND request_key=?", (user_id, key)).fetchone()
                    state, reason = row["state"], row["reason"]
                else:
                    state, reason = resolved, why
            elif row["cancel_requested"]:
                state = "cancel_requested"
        return {
            "request_key": key, "state": state, "reason": reason, "session_id": row["session_id"], "message_id": row["message_id"],
            "user_message_id": row["user_message_id"], "revision": row["revision"], "turn_id": row["turn_id"], "request_hash": row["request_hash"], "cancel_requested": bool(row["cancel_requested"]),
            "updated_at": row["updated_at"],
            "safe_to_retry": state in ("not_committed", "cancelled", "superseded"),
            "terminal": state in TERMINAL,
        }
    finally:
        conn.close()
