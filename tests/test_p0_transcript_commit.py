"""P0-3 follow-up: authoritative transcript commit under lease expiry (updated API)."""

from __future__ import annotations

from tests._redis_guard import safe_flush

import time
import uuid

import pytest

REDIS_URL = "redis://localhost:6379/15"


def _reachable() -> bool:
    try:
        import redis

        redis.from_url(REDIS_URL, socket_connect_timeout=2).ping()
        return True
    except Exception:
        return False


_needs_redis = pytest.mark.skipif(not _reachable(), reason="needs real Redis")


def _enable_redis(monkeypatch):
    import redis as redis_lib

    from orca.serve import session_store as store

    safe_flush(redis_lib.from_url(REDIS_URL))
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
    a = conversations.acquire_authority(sid, "u", "old-fence", ttl_s=0.05)
    assert a is not None
    time.sleep(0.08)
    assert store.acquire_session_lease(sid, "new-fence", ttl_ms=5_000)
    b = conversations.acquire_authority(sid, "u", "new-fence", ttl_s=30)
    assert b is not None and b.epoch > a.epoch

    with pytest.raises(InferenceError) as exc:
        _persist(
            user_id="u",
            session_id=sid,
            message="stale-user",
            text="stale-asst",
            identity={"served_model": "fixture-llama"},
            model="fixture-llama",
            fence_token="old-fence",
            epoch=a.epoch,
        )
    assert exc.value.code == "stale_worker"
    assert conversations.transcript(sid)["total"] == 0

    safe = _persist(
        user_id="u",
        session_id=sid,
        message="fresh-user",
        text="fresh-asst",
        identity={"served_model": "fixture-llama"},
        model="fixture-llama",
        fence_token="new-fence",
        epoch=b.epoch,
    )
    assert safe == "fresh-asst"
    body = conversations.transcript(sid)
    assert [m["content"] for m in body["messages"]] == ["fresh-user", "fresh-asst"]


@_needs_redis
def test_complete_turn_is_atomic_user_assistant_pair(isolated_home, ollama_fixture, monkeypatch):
    from orca.auth.db import init_db
    from orca.auth.store import User
    from orca.serve import conversations
    from orca.serve.inference import complete

    _enable_redis(monkeypatch)
    init_db()
    sid = "pair-" + uuid.uuid4().hex[:10]
    user = User(id="u-pair", email="pair@example.com", name="pair", tier="free", verified=True)
    out = complete(
        user=user,
        message="hello",
        model="fixture-llama",
        host=ollama_fixture,
        session_id=sid,
        synthetic_provider=True,
    )
    assert out["text"]
    body = conversations.transcript(sid)
    roles = [m["role"] for m in body["messages"]]
    assert roles == ["user", "assistant"]
    assert body["messages"][0]["content"] == "hello"
