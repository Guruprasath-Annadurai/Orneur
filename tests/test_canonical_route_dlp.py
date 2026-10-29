"""LANDMARK-01 Wave 2: the canonical product routes cannot bypass the output DLP the inference routes enforce.

Reproduced before the fix: with the Kernel's direct-answer path (the common case) ``/api/stream`` sent the model's text to the browser UNSCANNED and wrote
it, secret included, into the authoritative transcript; ``/api/chat`` redacted what it returned but committed the RAW text to long-term memory and the live
agent window first. Every assertion here looks at all four places a leaked credential could land: the wire, the transcript, long-term memory and the
live agent window.
"""
from __future__ import annotations

import json
import uuid

import pytest

from tests.fake_ollama import FakeOllama, point_orneur_at
from tests.test_g006_tenant_isolation import _hdr, _signup, client  # noqa: F401  (fixture re-export)

SECRET = "sk-" + "a1B2c3D4e5F6g7H8i9J0k1L2"
AWS = "AKIAIOSFODNN7EXAMPLE"
GH = "ghp_" + "A1b2C3d4E5f6G7h8I9j0K1l2M3"
REPLY = f"keys: {SECRET} and {AWS} and {GH} end"
LEAKS = (SECRET, AWS, GH)


@pytest.fixture
def fake(client, monkeypatch):  # noqa: F811
    from orca.serve import ratelimit

    monkeypatch.setattr(ratelimit, "enforce", lambda *a, **k: None)
    # chunks must carry the secret-bearing reply: Kernel-direct /api/stream now
    # uses ModelGateway.stream() (B-01), which reads FakeOllama.chunks — not reply.
    f = FakeOllama(models=("orca-nano", "orca-core", "orca-ultra"), reply=REPLY, chunks=(REPLY,))
    f.__enter__()
    point_orneur_at(f, monkeypatch)
    yield f
    f.__exit__(None, None, None)


def _sid(label: str) -> str:
    return f"{uuid.uuid4().hex[:8]}-{label}"          # the first 8 characters are a storage key and must be unique per test


def _stream(client, token, sid, msg="show me the keys"):
    with client.stream("POST", "/api/stream", json={"message": msg, "session_id": sid, "model_variant": "nano"}, headers=_hdr(token)) as r:
        text = "".join(r.iter_text())
    return text, [json.loads(line[6:]) for line in text.splitlines() if line.startswith("data: ")]


def _assert_no_leak(client, token, sid, wire: str):
    for leak in LEAKS:
        assert leak not in wire, f"{leak[:6]}... reached the browser"
    transcript = client.get(f"/api/session/{sid}/messages", headers=_hdr(token)).text
    for leak in LEAKS:
        assert leak not in transcript, f"{leak[:6]}... was persisted to the authoritative transcript"
    export = client.get(f"/api/session/{sid}/export?format=md", headers=_hdr(token)).text
    for leak in LEAKS:
        assert leak not in export, f"{leak[:6]}... reached the export"
    from orca.serve.api import _sessions

    sess = _sessions.get(sid)
    if sess is not None:
        for hit in sess.memory.long.recall("keys", n=20) or []:
            text = hit if isinstance(hit, str) else json.dumps(hit, default=str)
            for leak in LEAKS:
                assert leak not in text, f"{leak[:6]}... was written to long-term memory"
        agent = getattr(sess, "_agent", None)
        window = json.dumps(getattr(agent, "_history", []) or [], default=str)
        for leak in LEAKS:
            assert leak not in window, f"{leak[:6]}... is in the live agent window"


def test_chat_kernel_direct_redacts_everywhere(client, fake):
    token, _ = _signup(client)
    sid = _sid("dlp-chat")
    r = client.post("/api/chat", json={"message": "show me the keys", "session_id": sid, "model_variant": "nano"}, headers=_hdr(token))
    assert r.status_code == 200
    assert "REDACTED" in r.json()["response"]
    _assert_no_leak(client, token, sid, r.text)


def test_stream_kernel_direct_redacts_everywhere(client, fake):
    token, _ = _signup(client)
    sid = _sid("dlp-strm")
    wire, events = _stream(client, token, sid)
    assert any(e["type"] == "done" for e in events)
    assert "REDACTED" in wire
    _assert_no_leak(client, token, sid, wire)


@pytest.mark.parametrize("cut", [3, 8, 14, 20, 30])
def test_stream_upstream_chunk_split_secret_is_redacted_everywhere(client, fake, cut):
    """A loaded document forces the AgentLoop (upstream, genuinely chunked) path; the secret is split across model chunks at several offsets."""
    from orca.docs import chunk_text
    from orca.serve.api import _get_session

    token, uid = _signup(client)
    sid = _sid("dlp-up")
    sess = _get_session(sid, "nano", user_id=uid)
    sess.doc_store.add_chunks(chunk_text("Orneur is a fictional architecture used in tests.", doc_id="d1", filename="t.txt"), doc_id="d1", filename="t.txt")
    i = REPLY.index(SECRET) + cut
    fake.chunks = [REPLY[:i], REPLY[i:i + 7], REPLY[i + 7:]]
    wire, events = _stream(client, token, sid)
    chunks = [e for e in events if e["type"] == "chunk"]
    assert len(chunks) >= 2 or any(e["type"] == "done" for e in events)
    joined = "".join(c["text"] for c in chunks)
    for leak in LEAKS:
        assert leak not in joined
    assert any(e["type"] == "done" for e in events)
    _assert_no_leak(client, token, sid, wire)


def test_what_the_client_saw_is_what_was_stored(client, fake):
    token, _ = _signup(client)
    sid = _sid("dlp-same")
    wire, events = _stream(client, token, sid)
    shown = "".join(e["text"] for e in events if e["type"] == "chunk")
    msgs = client.get(f"/api/session/{sid}/messages", headers=_hdr(token)).json()["messages"]
    stored = [m["content"] for m in msgs if m["role"] == "assistant"][-1]
    assert stored == shown
