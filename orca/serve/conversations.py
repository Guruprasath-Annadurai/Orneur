"""Durable conversation history for signed-in users (Workstream B).

Until now a conversation survived a server restart only if the client had called /api/session/save, and even then only the last 20 exchanges (the
sliding window of `ShortTermMemory`). This module keeps an append-only, per-session transcript on disk:

  <MEMORY_DIR>/conversations/<session_id>.jsonl   (dir 0700, files 0600, one JSON object per message, written with a single O_APPEND write)

It is the source for the transcript, search and export endpoints. Ownership is NEVER decided here: every caller must have passed the session-ownership
check (`check_session_access`) first. File names are the full, validated session id (`[A-Za-z0-9_-]{1,64}`), never a prefix, so two sessions can not share a
file. Anonymous sessions are not persisted (nobody could retrieve or delete them).
"""
from __future__ import annotations

import json
import os
import re
import time
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


def _shown(session_id: str, rec: dict) -> tuple[str, dict]:
    """Active version text when one exists. The JSONL line is not rewritten."""
    meta = rec.get("meta") if isinstance(rec.get("meta"), dict) else {}
    message_id = meta.get("message_id")
    extra: dict = {}
    if isinstance(message_id, str):
        extra["message_id"] = message_id
        try:
            from orca.serve import message_versions

            view = message_versions.active_view(session_id, message_id)
        except Exception:
            view = None
        if view is not None:
            extra["version_id"] = view["version_id"]
            extra["version_count"] = view["version_count"]
            extra["edited"] = view["edited"]
            return view["content"], extra
    return rec["content"], extra


def find_message(session_id: str, message_id: str) -> dict | None:
    for rec in _iter_file(_path(session_id)):
        meta = rec.get("meta") if isinstance(rec.get("meta"), dict) else {}
        if meta.get("message_id") == message_id:
            return rec
    return None


def preceding_user_message(session_id: str, message_id: str) -> dict | None:
    previous = None
    for rec in _iter_file(_path(session_id)):
        if rec.get("role") == "user":
            previous = rec
        meta = rec.get("meta") if isinstance(rec.get("meta"), dict) else {}
        if meta.get("message_id") == message_id:
            return previous if rec.get("role") == "assistant" else None
    return None


def transcript(session_id: str, *, limit: int = 200, offset: int = 0) -> dict:
    limit = max(1, min(int(limit), 1000))
    offset = max(0, int(offset))
    msgs = list(_iter_file(_path(session_id)))
    page = msgs[offset: offset + limit]
    rendered = []
    for i, message in enumerate(page):
        content, extra = _shown(session_id, message)
        item = {"index": offset + i, "role": message["role"], "content": content, "timestamp": message.get("ts"), **extra}
        if message.get("meta"):
            item["meta"] = message["meta"]
        rendered.append(item)
    return {
        "session_id": session_id,
        "total": len(msgs),
        "offset": offset,
        "limit": limit,
        "messages": rendered,
    }


def last_activity(session_id: str) -> float | None:
    try:
        return _path(session_id).stat().st_mtime
    except (FileNotFoundError, ValueError):
        return None


def delete(session_id: str) -> bool:
    try:
        _path(session_id).unlink()
        return True
    except (FileNotFoundError, ValueError):
        return False


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
            content, _extra = _shown(sid, m)
            c = content.casefold()
            n = c.count(q)
            if n:
                matches += n
                if first is None:
                    first = (m["role"], content, c.index(q))
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
        content, _extra = _shown(session_id, m)
        lines.append(f"{who}\n\n{content}\n")
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
