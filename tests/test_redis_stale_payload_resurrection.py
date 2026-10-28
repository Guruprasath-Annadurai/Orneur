"""Antigravity FAILED_QUALIFICATION reproduction: stale Redis session
payload resurrection (2026-10-28).

Worker A persists the original history to Redis; worker B commits an
edit with nothing cached locally (bumps the revision but leaves the old
payload); worker C builds a fresh session from that payload and adopts
the NEW revision despite pre-edit content. Fix: payloads are revision-
stamped, loads validate the stamp atomically, bumps atomically delete
the payload, and writes are compare-and-set against the writer's known
revision. Real Redis (db 15) required; skips otherwise.
"""
from __future__ import annotations

from tests._redis_guard import safe_flush

import time

import pytest

from tests.test_multiworker_edit_consistency import (  # noqa: F401
    _redis_reachable, _signup_and_chat, client, fake, two_workers,
)

pytestmark = pytest.mark.skipif(not _redis_reachable(), reason="needs real Redis at localhost:6379/15")


def _texts(sess):
    return [m.get("content") for m in sess.agent.get_history()]


def test_worker_c_never_adopts_stale_history_after_worker_b_edit(client, fake, two_workers):
    """The exact audited A -> B -> C sequence."""
    two_workers.as_worker_a()
    headers, sid, message_id, user_id = _signup_and_chat(client, fake)
    a = two_workers.api._sessions[sid]
    a.agent.load_history([{"role": "user", "content": "original message text"}])
    assert a.persist_to_redis() is True

    two_workers.as_worker_b()
    r = client.post(f"/api/session/{sid}/messages/{message_id}/edits",
                    json={"content": "EDITED on worker B"}, headers=headers)
    assert r.status_code == 200 and r.json()["live_sync"] is True

    two_workers.as_worker_c = lambda: setattr(two_workers.api, "_sessions", {})
    two_workers.as_worker_c()
    c = two_workers.api._get_session(sid, user_id=user_id)
    texts = _texts(c)
    assert "original message text" not in texts
    assert "EDITED on worker B" in texts


def test_stale_writer_cannot_overwrite_after_edit(client, fake, two_workers):
    """Worker A, mid-turn at the old revision, must not re-publish old history."""
    two_workers.as_worker_a()
    headers, sid, message_id, user_id = _signup_and_chat(client, fake)
    a = two_workers.api._sessions[sid]
    a.agent.load_history([{"role": "user", "content": "original message text"}])

    two_workers.as_worker_b()
    assert client.post(f"/api/session/{sid}/messages/{message_id}/edits",
                       json={"content": "EDITED"}, headers=headers).status_code == 200

    two_workers.as_worker_a()
    assert a.persist_to_redis() is False, "stale writer must be refused"
    two_workers.as_worker_c = lambda: setattr(two_workers.api, "_sessions", {})
    two_workers.as_worker_c()
    c = two_workers.api._get_session(sid, user_id=user_id)
    assert "original message text" not in _texts(c)


def test_unstamped_legacy_payload_is_not_trusted(client, fake, two_workers):
    import json
    two_workers.as_worker_a()
    headers, sid, message_id, user_id = _signup_and_chat(client, fake)
    two_workers.ss.get_client().set(two_workers.ss._key(sid), json.dumps(
        {"model_variant": "core", "history": [{"role": "user", "content": "LEGACY STALE"}], "saved_at": time.time()}))
    assert two_workers.ss.load_session_state(sid) is None


def test_payload_mismatching_revision_is_rejected_and_revision_expiry_is_safe(client, fake, two_workers):
    ss = two_workers.ss
    sid = "rev-expiry-sid"
    rev = ss.bump_revision(sid)
    assert rev >= 1
    assert ss.save_session_state(sid, "core", [{"role": "user", "content": "x"}], expected_revision=rev) is True
    assert ss.load_session_state(sid)["history"][0]["content"] == "x"
    ss.get_client().delete(ss._rev_key(sid))  # revision key TTL expiry
    assert ss.load_session_state(sid) is None, "stamp vs revision 0 must not be trusted"


def test_bump_atomically_deletes_payload(client, fake, two_workers):
    ss = two_workers.ss
    sid = "bump-del-sid"
    assert ss.save_session_state(sid, "core", [{"role": "user", "content": "old"}], expected_revision=0) is True
    assert ss.bump_revision(sid) >= 1
    assert ss.get_client().get(ss._key(sid)) is None


def test_touch_keeps_revision_key_alive(client, fake, two_workers):
    ss = two_workers.ss
    sid = "touch-sid"
    ss.bump_revision(sid)
    ss.get_client().expire(ss._rev_key(sid), 5)
    ss.touch_session(sid)
    assert ss.get_client().ttl(ss._rev_key(sid)) > 5


def test_concurrent_edits_get_distinct_monotonic_revisions(client, fake, two_workers):
    import concurrent.futures as cf
    ss = two_workers.ss
    with cf.ThreadPoolExecutor(16) as ex:
        revs = list(ex.map(lambda _: ss.bump_revision("conc-sid"), range(50)))
    assert len(set(revs)) == 50 and sorted(revs) == list(range(min(revs), min(revs) + 50))


def test_worker_with_unknown_revision_is_evicted_once_redis_returns(client, fake, two_workers):
    two_workers.as_worker_a()
    headers, sid, message_id, user_id = _signup_and_chat(client, fake)
    a = two_workers.api._sessions[sid]
    a._known_revision = None  # built during an outage
    s = two_workers.api._get_session(sid, user_id=user_id)
    assert s is not a, "a session built without a confirmed revision must be rebuilt once Redis is back"


def test_payload_ttl_expiry_rebuilds_from_transcript(client, fake, two_workers):
    two_workers.as_worker_a()
    headers, sid, message_id, user_id = _signup_and_chat(client, fake)
    a = two_workers.api._sessions[sid]
    a.agent.load_history([{"role": "user", "content": "stale cached"}])
    assert a.persist_to_redis() is True
    two_workers.ss.get_client().delete(two_workers.ss._key(sid))  # payload TTL expiry
    two_workers.api._sessions = {}
    c = two_workers.api._get_session(sid, user_id=user_id)
    assert "stale cached" not in _texts(c)


def test_revision_counter_never_reissues_a_value_after_restart_or_expiry(client, fake, two_workers):
    """ABA guard: counter vanishing (Redis restart without persistence,
    key expiry) must not let a later edit re-use a revision a worker holds."""
    ss = two_workers.ss
    sid = "aba-sid"
    first = ss.bump_revision(sid)
    safe_flush(ss.get_client())  # simulated restart: all state gone
    second = ss.bump_revision(sid)
    assert second > first


def test_edit_after_redis_restart_evicts_worker_with_pre_restart_cache(client, fake, two_workers):
    two_workers.as_worker_a()
    headers, sid, message_id, user_id = _signup_and_chat(client, fake)
    a = two_workers.api._sessions[sid]
    a.agent.load_history([{"role": "user", "content": "original message text"}])
    two_workers.api._get_session(sid, user_id=user_id)
    safe_flush(two_workers.ss.get_client())  # Redis restart, nothing persisted
    two_workers.as_worker_b()
    assert client.post(f"/api/session/{sid}/messages/{message_id}/edits",
                       json={"content": "EDITED after restart"}, headers=headers).status_code == 200
    two_workers.as_worker_a()
    two_workers.api._sessions[sid] = a
    s = two_workers.api._get_session(sid, user_id=user_id)
    assert s is not a
    assert "original message text" not in _texts(s)


def _broken_client(ss):
    def _boom(*a, **k):
        raise ConnectionError("simulated outage")
    return type("Broken", (), {n: _boom for n in ("incr", "get", "set", "delete", "expire", "eval", "ping")})()


def test_request_during_outage_never_claims_confirmed_freshness(client, fake, two_workers):
    two_workers.as_worker_a()
    headers, sid, message_id, user_id = _signup_and_chat(client, fake)
    a = two_workers.api._sessions[sid]
    a.agent.load_history([{"role": "user", "content": "original message text"}])
    real = two_workers.ss._client()
    two_workers.ss._redis_client = _broken_client(two_workers.ss)
    try:
        s = two_workers.api._get_session(sid, user_id=user_id)
        assert s is not a, "user session must be rebuilt from the transcript, not served from an unverifiable cache"
        assert s.context_freshness == "rebuilt_authoritative"
        assert s.persist_to_redis() is False, "a session with unknown revision must not publish"
        anon = two_workers.api._get_session("anon-outage-sid")
        assert anon.context_freshness != "confirmed"
        anon2 = two_workers.api._get_session("anon-outage-sid")
        assert anon2.context_freshness == "unconfirmed"
    finally:
        two_workers.ss._redis_client = real
    s2 = two_workers.api._get_session(sid, user_id=user_id)
    assert s2 is not s and s2.context_freshness == "confirmed", "reconnect: rebuilt and re-fenced"


def test_chat_response_reports_context_freshness(client, fake, two_workers):
    from tests.test_b_conversations import _chat
    headers, sid, message_id, user_id = _signup_and_chat(client, fake)
    r = client.post("/api/chat", json={"message": "hi", "session_id": sid}, headers=headers)
    assert r.status_code == 200
    assert r.json()["context_freshness"] == "confirmed"
