"""LANDMARK-01 Wave 6: every failure ends in (1) correct recovery with authoritative state intact, (2) a safe, truthful refusal, or (3) a documented blocker.

Evidence class: FIXTURE-PROVIDER (FakeOllama over real HTTP) through the real FastAPI app. The same failures are exercised against real Ollama / Redis /
Chromium in tests/journey. Nothing here may fabricate a successful completion, a saved message or a provider response.
"""
from __future__ import annotations

import json
import uuid

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
    try:
        f.__exit__(None, None, None)
    except Exception:
        pass


def _sid(label):
    return f"{uuid.uuid4().hex[:8]}-{label}"


def _usage(uid):
    from orca.auth.store import get_usage_today

    return get_usage_today(uid)["messages"]


def _stream(client, token, sid, msg="hello there", **hdr):
    with client.stream("POST", "/api/stream", json={"message": msg, "session_id": sid, "model_variant": "nano"}, headers={**_hdr(token), **hdr}) as r:
        text = "".join(r.iter_text())
    return [json.loads(line[6:]) for line in text.splitlines() if line.startswith("data: ")]


def _chat(client, token, sid, msg="hello there", **hdr):
    return client.post("/api/chat", json={"message": msg, "session_id": sid, "model_variant": "nano"}, headers={**_hdr(token), **hdr})


def _messages(client, token, sid):
    r = client.get(f"/api/session/{sid}/messages", headers=_hdr(token))
    return [] if r.status_code == 404 else [(m["role"], m["content"]) for m in r.json()["messages"]]


def _assert_clean_failure(client, token, uid, sid, events=None, resp=None):
    if events is not None:
        assert not any(e["type"] == "done" for e in events), f"a failed generation was reported as done: {events}"
        assert any(e["type"] == "error" for e in events), events
    if resp is not None:
        assert resp.status_code >= 400, resp.text
    assert _messages(client, token, sid) == [], "a turn the model never answered was persisted"
    assert _usage(uid) == 0, "quota was spent on a request that produced no answer"


def test_ollama_unreachable(client, fake):
    token, uid = _signup(client)
    fake.__exit__(None, None, None)                   # the provider process goes away
    sid = _sid("down-chat")
    _assert_clean_failure(client, token, uid, sid, resp=_chat(client, token, sid))
    sid2 = _sid("down-strm")
    _assert_clean_failure(client, token, uid, sid2, events=_stream(client, token, sid2))


def test_ollama_http_error(client, fake):
    token, uid = _signup(client)
    fake.fail_status = 500
    sid = _sid("err-chat")
    _assert_clean_failure(client, token, uid, sid, resp=_chat(client, token, sid))
    sid2 = _sid("err-strm")
    _assert_clean_failure(client, token, uid, sid2, events=_stream(client, token, sid2))


def test_ollama_malformed_response(client, fake):
    token, uid = _signup(client)
    fake.malformed = True
    sid = _sid("bad-chat")
    _assert_clean_failure(client, token, uid, sid, resp=_chat(client, token, sid))
    sid2 = _sid("bad-strm")
    _assert_clean_failure(client, token, uid, sid2, events=_stream(client, token, sid2))


def test_ollama_timeout_is_classified_and_not_saved(client, fake, monkeypatch):
    import httpx

    real_post = httpx.AsyncClient.post

    async def slow(self, url, *a, **k):
        if str(url).endswith("/api/chat"):
            raise httpx.ReadTimeout("simulated read timeout")
        return await real_post(self, url, *a, **k)

    monkeypatch.setattr(httpx.AsyncClient, "post", slow)
    token, uid = _signup(client)
    sid = _sid("tmo-chat")
    r = _chat(client, token, sid)
    assert r.status_code in (500, 502, 503, 504), r.text
    assert r.json().get("code") in {"upstream_timeout", "backend_unreachable", "backend_error", "model_unavailable", "internal_error"}
    assert _messages(client, token, sid) == [] and _usage(uid) == 0


def test_truncated_upstream_stream_is_not_a_completed_turn(client, fake):
    """The provider hangs up mid-answer without its final done marker. A document forces the genuinely-streamed (AgentLoop) path."""
    from orca.docs import chunk_text
    from orca.serve.api import _get_session

    token, uid = _signup(client)
    sid = _sid("trunc")
    sess = _get_session(sid, "nano", user_id=uid)
    sess.doc_store.add_chunks(chunk_text("Orneur is a fictional architecture.", doc_id="d1", filename="t.txt"), doc_id="d1", filename="t.txt")
    fake.chunks, fake.reply, fake.truncate_after = ["alpha ", "beta ", "gamma ", "delta "], "alpha beta gamma delta ", 2
    events = _stream(client, token, sid)
    done = [e for e in events if e["type"] == "done"]
    persisted = _messages(client, token, sid)
    # Either the server reports an error, or it completes with what it genuinely received -- but it must never persist beyond what was received
    # while claiming a full answer.
    if done:
        got = "".join(e["text"] for e in events if e["type"] == "chunk")
        assert "gamma" not in got and "delta" not in got
        assert all("gamma" not in c and "delta" not in c for _, c in persisted)
    else:
        assert any(e["type"] == "error" for e in events), events
        assert persisted == []


def test_service_recovers_after_every_failure_with_no_residual_authority(client, fake):
    token, uid = _signup(client)
    sid = _sid("recover")
    for mode in ("fail_status", "malformed"):
        setattr(fake, mode, 500 if mode == "fail_status" else True)
        assert _chat(client, token, sid).status_code >= 400
        setattr(fake, mode, None if mode == "fail_status" else False)
    fake.reply = "RECOVERED"
    r = _chat(client, token, sid, "after the outage")
    assert r.status_code == 200 and r.json()["persisted"] == "saved", r.text
    assert _messages(client, token, sid) == [("user", "after the outage"), ("assistant", "RECOVERED")]
    assert _usage(uid) == 1


def test_sqlite_down_refuses_up_front_and_nothing_is_generated_or_charged(client, fake, monkeypatch):
    from orca.serve import conversations

    token, uid = _signup(client)
    before = len(fake.requests)

    def boom():
        raise RuntimeError("disk I/O error")

    monkeypatch.setattr(conversations, "_turns_conn", boom)
    sid = _sid("sqlite-down")
    r = _chat(client, token, sid)
    assert r.status_code == 503 and r.json()["code"] == "history_unavailable", r.text
    events = _stream(client, token, _sid("sqlite-dn2"))
    assert any(e.get("code") == "history_unavailable" for e in events), events
    assert len(fake.requests) == before, "the model was called although the turn could not have been saved"
    assert _usage(uid) == 0


def test_sqlite_commit_failure_is_reported_as_not_saved_and_leaves_no_derived_state(client, fake, monkeypatch):
    from orca.serve import conversations

    token, uid = _signup(client)
    real = conversations.commit_turn

    def failing(*a, **k):
        return conversations.CommitResult(ok=False, reason="persist_failed")

    monkeypatch.setattr(conversations, "commit_turn", failing)
    sid = _sid("commit-fail")
    fake.reply = "UNSAVED-ANSWER"
    r = _chat(client, token, sid)
    assert r.status_code == 200 and r.json()["persisted"] == "failed" and r.json()["user_message_id"] is None
    ev = _stream(client, token, _sid("commit-fl2"))
    assert [e for e in ev if e["type"] == "done"][0]["persisted"] == "failed"
    monkeypatch.setattr(conversations, "commit_turn", real)
    assert _messages(client, token, sid) == []
    # ...and the next turn on the same session works and contains only itself.
    fake.reply = "SAVED-ANSWER"
    assert _chat(client, token, sid, "second try").json()["persisted"] == "saved"
    assert _messages(client, token, sid) == [("user", "second try"), ("assistant", "SAVED-ANSWER")]
    assert "UNSAVED-ANSWER" not in json.dumps(fake.requests[-1]), "an unsaved answer leaked into the next prompt"


def test_duplicate_stream_delivery_replays_without_a_second_model_call_or_turn(client, fake):
    token, uid = _signup(client)
    sid = _sid("idem")
    key = "dup-key-" + uuid.uuid4().hex[:12]
    fake.reply = "ONLY-ONCE"
    first = _stream(client, token, sid, "same message", **{"Idempotency-Key": key})
    calls = len(fake.requests)
    again = _stream(client, token, sid, "same message", **{"Idempotency-Key": key})
    assert len(fake.requests) == calls, "a duplicate delivery re-called the model"
    assert [e for e in again if e["type"] == "done"][0].get("idempotent_replay") is True
    assert "".join(e["text"] for e in again if e["type"] == "chunk") == "ONLY-ONCE"
    assert _messages(client, token, sid) == [("user", "same message"), ("assistant", "ONLY-ONCE")]
    assert _usage(uid) == 1
    other = _stream(client, token, sid, "a different message", **{"Idempotency-Key": key})
    assert any(e.get("code") == "invalid_request" for e in other), other
    assert [e for e in first if e["type"] == "done"]


def test_duplicate_chat_delivery_is_also_exactly_once(client, fake):
    token, uid = _signup(client)
    sid = _sid("idem-chat")
    key = "dup-chat-" + uuid.uuid4().hex[:12]
    a = _chat(client, token, sid, "once please", **{"Idempotency-Key": key})
    n = len(fake.requests)
    b = _chat(client, token, sid, "once please", **{"Idempotency-Key": key})
    assert b.headers.get("Idempotent-Replay") == "true" and b.json()["response"] == a.json()["response"]
    assert len(fake.requests) == n and _usage(uid) == 1
    assert len(_messages(client, token, sid)) == 2


def test_failed_attempt_does_not_poison_its_idempotency_key(client, fake):
    token, uid = _signup(client)
    sid = _sid("idem-fail")
    key = "retry-key-" + uuid.uuid4().hex[:12]
    fake.fail_status = 500
    bad = _stream(client, token, sid, "try me", **{"Idempotency-Key": key})
    assert not any(e["type"] == "done" for e in bad)
    fake.fail_status = None
    fake.reply = "WORKED"
    good = _stream(client, token, sid, "try me", **{"Idempotency-Key": key})
    assert [e for e in good if e["type"] == "done"][0]["persisted"] == "saved"
    assert _messages(client, token, sid) == [("user", "try me"), ("assistant", "WORKED")]
