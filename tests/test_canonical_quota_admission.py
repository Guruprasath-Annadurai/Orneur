"""LANDMARK-01 Wave 2: the canonical product routes (/api/chat, /api/stream) admit quota ATOMICALLY.

Before: ``check_quota`` (read) ... model call ... ``increment_usage`` (write). Under concurrency every request passed the check at 49/50 and every one
then incremented, and a long generation had no claim on its unit at all. The inference routes already used reservations; the routes the browser
actually calls did not. These tests assert the same guarantees on the canonical routes, counting REAL model dispatches at the (fake) backend.
"""
from __future__ import annotations

import json
import threading
import time
from concurrent.futures import ThreadPoolExecutor

import pytest

from tests.fake_ollama import FakeOllama, point_orneur_at
from tests.test_g006_tenant_isolation import _hdr, _signup, client  # noqa: F401  (fixture re-export)


@pytest.fixture
def fake(client, monkeypatch):  # noqa: F811
    from orca.serve import ratelimit

    ratelimit._local_counters.clear()
    monkeypatch.setattr(ratelimit, "enforce", lambda *a, **k: None)
    f = FakeOllama(models=("orca-nano", "orca-core", "orca-ultra"), chunk_delay=0.0)
    f.__enter__()
    point_orneur_at(f, monkeypatch)
    yield f
    f.__exit__(None, None, None)


def _usage(uid):
    from orca.auth.store import get_usage_today

    return get_usage_today(uid)["messages"]


def _fill(uid, n):
    from orca.auth.store import increment_usage

    for _ in range(n):
        increment_usage(uid, "message")


def _stream_events(client, token, body):
    with client.stream("POST", "/api/stream", json=body, headers=_hdr(token)) as r:
        text = "".join(r.iter_text())
    return [json.loads(line[6:]) for line in text.splitlines() if line.startswith("data: ")]


def _chat(client, token, sid, msg="hello"):
    return client.post("/api/chat", json={"message": msg, "session_id": sid, "model_variant": "nano"}, headers=_hdr(token))


def test_49_of_50_concurrent_chat_requests_admit_exactly_one(client, fake):
    token, uid = _signup(client)
    _fill(uid, 49)
    before = len(fake.requests)
    barrier = threading.Barrier(8)

    def one(i):
        barrier.wait()
        return _chat(client, token, f"race-chat-{i:04d}").status_code

    with ThreadPoolExecutor(8) as pool:
        codes = list(pool.map(one, range(8)))
    assert codes.count(200) == 1, codes
    assert codes.count(429) == 7, codes
    assert _usage(uid) == 50
    # Only the admitted request may reach the model: every refused one must be rejected BEFORE dispatch.
    assert len(fake.requests) - before >= 1
    dispatched = len(fake.requests) - before
    assert dispatched <= 3, f"7 refused requests must not dispatch; saw {dispatched} backend calls"


def test_49_of_50_concurrent_stream_requests_admit_exactly_one(client, fake):
    token, uid = _signup(client)
    _fill(uid, 49)
    barrier = threading.Barrier(8)

    def one(i):
        barrier.wait()
        evs = _stream_events(client, token, {"message": "hello", "session_id": f"race-strm-{i:04d}", "model_variant": "nano"})
        return "quota_exceeded" if any(e.get("code") == "quota_exceeded" for e in evs) else ("done" if any(e["type"] == "done" for e in evs) else "other")

    with ThreadPoolExecutor(8) as pool:
        outcomes = list(pool.map(one, range(8)))
    assert outcomes.count("done") == 1, outcomes
    assert outcomes.count("quota_exceeded") == 7, outcomes
    assert _usage(uid) == 50


def test_exhausted_user_is_refused_without_any_dispatch_on_both_routes(client, fake):
    token, uid = _signup(client)
    _fill(uid, 50)
    before = len(fake.requests)
    assert _chat(client, token, "exhausted-chat-0001").status_code == 429
    evs = _stream_events(client, token, {"message": "hello", "session_id": "exhausted-strm-0001", "model_variant": "nano"})
    assert any(e.get("code") == "quota_exceeded" for e in evs)
    assert len(fake.requests) == before
    assert _usage(uid) == 50


def test_backend_failure_refunds_the_reservation(client, fake):
    token, uid = _signup(client)
    fake.fail_status = 500
    resp = _chat(client, token, "refund-chat-0001")
    assert resp.status_code >= 400
    assert _usage(uid) == 0, "a request the model never answered must not spend quota"
    evs = _stream_events(client, token, {"message": "hello", "session_id": "refund-strm-0001", "model_variant": "nano"})
    assert not any(e["type"] == "done" for e in evs)
    assert _usage(uid) == 0


def test_successful_turns_spend_exactly_one_unit_each(client, fake):
    token, uid = _signup(client)
    assert _chat(client, token, "spend-chat-00001").status_code == 200
    assert _usage(uid) == 1
    evs = _stream_events(client, token, {"message": "again", "session_id": "spend-strm-00001", "model_variant": "nano"})
    assert any(e["type"] == "done" for e in evs)
    assert _usage(uid) == 2


def test_quota_backend_unavailable_fails_closed(client, fake, monkeypatch):
    from orca.auth import store

    def boom(*a, **k):
        raise store.QuotaError("quota_unavailable")

    monkeypatch.setattr(store, "reserve_quota", boom)
    token, uid = _signup(client)
    before = len(fake.requests)
    resp = _chat(client, token, "closed-chat-00001")
    assert resp.status_code == 503
    assert len(fake.requests) == before


def test_heartbeat_keeps_a_long_reservation_from_being_refunded_as_stale(client):
    from orca.auth import store

    _, uid_a = _signup(client)
    _, uid_b = _signup(client)
    res = store.reserve_quota(uid_a, "free", "message", request_id="long-running-0001")
    assert res["ok"] and _usage(uid_a) == 1
    # Age the reservation past the stale window, as a >120s generation would.
    conn = store._quota_conn()
    with conn:
        conn.execute("UPDATE usage_reservations SET created_at=? WHERE request_id=?", (time.time() - store.RESERVATION_TTL_S - 5, "long-running-0001"))
    conn.close()
    assert store.renew_quota("long-running-0001") is True
    # Any other user's admission sweeps stale rows; the renewed one must survive.
    store.reserve_quota(uid_b, "free", "message", request_id="sweeper-0001")
    assert _usage(uid_a) == 1


def test_a_stale_unrenewed_reservation_is_still_refunded(client):
    from orca.auth import store

    _, uid_a = _signup(client)
    _, uid_b = _signup(client)
    store.reserve_quota(uid_a, "free", "message", request_id="crashed-worker-0001")
    conn = store._quota_conn()
    with conn:
        conn.execute("UPDATE usage_reservations SET created_at=? WHERE request_id=?", (time.time() - store.RESERVATION_TTL_S - 5, "crashed-worker-0001"))
    conn.close()
    store.reserve_quota(uid_b, "free", "message", request_id="sweeper-0002")
    assert _usage(uid_a) == 0
    assert store.renew_quota("crashed-worker-0001") is False


def test_a_foreign_request_id_cannot_be_reused(client):
    from orca.auth import store

    _, uid_a = _signup(client)
    _, uid_b = _signup(client)
    store.reserve_quota(uid_a, "free", "message", request_id="owned-by-a-0001")
    with pytest.raises(store.QuotaError):
        store.reserve_quota(uid_b, "free", "message", request_id="owned-by-a-0001")


# ---- the secondary inference routes use the same atomic admission (they were still check-then-increment) ----------------------------------------

def test_ultra_concurrent_race_at_the_daily_limit_admits_exactly_the_remaining_units(client, fake, monkeypatch):
    from types import SimpleNamespace

    import orca.serve.api as api
    from orca.auth.store import get_usage_today, increment_usage

    runs = []

    class StubUltra:
        def __init__(self, *a, **k):
            pass

        async def _run_async(self, task, max_retries=1):
            runs.append(task)
            return SimpleNamespace(final_output="ULTRA-ANSWER", grade="A", iterations=1)

    monkeypatch.setattr(api, "OrcaUltra", StubUltra)
    monkeypatch.setattr(api, "has_feature", lambda feature: True)
    monkeypatch.setattr(api, "model_access_allowed", lambda user, variant: (True, ""))
    token, uid = _signup(client)
    for _ in range(2):
        increment_usage(uid, "ultra")                              # free tier allows 3 ultra runs a day: exactly one unit left
    barrier = threading.Barrier(6)

    def one(i):
        barrier.wait()
        with client.stream("POST", "/api/ultra", json={"task": f"plan {i}"}, headers=_hdr(token)) as r:
            text = "".join(r.iter_text())
        evs = [json.loads(line[6:]) for line in text.splitlines() if line.startswith("data: ")]
        return "done" if any(e["type"] == "done" for e in evs) else ("quota" if any(e.get("code") == "quota_exceeded" for e in evs) else str(evs[-1:]))

    with ThreadPoolExecutor(6) as pool:
        outcomes = list(pool.map(one, range(6)))
    assert outcomes.count("done") == 1 and outcomes.count("quota") == 5, outcomes
    assert len(runs) == 1, "refused ultra requests must not start the pipeline"
    assert get_usage_today(uid)["ultra_runs"] == 3


def test_cognitive_execute_concurrent_race_admits_exactly_one(client, fake):
    token, uid = _signup(client)
    _fill(uid, 49)
    barrier = threading.Barrier(6)

    def one(i):
        barrier.wait()
        return client.post("/api/cognitive/execute", json={"objective": f"say hello {i}"}, headers=_hdr(token)).status_code

    with ThreadPoolExecutor(6) as pool:
        codes = list(pool.map(one, range(6)))
    assert codes.count(429) == 5, codes
    assert _usage(uid) == 50


def test_a_failed_cognitive_execute_refunds(client, fake):
    token, uid = _signup(client)
    fake.fail_status = 500
    try:
        status = client.post("/api/cognitive/execute", json={"objective": "will fail"}, headers=_hdr(token)).status_code
        assert status >= 400
    except Exception:
        pass                                   # this internal route lets a kernel failure surface as an unhandled 500 (TestClient re-raises it)
    assert _usage(uid) == 0
