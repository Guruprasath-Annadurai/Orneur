"""B11: immutable message versions, edits, and regeneration.

The JSONL transcript line stays as it was written. The active version is
what the transcript, search, and export show. A failed regeneration does
not move the active pointer.
"""
from __future__ import annotations

import json
import threading
from pathlib import Path

import pytest

from orca.serve import generations, message_versions
from tests.fake_ollama import FakeOllama, point_orneur_at
from tests.test_b_conversations import _chat, _msgs
from tests.test_g006_tenant_isolation import _hdr, _signup, client  # noqa: F401


@pytest.fixture
def home(tmp_path, monkeypatch):
    import orca.brain.memory as mem

    monkeypatch.setattr(mem, "MEMORY_DIR", tmp_path)
    generations.publish_fault = None
    yield tmp_path
    generations.publish_fault = None


def _seed(role: str = "assistant", content: str = "original answer") -> str:
    message_versions.seed("sess-b11", "user-1", "message-01", role, content)
    return "message-01"


def test_edit_appends_a_version_and_keeps_the_original(home):
    message_id = _seed()
    view = message_versions.edit("sess-b11", "user-1", message_id, "edited answer")
    assert view["created"] is True
    assert view["version_count"] == 2
    assert view["active_content"] == "edited answer"
    kinds = [version["kind"] for version in view["versions"]]
    assert kinds == ["original", "edit"]
    assert view["versions"][0]["content"] == "original answer"
    stored = json.loads((Path(home) / "message_versions" / "sess-b11" / f"{message_id}.json").read_text())
    assert stored["versions"][0]["content"] == "original answer"


def test_same_edit_key_is_one_version_and_a_different_body_is_rejected(home):
    message_id = _seed()
    first = message_versions.edit("sess-b11", "user-1", message_id, "edited answer", idempotency_key="edit-key-1")
    second = message_versions.edit("sess-b11", "user-1", message_id, "edited answer", idempotency_key="edit-key-1")
    assert second["created"] is False
    assert second["version_id"] == first["version_id"]
    assert second["version_count"] == 2
    with pytest.raises(message_versions.MessageVersionMismatch):
        message_versions.edit("sess-b11", "user-1", message_id, "a different edit", idempotency_key="edit-key-1")
    assert message_versions.read("sess-b11", message_id, "user-1")["version_count"] == 2


def test_concurrent_edits_keep_every_version(home):
    message_id = _seed()
    barrier = threading.Barrier(2)

    def once(text: str) -> None:
        barrier.wait()
        message_versions.edit("sess-b11", "user-1", message_id, text)

    threads = [threading.Thread(target=once, args=(text,)) for text in ("left edit", "right edit")]
    for thread in threads:
        thread.start()
    for thread in threads:
        thread.join()
    view = message_versions.read("sess-b11", message_id, "user-1")
    contents = {version["content"] for version in view["versions"]}
    assert contents == {"original answer", "left edit", "right edit"}
    assert view["active_content"] in {"left edit", "right edit"}


def test_a_dead_regeneration_can_be_retried_without_losing_the_original(home):
    message_id = _seed()
    first = message_versions.begin_regeneration("sess-b11", "user-1", message_id, idempotency_key="regen-key-1")
    first.pop("_heartbeat").stop()
    second = message_versions.begin_regeneration("sess-b11", "user-1", message_id, idempotency_key="regen-key-1")
    heartbeat = second.pop("_heartbeat")
    try:
        assert second["created"] is True
        assert second["version_id"] != first["version_id"]
        failed = generations.read(first["generation_id"])
        assert failed["state"] == "failed"
        assert failed["reason"] == "regeneration_interrupted"
        committed = message_versions.commit_regeneration(
            "sess-b11", "user-1", message_id, second["version_id"], "recovered answer",
        )
        generations.finish(second["generation_id"], "completed")
    finally:
        heartbeat.stop()
    assert committed["active_content"] == "recovered answer"
    assert [version["content"] for version in committed["versions"] if version["committed"]] == [
        "original answer",
        "recovered answer",
    ]


def test_a_live_regeneration_rejects_a_second_caller(home):
    message_id = _seed()
    first = message_versions.begin_regeneration("sess-b11", "user-1", message_id, idempotency_key="regen-key-2")
    heartbeat = first.pop("_heartbeat")
    try:
        with pytest.raises(message_versions.MessageVersionInProgress):
            message_versions.begin_regeneration("sess-b11", "user-1", message_id, idempotency_key="regen-key-2")
        view = message_versions.read("sess-b11", message_id, "user-1")
        assert view["active_content"] == "original answer"
    finally:
        message_versions.abort_regeneration("sess-b11", "user-1", message_id, first["version_id"])
        generations.finish(first["generation_id"], "failed", reason="regeneration_failed")
        heartbeat.stop()


def test_another_owner_cannot_read_a_version_file(home):
    message_id = _seed()
    with pytest.raises(message_versions.MessageVersionDenied):
        message_versions.read("sess-b11", message_id, "user-2")


@pytest.fixture
def fake(client, monkeypatch):
    from orca.serve import ratelimit

    ratelimit._local_counters.clear()
    with FakeOllama(reply="The answer is 42.", chunks=("The answer ", "is 42.")) as backend:
        point_orneur_at(backend, monkeypatch)
        yield backend


def _assistant(client, headers, sid):
    return next(message for message in _msgs(client, headers, sid)["messages"] if message["role"] == "assistant")


def test_edit_keeps_the_jsonl_line_and_shows_the_new_text(client, fake):
    token, _user = _signup(client)
    headers = _hdr(token)
    sid = _chat(client, headers, "What is the answer?")["session_id"]
    assistant = _assistant(client, headers, sid)
    edited = client.post(
        f"/api/session/{sid}/messages/{assistant['message_id']}/edits",
        json={"content": "A revised answer."},
        headers={**headers, "Idempotency-Key": "edit-key-http"},
    )
    assert edited.status_code == 200, edited.text
    body = edited.json()
    assert body["created"] is True
    assert body["version_count"] == 2
    again = client.post(
        f"/api/session/{sid}/messages/{assistant['message_id']}/edits",
        json={"content": "A revised answer."},
        headers={**headers, "Idempotency-Key": "edit-key-http"},
    )
    assert again.status_code == 200 and again.json()["created"] is False
    assert again.json()["version_count"] == 2
    mismatch = client.post(
        f"/api/session/{sid}/messages/{assistant['message_id']}/edits",
        json={"content": "A different revision."},
        headers={**headers, "Idempotency-Key": "edit-key-http"},
    )
    assert mismatch.status_code == 422 and mismatch.json()["code"] == "idempotency_mismatch"
    shown = _assistant(client, headers, sid)
    assert shown["content"] == "A revised answer."
    assert shown["edited"] is True
    history = client.get(f"/api/session/{sid}/messages/{assistant['message_id']}/versions", headers=headers)
    assert history.status_code == 200
    assert [version["content"] for version in history.json()["versions"]] == ["The answer is 42.", "A revised answer."]
    import orca.brain.memory as mem
    raw = (Path(mem.MEMORY_DIR) / "conversations" / f"{sid}.jsonl").read_text()
    assert "The answer is 42." in raw
    assert "A revised answer." not in raw


def test_another_account_cannot_edit_or_list_versions(client, fake):
    owner, _owner_id = _signup(client)
    other, _other_id = _signup(client)
    sid = _chat(client, _hdr(owner), "What is the answer?")["session_id"]
    message_id = _assistant(client, _hdr(owner), sid)["message_id"]
    assert client.post(
        f"/api/session/{sid}/messages/{message_id}/edits",
        json={"content": "stolen"},
        headers=_hdr(other),
    ).status_code == 404
    assert client.get(f"/api/session/{sid}/messages/{message_id}/versions", headers=_hdr(other)).status_code == 404
    assert _assistant(client, _hdr(owner), sid)["content"] == "The answer is 42."


def test_regenerate_keeps_history_and_a_retry_does_not_call_the_model_again(client, fake):
    token, _user = _signup(client)
    headers = _hdr(token)
    sid = _chat(client, headers, "What is the answer?")["session_id"]
    message_id = _assistant(client, headers, sid)["message_id"]
    before = len(fake.requests)
    fake.reply = "A regenerated answer."
    first = client.post(
        f"/api/session/{sid}/messages/{message_id}/regenerate",
        headers={**headers, "Idempotency-Key": "regen-key-http"},
    )
    assert first.status_code == 200, first.text
    body = first.json()
    assert body["created"] is True
    assert body["active_content"] == "A regenerated answer."
    assert body["generation_state"] == "completed"
    assert body["generation_id"]
    assert len(fake.requests) > before
    called = len(fake.requests)
    second = client.post(
        f"/api/session/{sid}/messages/{message_id}/regenerate",
        headers={**headers, "Idempotency-Key": "regen-key-http"},
    )
    assert second.status_code == 200, second.text
    assert second.json()["created"] is False
    assert len(fake.requests) == called
    history = client.get(f"/api/session/{sid}/messages/{message_id}/versions", headers=headers).json()
    assert [version["content"] for version in history["versions"] if version["committed"]] == [
        "The answer is 42.",
        "A regenerated answer.",
    ]
    assert "What is the answer?" in json.dumps(fake.requests[before:])
    import orca.serve.api as api
    api._sessions.clear()
    assert _assistant(client, headers, sid)["content"] == "A regenerated answer."


def test_regenerate_failure_leaves_the_active_version(client, fake, monkeypatch):
    import orca.serve.api as api

    token, _user = _signup(client)
    headers = _hdr(token)
    sid = _chat(client, headers, "What is the answer?")["session_id"]
    message_id = _assistant(client, headers, sid)["message_id"]

    def explode(_sess, _prompt):
        raise RuntimeError("backend-sentinel-should-not-leak")

    monkeypatch.setattr(api, "_regenerate_text", explode)
    failed = client.post(f"/api/session/{sid}/messages/{message_id}/regenerate", headers=headers)
    assert failed.status_code >= 500, failed.text
    assert "backend-sentinel-should-not-leak" not in failed.text
    generation_id = failed.json()["generation_id"]
    status = client.get(f"/api/generations/{generation_id}", headers=headers)
    assert status.status_code == 200
    assert status.json()["state"] == "failed"
    assert status.json()["retry_eligible"] is True
    assert _assistant(client, headers, sid)["content"] == "The answer is 42."
    history = client.get(f"/api/session/{sid}/messages/{message_id}/versions", headers=headers).json()
    assert history["active_content"] == "The answer is 42."
    assert history["version_count"] == 1


def test_search_and_export_follow_the_active_version(client, fake):
    token, _user = _signup(client)
    headers = _hdr(token)
    sid = _chat(client, headers, "What is the answer?")["session_id"]
    message_id = _assistant(client, headers, sid)["message_id"]
    edited = client.post(
        f"/api/session/{sid}/messages/{message_id}/edits",
        json={"content": "Look for PHRASE-NEW in this answer."},
        headers=headers,
    )
    assert edited.status_code == 200, edited.text
    found = client.get("/api/sessions/search", params={"q": "PHRASE-NEW"}, headers=headers)
    assert found.status_code == 200 and found.json()["results"]
    missed = client.get("/api/sessions/search", params={"q": "The answer is 42"}, headers=headers)
    assert missed.json()["results"] == []
    exported = client.get(f"/api/session/{sid}/export", headers=headers)
    assert "PHRASE-NEW" in exported.text
    assert "The answer is 42." not in exported.text
    history = client.get(f"/api/session/{sid}/messages/{message_id}/versions", headers=headers).json()
    assert history["versions"][0]["content"] == "The answer is 42."


def test_deleting_the_conversation_removes_versions(client, fake):
    token, _user = _signup(client)
    headers = _hdr(token)
    sid = _chat(client, headers, "What is the answer?")["session_id"]
    import orca.brain.memory as mem
    version_dir = Path(mem.MEMORY_DIR) / "message_versions" / sid
    assert any(version_dir.glob("*.json"))
    deleted = client.delete(f"/api/session/{sid}", headers=headers)
    assert deleted.status_code == 200, deleted.text
    assert deleted.json()["stores"]["message_versions_deleted"] is True
    assert not version_dir.exists()
