"""L02-01: authoritative, idempotent conversation deletion.

A deletion has a durable identity (``session_deletions`` in the authoritative turns database) that is written FIRST, before any store is touched.
From that instant the conversation is *access revoked*: every access gate (``api._check_session_ownership`` / ``_get_session`` / the session list),
``conversations.commit_turn`` and ``conversations.acquire_authority`` refuse it, so a stale worker or an in-flight generation can neither read
nor resurrect it while physical cleanup proceeds. The row is never removed: a session id is a uuid and is never legitimately reused.

States:  ``revoked`` (tombstone written, nothing cleaned yet) -> ``running`` (one worker holds the cleanup lease) -> ``complete`` | ``partial``.
``partial`` is retryable (same DELETE again, or ``resume_pending()`` from the periodic sweep) and is reported to the caller as NOT deleted.
The ownership claim is released only when every store confirmed, so the owner can always retry.

What "complete" means here and what it does not (see docs/orneur/landmarks/landmark-02/L02_DATA_LIFECYCLE_AND_DELETION.md):
every application-controlled store reported success. It is not a claim of physical or cryptographic erasure, and it says nothing about copies the
application does not control (host backups, filesystem snapshots, a third-party provider that received the prompt).
"""
from __future__ import annotations

import json
import logging
import time
import uuid

from orca.serve import conversations

_logger = logging.getLogger("orneur.deletions")

LEASE_S = 60.0
MAX_ATTEMPTS = 8

# Honest, fixed statement returned with every deletion result.
RETENTION_NOTICE = {
    "application_backups": "ORNEUR does not create backups of conversation data; copies made by the host (disk snapshots, backups) are outside this deletion.",
    "external_copies": "Text sent to a model provider while answering is governed by that provider; a local Ollama keeps no copy.",
    "physical_erasure": "Not claimed. The transcript database overwrites freed pages (secure_delete) and truncates its WAL; the vector store reports RECLAIMED or DEFERRED.",
}


def _now() -> float:
    return time.time()


def _row(conn, session_id: str):
    return conn.execute("SELECT * FROM session_deletions WHERE session_id=?", (session_id,)).fetchone()


def _view(row) -> dict:
    stores = json.loads(row["stores_json"] or "{}")
    state = row["state"]
    return {
        "deletion_id": row["deletion_id"], "session_id": row["session_id"], "state": state, "attempts": int(row["attempts"]),
        "access_revoked": True, "deleted": state == "complete", "retryable": state in ("revoked", "running", "partial"),
        "stores": stores,
    }


def is_tombstoned(session_id: str) -> bool:
    """True when the conversation has a deletion identity. Fails CLOSED: if the authoritative database cannot answer, the conversation is treated as unavailable."""
    try:
        conn = conversations._turns_conn()
        try:
            return _row(conn, session_id) is not None
        finally:
            conn.close()
    except Exception:
        _logger.warning("deletion tombstone lookup failed; treating the conversation as unavailable", exc_info=True)
        return True


def tombstoned_among(session_ids) -> set[str]:
    ids = list(session_ids)
    if not ids:
        return set()
    try:
        conn = conversations._turns_conn()
        try:
            found: set[str] = set()
            for i in range(0, len(ids), 500):
                chunk = ids[i:i + 500]
                q = ",".join("?" * len(chunk))
                found.update(r["session_id"] for r in conn.execute(f"SELECT session_id FROM session_deletions WHERE session_id IN ({q})", chunk))
            return found
        finally:
            conn.close()
    except Exception:
        _logger.warning("deletion tombstone listing failed; hiding every candidate", exc_info=True)
        return set(ids)


def begin(session_id: str, user_id: str) -> dict:
    """Write the durable deletion identity (idempotent: a repeat returns the existing one). Access is revoked when this returns."""
    now = _now()
    conn = conversations._turns_conn()
    try:
        with conn:
            conn.execute(          # conflict-resolved by the primary key: exactly one concurrent caller creates the identity, the rest read it back
                "INSERT INTO session_deletions (session_id, deletion_id, user_id, state, created_at, updated_at) VALUES (?,?,?,?,?,?) "
                "ON CONFLICT(session_id) DO NOTHING",
                (session_id, str(uuid.uuid4()), user_id, "revoked", now, now),
            )
            row = _row(conn, session_id)
        return _view(row)
    finally:
        conn.close()


def get(session_id: str) -> dict | None:
    conn = conversations._turns_conn()
    try:
        row = _row(conn, session_id)
        return _view(row) if row else None
    finally:
        conn.close()


def _lease(session_id: str) -> bool:
    """Take the cleanup lease. Exactly one worker wins; a crashed holder's lease lapses after LEASE_S."""
    now = _now()
    conn = conversations._turns_conn()
    try:
        with conn:
            cur = conn.execute(
                "UPDATE session_deletions SET state='running', lease_until=?, attempts=attempts+1, updated_at=? "
                "WHERE session_id=? AND state!='complete' AND (state!='running' OR lease_until<?)",
                (now + LEASE_S, now, session_id, now),
            )
            return cur.rowcount == 1
    finally:
        conn.close()


def _finish(session_id: str, state: str, stores: dict) -> dict:
    conn = conversations._turns_conn()
    try:
        with conn:
            conn.execute(
                "UPDATE session_deletions SET state=?, stores_json=?, lease_until=0, updated_at=? WHERE session_id=?",
                (state, json.dumps(stores), _now(), session_id),
            )
        return _view(_row(conn, session_id))
    finally:
        conn.close()


def classify(result: dict) -> dict[str, str]:
    """Reduce the cascade's raw report to ``store -> ok | failed``. A store is *failed* only when it reported an error (or the transcript reported that
    rows may remain); "nothing to delete" is ok. Error text is never returned to the caller (it can contain paths)."""
    out: dict[str, str] = {}
    for key, value in result.items():
        if key.endswith("_error"):
            out[key[: -len("_error")]] = "failed"
    if result.get("conversation_transcript_deleted") is False:
        out["conversation_transcript"] = "failed"
    names = {
        "memory": 1, "conversation_transcript": 1, "message_versions": 1, "long_term_vector_memory": 1, "docs": 1,
        "knowledge_graph": 1, "redis": 1, "semantic_facts": 1, "memory_continuum": 1,
    }
    for n in names:
        out.setdefault(n, "ok")
    return out


def run(session_id: str, user_id: str) -> dict:
    """Run (or resume) the cleanup cascade for an already-begun deletion. Blocking: call from a worker thread. Returns the deletion view."""
    return run_with_report(session_id, user_id)[0]


def run_with_report(session_id: str, user_id: str) -> tuple[dict, dict | None]:
    """``run`` plus the cascade's raw per-store report (None when another worker holds the lease / it was already complete)."""
    from orca.serve.account_delete import _delete_session_data, _remove_session_title

    if not _lease(session_id):
        return (get(session_id) or begin(session_id, user_id)), None  # another worker holds the lease (or it is already complete)
    try:
        result = _delete_session_data(session_id)
        try:
            from orca.serve import message_versions
            message_versions.delete_session(session_id)
        except Exception:
            result["message_versions_error"] = "failed"
        _remove_session_title(session_id)
        stores = classify(result)
        stores["_vector_physical_reclamation"] = str(result.get("long_term_vector_memory_physical_reclamation") or "n/a")
        ok = all(v == "ok" for k, v in stores.items() if not k.startswith("_"))
        if ok:
            from orca.auth.store import release_session
            release_session(session_id, user_id)
        return _finish(session_id, "complete" if ok else "partial", stores), result
    except Exception:
        _logger.warning("deletion cascade crashed; left partial for retry", exc_info=True)
        return _finish(session_id, "partial", {"cascade": "failed"}), None


def resume_pending(limit: int = 20) -> int:
    """Periodic/startup sweep: re-run every unfinished deletion (idempotent, bounded attempts, lease-guarded). Returns how many it advanced."""
    now = _now()
    conn = conversations._turns_conn()
    try:
        rows = conn.execute(
            "SELECT session_id, user_id FROM session_deletions WHERE state!='complete' AND attempts<? AND (state!='running' OR lease_until<?) "
            "ORDER BY updated_at LIMIT ?", (MAX_ATTEMPTS, now, int(limit)),
        ).fetchall()
    finally:
        conn.close()
    n = 0
    for r in rows:
        run(r["session_id"], r["user_id"])
        n += 1
    return n
