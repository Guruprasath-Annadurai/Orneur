"""Post-commit edit reconciliation and temporary-chat closure recovery."""
from __future__ import annotations

import asyncio
import json
from types import SimpleNamespace

import pytest

from orca.serve import api as api_module
from orca.serve import message_versions, temporary_chat
from orca.serve.api import MessageEditRequest


class _Line:
    def __init__(self, role: str, content: str):
        self.role = role
        self.content = content


def _user():
    return SimpleNamespace(id="user-a")


def _request(key: str = "idem-key-edit-1111"):
    return SimpleNamespace(headers={"idempotency-key": key})


def _arm(monkeypatch, tmp_path, *, history: str = "hello"):
    import orca.brain.memory as mem

    monkeypatch.setattr(mem, "MEMORY_DIR", tmp_path)
    monkeypatch.setattr(api_module, "_owned_session_or_404", lambda *args, **kwargs: None)
    monkeypatch.setattr(api_module.ratelimit, "enforce", lambda *args, **kwargs: None)
    monkeypatch.setattr(
        "orca.serve.conversations.find_message",
        lambda session_id, message_id: {"role": "user", "content": "hello", "message_id": message_id},
    )
    session = SimpleNamespace(
        _agent=SimpleNamespace(_history=[{"role": "user", "content": history}]),
        memory=SimpleNamespace(short=SimpleNamespace(_messages=[_Line("user", history)])),
        persist_to_redis=lambda: None,
    )
    api_module._sessions["sess-edit-1"] = session
    return session


def _edit(content: str = "hello there", key: str = "idem-key-edit-1111"):
    response = asyncio.run(
        api_module.edit_session_message(
            "sess-edit-1",
            "msg-11111111",
            MessageEditRequest(content=content),
            _request(key),
            _user(),
        )
    )
    if isinstance(response, dict):
        return 200, response
    return response.status_code, json.loads(response.body)


def test_empty_edit_is_rejected_before_a_version_is_committed(tmp_path, monkeypatch):
    _arm(monkeypatch, tmp_path)
    status, body = _edit("   ")
    assert status == 400
    assert body["code"] == "message_version_rejected"
    stored = message_versions.read("sess-edit-1", "msg-11111111", "user-a")
    assert stored["version_count"] == 1
    assert stored["active_content"] == "hello"


def test_persistence_failure_before_replace_does_not_commit(tmp_path, monkeypatch):
    _arm(monkeypatch, tmp_path)
    real_write = message_versions._write

    def fail_write(path, payload):
        if path.name.endswith(".json") and "hello there" in json.dumps(payload):
            raise RuntimeError("disk failed before replace")
        return real_write(path, payload)

    monkeypatch.setattr(message_versions, "_write", fail_write)
    with pytest.raises(RuntimeError, match="disk failed"):
        _edit()
    monkeypatch.setattr(message_versions, "_write", real_write)
    stored = message_versions.read("sess-edit-1", "msg-11111111", "user-a")
    assert stored["version_count"] == 1
    assert stored["active_content"] == "hello"
    status, saved = _edit()
    assert status == 200
    assert saved["created"] is True


def test_cache_failure_after_commit_keeps_the_version_and_same_key_replay_heals_it(tmp_path, monkeypatch):
    session = _arm(monkeypatch, tmp_path)
    real = api_module._replace_visible_copy
    calls = {"n": 0}

    def fail_once(*args, **kwargs):
        calls["n"] += 1
        if calls["n"] == 1:
            raise RuntimeError("cache sync failed")
        return real(*args, **kwargs)

    monkeypatch.setattr(api_module, "_replace_visible_copy", fail_once)
    status, body = _edit()
    assert status == 500
    assert body["code"] == "edit_saved_cache_uncertain"
    assert body["created"] is True
    assert body["cache_sync"] == "failed"
    assert body["authoritative_content"] == "hello there"
    stored = message_versions.read("sess-edit-1", "msg-11111111", "user-a")
    assert stored["version_count"] == 2
    assert stored["active_content"] == "hello there"
    assert session._agent._history[0]["content"] == "hello"

    status, again = _edit()
    assert status == 200
    assert again["created"] is False
    assert again["reconciled"] is True
    assert again["authoritative_content"] == "hello there"
    assert again["version_count"] == 2
    assert session._agent._history[0]["content"] == "hello there"
    assert session.memory.short._messages[0].content == "hello there"
    reread = message_versions.read("sess-edit-1", "msg-11111111", "user-a")
    assert reread["active_content"] == "hello there"
    assert reread["version_count"] == 2


def test_temporary_closure_retry_is_owner_scoped_and_lists_remaining_data(tmp_path, monkeypatch):
    import orca.brain.memory as mem
    import orca.config as orca_config

    monkeypatch.setattr(mem, "MEMORY_DIR", tmp_path)
    monkeypatch.setattr(orca_config, "ORCA_HOME", tmp_path)
    session_id = "temp-session-1"
    record = tmp_path / "temporary_chats" / f"{session_id}.json"
    record.parent.mkdir()
    record.write_text('{"user_id":"owner-a","session_id":"temp-session-1","state":"failed","intended_state":"closed","transitions":[]}\n')
    transcript = tmp_path / "conversations" / f"{session_id}.jsonl"
    transcript.parent.mkdir()
    transcript.write_text('{"role":"user","content":"secret"}\n')
    monkeypatch.setattr(temporary_chat, "_delete_contents", lambda *_args: {})

    denied = asyncio.run(api_module.retry_temporary_closure(session_id, SimpleNamespace(id="other-user")))
    assert denied.status_code == 404
    assert transcript.exists()

    blocked = asyncio.run(api_module.retry_temporary_closure(session_id, SimpleNamespace(id="owner-a")))
    assert blocked.status_code == 409
    body = json.loads(blocked.body)
    assert body["state"] == "failed"
    assert body["deleted"] is False
    assert any(row["store"] == "transcript" for row in body["remaining"])
    assert transcript.exists()

    transcript.unlink()
    cleared = asyncio.run(api_module.retry_temporary_closure(session_id, SimpleNamespace(id="owner-a")))
    assert cleared.status_code == 200
    success = json.loads(cleared.body)
    assert success["state"] == "closed"
    assert success["deleted"] is True
    assert success["remaining"] == []
    assert success["retried"] is True
    replay = asyncio.run(api_module.retry_temporary_closure(session_id, SimpleNamespace(id="owner-a")))
    assert replay.status_code == 200
    assert json.loads(replay.body)["retried"] is False
    assert json.loads(replay.body)["state"] == "closed"


def test_an_authorized_binding_blocks_a_closed_claim(tmp_path, monkeypatch):
    import orca.brain.memory as mem
    import orca.config as orca_config

    monkeypatch.setattr(mem, "MEMORY_DIR", tmp_path)
    monkeypatch.setattr(orca_config, "ORCA_HOME", tmp_path)
    session_id = "temp-session-2"
    record = tmp_path / "temporary_chats" / f"{session_id}.json"
    record.parent.mkdir()
    record.write_text('{"user_id":"owner-a","session_id":"temp-session-2","state":"failed","intended_state":"expired","transitions":[]}\n')
    binding = tmp_path / "authorized_index" / "owner-a" / "bindings" / f"{session_id}.json"
    binding.parent.mkdir(parents=True)
    binding.write_text('{"user_id":"owner-a","product_session_id":"temp-session-2","revoked":true}\n')
    monkeypatch.setattr(temporary_chat, "_delete_contents", lambda *_args: {})
    monkeypatch.setattr(temporary_chat, "_transcript_gone", lambda *_args: True)

    response = asyncio.run(api_module.retry_temporary_closure(session_id, SimpleNamespace(id="owner-a")))
    assert response.status_code == 409
    body = json.loads(response.body)
    assert body["state"] == "failed"
    assert body["deleted"] is False
    assert any(row["store"] == "authorized_binding" for row in body["remaining"])
    assert binding.exists()
