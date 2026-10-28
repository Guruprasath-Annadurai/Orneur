"""Durable conversation history for signed-in users (Workstream B).

Until now a conversation survived a server restart only if the client had called /api/session/save, and even then only the last 20 exchanges (the
sliding window of `ShortTermMemory`). This module keeps an append-only, per-session transcript on disk:

  <MEMORY_DIR>/conversations/<session_id>.jsonl   (dir 0700, files 0600, one JSON object per message, written with a single O_APPEND write)

Committed inference turns are also recorded in a transactional SQLite store
(``turns.db``) that is the authoritative commit log for user/assistant pairs.
JSONL remains the compatible read/export format and is written as a derived
export of each successful commit (both messages in one ``O_APPEND`` write so a
crash cannot leave a split pair). Ownership is NEVER decided here: every caller
must have passed the session-ownership check (`check_session_access`) first.
File names are the full, validated session id (`[A-Za-z0-9_-]{1,64}`), never a
prefix, so two sessions can not share a file. Anonymous sessions are not
persisted (nobody could retrieve or delete them).
"""
from __future__ import annotations

import json
import os
import re
import sqlite3
import time
from dataclasses import dataclass
from pathlib import Path
from typing import Iterator

_SESSION_ID_RE = re.compile(r"^[A-Za-z0-9_-]{1,64}$")
MAX_MESSAGE_CHARS = 200_000
MAX_MESSAGES_PER_SESSION = 20_000
MAX_FILE_BYTES = 64 * 1024 * 1024
_SNIPPET_RADIUS = 70


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
    conn = sqlite3.connect(str(path), isolation_level="IMMEDIATE", check_same_thread=False, timeout=30)
    conn.row_factory = sqlite3.Row
    conn.execute("PRAGMA journal_mode=WAL")
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
    return conn


@dataclass(frozen=True)
class CommitResult:
    ok: bool
    reason: str = ""
    turn_id: str = ""
    revision: int = 0


def append(session_id: str, role: str, content: str, *, meta: dict | None = None, now: float | None = None) -> None:
    """Append one message. Never raises into the request path for I/O problems (history is best-effort), but refuses invalid ids loudly."""
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


def commit_turn(
    session_id: str,
    user_content: str,
    assistant_content: str,
    *,
    user_id: str,
    turn_id: str,
    revision: int,
    meta: dict | None = None,
    now: float | None = None,
) -> CommitResult:
    """Atomically commit one complete user/assistant turn.

    The SQLite turns table is the authoritative commit log. JSONL is updated
    in the same successful path as a derived export — both message lines are
    written in a single ``os.write`` so a crash cannot leave a split pair.
    Idempotent on ``turn_id`` / ``(session_id, revision)``.
    """
    if not _SESSION_ID_RE.match(session_id or ""):
        raise ValueError("invalid session id")
    if not user_id or not turn_id or int(revision) <= 0:
        return CommitResult(ok=False, reason="invalid_commit")
    ts = float(time.time() if now is None else now)
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
    payload = (
        json.dumps(user_rec, ensure_ascii=False, separators=(",", ":"))
        + "\n"
        + json.dumps(asst_rec, ensure_ascii=False, separators=(",", ":"))
        + "\n"
    ).encode("utf-8")
    conn = _turns_conn()
    try:
        with conn:
            existing = conn.execute(
                "SELECT turn_id FROM conversation_turns WHERE turn_id=? OR (session_id=? AND revision=?)",
                (turn_id, session_id, int(revision)),
            ).fetchone()
            if existing:
                if existing["turn_id"] == turn_id:
                    return CommitResult(ok=True, reason="idempotent", turn_id=turn_id, revision=int(revision))
                return CommitResult(ok=False, reason="revision_conflict", turn_id=turn_id, revision=int(revision))
            conn.execute(
                "INSERT INTO conversation_turns "
                "(turn_id, session_id, user_id, revision, user_content, assistant_content, meta_json, created_at) "
                "VALUES (?,?,?,?,?,?,?,?)",
                (
                    turn_id,
                    session_id,
                    user_id,
                    int(revision),
                    (user_content or "")[:MAX_MESSAGE_CHARS],
                    (assistant_content or "")[:MAX_MESSAGE_CHARS],
                    json.dumps(meta or {}, default=str),
                    ts,
                ),
            )
            p = _path(session_id)
            if p.exists() and p.stat().st_size + len(payload) > MAX_FILE_BYTES:
                raise OSError("transcript_cap")
            fd = os.open(p, os.O_WRONLY | os.O_APPEND | os.O_CREAT | getattr(os, "O_NOFOLLOW", 0), 0o600)
            try:
                os.write(fd, payload)
            finally:
                os.close(fd)
        return CommitResult(ok=True, turn_id=turn_id, revision=int(revision))
    except Exception:
        return CommitResult(ok=False, reason="persist_failed", turn_id=turn_id, revision=int(revision))
    finally:
        try:
            conn.close()
        except Exception:
            pass


def turns_for_session(session_id: str) -> list[dict]:
    """Authoritative committed turns for a session (empty if none / legacy-only)."""
    if not _SESSION_ID_RE.match(session_id or ""):
        return []
    try:
        conn = _turns_conn()
    except Exception:
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
    except Exception:
        return []
    finally:
        try:
            conn.close()
        except Exception:
            pass


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


def transcript(session_id: str, *, limit: int = 200, offset: int = 0) -> dict:
    limit = max(1, min(int(limit), 1000))
    offset = max(0, int(offset))
    msgs = list(_iter_file(_path(session_id)))
    page = msgs[offset: offset + limit]
    return {
        "session_id": session_id,
        "total": len(msgs),
        "offset": offset,
        "limit": limit,
        "messages": [{"index": offset + i, "role": m["role"], "content": m["content"], "timestamp": m.get("ts"), **({"meta": m["meta"]} if m.get("meta") else {})}
                     for i, m in enumerate(page)],
    }


def last_activity(session_id: str) -> float | None:
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
            with conn:
                conn.execute("DELETE FROM conversation_turns WHERE session_id=?", (session_id,))
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
        for m in _iter_file(_path(sid)):
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
    for m in _iter_file(_path(session_id)):
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
