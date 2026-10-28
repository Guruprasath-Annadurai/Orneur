"""B13: a temporary chat has a server-owned lifetime.

History list, search, export, and long-term memory do not keep it.
Close and expiry delete the transcript before the terminal state is stored.
"""
from __future__ import annotations

import json
import time
from pathlib import Path

import pytest

from tests.fake_ollama import FakeOllama, point_orneur_at
from tests.test_b_conversations import _chat, _msgs
from tests.test_g006_tenant_isolation import _hdr, _signup, client  # noqa: F401


@pytest.fixture
def fake(client, monkeypatch):
    from orca.serve import ratelimit

    ratelimit._local_counters.clear()
    with FakeOllama(reply="The answer is 42.", chunks=("The answer ", "is 42.")) as backend:
        point_orneur_at(backend, monkeypatch)
        yield backend


def _open(client, headers, **body):
    response = client.post("/api/sessions/temporary", json=body or {"ttl_seconds": 3600}, headers=headers)
    return response


def test_temporary_chat_is_hidden_and_skips_long_term_memory(client, fake, monkeypatch):
    import orca.brain.memory as memory

    calls = []
    original = memory.MemoryEngine.commit_to_long_term

    def wrapped(self, text, meta=None):
        calls.append(self.session_id)
        return original(self, text, meta)

    monkeypatch.setattr(memory.MemoryEngine, "commit_to_long_term", wrapped)
    token, _user = _signup(client)
    headers = _hdr(token)
    normal = _chat(client, headers, "Please remember NORM-PHRASE-77")["session_id"]
    opened = _open(client, headers)
    assert opened.status_code == 200, opened.text
    body = opened.json()
    assert body["state"] == "active" and body["created"] is True
    assert body["transitions"][0]["state"] == "policy_check"
    assert body["transitions"][-1]["state"] == "active"
    sid = body["session_id"]
    again = _open(client, headers, ttl_seconds=3600, session_id=sid)
    assert again.status_code == 200 and again.json()["created"] is False
    assert again.json()["expires_at"] == body["expires_at"]
    temporary = _chat(client, headers, "Please remember TEMP-PHRASE-77", sid=sid)
    assert temporary["session_id"] == sid
    assert _msgs(client, headers, sid)["messages"][0]["content"] == "Please remember TEMP-PHRASE-77"
    listed = client.get("/api/sessions", headers=headers).json()["sessions"]
    assert normal in [item["id"] for item in listed]
    assert sid not in [item["id"] for item in listed]
    assert client.get("/api/sessions/search", params={"q": "TEMP-PHRASE-77"}, headers=headers).json()["results"] == []
    assert client.get("/api/sessions/search", params={"q": "NORM-PHRASE-77"}, headers=headers).json()["results"]
    exported = client.get(f"/api/session/{sid}/export", headers=headers)
    assert exported.status_code == 409 and exported.json()["code"] == "temporary_not_exportable"
    remembered = client.post("/api/remember", json={"fact": "keep this", "session_id": sid}, headers=headers)
    assert remembered.status_code == 409 and remembered.json()["code"] == "temporary_memory_disabled"
    assert sid not in calls and normal in calls


def test_a_normal_transcript_cannot_become_temporary(client, fake):
    token, _user = _signup(client)
    headers = _hdr(token)
    sid = _chat(client, headers, "ordinary history")["session_id"]
    refused = _open(client, headers, session_id=sid)
    assert refused.status_code == 409 and refused.json()["code"] == "temporary_not_empty"
    assert _msgs(client, headers, sid)["total"] == 2
    short = client.post("/api/sessions/temporary", json={"ttl_seconds": 10}, headers=headers)
    assert short.status_code == 400 and short.json()["code"] == "temporary_rejected"


def test_close_deletes_the_transcript_before_reporting_closed(client, fake):
    token, _user = _signup(client)
    other, _other = _signup(client)
    headers = _hdr(token)
    sid = _open(client, headers).json()["session_id"]
    _chat(client, headers, "temporary words", sid=sid)
    import orca.brain.memory as mem
    transcript = Path(mem.MEMORY_DIR) / "conversations" / f"{sid}.jsonl"
    versions = Path(mem.MEMORY_DIR) / "message_versions" / sid
    assert transcript.exists() and any(versions.glob("*.json"))
    denied = client.post(f"/api/session/{sid}/temporary/close", headers=_hdr(other))
    assert denied.status_code == 404
    assert transcript.exists()
    closed = client.post(f"/api/session/{sid}/temporary/close", headers=headers)
    assert closed.status_code == 200, closed.text
    assert closed.json()["state"] == "closed"
    assert closed.json()["deleted"] is True
    assert not transcript.exists()
    assert not versions.exists()
    # PR #111 CTO closeout review, issue 1 (2026-10-28): session_messages()
    # now carries the same _temporary_block() terminal-state guard every
    # other owned-session route already had, so a closed temporary chat's
    # transcript route correctly refuses (409 temporary_closed) instead of
    # degrading to an empty 200 -- the dedicated /temporary status route
    # below is the correct, already-existing way to confirm "this was
    # closed". Either way, the deleted content is never readable.
    messages = client.get(f"/api/session/{sid}/messages", headers=headers)
    assert messages.status_code == 409 and messages.json()["code"] == "temporary_closed"
    assert "temporary words" not in messages.text
    status = client.get(f"/api/session/{sid}/temporary", headers=headers)
    assert status.status_code == 200 and status.json()["state"] == "closed"
    assert client.get(f"/api/session/{sid}/temporary", headers=_hdr(other)).status_code == 404


def test_expiry_deletes_before_the_expired_state_is_visible(client, fake):
    from orca.serve import temporary_chat

    token, _user = _signup(client)
    headers = _hdr(token)
    sid = _open(client, headers, ttl_seconds=60).json()["session_id"]
    _chat(client, headers, "expires soon", sid=sid)
    import orca.brain.memory as mem
    transcript = Path(mem.MEMORY_DIR) / "conversations" / f"{sid}.jsonl"
    assert transcript.exists()
    result = temporary_chat.expire_due(now=time.time() + 120)
    assert sid in result["expired"]
    assert not transcript.exists()
    status = client.get(f"/api/session/{sid}/temporary", headers=headers)
    assert status.json()["state"] == "expired"
    record = json.loads((Path(mem.MEMORY_DIR) / "temporary_chats" / f"{sid}.json").read_text())
    assert record["state"] == "expired"
    assert "expires soon" not in json.dumps(record)
    direct = client.post("/api/chat", json={"message": "another turn", "session_id": sid, "model_variant": "core"}, headers=headers)
    assert direct.status_code == 409 and direct.json()["code"] == "temporary_expired"
