"""
Redis-backed session continuity — makes conversation history survive process
restarts and cross-instance load-balanced traffic.

Problem: the `_sessions` dict in orca/serve/api.py is process-local. Two
genuinely-volatile pieces of state live only in that process's memory:
  - AgentLoop._history (the turn-by-turn conversation the model sees)
  - which model_variant this session is pinned to

Everything else a session touches is already durable and shared, so it needs
no Redis involvement:
  - DocStore (RAG) — ChromaDB + JSON registry on disk
  - EpisodicMemory / LongTermMemory — JSON files / ChromaDB on disk
  - ExplainStore — deliberately ephemeral (documented in brain/explainability.py),
    low-stakes if lost, not worth the complexity of replicating

If a load-balanced request for an existing session lands on an API instance
that doesn't have it in local memory (process restart, different replica),
today's code silently starts a fresh AgentLoop with empty history — the user
just loses conversation context with no error. This module fixes that.

Opt-in via ORCA_REDIS_URL, same pattern as ORCA_DATABASE_URL for Postgres —
unset means exactly today's in-memory-only behavior (single instance, local
dev, zero setup required). Every function here is a no-op when disabled and
never raises when Redis is unreachable — losing session continuity is bad,
but crashing the chat request over it would be worse.
"""
from __future__ import annotations

import json
import os
import time
from typing import Optional

from orca.config import orneur_env

REDIS_URL = orneur_env("REDIS_URL") or None
SESSION_TTL_SECONDS = 7200  # matches the existing 2h idle-eviction window in api.py

_redis_client = None


def enabled() -> bool:
    return REDIS_URL is not None


def _client():
    global _redis_client
    if _redis_client is None:
        import redis
        _redis_client = redis.from_url(REDIS_URL, decode_responses=True)
    return _redis_client


def get_client():
    """Public accessor — other modules (e.g. ratelimit.py) share this same
    Redis connection rather than opening their own."""
    return _client()


def _key(session_id: str) -> str:
    return f"orca:session:{session_id}"


def save_session_state(session_id: str, model_variant: str, history: list[dict]) -> bool:
    """Persist just enough to reconstruct this session on any instance.

    Never raises -- Redis being down must never break the chat request --
    but CTO closeout review, issue 2 (2026-10-28): a caller that silently
    swallows this too loses the one signal that distinguishes "wrote the
    new value" from "left whatever was there before untouched" -- the
    difference between a cold cache and a STALE one holding a pre-edit
    value under its own still-live TTL, readable by any other instance.

    Returns True when there is genuinely nothing to worry about -- either
    the write succeeded, OR Redis is not configured at all (single-
    instance/local-dev, the default for this whole test suite and for
    any deployment that never set REDIS_URL): with no shared cache in
    play, there is no OTHER instance that could ever read a stale entry,
    so this is not a failure from a caller's point of view, just a no-op.
    Returns False ONLY when Redis IS configured but the write itself
    could not be confirmed (unreachable, timed out, or raised) -- the one
    case where a stale value genuinely could be left behind for another
    instance to load. A caller that only ever wanted "fire and forget"
    is unaffected by ignoring this either way; a caller that needs to
    react specifically to a genuine, actionable failure (post-commit-edit
    live sync) can now tell the two apart.
    """
    if not enabled():
        return True
    try:
        payload = json.dumps({
            "model_variant": model_variant,
            "history": history,
            "saved_at": time.time(),
        })
        _client().set(_key(session_id), payload, ex=SESSION_TTL_SECONDS)
        return True
    except Exception:
        return False  # Redis being down must never break the chat request


def load_session_state(session_id: str) -> Optional[dict]:
    """Returns {'model_variant': str, 'history': list[dict], 'saved_at': float} or None."""
    if not enabled():
        return None
    try:
        raw = _client().get(_key(session_id))
        if not raw:
            return None
        return json.loads(raw)
    except Exception:
        return None


def touch_session(session_id: str) -> None:
    """Refresh TTL without rewriting the payload — cheap keepalive per request."""
    if not enabled():
        return
    try:
        _client().expire(_key(session_id), SESSION_TTL_SECONDS)
    except Exception:
        pass


def delete_session(session_id: str) -> bool:
    """Evict a cached session's Redis entry. Never raises. Returns True
    only on a confirmed delete (including "there was nothing to delete" --
    a no-op success, since the end state the caller wants, no poisoned
    entry under this key, is achieved either way); False means the
    attempt itself failed (Redis unreachable), which a caller that needs
    to know "is this key definitely gone now" (e.g. before reporting a
    post-commit live-sync failure as resolved) should treat as
    unresolved, not as success."""
    if not enabled():
        return True  # nothing to delete, and nothing can read a stale value from a disabled store either
    try:
        _client().delete(_key(session_id))
        return True
    except Exception:
        return False


def _rev_key(session_id: str) -> str:
    return f"orca:session:{session_id}:rev"


def bump_revision(session_id: str) -> Optional[int]:
    """CTO follow-up, Priority 1 (2026-10-28): the one cross-worker
    fencing primitive this module provides. A committed message edit
    calls this UNCONDITIONALLY -- regardless of whether the worker that
    handled the edit happens to have this session cached locally -- so
    that every OTHER worker (including one with no local cache at all, or
    a stale cached copy from before the edit) has a single, atomic,
    monotonic signal it can compare against before trusting its own
    in-memory history for a new inference turn (see _get_session()'s
    revision check in orca/serve/api.py).

    Atomic (Redis INCR), so concurrent edits from different workers never
    collide or go backward. Returns the new revision, or None if Redis is
    disabled OR the increment could not be confirmed -- the latter case
    means NO fencing signal was published for this edit at all, which the
    caller must treat as "cross-worker consistency cannot be established
    right now" (a disclosed limitation of a Redis outage), never as
    silent success.
    """
    if not enabled():
        return None
    try:
        new_rev = _client().incr(_rev_key(session_id))
        _client().expire(_rev_key(session_id), SESSION_TTL_SECONDS)
        return int(new_rev)
    except Exception:
        return None


def get_revision(session_id: str) -> Optional[int]:
    """The current shared revision for this session, or None if Redis is
    disabled or unreachable -- indistinguishable, by design, from "no
    fencing signal is available right now," which a caller must treat as
    "cannot confirm freshness either way" (keep what you have; do not
    evict on a mere Redis hiccup), never as "definitely fresh." A session
    with no revision key yet (never edited, or the key expired) reads
    back as 0, which compares as "not behind" against any real revision
    a caller may be holding (every real bump starts at 1).
    """
    if not enabled():
        return None
    try:
        raw = _client().get(_rev_key(session_id))
        return int(raw) if raw is not None else 0
    except Exception:
        return None


def ping() -> bool:
    """Health check — used by /api/status to report Redis connectivity honestly."""
    if not enabled():
        return False
    try:
        return bool(_client().ping())
    except Exception:
        return False
