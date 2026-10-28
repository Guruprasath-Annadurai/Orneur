"""Durable conversation history for signed-in users (Workstream B).

Until now a conversation survived a server restart only if the client had called /api/session/save, and even then only the last 20 exchanges (the
sliding window of `ShortTermMemory`). This module keeps an append-only, per-session transcript on disk:

  <MEMORY_DIR>/conversations/<session_id>.jsonl   (dir 0700, files 0600, one JSON object per message, written with a single O_APPEND write)

Committed inference turns are recorded in a transactional SQLite store
(``turns.db``) that is the **authoritative** commit log for user/assistant
pairs and monotonic per-session revisions. JSONL is a derived export written
**only after** the SQLite transaction commits successfully — never inside an
uncommitted transaction. Inference prompt context reads SQLite only and never
falls back to JSONL. Legacy JSONL-only history is imported only via an
explicit ``migrate_legacy_jsonl`` call. Ownership is NEVER decided here: every
caller must have passed the session-ownership check (`check_session_access`)
first. File names are the full, validated session id (`[A-Za-z0-9_-]{1,64}`),
never a prefix, so two sessions can not share a file. Anonymous sessions are
not persisted (nobody could retrieve or delete them).
"""
from __future__ import annotations

import json
import os
import re
import sqlite3
import threading
import time
from dataclasses import dataclass
from pathlib import Path
from typing import Callable, Iterator

_SESSION_ID_RE = re.compile(r"^[A-Za-z0-9_-]{1,64}$")
MAX_MESSAGE_CHARS = 200_000
MAX_MESSAGES_PER_SESSION = 20_000
MAX_FILE_BYTES = 64 * 1024 * 1024
_SNIPPET_RADIUS = 70
_DB_LOCK = threading.RLock()


def _dir() -> Path:
    import orca.brain.memory as mem          # resolved at call time: tests and deployments may relocate MEMORY_DIR

    d = Path(mem.MEMORY_DIR) / "conversations"
    d.mkdir(parents=True, exist_ok=True)
    try:
        os.chmod(d, 0o700)
    except OSError:
        pass
    return d


def _path(session_id: str) -> Path:
    if not _SESSION_ID_RE.match(session_id or ""):
        raise ValueError("invalid session id")
    return _dir() / f"{session_id}.jsonl"


def _turns_db() -> Path:
    return _dir() / "turns.db"


def _turns_conn() -> sqlite3.Connection:
    path = _turns_db()
    conn = sqlite3.connect(str(path), isolation_level=None, check_same_thread=False, timeout=30)
    conn.row_factory = sqlite3.Row
    conn.execute("PRAGMA journal_mode=WAL")
    conn.execute("PRAGMA busy_timeout=30000")
    conn.execute(
        "CREATE TABLE IF NOT EXISTS conversation_turns ("
        "turn_id TEXT PRIMARY KEY,"
        "session_id TEXT NOT NULL,"
        "user_id TEXT NOT NULL,"
        "revision INTEGER NOT NULL,"
        "user_content TEXT NOT NULL,"
        "assistant_content TEXT NOT NULL,"
        "meta_json TEXT,"
        "created_at REAL NOT NULL,"
        "UNIQUE(session_id, revision)"
        ")"
    )
    conn.execute(
        "CREATE INDEX IF NOT EXISTS ix_conversation_turns_session "
        "ON conversation_turns(session_id, revision)"
    )
    conn.execute(
        "CREATE TABLE IF NOT EXISTS session_export_state ("
        "session_id TEXT PRIMARY KEY,"
        "head_revision INTEGER NOT NULL DEFAULT 0,"
        "export_revision INTEGER NOT NULL DEFAULT 0,"
        "migrated_legacy INTEGER NOT NULL DEFAULT 0,"
        "updated_at REAL NOT NULL"
        ")"
    )
    return conn


@dataclass(frozen=True)
class CommitResult:
    ok: bool
    reason: str = ""
    turn_id: str = ""
    revision: int = 0


def append(session_id: str, role: str, content: str, *, meta: dict | None = None, now: float | None = None) -> None:
    """Append one message. Never raises into the request path for I/O problems (history is best-effort), but refuses invalid ids loudly.

    Legacy / API chat path. Inference commits must use ``commit_turn``; prompt
    builders must not treat this JSONL as authoritative without migration.
    """
    p = _path(session_id)
    if role not in ("user", "assistant", "system"):
        raise ValueError("invalid role")
    rec = {"role": role, "content": (content or "")[:MAX_MESSAGE_CHARS], "ts": float(time.time() if now is None else now)}
    if meta:
        rec["meta"] = meta
    line = (json.dumps(rec, ensure_ascii=False, separators=(",", ":")) + "\n").encode("utf-8")
    try:
        if p.exists() and p.stat().st_size + len(line) > MAX_FILE_BYTES:
            return
        fd = os.open(p, os.O_WRONLY | os.O_APPEND | os.O_CREAT | getattr(os, "O_NOFOLLOW", 0), 0o600)
        try:
            os.write(fd, line)
        finally:
            os.close(fd)
    except OSError:
        return


def _pair_payload(
    *,
    turn_id: str,
    revision: int,
    user_content: str,
    assistant_content: str,
    meta: dict | None,
    ts: float,
) -> bytes:
    user_rec = {
        "role": "user",
        "content": (user_content or "")[:MAX_MESSAGE_CHARS],
        "ts": ts,
        "meta": {"turn_id": turn_id, "revision": int(revision)},
    }
    asst_meta = {"turn_id": turn_id, "revision": int(revision)}
    if meta:
        asst_meta.update(meta)
    asst_rec = {
        "role": "assistant",
        "content": (assistant_content or "")[:MAX_MESSAGE_CHARS],
        "ts": ts,
        "meta": asst_meta,
    }
    return (
        json.dumps(user_rec, ensure_ascii=False, separators=(",", ":"))
        + "\n"
        + json.dumps(asst_rec, ensure_ascii=False, separators=(",", ":"))
        + "\n"
    ).encode("utf-8")


def _export_pair_after_commit(session_id: str, payload: bytes) -> bool:
    """Write derived JSONL only after SQLite has already committed. Never called inside a txn."""
    p = _path(session_id)
    try:
        if p.exists() and p.stat().st_size + len(payload) > MAX_FILE_BYTES:
            return False
        fd = os.open(p, os.O_WRONLY | os.O_APPEND | os.O_CREAT | getattr(os, "O_NOFOLLOW", 0), 0o600)
        try:
            os.write(fd, payload)
        finally:
            os.close(fd)
        return True
    except OSError:
        return False


def _head_revision(conn: sqlite3.Connection, session_id: str) -> int:
    row = conn.execute(
        "SELECT COALESCE(MAX(revision), 0) AS head FROM conversation_turns WHERE session_id=?",
        (session_id,),
    ).fetchone()
    return int(row["head"] if row else 0)


def commit_turn(
    session_id: str,
    user_content: str,
    assistant_content: str,
    *,
    user_id: str,
    turn_id: str,
    revision: int | None = None,
    meta: dict | None = None,
    now: float | None = None,
    authority_check: Callable[[], bool] | None = None,
) -> CommitResult:
    """Atomically commit one complete user/assistant turn under SQLite authority.

    Protocol:
      1. ``BEGIN IMMEDIATE`` (exclusive writer lock).
      2. Optional ``authority_check`` (lease still held) runs *inside* the txn.
      3. Allocate the next monotonic revision from SQLite (caller ``revision``
         must match if provided; otherwise auto-assigned).
      4. Insert the turn row; update ``session_export_state.head_revision``.
      5. ``COMMIT`` — only then is the turn durable/authoritative.
      6. Derived JSONL export happens **after** commit (never inside the txn).
         Export failure leaves SQLite authoritative; ``reconcile_export`` repairs.

    Idempotent on ``turn_id``. Returns ``stale_worker`` when authority fails.
    """
    if not _SESSION_ID_RE.match(session_id or ""):
        raise ValueError("invalid session id")
    if not user_id or not turn_id:
        return CommitResult(ok=False, reason="invalid_commit")
    if revision is not None and int(revision) <= 0:
        return CommitResult(ok=False, reason="invalid_commit")
    ts = float(time.time() if now is None else now)

    with _DB_LOCK:
        conn = _turns_conn()
        allocated = 0
        try:
            conn.execute("BEGIN IMMEDIATE")
            existing = conn.execute(
                "SELECT turn_id, revision FROM conversation_turns WHERE turn_id=?",
                (turn_id,),
            ).fetchone()
            if existing:
                conn.execute("COMMIT")
                return CommitResult(
                    ok=True,
                    reason="idempotent",
                    turn_id=turn_id,
                    revision=int(existing["revision"]),
                )

            if authority_check is not None:
                try:
                    allowed = bool(authority_check())
                except Exception:
                    allowed = False
                if not allowed:
                    conn.execute("ROLLBACK")
                    return CommitResult(ok=False, reason="stale_worker", turn_id=turn_id)

            next_rev = _head_revision(conn, session_id) + 1
            if revision is not None and int(revision) != next_rev:
                conn.execute("ROLLBACK")
                return CommitResult(
                    ok=False,
                    reason="revision_conflict",
                    turn_id=turn_id,
                    revision=int(revision),
                )
            allocated = int(revision) if revision is not None else next_rev

            conn.execute(
                "INSERT INTO conversation_turns "
                "(turn_id, session_id, user_id, revision, user_content, assistant_content, meta_json, created_at) "
                "VALUES (?,?,?,?,?,?,?,?)",
                (
                    turn_id,
                    session_id,
                    user_id,
                    allocated,
                    (user_content or "")[:MAX_MESSAGE_CHARS],
                    (assistant_content or "")[:MAX_MESSAGE_CHARS],
                    json.dumps(meta or {}, default=str),
                    ts,
                ),
            )
            conn.execute(
                "INSERT INTO session_export_state (session_id, head_revision, export_revision, migrated_legacy, updated_at) "
                "VALUES (?,?,?,?,?) "
                "ON CONFLICT(session_id) DO UPDATE SET "
                "head_revision=excluded.head_revision, updated_at=excluded.updated_at",
                (session_id, allocated, 0, 0, ts),
            )
            # Keep export_revision on conflict — only bump head.
            conn.execute(
                "UPDATE session_export_state SET head_revision=?, updated_at=? WHERE session_id=?",
                (allocated, ts, session_id),
            )
            conn.execute("COMMIT")
        except Exception:
            try:
                conn.execute("ROLLBACK")
            except Exception:
                pass
            return CommitResult(ok=False, reason="persist_failed", turn_id=turn_id, revision=int(revision or 0))
        finally:
            try:
                conn.close()
            except Exception:
                pass

    # JSONL is derived — only after durable SQLite commit.
    payload = _pair_payload(
        turn_id=turn_id,
        revision=allocated,
        user_content=user_content,
        assistant_content=assistant_content,
        meta=meta,
        ts=ts,
    )
    exported = _export_pair_after_commit(session_id, payload)
    if exported:
        try:
            conn2 = _turns_conn()
            try:
                conn2.execute("BEGIN IMMEDIATE")
                conn2.execute(
                    "UPDATE session_export_state SET export_revision=?, updated_at=? "
                    "WHERE session_id=? AND export_revision < ?",
                    (allocated, time.time(), session_id, allocated),
                )
                conn2.execute("COMMIT")
            except Exception:
                try:
                    conn2.execute("ROLLBACK")
                except Exception:
                    pass
            finally:
                conn2.close()
        except Exception:
            pass
    return CommitResult(ok=True, turn_id=turn_id, revision=allocated)


class TurnsUnavailable(RuntimeError):
    """SQLite turns store could not be opened or queried."""


def turns_for_session(session_id: str, *, raise_on_unavailable: bool = False) -> list[dict]:
    """Authoritative committed turns for a session (empty if none). Never reads JSONL."""
    if not _SESSION_ID_RE.match(session_id or ""):
        return []
    try:
        conn = _turns_conn()
    except Exception as exc:
        if raise_on_unavailable:
            raise TurnsUnavailable(str(exc)) from exc
        return []
    try:
        rows = conn.execute(
            "SELECT turn_id, revision, user_content, assistant_content, meta_json, created_at "
            "FROM conversation_turns WHERE session_id=? ORDER BY revision ASC",
            (session_id,),
        ).fetchall()
        out = []
        for row in rows:
            try:
                meta = json.loads(row["meta_json"] or "{}")
            except Exception:
                meta = {}
            out.append(
                {
                    "turn_id": row["turn_id"],
                    "revision": int(row["revision"]),
                    "user_content": row["user_content"],
                    "assistant_content": row["assistant_content"],
                    "meta": meta,
                    "created_at": row["created_at"],
                }
            )
        return out
    except Exception as exc:
        if raise_on_unavailable:
            raise TurnsUnavailable(str(exc)) from exc
        return []
    finally:
        try:
            conn.close()
        except Exception:
            pass


def committed_messages(session_id: str, *, limit: int = MAX_MESSAGES_PER_SESSION) -> list[dict]:
    """SQLite-authoritative message list for LLM prompts. Never falls back to JSONL."""
    limit = max(1, min(int(limit), MAX_MESSAGES_PER_SESSION))
    turns = turns_for_session(session_id)
    msgs: list[dict] = []
    for turn in turns:
        msgs.append({"role": "user", "content": turn["user_content"], "timestamp": turn["created_at"],
                     "meta": {"turn_id": turn["turn_id"], "revision": turn["revision"]}})
        asst_meta = {"turn_id": turn["turn_id"], "revision": turn["revision"]}
        if turn.get("meta"):
            asst_meta.update(turn["meta"])
        msgs.append({"role": "assistant", "content": turn["assistant_content"], "timestamp": turn["created_at"],
                     "meta": asst_meta})
    if len(msgs) > limit:
        msgs = msgs[-limit:]
    return msgs


def sqlite_available() -> bool:
    try:
        conn = _turns_conn()
        try:
            conn.execute("SELECT 1 FROM conversation_turns LIMIT 1")
            return True
        finally:
            conn.close()
    except Exception:
        return False


def reconcile_export(session_id: str) -> dict:
    """Crash-safe rewrite of the JSONL export from authoritative SQLite turns."""
    if not _SESSION_ID_RE.match(session_id or ""):
        raise ValueError("invalid session id")
    turns = turns_for_session(session_id)
    p = _path(session_id)
    tmp = p.with_suffix(".jsonl.reconcile")
    lines = []
    head = 0
    for turn in turns:
        head = max(head, int(turn["revision"]))
        lines.append(
            _pair_payload(
                turn_id=turn["turn_id"],
                revision=int(turn["revision"]),
                user_content=turn["user_content"],
                assistant_content=turn["assistant_content"],
                meta=turn.get("meta") or {},
                ts=float(turn["created_at"] or time.time()),
            )
        )
    data = b"".join(lines)
    fd = os.open(tmp, os.O_WRONLY | os.O_CREAT | os.O_TRUNC | getattr(os, "O_NOFOLLOW", 0), 0o600)
    try:
        if data:
            os.write(fd, data)
    finally:
        os.close(fd)
    os.replace(tmp, p)
    conn = _turns_conn()
    try:
        conn.execute("BEGIN IMMEDIATE")
        conn.execute(
            "INSERT INTO session_export_state (session_id, head_revision, export_revision, migrated_legacy, updated_at) "
            "VALUES (?,?,?,?,?) "
            "ON CONFLICT(session_id) DO UPDATE SET "
            "head_revision=excluded.head_revision, export_revision=excluded.export_revision, updated_at=excluded.updated_at",
            (session_id, head, head, 0, time.time()),
        )
        conn.execute("COMMIT")
    except Exception:
        try:
            conn.execute("ROLLBACK")
        except Exception:
            pass
        raise
    finally:
        conn.close()
    return {"session_id": session_id, "exported_turns": len(turns), "head_revision": head}


def migrate_legacy_jsonl(session_id: str, *, user_id: str = "legacy") -> dict:
    """Explicit one-shot import of legacy JSONL pairs into SQLite. Never implicit.

    Pairs consecutive user/assistant lines into turns. Incomplete trailing user
    lines are skipped. Idempotent when ``migrated_legacy`` is already set and
    SQLite already has turns.
    """
    if not _SESSION_ID_RE.match(session_id or ""):
        raise ValueError("invalid session id")
    conn = _turns_conn()
    try:
        conn.execute("BEGIN IMMEDIATE")
        state = conn.execute(
            "SELECT migrated_legacy, head_revision FROM session_export_state WHERE session_id=?",
            (session_id,),
        ).fetchone()
        head = _head_revision(conn, session_id)
        if state and int(state["migrated_legacy"]) == 1 and head > 0:
            conn.execute("COMMIT")
            return {"session_id": session_id, "imported": 0, "reason": "already_migrated", "head_revision": head}

        msgs = list(_iter_file(_path(session_id)))
        imported = 0
        i = 0
        while i + 1 < len(msgs):
            a, b = msgs[i], msgs[i + 1]
            if a.get("role") == "user" and b.get("role") == "assistant":
                next_rev = _head_revision(conn, session_id) + 1
                turn_id = f"legacy-{session_id}-{next_rev}"
                exists = conn.execute(
                    "SELECT 1 FROM conversation_turns WHERE turn_id=?", (turn_id,)
                ).fetchone()
                if not exists:
                    conn.execute(
                        "INSERT INTO conversation_turns "
                        "(turn_id, session_id, user_id, revision, user_content, assistant_content, meta_json, created_at) "
                        "VALUES (?,?,?,?,?,?,?,?)",
                        (
                            turn_id,
                            session_id,
                            user_id,
                            next_rev,
                            (a.get("content") or "")[:MAX_MESSAGE_CHARS],
                            (b.get("content") or "")[:MAX_MESSAGE_CHARS],
                            json.dumps(b.get("meta") or {}, default=str),
                            float(b.get("ts") or a.get("ts") or time.time()),
                        ),
                    )
                    imported += 1
                i += 2
            else:
                i += 1
        head = _head_revision(conn, session_id)
        conn.execute(
            "INSERT INTO session_export_state (session_id, head_revision, export_revision, migrated_legacy, updated_at) "
            "VALUES (?,?,?,?,?) "
            "ON CONFLICT(session_id) DO UPDATE SET "
            "head_revision=excluded.head_revision, migrated_legacy=1, updated_at=excluded.updated_at",
            (session_id, head, 0, 1, time.time()),
        )
        conn.execute("COMMIT")
    except Exception:
        try:
            conn.execute("ROLLBACK")
        except Exception:
            pass
        raise
    finally:
        conn.close()
    reconcile_export(session_id)
    return {"session_id": session_id, "imported": imported, "head_revision": head}


def _iter_file(p: Path) -> Iterator[dict]:
    try:
        with open(p, "rb") as fh:
            for i, raw in enumerate(fh):
                if i >= MAX_MESSAGES_PER_SESSION:
                    return
                try:
                    rec = json.loads(raw)
                except ValueError:
                    continue                         # a torn/garbled line never breaks the rest of the transcript
                if isinstance(rec, dict) and rec.get("role") in ("user", "assistant", "system") and isinstance(rec.get("content"), str):
                    yield rec
    except FileNotFoundError:
        return


def transcript(session_id: str, *, limit: int = 200, offset: int = 0, source: str = "auto") -> dict:
    """Paged transcript view.

    ``source``:
      - ``committed``: SQLite only (inference / authoritative reads).
      - ``auto``: if the session has any SQLite turns, SQLite only (JSONL
        phantoms ignored); if SQLite is unavailable, return empty (no JSONL
        fallback); if SQLite is empty, legacy JSONL is used for API chat
        history that never went through ``commit_turn``.
    """
    limit = max(1, min(int(limit), 1000))
    offset = max(0, int(offset))
    msgs: list[dict] = []

    if source in ("committed", "auto"):
        try:
            turns = turns_for_session(session_id, raise_on_unavailable=True)
        except TurnsUnavailable:
            # SQLite unavailable — refuse untrusted JSONL fallback.
            return {
                "session_id": session_id,
                "total": 0,
                "offset": offset,
                "limit": limit,
                "messages": [],
                "source": "sqlite_unavailable",
            }
        if turns:
            for turn in turns:
                msgs.append(
                    {
                        "role": "user",
                        "content": turn["user_content"],
                        "ts": turn["created_at"],
                        "meta": {"turn_id": turn["turn_id"], "revision": turn["revision"]},
                    }
                )
                asst_meta = {"turn_id": turn["turn_id"], "revision": turn["revision"]}
                if turn.get("meta"):
                    asst_meta.update(turn["meta"])
                msgs.append(
                    {
                        "role": "assistant",
                        "content": turn["assistant_content"],
                        "ts": turn["created_at"],
                        "meta": asst_meta,
                    }
                )
            src_label = "sqlite"
        elif source == "committed":
            src_label = "sqlite"
        else:
            # SQLite empty: legacy API append path only.
            msgs = list(_iter_file(_path(session_id)))
            src_label = "legacy_jsonl"
    else:
        raise ValueError("invalid transcript source")

    page = msgs[offset: offset + limit]
    return {
        "session_id": session_id,
        "total": len(msgs),
        "offset": offset,
        "limit": limit,
        "source": src_label,
        "messages": [
            {
                "index": offset + i,
                "role": m["role"],
                "content": m["content"],
                "timestamp": m.get("ts"),
                **({"meta": m["meta"]} if m.get("meta") else {}),
            }
            for i, m in enumerate(page)
        ],
    }


def last_activity(session_id: str) -> float | None:
    turns = turns_for_session(session_id)
    if turns:
        return float(turns[-1]["created_at"])
    try:
        return _path(session_id).stat().st_mtime
    except (FileNotFoundError, ValueError):
        return None


def delete(session_id: str) -> bool:
    ok = False
    try:
        _path(session_id).unlink()
        ok = True
    except FileNotFoundError:
        ok = True
    except ValueError:
        return False
    try:
        conn = _turns_conn()
        try:
            conn.execute("BEGIN IMMEDIATE")
            conn.execute("DELETE FROM conversation_turns WHERE session_id=?", (session_id,))
            conn.execute("DELETE FROM session_export_state WHERE session_id=?", (session_id,))
            conn.execute("COMMIT")
        except Exception:
            try:
                conn.execute("ROLLBACK")
            except Exception:
                pass
        finally:
            conn.close()
    except Exception:
        pass
    return ok


def _snippet(text: str, idx: int, qlen: int) -> str:
    a, b = max(0, idx - _SNIPPET_RADIUS), min(len(text), idx + qlen + _SNIPPET_RADIUS)
    s = text[a:b].replace("\n", " ")
    return ("…" if a else "") + s + ("…" if b < len(text) else "")


def search(session_ids: list[str], titles: dict[str, str], query: str, *, limit: int = 20, scan_cap: int = 500) -> dict:
    """Plain, case-insensitive substring search over the GIVEN sessions only (the caller passes the user's own ids). No regex: query text is never compiled."""
    q = query.casefold()
    scanned, results = 0, []
    for sid in session_ids[:scan_cap]:
        if not _SESSION_ID_RE.match(sid):
            continue
        scanned += 1
        title = titles.get(sid, "")
        matches, first = 0, None
        if q in title.casefold():
            matches += 1
            first = ("title", title, title.casefold().index(q))
        body = transcript(sid, limit=MAX_MESSAGES_PER_SESSION, offset=0)
        for m in body["messages"]:
            c = m["content"].casefold()
            n = c.count(q)
            if n:
                matches += n
                if first is None:
                    first = (m["role"], m["content"], c.index(q))
        if matches:
            where, text, idx = first
            results.append({"session_id": sid, "title": title, "matches": matches, "snippet": _snippet(text, idx, len(q)), "in": where,
                            "updated_at": last_activity(sid)})
    results.sort(key=lambda r: (r["updated_at"] or 0), reverse=True)
    return {"query": query, "results": results[:limit], "truncated": len(results) > limit or len(session_ids) > scan_cap, "scanned": scanned}


def export_markdown(session_id: str, title: str) -> str:
    lines = [f"# {title}", f"\n_Exported from ORNEUR — {time.strftime('%Y-%m-%d %H:%M UTC', time.gmtime())}_\n", "---\n"]
    body = transcript(session_id, limit=MAX_MESSAGES_PER_SESSION, offset=0)
    for m in body["messages"]:
        who = {"user": "**You**", "assistant": "**ORNEUR**"}.get(m["role"], f"**{m['role']}**")
        lines.append(f"{who}\n\n{m['content']}\n")
        meta = m.get("meta") or {}
        ident = meta.get("model_identity") or {}
        if m["role"] == "assistant" and ident.get("served_model"):
            note = f"_Answered by {ident['served_model']}" + (f" (requested {ident.get('requested_tier')})" if ident.get("substituted") else "") + "_"
            lines.append(note + "\n")
        refs = meta.get("sources") or []
        if refs:
            lines.append("Sources: " + "; ".join(f"[{s.get('ref')}] {s.get('filename') or s.get('url') or ''}" for s in refs) + "\n")
        lines.append("---\n")
    return "\n".join(lines)


def export_json(session_id: str, title: str) -> dict:
    t = transcript(session_id, limit=MAX_MESSAGES_PER_SESSION)
    return {"schema": "orneur.conversation/1", "session_id": session_id, "title": title,
            "exported_at": time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime()), "total": t["total"], "messages": t["messages"]}
