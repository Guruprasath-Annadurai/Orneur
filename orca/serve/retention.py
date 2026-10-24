"""Per-user conversation retention (Workstream B).

A user chooses `retention_days` (0 = keep until I delete, else 1..3650). `purge_expired_conversations()` deletes every session of every user whose last activity
(transcript mtime; session creation time if there is no transcript) is older than that user's cutoff, through the SAME cascade account deletion uses (episodic memory,
vector memory, documents, knowledge graph, Redis state, semantic facts, memory-continuum records, transcript), then releases the ownership claim and the title.
It is conservative: a user with retention 0 is never touched; an error on one session never aborts the rest.

Run it on a schedule with `python -m orca.serve.retention` (once) -- the API process also runs it every 6 hours.
"""
from __future__ import annotations

import time
from datetime import datetime, timezone

_DAY = 86_400.0


def _created_ts(iso: str) -> float:
    try:
        dt = datetime.fromisoformat(iso)
        return (dt if dt.tzinfo else dt.replace(tzinfo=timezone.utc)).timestamp()
    except (TypeError, ValueError):
        return time.time()          # unparseable => treat as brand new (never delete on a guess)


def purge_expired_conversations(now: float | None = None) -> dict:
    from orca.auth.store import get_user_sessions_with_created, release_session, users_with_retention
    from orca.serve import conversations
    from orca.serve.account_delete import _delete_session_data, _remove_session_title

    now = time.time() if now is None else now
    from orca.serve import temporary_chat

    temporary_result = temporary_chat.expire_due(now=now)
    deleted, errors, scanned = [], 0, 0
    for user_id, days in users_with_retention():
        cutoff = now - days * _DAY
        for sid, created in get_user_sessions_with_created(user_id):
            scanned += 1
            last = conversations.last_activity(sid) or _created_ts(created)
            if last >= cutoff:
                continue
            try:
                _delete_session_data(sid)
                _remove_session_title(sid)
                import sys

                live = getattr(sys.modules.get("orca.serve.api"), "_sessions", None)
                if isinstance(live, dict):
                    live.pop(sid, None)
                release_session(sid, user_id)
                deleted.append(sid)
            except Exception:
                errors += 1
    return {
        "scanned": scanned,
        "deleted": len(deleted),
        "errors": errors,
        "deleted_session_ids": deleted,
        "temporary_expired": temporary_result["expired"],
        "temporary_failed": temporary_result["failed"],
    }


if __name__ == "__main__":
    import json

    r = purge_expired_conversations()
    print(json.dumps({k: v for k, v in r.items() if k != "deleted_session_ids"}))
