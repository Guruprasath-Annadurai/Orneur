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


# Stored value is '<revision>|<json>'; anything else (e.g. legacy bare
# JSON) fails validation. Revision-stamped payloads (Antigravity FAILED_QUALIFICATION, 2026-10-28).
# A cached history payload is only ever trusted if the revision it was
# stamped with equals the session's CURRENT shared revision. Every
# decision is made inside one Lua script so it is atomic against
# concurrent edits on other workers:
#   * save: compare-and-set -- writes only if the writer's known revision
#     still equals the current one (stale writers are refused).
#   * load: returns the payload only if its stamp equals the current
#     revision; legacy/unstamped/mismatched payloads are never trusted.
#   * bump: INCR the revision and DELETE the payload in one step.
_SAVE_LUA = """
if ARGV[5] ~= '' then
  local owner = redis.call('GET', KEYS[3])
  if (not owner) or owner ~= ARGV[5] then return -2 end
end
local cur = redis.call('GET', KEYS[2]) or '0'
local expected = ARGV[1]
if expected == '' then expected = cur end
if cur ~= expected then return -1 end
redis.call('SET', KEYS[1], cur .. '|' .. ARGV[2], 'EX', ARGV[3])
redis.call('EXPIRE', KEYS[2], ARGV[4])
return 1
"""

_LEASE_ACQUIRE_LUA = """
if redis.call('SET', KEYS[1], ARGV[1], 'PX', ARGV[2], 'NX') then
  return 1
end
if redis.call('GET', KEYS[1]) == ARGV[1] then
  redis.call('PEXPIRE', KEYS[1], ARGV[2])
  return 1
end
return 0
"""

_LEASE_RELEASE_LUA = """
if redis.call('GET', KEYS[1]) == ARGV[1] then
  redis.call('DEL', KEYS[1])
  return 1
end
return 0
"""

# Claim exclusive authority to commit one turn: lease must match the caller's
# fence, expected revision must still be current, then INCR. A stale worker
# whose lease expired cannot claim; the new revision is the commit ticket.
_CLAIM_TURN_LUA = """
local owner = redis.call('GET', KEYS[2])
if (not owner) or owner ~= ARGV[1] then return -2 end
local cur = redis.call('GET', KEYS[1]) or '0'
local expected = ARGV[2]
if expected ~= '' and cur ~= expected then return -1 end
if cur == '0' then
  local t = redis.call('TIME')
  redis.call('SET', KEYS[1], t[1] .. string.format('%06d', tonumber(t[2])))
end
local rev = redis.call('INCR', KEYS[1])
redis.call('EXPIRE', KEYS[1], ARGV[3])
redis.call('DEL', KEYS[3])
return rev
"""

# Revisions are compared as strings: they are ~1e15 and Lua's number->string
# conversion would round them.
_LOAD_LUA = """
local cur = redis.call('GET', KEYS[2]) or '0'
local raw = redis.call('GET', KEYS[1])
if not raw then return {cur, false} end
local sep = string.find(raw, '|', 1, true)
if not sep or string.sub(raw, 1, sep - 1) ~= cur then return {cur, false} end
return {cur, string.sub(raw, sep + 1)}
"""

_BUMP_LUA = """
local prev = redis.call('GET', KEYS[2]) or '0'
if prev == '0' then
  -- (Re)initialise from the server clock in microseconds, so a counter
  -- that vanished (Redis restart without persistence, key expiry) can
  -- never re-issue a revision a worker may still hold from before.
  local t = redis.call('TIME')
  redis.call('SET', KEYS[2], t[1] .. string.format('%06d', tonumber(t[2])))
end
local rev = redis.call('INCR', KEYS[2])
redis.call('EXPIRE', KEYS[2], ARGV[1])
redis.call('DEL', KEYS[1])
return {rev, prev}
"""

# The revision counter outlives the payload so a payload can never
# outlive the counter that fences it (see touch_session()).
_REV_TTL_SECONDS = SESSION_TTL_SECONDS * 2


def save_session_state(session_id: str, model_variant: str, history: list[dict],
                       expected_revision: Optional[int] = None,
                       fence_token: Optional[str] = None) -> bool:
    """Persist just enough to reconstruct this session on any instance.

    Never raises -- Redis being down must never break the chat request.

    The write is a revision-fenced compare-and-set: `expected_revision` is
    the shared revision the caller's history is known to reflect. If the
    shared revision has moved on (an edit committed elsewhere), the write
    is REFUSED and False is returned, so a stale writer can never
    re-publish pre-edit history. `None` means "stamp with whatever the
    current revision is" and is only for callers that have no cached
    revision notion (tests/legacy); the API always passes its own.

    Returns True when there is nothing to worry about -- the write
    succeeded, OR Redis is not configured (no shared cache, so no other
    instance can read a stale entry). Returns False when Redis is
    configured but the write was refused as stale or could not be
    confirmed.
    """
    if not enabled():
        return True
    try:
        payload = json.dumps({
            "model_variant": model_variant,
            "history": history,
            "saved_at": time.time(),
        })
        res = _client().eval(
            _SAVE_LUA, 3, _key(session_id), _rev_key(session_id), _lease_key(session_id),
            "" if expected_revision is None else int(expected_revision),
            payload, SESSION_TTL_SECONDS, _REV_TTL_SECONDS,
            fence_token or "",
        )
        return int(res) == 1
    except Exception:
        return False  # Redis being down must never break the chat request


def load_session_state(session_id: str) -> Optional[dict]:
    """Returns {'model_variant', 'history', 'saved_at', 'revision'} or None.

    None also covers a payload whose revision stamp does not equal the
    current shared revision (stale, legacy/unstamped, or the counter
    expired): the caller must rebuild from the authoritative transcript."""
    state, _rev = load_session_state_with_revision(session_id)
    return state


def load_session_state_with_revision(session_id: str) -> tuple[Optional[dict], Optional[int]]:
    """(validated payload or None, current revision or None if unknown).
    Both come from one atomic read, so the revision returned is exactly
    the one the payload was validated against."""
    if not enabled():
        return None, None
    try:
        rev, raw = _client().eval(_LOAD_LUA, 2, _key(session_id), _rev_key(session_id))
        rev = int(rev)
        if not raw:
            return None, rev
        state = json.loads(raw)
        state["revision"] = rev
        return state, rev
    except Exception:
        return None, None


def touch_session(session_id: str) -> None:
    """Refresh TTL without rewriting the payload — cheap keepalive per request."""
    if not enabled():
        return
    try:
        _client().expire(_key(session_id), SESSION_TTL_SECONDS)
        _client().expire(_rev_key(session_id), _REV_TTL_SECONDS)
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
        _client().delete(_key(session_id), _rev_key(session_id), _lease_key(session_id))      # L02-01f: history, revision and lease keys of the session
        return True
    except Exception:
        return False


def _rev_key(session_id: str) -> str:
    return f"orca:session:{session_id}:rev"


def bump_revision(session_id: str) -> Optional[int]:
    """New revision only; see bump_revision_with_previous()."""
    res = bump_revision_with_previous(session_id)
    return res[0] if res else None


def bump_revision_with_previous(session_id: str) -> Optional[tuple[int, int]]:
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
        # Atomic: advance the revision AND drop the (now stale) payload.
        new, prev = _client().eval(_BUMP_LUA, 2, _key(session_id), _rev_key(session_id), _REV_TTL_SECONDS)
        return int(new), int(prev)
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


def _lease_key(session_id: str) -> str:
    return f"orca:session:{session_id}:lease"


def acquire_session_lease(session_id: str, fence_token: str, ttl_ms: int = 30_000) -> bool:
    """Exclusive turn lease. Expired leases can be taken by a new worker; the
    previous fence can no longer CAS-save or release."""
    if not enabled():
        return True
    if not fence_token or ttl_ms <= 0:
        return False
    try:
        return int(_client().eval(_LEASE_ACQUIRE_LUA, 1, _lease_key(session_id), fence_token, int(ttl_ms))) == 1
    except Exception:
        return False


def lease_acquire_state(session_id: str, fence_token: str, ttl_ms: int = 30_000) -> str:
    """Like ``acquire_session_lease`` but tells "someone else holds it" apart from "Redis cannot be reached".

    ``acquired`` | ``held`` (another live turn owns the lease) | ``unavailable`` (Redis error). Redis is advisory coordination only -- the
    durable SQLite authority is the fence -- so callers may proceed on ``unavailable`` but must refuse on ``held``. Re-acquiring with the
    same token renews the TTL.
    """
    if not enabled():
        return "acquired"
    if not fence_token or ttl_ms <= 0:
        return "held"
    try:
        won = int(_client().eval(_LEASE_ACQUIRE_LUA, 1, _lease_key(session_id), fence_token, int(ttl_ms))) == 1
    except Exception:
        return "unavailable"
    return "acquired" if won else "held"


def lease_state(session_id: str, fence_token: str) -> Optional[bool]:
    """True: lease is ours. False: someone else (or nobody) holds it. None: Redis cannot be reached."""
    if not enabled():
        return True
    try:
        return _client().get(_lease_key(session_id)) == fence_token
    except Exception:
        return None


def release_session_lease(session_id: str, fence_token: str) -> bool:
    if not enabled():
        return True
    try:
        return int(_client().eval(_LEASE_RELEASE_LUA, 1, _lease_key(session_id), fence_token)) == 1
    except Exception:
        return False


def lease_held(session_id: str, fence_token: str) -> bool:
    if not enabled():
        return True
    try:
        return _client().get(_lease_key(session_id)) == fence_token
    except Exception:
        return False


def claim_turn_commit(
    session_id: str,
    fence_token: str,
    expected_revision: Optional[int] = None,
) -> Optional[int]:
    """Claim durable authority to commit one user/assistant turn.

    Returns the new conversation revision on success, or None when the
    caller's fence is stale / revision moved / Redis refused the claim.
    When Redis is disabled, the next revision is taken from the
    authoritative turns table (process lock serializes callers).
    """
    if not enabled():
        from orca.serve import conversations

        turns = conversations.turns_for_session(session_id)
        base = max((int(t["revision"]) for t in turns), default=0)
        if expected_revision is not None and int(expected_revision) < base:
            return None
        return base + 1
    if not fence_token:
        return None
    try:
        res = _client().eval(
            _CLAIM_TURN_LUA,
            3,
            _rev_key(session_id),
            _lease_key(session_id),
            _key(session_id),
            fence_token,
            "" if expected_revision is None else int(expected_revision),
            _REV_TTL_SECONDS,
        )
        rev = int(res)
        return rev if rev > 0 else None
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
