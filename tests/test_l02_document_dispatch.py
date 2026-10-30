"""L02-02 — a document session must not pay for an answer it throws away.

Measured on baseline 9cb864c (fake provider, document session, one question): 4 provider requests —
  REQ0 non-streaming "answering" request from the Kernel (its output is DISCARDED for a document session; the quota unit was charged for it),
  REQ1 deep-RAG pipeline stage, REQ2 the streamed answer the user actually sees, REQ3 knowledge-graph side call.
"""
from __future__ import annotations

import json

from tests.test_g006_tenant_isolation import _hdr, _signup, client  # noqa: F401
from tests.test_product_flows_fake_ollama import DOC, _events, _upload, fake  # noqa: F401

Q = "What is the retention period for customer data?"


def _answering(fake, since):
    """Requests whose final user message is the bare question (the Kernel's own direct answer) or a streamed answer carrying the document context."""
    out = []
    for q in fake.requests[since:]:
        last = (q.get("messages") or [{}])[-1].get("content", "")
        if q.get("format") is None and ("Extract factual relationships" not in last):
            out.append((bool(q.get("stream")), last.startswith(Q), "[Document context" in last))
    return out


def test_document_session_has_exactly_one_answering_dispatch_and_it_is_streamed(client, fake):
    t, _ = _signup(client)
    h = _hdr(t)
    sid = _upload(client, h)
    n0 = len(fake.requests)
    evs = _events(client, h, {"message": Q, "session_id": sid})
    assert evs[-1]["type"] == "done"
    streamed_answers = [a for a in _answering(fake, n0) if a[0]]
    bare_kernel_answers = [a for a in _answering(fake, n0) if (not a[0]) and a[1]]
    assert len(streamed_answers) == 1, _answering(fake, n0)
    assert bare_kernel_answers == [], "the Kernel's discarded direct answer must not be generated for a document session"
    assert any("ninety days" in json.dumps(q) for q in fake.requests[n0:])            # the document still reaches the model
    assert evs[-1].get("sources"), "citations/sources still delivered"


def test_document_session_chat_route_has_no_discarded_dispatch_either(client, fake):
    t, _ = _signup(client)
    h = _hdr(t)
    sid = _upload(client, h)
    n0 = len(fake.requests)
    r = client.post("/api/chat", json={"message": Q, "session_id": sid}, headers=h)
    assert r.status_code == 200
    assert [a for a in _answering(fake, n0) if (not a[0]) and a[1]] == []
    assert any("ninety days" in json.dumps(q) for q in fake.requests[n0:])


def test_plain_session_is_unchanged_one_streamed_answer(client, fake):
    t, _ = _signup(client)
    h = _hdr(t)
    n0 = len(fake.requests)
    _events(client, h, {"message": "hello there friend"})
    ans = [q for q in fake.requests[n0:] if (q.get("messages") or [{}])[-1].get("content") == "hello there friend"]
    assert len(ans) == 1 and ans[0].get("stream") is True


def test_document_turn_quota_is_charged_once(client, fake):
    t, uid = _signup(client)
    h = _hdr(t)
    sid = _upload(client, h)
    from orca.auth.store import get_usage_today

    before = get_usage_today(uid)
    _events(client, h, {"message": Q, "session_id": sid})
    after = get_usage_today(uid)
    assert after["messages"] - before["messages"] == 1


# ── Stop / quota / single commit in a document turn ─────────────────────────────────────────────────────────────────────────────────

import asyncio

from tests.fake_ollama import FakeOllama, point_orneur_at
from tests.test_product_flows_fake_ollama import _drive


def _doc_session_with_slow_provider(client, monkeypatch, n=40, delay=0.1):
    f = FakeOllama(chunks=tuple(f"w{i} " for i in range(n)), chunk_delay=delay)
    f.__enter__()
    point_orneur_at(f, monkeypatch)
    t, uid = _signup(client)
    sid = _upload(client, _hdr(t))
    return f, t, uid, sid


def test_stop_in_a_document_turn_cancels_the_provider_charges_once_and_stores_no_turn(client, monkeypatch):
    import orca.serve.api as api
    from orca.auth.store import get_usage_today
    from orca.serve import conversations

    f, t, uid, sid = _doc_session_with_slow_provider(client, monkeypatch)
    try:
        before = get_usage_today(uid)["messages"]
        got, took = asyncio.run(_drive(api.app, "/api/stream", {"message": Q, "session_id": sid}, t, 2))
        assert f.stream_aborted.wait(timeout=3), "the provider never saw the hang-up: Stop did not cancel the document-turn generation"
        assert got == 2 and took < 3.0 and f.chunks_sent < 40
        assert get_usage_today(uid)["messages"] - before == 1, "output was produced: exactly one unit is spent (policy unchanged), never two"
        assert conversations.turns_for_session(sid) == [], "no phantom turn after Stop"
    finally:
        f.__exit__(None, None, None)


def test_a_completed_document_turn_is_committed_exactly_once(client, fake):
    from orca.serve import conversations

    t, _ = _signup(client)
    h = _hdr(t)
    sid = _upload(client, h)
    evs = _events(client, h, {"message": Q, "session_id": sid})
    done = evs[-1]
    assert done["persisted"] == "saved"
    turns = conversations.turns_for_session(sid)
    assert len(turns) == 1 and turns[0]["user_content"] == Q
    assert "".join(e["text"] for e in evs if e["type"] == "chunk") == turns[0]["assistant_content"]


def test_a_provider_failure_in_a_document_turn_refunds_the_unit_and_stores_nothing(client, fake):
    from orca.auth.store import get_usage_today
    from orca.serve import conversations

    t, uid = _signup(client)
    h = _hdr(t)
    sid = _upload(client, h)
    before = get_usage_today(uid)["messages"]
    fake.fail_status = 500
    evs = _events(client, h, {"message": Q, "session_id": sid})
    assert evs[-1]["type"] == "error" and "fake backend failure" not in json.dumps(evs)
    assert get_usage_today(uid)["messages"] == before
    assert conversations.turns_for_session(sid) == []
