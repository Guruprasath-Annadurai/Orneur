"""Task F -- what ORNEUR's own request path actually does around a model, verified end to end.

The model is a TEST DOUBLE (``tests/fake_ollama.py``): these tests verify routing, sessions, streaming, cancellation, errors, limits, storage and deletion in
the real FastAPI app. They say nothing about any model's quality, and nothing here is a working-model claim.

Passing tests pin behaviour that works. ``xfail(strict=True)`` pins a REAL, reproduced gap (register ids in the reason) so it cannot be forgotten, and
fails loudly -- forcing the marker's removal -- the day it is fixed.
"""
from __future__ import annotations

import asyncio
import json
import time
from pathlib import Path

import pytest

from tests.fake_ollama import FakeOllama, point_orneur_at
from tests.test_g006_tenant_isolation import PASSWORD, _hdr, _signup, client  # noqa: F401  (fixture re-export)

DOC = b"The retention period for customer data is ninety days after termination. Backups are purged within 120 days."


@pytest.fixture
def fake(client, monkeypatch):
    from orca.serve import ratelimit

    ratelimit._local_counters.clear()          # the per-IP limiter is process-wide state; every test here comes from one synthetic IP
    with FakeOllama() as f:
        point_orneur_at(f, monkeypatch)
        yield f


def _events(client, headers, body) -> list:
    with client.stream("POST", "/api/stream", json=body, headers=headers) as s:
        text = "".join(s.iter_text())
    return [json.loads(line[6:]) for line in text.splitlines() if line.startswith("data: ")]


# ── model request lifecycle ───────────────────────────────────────────────────────────────────────────────────────────────────────

def test_chat_reaches_the_model_and_returns_the_reply_with_a_session(client, fake):
    t, _ = _signup(client)
    r = client.post("/api/chat", json={"message": "hello there", "model_variant": "core"}, headers=_hdr(t))
    assert r.status_code == 200 and r.json()["response"] == "FAKE-REPLY" and r.json()["session_id"]
    assert fake.requests and fake.requests[0]["messages"][-1]["content"] == "hello there"


def test_stream_emits_session_chunk_done_with_a_message_id(client, fake):
    t, _ = _signup(client)
    evs = _events(client, _hdr(t), {"message": "hello again", "model_variant": "core"})
    assert [e["type"] for e in evs] == ["session", "model", "stream", "chunk", "done"]
    chunk, done = evs[3], evs[4]
    assert chunk["text"] == "FAKE-REPLY" and chunk["replayed"] is True and done["message_id"] and "citation_compliance" in done


def test_response_discloses_which_model_served(client, fake):
    t, _ = _signup(client)
    r = client.post("/api/chat", json={"message": "hello there", "model_variant": "core"}, headers=_hdr(t)).json()
    assert fake.requests[0]["model"] in json.dumps(r)


@pytest.mark.xfail(strict=True, reason="G-026: a simple question is generated NON-streaming (stream=false upstream) and delivered as one chunk after the whole "
                                       "answer exists, so there is nothing incremental to show and nothing to cancel mid-generation.")
def test_simple_answers_are_generated_with_streaming_upstream(client, fake):
    t, _ = _signup(client)
    _events(client, _hdr(t), {"message": "long answer please", "model_variant": "core"})
    assert fake.requests and all(q.get("stream") for q in fake.requests)


# ── streaming and cancellation ─────────────────────────────────────────────────────────────────────────────────────────────────────

def test_agent_path_streams_incrementally_from_the_backend(client, monkeypatch):
    with FakeOllama(chunks=tuple(f"w{i} " for i in range(5)), chunk_delay=0.02) as f:
        point_orneur_at(f, monkeypatch)
        t, _ = _signup(client)
        evs = _events(client, _hdr(t), {"message": "Write a python function to reverse a string and run it", "model_variant": "core"})
        assert [e["type"] for e in evs].count("chunk") == 5 and any(q.get("stream") for q in f.requests)


async def _drive(app, path, body, token, stop_after):
    scope = {"type": "http", "method": "POST", "path": path, "raw_path": path.encode(), "query_string": b"", "root_path": "", "scheme": "http",
             "http_version": "1.1", "server": ("test", 80), "client": ("9.9.9.9", 1234),
             "headers": [(b"content-type", b"application/json"), (b"authorization", f"Bearer {token}".encode()), (b"host", b"test")]}
    sent, disconnect, chunks = False, asyncio.Event(), []

    async def receive():
        nonlocal sent
        if not sent:
            sent = True
            return {"type": "http.request", "body": json.dumps(body).encode(), "more_body": False}
        await disconnect.wait()
        return {"type": "http.disconnect"}

    async def send(msg):
        if msg["type"] == "http.response.body" and b'"chunk"' in msg.get("body", b""):
            chunks.append(msg["body"])
            if len(chunks) >= stop_after:
                disconnect.set()

    t0 = time.monotonic()
    await app(scope, receive, send)
    return len(chunks), time.monotonic() - t0


def test_client_disconnect_cancels_the_backend_generation_on_the_streaming_path(client, monkeypatch):
    import orca.serve.api as api

    with FakeOllama(chunks=tuple(f"w{i} " for i in range(40)), chunk_delay=0.1) as f:
        point_orneur_at(f, monkeypatch)
        t, _ = _signup(client)
        got, took = asyncio.run(_drive(api.app, "/api/stream", {"message": "Write a python function to reverse a string and run it", "model_variant": "core"}, t, 2))
        assert f.stream_aborted.wait(timeout=3), "backend never saw the hang-up"
        assert got == 2 and took < 2.0 and f.chunks_sent < 40


# ── error recovery ───────────────────────────────────────────────────────────────────────────────────────────────────────────────

def test_a_backend_failure_is_a_safe_error_and_the_next_request_recovers(client, fake):
    t, _ = _signup(client)
    h = _hdr(t)
    sid = client.post("/api/chat", json={"message": "first"}, headers=h).json()["session_id"]
    fake.fail_status = 500
    r = client.post("/api/chat", json={"message": "will fail", "session_id": sid}, headers=h)
    assert r.status_code == 500 and "fake backend failure" not in r.text and "Traceback" not in r.text
    evs = _events(client, h, {"message": "will fail", "session_id": sid})
    assert evs[-1]["type"] == "error" and "fake backend failure" not in json.dumps(evs)
    fake.fail_status = None
    assert client.post("/api/chat", json={"message": "recovered?", "session_id": sid}, headers=h).json()["response"] == "FAKE-REPLY"


def test_chat_errors_carry_a_machine_readable_code(client, fake):
    t, _ = _signup(client)
    fake.fail_status = 500
    body = client.post("/api/chat", json={"message": "will fail"}, headers=_hdr(t)).json()
    assert body.get("code") and body.get("error_id")


# ── usage limits ─────────────────────────────────────────────────────────────────────────────────────────────────────────────────

def test_daily_limit_is_enforced_with_a_clear_message_and_failures_do_not_consume_it(client, fake):
    t, _ = _signup(client)
    h = _hdr(t)
    fake.fail_status = 500
    for _ in range(3):
        assert client.post("/api/chat", json={"message": "fails"}, headers=h).status_code == 500
    fake.fail_status = None
    codes = []
    for i in range(55):
        r = client.post("/api/chat", json={"message": f"q{i}"}, headers=h)
        codes.append(r.status_code)
        if r.status_code != 200:
            break
    assert codes.count(200) == 50 and codes[-1] == 429, "free tier is 50/day and the 3 failed calls must not count"
    assert "Daily limit reached" in r.json()["error"]
    assert client.get("/api/auth/me", headers=h).json()["usage"]["messages"] == 50


# ── conversation storage ────────────────────────────────────────────────────────────────────────────────────────────────────────

def test_a_conversation_can_be_saved_listed_exported_and_reloaded(client, fake):
    t, _ = _signup(client)
    h = _hdr(t)
    sid = client.post("/api/chat", json={"message": "remember this exchange"}, headers=h).json()["session_id"]
    assert client.post("/api/session/save", json={"message": "x", "session_id": sid}, headers=h).json()["saved"] is True
    assert [s["id"] for s in client.get("/api/sessions", headers=h).json()["sessions"]] == [sid]
    md = client.get(f"/api/session/{sid}/export", headers=h).text
    assert "remember this exchange" in md and "FAKE-REPLY" in md
    assert client.post("/api/session/load", json={"session_id": sid}, headers=h).json()["loaded"] is True


# ── documents and citations ──────────────────────────────────────────────────────────────────────────────────────────────────────

def _upload(client, h):
    up = client.post("/api/docs/upload", files={"file": ("policy.txt", DOC, "text/plain")}, headers=h)
    assert up.status_code == 200 and up.json()["chunks"] == 1
    return up.json()["session_id"]


def test_uploaded_documents_are_listed_and_reach_the_model_on_the_stream_path(client, fake):
    t, _ = _signup(client)
    h = _hdr(t)
    sid = _upload(client, h)
    assert client.get("/api/docs/list", params={"session_id": sid}, headers=h).json()["total_chunks"] == 1
    _events(client, h, {"message": "What is the retention period for customer data?", "session_id": sid})
    assert any("ninety days" in json.dumps(q) for q in fake.requests)


@pytest.mark.xfail(strict=True, reason="G-024: /api/chat sends the model the uploaded document only when the question happens to trigger retrieval; a plain "
                                       "question ('What is the retention period…?') about an uploaded file is answered WITHOUT it, while /api/stream includes it.")
def test_chat_uses_an_uploaded_document_for_a_plain_question(client, fake):
    t, _ = _signup(client)
    h = _hdr(t)
    sid = _upload(client, h)
    client.post("/api/chat", json={"message": "What is the retention period for customer data?", "session_id": sid}, headers=h)
    assert any("ninety days" in json.dumps(q) for q in fake.requests)


@pytest.mark.xfail(strict=True, reason="G-027: the stream 'done' event has no structured sources (source, locator, retrieved-at); only a citation_compliance "
                                       "note, so the UI's source cards have no backend contract to render from.")
def test_stream_done_event_carries_structured_sources(client, fake):
    t, _ = _signup(client)
    h = _hdr(t)
    sid = _upload(client, h)
    done = _events(client, h, {"message": "According to the uploaded document, what is the retention period?", "session_id": sid})[-1]
    assert done["type"] == "done" and isinstance(done.get("sources"), list) and done["sources"]


# ── privacy and deletion ────────────────────────────────────────────────────────────────────────────────────────────────────────

def test_account_deletion_removes_data_signs_the_user_out_and_does_not_resurrect_titles(client, fake, monkeypatch):
    import orca.serve.account_delete as account_delete

    monkeypatch.setattr(account_delete, "ORCA_HOME", client.storage)      # production: api and the cascade share one ORCA_HOME
    ta, _ = _signup(client)
    tb, _ = _signup(client)
    sid_a = client.post("/api/chat", json={"message": "hi"}, headers=_hdr(ta)).json()["session_id"]
    for call in (lambda: client.post("/api/session/save", json={"message": "x", "session_id": sid_a}, headers=_hdr(ta)),
                 lambda: client.post("/api/remember", json={"session_id": sid_a, "fact": "my secret preference"}, headers=_hdr(ta)),
                 lambda: client.patch(f"/api/session/{sid_a}/title", json={"title": "A-PRIVATE-TITLE"}, headers=_hdr(ta))):
        assert call().status_code == 200
    sid_b = client.post("/api/chat", json={"message": "hi"}, headers=_hdr(tb)).json()["session_id"]
    client.post("/api/session/save", json={"message": "x", "session_id": sid_b}, headers=_hdr(tb))

    assert client.post("/api/auth/account/delete", json={"password": PASSWORD}, headers=_hdr(ta)).status_code == 200
    assert client.get("/api/auth/me", headers=_hdr(ta)).status_code == 401
    # a later rename by another user must not bring the deleted user's title back (the API keeps a live copy and rewrites the whole file)
    assert client.patch(f"/api/session/{sid_b}/title", json={"title": "B-title"}, headers=_hdr(tb)).status_code == 200
    blob = "".join(p.read_text(errors="replace") for p in Path(client.storage).rglob("*") if p.is_file())
    assert "A-PRIVATE-TITLE" not in blob and "my secret preference" not in blob and "B-title" in blob
    assert not list((Path(client.storage) / "memory" / "episodes").glob(f"{sid_a}*"))


# ── authentication lifecycle ─────────────────────────────────────────────────────────────────────────────────────────────────────

def test_login_accepts_the_right_password_and_rejects_the_wrong_one(client):
    t, _ = _signup(client)
    email = client.get("/api/auth/me", headers=_hdr(t)).json()["user"]["email"]
    assert client.post("/api/auth/login", json={"email": email, "password": "wrong-password-123"}).status_code == 401
    ok = client.post("/api/auth/login", json={"email": email, "password": PASSWORD})
    assert ok.status_code == 200 and client.get("/api/auth/me", headers=_hdr(ok.json()["token"])).status_code == 200
