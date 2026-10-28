"""P0-3: authoritative transcript commit under lease expiry."""

from __future__ import annotations

import os
import time
import uuid

import pytest

REDIS_URL = "redis://localhost:6379/14"


def _reachable() -> bool:
    try:
        import redis

        redis.from_url(REDIS_URL, socket_connect_timeout=2).ping()
        return True
    except Exception:
        return False


_needs_redis = pytest.mark.skipif(not _reachable(), reason="needs real Redis at localhost:6379/14")


def _enable_redis(monkeypatch):
    """Point session_store at a real Redis DB without reloading inference."""
    import redis as redis_lib

    from orca.serve import session_store as store

    redis_lib.from_url(REDIS_URL).flushdb()
    monkeypatch.setenv("ORNEUR_REDIS_URL", REDIS_URL)
    monkeypatch.setattr(store, "REDIS_URL", REDIS_URL)
    monkeypatch.setattr(store, "_redis_client", None)
    return store


@_needs_redis
def test_stale_worker_cannot_commit_after_lease_expiry(isolated_home, monkeypatch):
    from orca.serve import conversations
    from orca.serve.inference import InferenceError, _persist

    store = _enable_redis(monkeypatch)
    sid = "lease-" + uuid.uuid4().hex[:10]
    assert store.acquire_session_lease(sid, "old-fence", ttl_ms=40)
    time.sleep(0.06)
    assert store.acquire_session_lease(sid, "new-fence", ttl_ms=5_000)

    with pytest.raises(InferenceError) as exc:
        _persist(
            user_id="u-stale",
            session_id=sid,
            message="stale-user",
            text="stale-asst",
            identity={"served_model": "fixture-llama"},
            model="fixture-llama",
            fence_token="old-fence",
        )
    assert exc.value.code == "stale_worker"
    assert conversations.transcript(sid)["total"] == 0
    assert conversations.turns_for_session(sid) == []

    safe = _persist(
        user_id="u-new",
        session_id=sid,
        message="fresh-user",
        text="fresh-asst",
        identity={"served_model": "fixture-llama"},
        model="fixture-llama",
        fence_token="new-fence",
    )
    assert safe == "fresh-asst"
    body = conversations.transcript(sid)
    assert body["total"] == 2
    assert [m["content"] for m in body["messages"]] == ["fresh-user", "fresh-asst"]
    turns = conversations.turns_for_session(sid)
    assert len(turns) == 1 and turns[0]["user_content"] == "fresh-user"
    state, rev = store.load_session_state_with_revision(sid)
    assert state is not None and rev is not None


@_needs_redis
def test_complete_turn_is_atomic_user_assistant_pair(isolated_home, ollama_fixture, monkeypatch):
    from orca.auth.db import init_db
    from orca.auth.store import User
    from orca.serve import conversations
    from orca.serve.inference import complete

    _enable_redis(monkeypatch)
    init_db()
    sid = "pair-" + uuid.uuid4().hex[:10]
    user = User(id="pair-u", email="pair@example.com", name="p", tier="free", verified=True)
    out = complete(
        user=user,
        message="hello pair",
        model="fixture-llama",
        host=ollama_fixture,
        session_id=sid,
        synthetic_provider=True,
    )
    assert out["text"]
    body = conversations.transcript(sid)
    assert body["total"] == 2
    assert body["messages"][0]["role"] == "user"
    assert body["messages"][1]["role"] == "assistant"
    assert len(conversations.turns_for_session(sid)) == 1


def test_commit_turn_idempotent_and_no_split_pair(isolated_home):
    from orca.serve import conversations

    sid = "idem-" + uuid.uuid4().hex[:10]
    first = conversations.commit_turn(
        sid, "u", "a", user_id="u1", turn_id="t1", revision=1, meta={"k": 1}
    )
    assert first.ok
    second = conversations.commit_turn(
        sid, "u", "a", user_id="u1", turn_id="t1", revision=1, meta={"k": 1}
    )
    assert second.ok and second.reason == "idempotent"
    conflict = conversations.commit_turn(
        sid, "x", "y", user_id="u1", turn_id="t2", revision=1, meta={}
    )
    assert conflict.ok is False and conflict.reason == "revision_conflict"
    assert conversations.transcript(sid)["total"] == 2
