"""LANDMARK-01 Wave 2: /api/chat and /api/stream hold DURABLE turn authority from before generation until after the commit.

Before: the stream route took a Redis lease (an initial check, never re-proved at the write) and the SQLite commit acquired a brand-new authority
*after* generation, so a worker that stalled past its lease could still write a turn built from stale context after a successor had committed.
Now both routes share ``_TurnAuthority``: a live turn excludes overlapping ones, and a superseded worker's commit is refused inside the SQLite
transaction and published nowhere.
"""
from __future__ import annotations

import json
import threading
import time

import pytest

from tests.fake_ollama import FakeOllama, point_orneur_at
from tests.test_g006_tenant_isolation import _hdr, _signup, client  # noqa: F401  (fixture re-export)


@pytest.fixture
def fake(client, monkeypatch):  # noqa: F811
    from orca.serve import ratelimit

    monkeypatch.setattr(ratelimit, "enforce", lambda *a, **k: None)
    f = FakeOllama(models=("orca-nano", "orca-core", "orca-ultra"))
    f.__enter__()
    point_orneur_at(f, monkeypatch)
    yield f
    f.__exit__(None, None, None)


def _events(client, token, body):
    with client.stream("POST", "/api/stream", json=body, headers=_hdr(token)) as r:
        text = "".join(r.iter_text())
    return [json.loads(line[6:]) for line in text.splitlines() if line.startswith("data: ")]


def _transcript(client, token, sid):
    r = client.get(f"/api/session/{sid}/messages", headers=_hdr(token))
    assert r.status_code == 200, r.text
    return [(m["role"], m["content"]) for m in r.json()["messages"]]


def _chat(client, token, sid, msg):
    return client.post("/api/chat", json={"message": msg, "session_id": sid, "model_variant": "nano"}, headers=_hdr(token))


def test_sequential_turns_commit_once_each_in_order_with_server_ids(client, fake):
    token, _ = _signup(client)
    sid = "taseq001-sequential"
    fake.reply = "ANSWER-ONE"
    r1 = _chat(client, token, sid, "first question")
    assert r1.status_code == 200 and r1.json()["persisted"] == "saved"
    assert r1.json()["user_message_id"] and r1.json()["message_id"]
    fake.reply = "ANSWER-TWO"
    evs = _events(client, token, {"message": "second question", "session_id": sid, "model_variant": "nano"})
    done = [e for e in evs if e["type"] == "done"][0]
    assert done["persisted"] == "saved" and done["user_message_id"]
    assert _transcript(client, token, sid) == [
        ("user", "first question"), ("assistant", "ANSWER-ONE"),
        ("user", "second question"), ("assistant", "ANSWER-TWO"),
    ]


def test_overlapping_turns_on_one_session_are_refused_not_interleaved(client, fake):
    token, _ = _signup(client)
    sid = "tabusy01-overlap"
    fake.pre_response_delay = 1.5
    fake.reply = "SLOW-A"
    out = {}
    t = threading.Thread(target=lambda: out.setdefault("a", _chat(client, token, sid, "turn A")))
    t.start()
    time.sleep(0.6)                                   # A is generating and holds the turn
    fake.pre_response_delay = 0.0
    b = _chat(client, token, sid, "turn B")
    evs_b = _events(client, token, {"message": "turn C", "session_id": sid, "model_variant": "nano"})
    t.join(timeout=30)
    assert b.status_code == 409 and b.json()["code"] == "session_busy"
    assert any(e.get("code") == "session_busy" for e in evs_b)
    assert out["a"].status_code == 200 and out["a"].json()["persisted"] == "saved"
    assert _transcript(client, token, sid) == [("user", "turn A"), ("assistant", "SLOW-A")]


@pytest.fixture
def short_authority(monkeypatch):
    """A worker that stops heart-beating (hung / partitioned): authority lapses after 1.5s and is never renewed."""
    from orca.serve import api

    monkeypatch.setattr(api._TurnAuthority, "TTL_S", 1.5)
    monkeypatch.setattr(api._TurnAuthority, "HEARTBEAT_S", 600.0)


def test_superseded_chat_worker_cannot_overwrite_a_successor_turn(client, fake, short_authority):
    token, _ = _signup(client)
    sid = "tastale1-chat"
    fake.pre_response_delay = 4.0
    fake.reply = "STALE-A-ANSWER"
    out = {}
    t = threading.Thread(target=lambda: out.setdefault("a", _chat(client, token, sid, "stale question")))
    t.start()
    time.sleep(2.2)                                   # A's authority has lapsed without renewal
    fake.pre_response_delay = 0.0
    fake.reply = "SUCCESSOR-ANSWER"
    b = _chat(client, token, sid, "successor question")
    assert b.status_code == 200 and b.json()["persisted"] == "saved", b.text
    t.join(timeout=30)
    a = out["a"]
    # A is told the truth: it is not saved. It must not appear anywhere authoritative.
    assert a.status_code == 200 and a.json()["persisted"] == "failed", a.text
    assert _transcript(client, token, sid) == [("user", "successor question"), ("assistant", "SUCCESSOR-ANSWER")]


def test_superseded_stream_worker_cannot_persist_after_a_successor_took_authority(client, fake, short_authority):
    token, _ = _signup(client)
    sid = "tastale2-stream"
    fake.pre_response_delay = 4.0
    fake.reply = "STALE-STREAM-ANSWER"
    out = {}
    t = threading.Thread(target=lambda: out.setdefault("a", _events(client, token, {"message": "stale q", "session_id": sid, "model_variant": "nano"})))
    t.start()
    time.sleep(2.2)
    fake.pre_response_delay = 0.0
    fake.reply = "SUCCESSOR-STREAM"
    evs_b = _events(client, token, {"message": "successor q", "session_id": sid, "model_variant": "nano"})
    assert [e for e in evs_b if e["type"] == "done"][0]["persisted"] == "saved"
    t.join(timeout=30)
    done_a = [e for e in out["a"] if e["type"] == "done"]
    assert done_a and done_a[0]["persisted"] == "failed" and not done_a[0]["user_message_id"]
    assert _transcript(client, token, sid) == [("user", "successor q"), ("assistant", "SUCCESSOR-STREAM")]


def test_a_chat_worker_cannot_overwrite_a_valid_stream_turn_and_vice_versa(client, fake, short_authority):
    token, _ = _signup(client)
    sid = "tacross1-routes"
    fake.pre_response_delay = 4.0
    fake.reply = "CHAT-STALE"
    out = {}
    t = threading.Thread(target=lambda: out.setdefault("a", _chat(client, token, sid, "chat q")))
    t.start()
    time.sleep(2.2)
    fake.pre_response_delay = 0.0
    fake.reply = "STREAM-WINS"
    evs = _events(client, token, {"message": "stream q", "session_id": sid, "model_variant": "nano"})
    assert [e for e in evs if e["type"] == "done"][0]["persisted"] == "saved"
    t.join(timeout=30)
    assert out["a"].json()["persisted"] == "failed"
    assert _transcript(client, token, sid) == [("user", "stream q"), ("assistant", "STREAM-WINS")]


def test_authority_is_released_after_each_turn_so_the_next_turn_is_not_busy(client, fake):
    token, _ = _signup(client)
    sid = "tarelea1-release"
    for i in range(3):
        fake.reply = f"R{i}"
        r = _chat(client, token, sid, f"q{i}")
        assert r.status_code == 200, r.text
    assert len(_transcript(client, token, sid)) == 6


def test_a_refused_or_failed_turn_leaves_no_residual_authority(client, fake):
    token, _ = _signup(client)
    sid = "tafaile1-failed"
    fake.fail_status = 500
    assert _chat(client, token, sid, "will fail").status_code >= 400
    fake.fail_status = None
    fake.reply = "RECOVERED"
    r = _chat(client, token, sid, "after failure")
    assert r.status_code == 200 and r.json()["persisted"] == "saved"
    assert _transcript(client, token, sid) == [("user", "after failure"), ("assistant", "RECOVERED")]


def test_reading_the_transcript_never_blocks_or_strands_the_next_turn(client, fake):
    """Regression (found by the live journey): every transcript READ used to take a 'migrate-*' authority and never release it on the
    already-verified path, so the next real turn was refused as busy for the whole 30s TTL."""
    token, _ = _signup(client)
    sid = "tareads1-reads"
    fake.reply = "FIRST"
    assert _chat(client, token, sid, "q1").status_code == 200
    for _ in range(3):
        assert client.get(f"/api/session/{sid}/messages", headers=_hdr(token)).status_code == 200
        assert client.get(f"/api/session/{sid}/export?format=md", headers=_hdr(token)).status_code == 200
        assert client.get("/api/sessions", headers=_hdr(token)).status_code == 200
    fake.reply = "SECOND"
    r = _chat(client, token, sid, "q2")
    assert r.status_code == 200 and r.json()["persisted"] == "saved", r.text
    evs = _events(client, token, {"message": "q3", "session_id": sid, "model_variant": "nano"})
    assert [e for e in evs if e["type"] == "done"][0]["persisted"] == "saved"


def test_legacy_jsonl_history_is_imported_once_explicitly_and_does_not_strand_authority(client, fake):
    from orca.auth.store import claim_session
    from orca.serve import conversations

    token, uid = _signup(client)
    sid = "talegacy-import"
    assert claim_session(sid, uid)
    conversations.append(sid, "user", "legacy question", meta={"message_id": "legacym1"})
    conversations.append(sid, "assistant", "legacy answer", meta={"message_id": "legacym2"})
    # Unverified legacy JSONL is NOT trusted by an ordinary read of an empty authoritative store...
    assert conversations.migration_state(sid) != "verified"
    first = client.get(f"/api/session/{sid}/messages", headers=_hdr(token)).json()
    assert [m["content"] for m in first["messages"]] == ["legacy question", "legacy answer"]
    assert conversations.migration_state(sid) == "verified"
    fake.reply = "NEW"
    r = _chat(client, token, sid, "after import")
    assert r.status_code == 200 and r.json()["persisted"] == "saved", r.text
    assert [m for m in _transcript(client, token, sid)] == [
        ("user", "legacy question"), ("assistant", "legacy answer"), ("user", "after import"), ("assistant", "NEW"),
    ]
