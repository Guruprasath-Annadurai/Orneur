"""Assemble the messages the answering model is actually sent.

Canonical source is the owned session transcript (`orca.serve.conversations`),
with active message-version text overlaid. Temporary/deleted data is excluded.
The current user turn is appended once. Bounded by turn count and characters.
"""
from __future__ import annotations

MAX_MESSAGES = 48
MAX_CHARS = 24_000


def assemble_messages(*, session_id: str | None, current_user_text: str, user_id: str | None = None) -> list[dict]:
    current = (current_user_text or "").strip()
    if session_id:
        try:
            from orca.auth.store import check_session_access

            allowed = check_session_access(session_id, user_id)
        except Exception:
            allowed = False
        if not allowed:
            return _bound([{"role": "user", "content": current}] if current else [])
    history = _history(session_id)
    if history and history[-1].get("role") == "user" and (history[-1].get("content") or "").strip() == current:
        messages = history
    else:
        messages = [*history, {"role": "user", "content": current}] if current else list(history)
    return _bound(messages)


def _history(session_id: str | None) -> list[dict]:
    if not session_id:
        return []
    try:
        from orca.serve import temporary_chat

        if temporary_chat.is_hidden(session_id) and not temporary_chat.is_active(session_id):
            return []
    except Exception:
        pass
    try:
        from orca.serve import conversations
    except Exception:
        return []
    try:
        body = conversations.transcript(session_id, limit=1000, offset=0)
    except Exception:
        return []
    total = int(body.get("total") or 0)
    rows = list(body.get("messages") or [])
    if total > len(rows):
        offset = max(0, total - MAX_MESSAGES)
        rows = conversations.transcript(session_id, limit=MAX_MESSAGES, offset=offset).get("messages") or []
    cut = None
    out: list[dict] = []
    for i, row in enumerate(rows):
        role = row.get("role")
        content = row.get("content")
        if role not in ("user", "assistant", "system") or not isinstance(content, str):
            continue
        meta = row.get("meta") if isinstance(row.get("meta"), dict) else {}
        if meta.get("deleted") or row.get("deleted"):
            continue
        item = {"role": role, "content": content}
        out.append(item)
        if row.get("edited"):
            cut = len(out) - 1
    if cut is not None:
        out = out[: cut + 1]
    return out[-MAX_MESSAGES:]


def _bound(messages: list[dict]) -> list[dict]:
    trimmed = messages[-MAX_MESSAGES:]
    while trimmed and sum(len(m.get("content") or "") for m in trimmed) > MAX_CHARS:
        if len(trimmed) == 1:
            only = dict(trimmed[0])
            only["content"] = (only.get("content") or "")[-MAX_CHARS:]
            return [only]
        trimmed = trimmed[1:]
    return trimmed
