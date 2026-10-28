"""Workstream B -- the assistant's conversation lifecycle, end to end against the FakeOllama TEST DOUBLE (no real model is involved anywhere in this file):
durable history, transcript, search, export, per-conversation deletion, retention, usage, tools, and idempotent retry."""
from __future__ import annotations

import json
import os
import stat
import threading
import time
import uuid
from pathlib import Path

import pytest

from tests.fake_ollama import FakeOllama, point_orneur_at
from tests.test_g006_tenant_isolation import PASSWORD, _hdr, _signup, client  # noqa: F401  (fixture re-export)
from tests.test_product_flows_fake_ollama import _events, _upload


@pytest.fixture
def fake(client, monkeypatch):
    from orca.serve import ratelimit
    ratelimit._local_counters.clear()
    with FakeOllama(reply="The answer is 42.", chunks=("The answer ", "is 42.")) as f:
        point_orneur_at(f, monkeypatch)
        yield f


def _chat(client, headers, message="hello there", sid=None, **extra):
    body = {"message": message, "model_variant": "core", **extra}
    if sid:
        body["session_id"] = sid
    r = client.post("/api/chat", json=body, headers=headers)
    assert r.status_code == 200, r.text
    return r.json()


def _msgs(client, headers, sid):
    r = client.get(f"/api/session/{sid}/messages", headers=headers)
    assert r.status_code == 200, r.text
    return r.json()


# ── durable history ────────────────────────────────────────────────────────────────────────────────────────────────────────────

def test_a_chat_turn_is_persisted_with_the_model_identity_that_served_it(client, fake):
    t, _ = _signup(client)
    sid = _chat(client, _hdr(t), "What is the answer?")["session_id"]
    tr = _msgs(client, _hdr(t), sid)
    assert tr["total"] == 2 and [m["role"] for m in tr["messages"]] == ["user", "assistant"]
    assert tr["messages"][0]["content"] == "What is the answer?" and tr["messages"][1]["content"] == "The answer is 42."
    assert tr["messages"][1]["meta"]["model_identity"]["served_model"] and tr["messages"][1]["meta"]["source_summary"]["grounding"] == "none"


def test_a_streamed_turn_is_persisted_with_message_id_and_sources(client, fake):
    t, _ = _signup(client)
    h = _hdr(t)
    sid = _upload(client, h)
    evs = _events(client, h, {"message": "According to the uploaded document, what is the retention period?", "session_id": sid})
    done = [e for e in evs if e["type"] == "done"][-1]
    last = _msgs(client, h, sid)["messages"][-1]
    assert last["role"] == "assistant" and last["meta"]["message_id"] == done["message_id"] and last["meta"]["sources"]


def test_history_survives_a_server_restart(client, fake):
    import orca.serve.api as api
    t, _ = _signup(client)
    sid = _chat(client, _hdr(t), "remember this conversation")["session_id"]
    api._sessions.clear()                                           # process restart: all in-memory sessions are gone
    tr = _msgs(client, _hdr(t), sid)
    assert tr["total"] == 2 and tr["messages"][0]["content"] == "remember this conversation"


def test_more_than_the_20_exchange_window_is_kept(client, fake):
    t, _ = _signup(client)
    h = _hdr(t)
    sid = _chat(client, h, "q0")["session_id"]
    for i in range(1, 25):
        _chat(client, h, f"q{i}", sid=sid)
    tr = _msgs(client, h, sid)
    assert tr["total"] == 50 and tr["messages"][0]["content"] == "q0"       # the in-memory window only ever held the last 40 messages


def test_anonymous_conversations_are_not_persisted(client, fake):
    sid = _chat(client, {}, "anonymous question", model_variant="nano")["session_id"]
    conv_dir = Path(__import__("orca.brain.memory", fromlist=["x"]).MEMORY_DIR) / "conversations"
    assert not (conv_dir / f"{sid}.jsonl").exists()


def test_transcript_files_are_private_and_named_by_the_full_validated_id(client, fake):
    t, _ = _signup(client)
    sid = _chat(client, _hdr(t))["session_id"]
    d = Path(__import__("orca.brain.memory", fromlist=["x"]).MEMORY_DIR) / "conversations"
    f = d / f"{sid}.jsonl"
    assert f.is_file() and stat.S_IMODE(f.stat().st_mode) == 0o600 and stat.S_IMODE(d.stat().st_mode) == 0o700


def test_a_torn_line_in_a_transcript_does_not_break_the_rest(client, fake):
    t, _ = _signup(client)
    sid = _chat(client, _hdr(t))["session_id"]
    f = Path(__import__("orca.brain.memory", fromlist=["x"]).MEMORY_DIR) / "conversations" / f"{sid}.jsonl"
    with open(f, "ab") as fh:
        fh.write(b'{"role":"user","content":"half a li')
    assert _msgs(client, _hdr(t), sid)["total"] == 2


def test_transcript_paging(client, fake):
    t, _ = _signup(client)
    h = _hdr(t)
    sid = _chat(client, h, "p0")["session_id"]
    for i in range(1, 5):
        _chat(client, h, f"p{i}", sid=sid)
    r = client.get(f"/api/session/{sid}/messages", params={"limit": 3, "offset": 4}, headers=h).json()
    assert r["total"] == 10 and [m["index"] for m in r["messages"]] == [4, 5, 6]


# ── isolation ──────────────────────────────────────────────────────────────────────────────────────────────────────────────────

def test_other_users_cannot_read_search_export_or_delete_a_conversation(client, fake):
    ta, _ = _signup(client)
    tb, _ = _signup(client)
    sid = _chat(client, _hdr(ta), "my private plan to acquire ACME-CORP-SECRET")["session_id"]
    for call in (lambda: client.get(f"/api/session/{sid}/messages", headers=_hdr(tb)),
                 lambda: client.get(f"/api/session/{sid}/export", headers=_hdr(tb)),
                 lambda: client.get(f"/api/session/{sid}/export", params={"format": "json"}, headers=_hdr(tb)),
                 lambda: client.delete(f"/api/session/{sid}", headers=_hdr(tb)),
                 lambda: client.get(f"/api/session/{sid}/messages")):
        assert call().status_code in (404, 401)
    found = client.get("/api/sessions/search", params={"q": "ACME-CORP-SECRET"}, headers=_hdr(tb)).json()
    assert found["results"] == []
    assert _msgs(client, _hdr(ta), sid)["total"] == 2                # still intact


def test_search_never_reads_a_planted_foreign_transcript(client, fake):
    """Even a transcript file for a session the caller does not own is invisible to search (the candidate set comes from the ownership table)."""
    ta, _ = _signup(client)
    tb, _ = _signup(client)
    sid = _chat(client, _hdr(ta), "nothing special")["session_id"]
    from orca.serve import conversations
    conversations.append("planted-foreign-session", "user", "ZEBRA-MARKER-12345")
    assert client.get("/api/sessions/search", params={"q": "ZEBRA-MARKER-12345"}, headers=_hdr(tb)).json()["results"] == []
    assert client.get("/api/sessions/search", params={"q": "ZEBRA-MARKER-12345"}, headers=_hdr(ta)).json()["results"] == []


def test_a_session_id_cannot_address_a_file_outside_the_conversation_directory(client, fake):
    t, _ = _signup(client)
    for bad in ("..%2F..%2Fetc%2Fpasswd", "a%00b", "x" * 80):
        r = client.get(f"/api/session/{bad}/messages", headers=_hdr(t))
        assert r.status_code in (404, 422)
    from orca.serve import conversations
    for bad in ("../x", "a/b", "", "x" * 65):
        with pytest.raises(ValueError):
            conversations.append(bad, "user", "x")


# ── search ─────────────────────────────────────────────────────────────────────────────────────────────────────────────────────

def test_search_finds_text_in_messages_and_titles_case_insensitively(client, fake):
    t, _ = _signup(client)
    h = _hdr(t)
    s1 = _chat(client, h, "Quarterly Revenue Forecast for Q3")["session_id"]
    s2 = _chat(client, h, "something unrelated")["session_id"]
    client.patch(f"/api/session/{s2}/title", json={"title": "Revenue brainstorm"}, headers=h)
    r = client.get("/api/sessions/search", params={"q": "revenue"}, headers=h).json()
    assert {x["session_id"] for x in r["results"]} == {s1, s2}
    hit = next(x for x in r["results"] if x["session_id"] == s1)
    assert "Revenue" in hit["snippet"] and hit["matches"] >= 1 and hit["in"] == "user"
    assert next(x for x in r["results"] if x["session_id"] == s2)["in"] == "title"


def test_search_treats_the_query_literally_not_as_a_pattern(client, fake):
    t, _ = _signup(client)
    h = _hdr(t)
    _chat(client, h, "plain text without punctuation")
    assert client.get("/api/sessions/search", params={"q": ".*"}, headers=h).json()["results"] == []
    assert client.get("/api/sessions/search", params={"q": "(a+)+$"}, headers=h).status_code == 200


@pytest.mark.parametrize("q", ["a", " ", "x" * 201])
def test_search_validates_the_query_length(client, fake, q):
    t, _ = _signup(client)
    r = client.get("/api/sessions/search", params={"q": q}, headers=_hdr(t))
    assert r.status_code == 422 and r.json()["code"] == "invalid_request"


def test_search_requires_a_signed_in_user(client, fake):
    r = client.get("/api/sessions/search", params={"q": "anything"})
    assert r.status_code == 401 and r.json()["code"] == "auth_required"


# ── export ─────────────────────────────────────────────────────────────────────────────────────────────────────────────────────

def test_export_markdown_and_json_carry_the_conversation_and_the_serving_model(client, fake):
    t, _ = _signup(client)
    h = _hdr(t)
    sid = _chat(client, h, "export me")["session_id"]
    md = client.get(f"/api/session/{sid}/export", headers=h)
    assert md.status_code == 200 and "ORNEUR" in md.text and "export me" in md.text and "The answer is 42." in md.text and "Answered by" in md.text
    assert md.headers["content-disposition"] == f'attachment; filename="orneur-{sid[:8]}.md"' and "Orca" not in md.text
    js = client.get(f"/api/session/{sid}/export", params={"format": "json"}, headers=h).json()
    assert js["schema"] == "orneur.conversation/1" and js["total"] == 2 and js["messages"][1]["meta"]["model_identity"]["served_model"]


# ── per-conversation deletion ──────────────────────────────────────────────────────────────────────────────────────────────────

def test_deleting_a_conversation_removes_its_content_everywhere_and_only_that(client, fake):
    t, _ = _signup(client)
    h = _hdr(t)
    keep = _chat(client, h, "Explain topic UNIQUE-KEEP briefly")["session_id"]
    gone = _chat(client, h, "Explain topic UNIQUE-GONE briefly")["session_id"]
    client.patch(f"/api/session/{gone}/title", json={"title": "UNIQUE-GONE-TITLE"}, headers=h)
    r = client.delete(f"/api/session/{gone}", headers=h)
    assert r.status_code == 200 and r.json()["deleted"] is True
    assert client.get("/api/sessions/search", params={"q": "UNIQUE-GONE"}, headers=h).json()["results"] == []
    assert _msgs(client, h, gone)["total"] == 0
    assert gone not in [s["id"] for s in client.get("/api/sessions", headers=h).json()["sessions"]]
    assert _msgs(client, h, keep)["total"] == 2
    assert client.delete(f"/api/session/{gone}", headers=h).status_code == 404         # second delete: nothing of yours by that id


def test_deleting_a_conversation_removes_its_uploaded_documents(client, fake):
    t, _ = _signup(client)
    h = _hdr(t)
    sid = _upload(client, h)
    assert client.get("/api/docs/list", params={"session_id": sid}, headers=h).json()["total_chunks"] >= 1
    assert client.delete(f"/api/session/{sid}", headers=h).status_code == 200
    from orca.docs.store import list_docs
    assert list_docs(sid) == []


def test_deleting_the_account_removes_the_transcripts(client, fake, monkeypatch):
    import orca.serve.account_delete as account_delete
    monkeypatch.setattr(account_delete, "ORCA_HOME", client.storage)
    t, _ = _signup(client)
    sid = _chat(client, _hdr(t), "account deletion test")["session_id"]
    f = Path(__import__("orca.brain.memory", fromlist=["x"]).MEMORY_DIR) / "conversations" / f"{sid}.jsonl"
    assert f.exists()
    r = client.post("/api/auth/account/delete", json={"password": PASSWORD}, headers=_hdr(t))
    assert r.status_code == 200, r.text
    assert not f.exists()


# ── retention ──────────────────────────────────────────────────────────────────────────────────────────────────────────────────

def test_retention_setting_round_trips_and_validates(client, fake):
    t, _ = _signup(client)
    h = _hdr(t)
    assert client.get("/api/auth/settings/retention", headers=h).json()["retention_days"] == 0
    assert client.put("/api/auth/settings/retention", json={"retention_days": 30}, headers=h).status_code == 200
    assert client.get("/api/auth/settings/retention", headers=h).json()["retention_days"] == 30
    for bad in (-1, 3651):
        r = client.put("/api/auth/settings/retention", json={"retention_days": bad}, headers=h)
        assert r.status_code == 422 and r.json()["code"] == "invalid_request"
    assert client.get("/api/auth/settings/retention").status_code == 401


def _backdate_session_activity(session_id: str, when: float) -> None:
    """Age authoritative SQLite turn timestamps (JSONL mtime is no longer SoT)."""
    import sqlite3

    from orca.serve import conversations

    db = conversations._turns_db()
    conn = sqlite3.connect(str(db))
    try:
        conn.execute(
            "UPDATE conversation_turns SET created_at=? WHERE session_id=?",
            (when, session_id),
        )
        conn.execute(
            "UPDATE session_authority SET updated_at=? WHERE session_id=?",
            (when, session_id),
        )
        conn.commit()
    finally:
        conn.close()
    # Keep derived export mtime in sync for any residual file-based scanners.
    p = Path(__import__("orca.brain.memory", fromlist=["x"]).MEMORY_DIR) / "conversations" / f"{session_id}.jsonl"
    if p.exists():
        os.utime(p, (when, when))


def test_the_purge_deletes_only_idle_conversations_of_users_who_asked_for_it(client, fake):
    from orca.serve.retention import purge_expired_conversations
    ta, _ = _signup(client)
    tb, _ = _signup(client)
    ha, hb = _hdr(ta), _hdr(tb)
    old_a = _chat(client, ha, "old A")["session_id"]
    new_a = _chat(client, ha, "new A")["session_id"]
    old_b = _chat(client, hb, "old B (retention 0)")["session_id"]
    client.put("/api/auth/settings/retention", json={"retention_days": 30}, headers=ha)
    long_ago = time.time() - 40 * 86400
    for sid in (old_a, old_b):
        _backdate_session_activity(sid, long_ago)
    r = purge_expired_conversations()
    assert r["deleted_session_ids"] == [old_a] and r["errors"] == 0
    assert _msgs(client, ha, old_a)["total"] == 0 and _msgs(client, ha, new_a)["total"] == 2 and _msgs(client, hb, old_b)["total"] == 2
    assert purge_expired_conversations()["deleted"] == 0                      # idempotent


def test_one_failing_session_does_not_stop_the_purge(client, fake, monkeypatch):
    import orca.serve.account_delete as ad
    from orca.serve.retention import purge_expired_conversations
    t, _ = _signup(client)
    h = _hdr(t)
    a, b = _chat(client, h, "a")["session_id"], _chat(client, h, "b")["session_id"]
    client.put("/api/auth/settings/retention", json={"retention_days": 1}, headers=h)
    aged = time.time() - 5 * 86400
    for sid in (a, b):
        _backdate_session_activity(sid, aged)
    real = ad._delete_session_data

    def flaky(sid):
        if sid == a:
            raise RuntimeError("boom")
        return real(sid)

    monkeypatch.setattr(ad, "_delete_session_data", flaky)
    r = purge_expired_conversations()
    assert r["errors"] == 1 and r["deleted_session_ids"] == [b]


# ── usage and tools ────────────────────────────────────────────────────────────────────────────────────────────────────────────

def test_usage_reports_plan_counters_and_remaining_allowance(client, fake):
    t, uid = _signup(client)
    h = _hdr(t)
    _chat(client, h, "one")
    _chat(client, h, "two")
    u = client.get("/api/usage", headers=h).json()
    assert u["plan"] == "free" and u["today"]["messages"] == 2 and u["remaining"]["messages"] == u["limits"]["messages"] - 2
    assert u["history"][0]["messages"] == 2 and u["cost_accounting"] == "not_implemented"
    from orca.auth.store import set_user_tier
    set_user_tier(uid, "pro")
    assert client.get("/api/usage", headers=h).json()["remaining"]["messages"] is None             # unlimited
    assert client.get("/api/usage").status_code == 401


def test_tools_endpoint_is_truthful_about_what_the_web_assistant_can_do(client):
    r = client.get("/api/tools").json()
    names = {t["name"] for t in r["available"]}
    assert r["surface"] == "web" and names == {"web_search", "investor_research"}
    assert {b["name"] for b in r["blocked"]} == {"shell", "run_code", "read_file", "write_file", "security_scan"}


# ── idempotent retry ───────────────────────────────────────────────────────────────────────────────────────────────────────────

def test_a_retried_request_with_the_same_key_is_answered_once_and_charged_once(client, fake):
    t, uid = _signup(client)
    h = {**_hdr(t), "Idempotency-Key": "retry-key-0001"}
    body = {"message": "do this exactly once", "model_variant": "core"}
    r1 = client.post("/api/chat", json=body, headers=h)
    calls_after_first = len(fake.requests)
    r2 = client.post("/api/chat", json=body, headers=h)
    assert r1.status_code == r2.status_code == 200 and r1.json() == r2.json()
    assert r2.headers.get("Idempotent-Replay") == "true" and "Idempotent-Replay" not in r1.headers
    assert len(fake.requests) == calls_after_first                       # no second model call
    from orca.auth.store import get_usage_today
    assert get_usage_today(uid)["messages"] == 1                         # no second charge
    assert _msgs(client, _hdr(t), r1.json()["session_id"])["total"] == 2   # no duplicated history


def test_the_same_key_with_a_different_payload_is_refused(client, fake):
    t, _ = _signup(client)
    h = {**_hdr(t), "Idempotency-Key": "retry-key-0002"}
    assert client.post("/api/chat", json={"message": "first"}, headers=h).status_code == 200
    r = client.post("/api/chat", json={"message": "second"}, headers=h)
    assert r.status_code == 422 and r.json()["code"] == "invalid_request"


def test_a_concurrent_duplicate_is_told_to_wait(client, fake):
    from orca.serve import idempotency
    t, uid = _signup(client)
    payload = {"message": "slow one", "model_variant": "core"}
    from orca.serve.api import ChatRequest
    state, _ = idempotency.begin(uid, "retry-key-0003", idempotency.request_hash(ChatRequest(**payload).model_dump()))
    assert state == "new"
    r = client.post("/api/chat", json=payload, headers={**_hdr(t), "Idempotency-Key": "retry-key-0003"})
    assert r.status_code == 409 and r.json()["code"] == "conflict"


def test_failures_are_not_cached_so_a_retry_is_a_real_retry(client, fake):
    t, _ = _signup(client)
    h = {**_hdr(t), "Idempotency-Key": "retry-key-0004"}
    fake.fail_status = 500
    assert client.post("/api/chat", json={"message": "will fail"}, headers=h).status_code == 500
    fake.fail_status = None
    r = client.post("/api/chat", json={"message": "will fail"}, headers=h)
    assert r.status_code == 200 and "Idempotent-Replay" not in r.headers


def test_keys_are_per_user_and_validated_and_ignored_for_anonymous_callers(client, fake):
    ta, _ = _signup(client)
    tb, _ = _signup(client)
    body = {"message": "same text"}
    a = client.post("/api/chat", json=body, headers={**_hdr(ta), "Idempotency-Key": "shared-key-01"})
    b = client.post("/api/chat", json=body, headers={**_hdr(tb), "Idempotency-Key": "shared-key-01"})
    assert a.status_code == b.status_code == 200 and "Idempotent-Replay" not in b.headers and a.json()["session_id"] != b.json()["session_id"]
    assert client.post("/api/chat", json=body, headers={**_hdr(ta), "Idempotency-Key": "bad key!"}).status_code == 422
    anon = [client.post("/api/chat", json=body, headers={"Idempotency-Key": "anon-key-0001"}) for _ in range(2)]
    assert all("Idempotent-Replay" not in r.headers for r in anon)


# ── the journey ────────────────────────────────────────────────────────────────────────────────────────────────────────────────

def test_user_journey_signup_chat_documents_sources_search_export_delete(client, fake):
    """One realistic path through the assistant. TEST-DOUBLE ONLY: the 'model' is FakeOllama, so this proves the product plumbing, not answer quality."""
    t, _ = _signup(client)
    h = _hdr(t)
    sid = _upload(client, h)                                                              # 1. upload a document
    r = client.post("/api/chat", json={"message": "What is the retention period for customer data?", "session_id": sid}, headers=h).json()
    assert r["sources"] and r["source_summary"]["retrieval_performed"] is True            # 2. an answer that used the document, with structured sources
    assert r["model_identity"]["served_model"]                                              # 3. which model served it
    evs = _events(client, h, {"message": "And the backup purge window?", "session_id": sid})
    assert [e["type"] for e in evs][-1] == "done"                                          # 4. a streamed follow-up
    assert _msgs(client, h, sid)["total"] == 4                                             # 5. durable history
    assert client.get("/api/sessions/search", params={"q": "retention period"}, headers=h).json()["results"][0]["session_id"] == sid   # 6. search
    assert "retention period" in client.get(f"/api/session/{sid}/export", headers=h).text  # 7. export
    assert client.delete(f"/api/session/{sid}", headers=h).status_code == 200              # 8. delete
    assert client.get("/api/sessions/search", params={"q": "retention period"}, headers=h).json()["results"] == []
