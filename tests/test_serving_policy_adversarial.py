from __future__ import annotations

import threading

import pytest

from orca.auth.db import init_db
from orca.auth.store import User, get_usage_today, increment_usage, release_quota, reserve_quota
from orca.serve.inference import InferenceError, complete


def _user(uid="quota-u"):
    return User(id=uid, email=f"{uid}@example.com", name=uid, tier="free", verified=True)


def test_atomic_quota_49_of_50_three_simultaneous(isolated_home, ollama_fixture):
    init_db()
    uid = "q49"
    for _ in range(49):
        increment_usage(uid, "message")
    assert get_usage_today(uid)["messages"] == 49
    results: list[str] = []

    def _run(i: int):
        try:
            complete(
                user=_user(uid),
                message="hello",
                model="fixture-llama",
                host=ollama_fixture,
                session_id=f"q49{i:02d}xxxx",
                synthetic_provider=True,
            )
            results.append("ok")
        except InferenceError as exc:
            results.append(exc.code)

    threads = [threading.Thread(target=_run, args=(i,)) for i in range(3)]
    for t in threads:
        t.start()
    for t in threads:
        t.join()
    assert results.count("ok") == 1
    assert results.count("quota_exceeded") == 2
    assert get_usage_today(uid)["messages"] == 50


def test_idempotent_request_id_and_provider_outage_refund(isolated_home, ollama_fixture):
    init_db()
    uid = "qid"
    first = reserve_quota(uid, "free", "message", request_id="same-req")
    second = reserve_quota(uid, "free", "message", request_id="same-req")
    assert first["ok"] and second["ok"] and second["duplicate"] is True
    assert get_usage_today(uid)["messages"] == 1
    with pytest.raises(InferenceError) as exc:
        complete(
            user=_user(uid),
            message="hello",
            model="fixture-llama",
            host="http://127.0.0.1:1",
            session_id="qidrefund01",
        )
    assert exc.value.code == "provider_unavailable"
    # outage reserved then released
    after = get_usage_today(uid)["messages"]
    assert after == 1


def test_release_is_idempotent_and_never_negative(isolated_home):
    init_db()
    rid = reserve_quota("u-rel", "free", "message", request_id="rel-1")["request_id"]
    release_quota(rid)
    release_quota(rid)
    assert get_usage_today("u-rel")["messages"] == 0


def test_stale_reservation_crash_recovery(isolated_home, monkeypatch):
    init_db()
    monkeypatch.setattr("orca.auth.store.RESERVATION_TTL_S", 0)
    reserve_quota("u-crash", "free", "message", request_id="old-crash")
    assert get_usage_today("u-crash")["messages"] == 1
    reserve_quota("u-crash", "free", "message", request_id="new-after-crash")
    assert get_usage_today("u-crash")["messages"] == 1
