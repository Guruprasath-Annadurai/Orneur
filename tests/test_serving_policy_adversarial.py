from __future__ import annotations

import threading
import uuid

import pytest

from orca.auth.db import init_db
from orca.auth.store import (
    User,
    get_committed_response,
    get_usage_today,
    increment_usage,
    mark_quota_consumed,
    release_quota,
    request_fingerprint,
    reserve_quota,
)
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
    fp = request_fingerprint(user_id=uid, session_id="qidrefund01", message="hello", model="fixture-llama")
    first = reserve_quota(uid, "free", "message", request_id="same-req", fingerprint=fp)
    second = reserve_quota(uid, "free", "message", request_id="same-req", fingerprint=fp)
    assert first["ok"] and second["ok"] and second["duplicate"] is True
    assert second.get("in_progress") is True
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


def test_consumed_request_id_cannot_dispatch_again(isolated_home, ollama_fixture):
    init_db()
    uid = "qcons"
    rid = "consumed-req-1"
    first = complete(
        user=_user(uid),
        message="hello",
        model="fixture-llama",
        host=ollama_fixture,
        session_id="qcons0000001",
        request_id=rid,
        synthetic_provider=True,
    )
    assert first["request_id"] == rid
    assert get_usage_today(uid)["messages"] == 1
    # Direct reserve must refuse consumed.
    refused = reserve_quota(
        uid,
        "free",
        "message",
        request_id=rid,
        fingerprint=request_fingerprint(user_id=uid, session_id="qcons0000001", message="hello", model="fixture-llama"),
    )
    assert refused["ok"] is False
    assert refused["status"] == "consumed"
    # complete() must not call the provider again — returns committed replay.
    calls = {"n": 0}

    def _boom(*_a, **_k):
        calls["n"] += 1
        raise AssertionError("provider must not run on consumed replay")

    replay = complete(
        user=_user(uid),
        message="hello",
        model="fixture-llama",
        host=ollama_fixture,
        session_id="qcons0000001",
        request_id=rid,
        transport_generate=_boom,
        synthetic_provider=True,
    )
    assert calls["n"] == 0
    assert replay.get("replayed") is True
    assert replay["text"] == first["text"]
    assert get_usage_today(uid)["messages"] == 1


def test_cross_user_reservation_reuse_refused(isolated_home):
    init_db()
    fp = request_fingerprint(user_id="alice", session_id="s1", message="hi", model="m")
    reserve_quota("alice", "free", "message", request_id="shared-rid", fingerprint=fp)
    foreign = reserve_quota("bob", "free", "message", request_id="shared-rid", fingerprint=fp)
    assert foreign["ok"] is False
    assert foreign["status"] == "foreign"


def test_fingerprint_mismatch_refused(isolated_home):
    init_db()
    reserve_quota("alice", "free", "message", request_id="fp-rid", fingerprint="aaa")
    bad = reserve_quota("alice", "free", "message", request_id="fp-rid", fingerprint="bbb")
    assert bad["ok"] is False
    assert bad["status"] == "fingerprint_mismatch"


def test_in_progress_duplicate_refuses_second_complete(isolated_home, ollama_fixture):
    init_db()
    uid = "qinprog"
    rid = "inprog-1"
    fp = request_fingerprint(user_id=uid, session_id="qinprog00001", message="hello", model="fixture-llama")
    reserve_quota(uid, "free", "message", request_id=rid, fingerprint=fp)
    with pytest.raises(InferenceError) as exc:
        complete(
            user=_user(uid),
            message="hello",
            model="fixture-llama",
            host=ollama_fixture,
            session_id="qinprog00001",
            request_id=rid,
            synthetic_provider=True,
        )
    assert exc.value.code == "request_in_progress"


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


def test_terminal_reservations_are_pruned(isolated_home, monkeypatch):
    import sqlite3

    from orca.auth.db import AUTH_DB

    init_db()
    monkeypatch.setattr("orca.auth.store.TERMINAL_RETENTION_S", 0)
    rid = reserve_quota("u-prune", "free", "message", request_id="keep-then-drop")["request_id"]
    mark_quota_consumed(rid)
    reserve_quota("u-prune", "free", "message", request_id="next-admit")
    conn = sqlite3.connect(str(AUTH_DB))
    left = conn.execute(
        "SELECT COUNT(*) FROM usage_reservations WHERE request_id=?",
        ("keep-then-drop",),
    ).fetchone()[0]
    conn.close()
    assert left == 0


def test_committed_response_only_for_owner(isolated_home, ollama_fixture):
    init_db()
    rid = "own-only"
    complete(
        user=_user("owner1"),
        message="secret-turn",
        model="fixture-llama",
        host=ollama_fixture,
        session_id="owner1sess01",
        request_id=rid,
        synthetic_provider=True,
    )
    assert get_committed_response(rid, "owner1") is not None
    assert get_committed_response(rid, "attacker") is None
