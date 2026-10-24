"""Consolidated Product Integration Journeys for Cursor Backend (PR #98) + Claude UI (PR #85).

Tests real frontend/backend journeys:
- Editing (B11)
- Regeneration
- Temporary Chat (B13)
- Stop / Real Active Cancel (B10)
- Quick Switch (B14)
- Attachments & Provenance Citations (B15/B16) with deletion & revocation context removal
- Pinning (B06)
- Sharing (B09)
"""
from __future__ import annotations

import hashlib
import json
import time
from pathlib import Path

import pytest

from orca.serve import api, conversations, generations, message_versions, organization, temporary_chat, runs
from orca.serve.authorized_product_index import revoke as revoke_authorized_index
from tests.fake_ollama import FakeOllama, point_orneur_at
from tests.test_b_conversations import _chat, _msgs
from tests.test_g006_tenant_isolation import _hdr, _signup, client  # noqa: F401


@pytest.fixture
def fake(client, monkeypatch):
    from orca.serve import ratelimit

    monkeypatch.setenv("ORNEUR_HOME", str(Path.home() / ".orca"))
    ratelimit._local_counters.clear()
    with FakeOllama(reply="The answer is 42.", chunks=("The answer ", "is 42.")) as backend:
        point_orneur_at(backend, monkeypatch)
        yield backend


def test_journey_1_editing_and_regeneration(client, fake, monkeypatch):
    monkeypatch.setenv("ORNEUR_HOME", str(Path.home() / ".orca"))
    owner, _ = _signup(client)
    h_owner = _hdr(owner)

    # User initiates chat
    chat_res = _chat(client, h_owner, "Initial question about science")
    sid = chat_res["session_id"]
    msgs = _msgs(client, h_owner, sid)["messages"]
    u_msg = next(m for m in msgs if m["role"] == "user")
    a_msg = next(m for m in msgs if m["role"] == "assistant")

    # 1. Edit user message
    edit_res = client.post(
        f"/api/session/{sid}/messages/{u_msg['message_id']}/edits",
        json={"content": "Revised question about astrophysics"},
        headers={**h_owner, "idempotency-key": "idem-key-journey-edit"},
    )
    assert edit_res.status_code == 200
    assert edit_res.json()["active_content"] == "Revised question about astrophysics"
    assert edit_res.json()["version_count"] == 2

    # Verify messages view displays active version
    updated_msgs = _msgs(client, h_owner, sid)["messages"]
    assert updated_msgs[0]["content"] == "Revised question about astrophysics"
    assert updated_msgs[0]["edited"] is True

    # 2. Regenerate assistant message
    regen_res = client.post(
        f"/api/session/{sid}/messages/{a_msg['message_id']}/regenerate",
        headers={**h_owner, "idempotency-key": "idem-key-journey-regen"},
    )
    assert regen_res.status_code == 200
    assert regen_res.json()["created"] is True
    assert regen_res.json()["version_count"] == 2
    assert regen_res.json()["generation_state"] == "completed"

    # Idempotent retry: does not create another version
    regen_retry = client.post(
        f"/api/session/{sid}/messages/{a_msg['message_id']}/regenerate",
        headers={**h_owner, "idempotency-key": "idem-key-journey-regen"},
    )
    assert regen_retry.status_code == 200
    assert regen_retry.json()["created"] is False


def test_journey_2_temporary_chat_lifecycle(client, fake, monkeypatch):
    monkeypatch.setenv("ORNEUR_HOME", str(Path.home() / ".orca"))
    owner, _ = _signup(client)
    h_owner = _hdr(owner)

    # 1. Start temporary chat
    temp_res = client.post("/api/sessions/temporary", json={"ttl_seconds": 300}, headers=h_owner)
    assert temp_res.status_code == 200
    sid = temp_res.json()["session_id"]

    # 2. Chat in temporary session
    _chat(client, h_owner, "Confidential query", sid=sid)

    # 3. Hidden from list and search
    sessions = client.get("/api/sessions", headers=h_owner).json()["sessions"]
    assert sid not in [s["id"] for s in sessions]

    search = client.get("/api/sessions/search", params={"q": "Confidential"}, headers=h_owner).json()["results"]
    assert len(search) == 0

    # 4. Long-term memory and export disabled
    assert client.get(f"/api/session/{sid}/export", headers=h_owner).status_code == 409
    assert client.post("/api/remember", json={"fact": "foo", "session_id": sid}, headers=h_owner).status_code == 409

    # 5. Close deletes transcript
    close_res = client.post(f"/api/session/{sid}/temporary/close", headers=h_owner)
    assert close_res.status_code == 200
    assert close_res.json()["state"] == "closed"
    assert close_res.json()["deleted"] is True


def test_journey_3_stop_cancel_streaming(client, monkeypatch):
    """Real active stream cancellation: verify immediate termination and terminal state."""
    import asyncio
    import orca.serve.api as api
    from orca.serve import ratelimit

    monkeypatch.setenv("ORNEUR_HOME", str(Path.home() / ".orca"))
    ratelimit._local_counters.clear()

    chunks = tuple(f"segment-{i} " for i in range(20))
    with FakeOllama(chunks=chunks, chunk_delay=0.04) as backend:
        point_orneur_at(backend, monkeypatch)
        owner, _ = _signup(client)
        h_owner = _hdr(owner)
        sid = _chat(client, h_owner, "First prompt", model_variant="nano")["session_id"]

        captured_gen_id = None
        chunks_received = []
        terminal_gen_event = None
        seen_done = False
        cancel_response_data = {}

        async def drive(token: str):
            nonlocal captured_gen_id, chunks_received, terminal_gen_event, seen_done, cancel_response_data
            path = "/api/stream"
            body = {"message": "Long generation prompt", "session_id": sid, "model_variant": "nano"}
            scope = {
                "type": "http",
                "method": "POST",
                "path": path,
                "raw_path": path.encode(),
                "query_string": b"",
                "root_path": "",
                "scheme": "http",
                "http_version": "1.1",
                "server": ("test", 80),
                "client": ("127.0.0.1", 1234),
                "headers": [
                    (b"content-type", b"application/json"),
                    (b"authorization", f"Bearer {token}".encode()),
                    (b"host", b"test"),
                    (b"idempotency-key", b"idem-stream-cancel-01"),
                ],
            }
            sent = False

            async def receive():
                nonlocal sent
                if not sent:
                    sent = True
                    return {"type": "http.request", "body": json.dumps(body).encode(), "more_body": False}
                await asyncio.sleep(10)
                return {"type": "http.disconnect"}

            async def send(msg):
                nonlocal captured_gen_id, chunks_received, terminal_gen_event, seen_done, cancel_response_data
                raw = msg.get("body") or b""
                for line in raw.decode("utf-8", errors="replace").splitlines():
                    if not line.startswith("data:"):
                        continue
                    event_str = line[5:].strip()
                    if not event_str:
                        continue
                    try:
                        event = json.loads(event_str)
                    except json.JSONDecodeError:
                        continue

                    event_type = event.get("type")
                    if event_type == "generation":
                        if captured_gen_id is None:
                            captured_gen_id = event.get("generation_id")
                        if event.get("state") == "cancelled":
                            terminal_gen_event = event

                    elif event_type == "chunk":
                        chunks_received.append(event.get("text"))
                        # Cancel actively as soon as chunk 1 arrives
                        if len(chunks_received) == 1 and captured_gen_id:
                            res = generations.request_cancel(captured_gen_id)
                            cancel_response_data.update(res)

                    elif event_type == "done":
                        seen_done = True

            await api.app(scope, receive, send)

        asyncio.run(drive(owner))

        assert captured_gen_id is not None, "Failed to capture generation_id from stream!"
        assert cancel_response_data.get("cancel_accepted") is True, f"Cancel was not accepted: {cancel_response_data}"
        assert terminal_gen_event is not None, "Stream did not emit cancelled generation event!"
        assert terminal_gen_event["state"] == "cancelled"
        assert terminal_gen_event["reason"] == "cancel_requested"
        assert not seen_done, "Stream emitted 'done' event despite active cancellation!"
        assert len(chunks_received) < len(chunks), f"Stream did not abort early: received {len(chunks_received)} chunks"
        assert backend.chunks_sent < len(chunks), f"FakeOllama sent all {backend.chunks_sent} chunks"

        # Confirm server-side terminal record
        stored = generations.read(captured_gen_id)
        assert stored is not None
        assert stored["state"] == "cancelled"
        assert stored["reason"] == "cancel_requested"
        view = generations.public(stored)
        assert view["state"] == "cancelled"
        assert view["terminal"] is True
        assert view["retry_eligible"] is True

        # Confirm via endpoint
        status_res = client.get(f"/api/generations/{captured_gen_id}", headers=h_owner)
        assert status_res.status_code == 200
        assert status_res.json()["state"] == "cancelled"
        assert status_res.json()["retry_eligible"] is True


def test_journey_4_quick_switch_and_runs(client, fake, monkeypatch):
    monkeypatch.setenv("ORNEUR_HOME", str(Path.home() / ".orca"))
    owner, _ = _signup(client)
    h_owner = _hdr(owner)

    # Create run
    run_res = client.post("/api/runs", headers=h_owner)
    assert run_res.status_code == 200
    run_id = run_res.json()["run_id"]

    # Session 1 in run
    s1 = _chat(client, h_owner, "Question in Tab 1")["session_id"]
    client.post(
        "/api/stream",
        json={"message": "Query 1", "session_id": s1},
        headers={**h_owner, "x-run-id": run_id},
    )

    # Quick Switch to Session 2 in run
    s2 = _chat(client, h_owner, "Question in Tab 2")["session_id"]
    client.post(
        "/api/stream",
        json={"message": "Query 2", "session_id": s2},
        headers={**h_owner, "x-run-id": run_id},
    )

    # Run correlates both generations
    run_info = client.get(f"/api/runs/{run_id}", headers=h_owner).json()
    assert run_info["count"] == 2
    session_ids = {m["session_id"] for m in run_info["members"]}
    assert s1 in session_ids and s2 in session_ids


def test_journey_5_attachments_and_citations(client, fake, monkeypatch):
    """Test document provenance with non-empty citation result, SHA-256 binding, and context removal on deletion/revocation."""
    monkeypatch.setenv("ORNEUR_HOME", str(Path.home() / ".orca"))
    owner, owner_id = _signup(client)
    h_owner = _hdr(owner)

    sid = _chat(client, h_owner, "Session with attachments")["session_id"]

    # 1. Upload attachment document with known text and compute expected SHA-256
    doc_text_1 = "Quantum computation utilizes quantum bits or qubits for superposition."
    expected_sha_1 = hashlib.sha256(doc_text_1.encode()).hexdigest()

    upload_res = client.post(
        "/api/docs/upload",
        files={"file": ("report.txt", doc_text_1.encode(), "text/plain")},
        params={"session_id": sid},
        headers=h_owner,
    )
    assert upload_res.status_code == 200
    doc_id_1 = upload_res.json()["doc_id"]

    # List attachments
    list_res = client.get(f"/api/docs/list?session_id={sid}", headers=h_owner)
    assert list_res.status_code == 200
    docs = list_res.json()["docs"]
    assert any(d["doc_id"] == doc_id_1 for d in docs)

    # 2. Query with document context -> require non-empty authorized citation with expected doc_id and SHA-256
    time.sleep(0.15)
    fake.requests.clear()
    chat_doc = client.post(
        "/api/chat",
        json={"message": "What does quantum computation utilize?", "session_id": sid, "model_variant": "nano"},
        headers=h_owner,
    )
    assert chat_doc.status_code == 200
    body = chat_doc.json()
    assert body.get("authorized_retrieval", {}).get("prompt_passage_count", 0) >= 1
    assert len(body.get("sources", [])) >= 1
    source_1 = body["sources"][0]
    assert source_1["doc_id"] == doc_id_1
    assert source_1["content_sha256"] == expected_sha_1
    assert "qubits" in source_1.get("excerpt", "")
    assert any("qubits" in json.dumps(req) for req in fake.requests), "Authorized text was not sent to model context!"

    # 3. Delete attachment -> assert deletion removes material from later model context
    del_doc = client.delete(f"/api/docs/{doc_id_1}", params={"session_id": sid}, headers=h_owner)
    assert del_doc.status_code == 200

    time.sleep(0.15)
    fake.requests.clear()
    chat_after_del = client.post(
        "/api/chat",
        json={"message": "What does quantum computation utilize?", "session_id": sid, "model_variant": "nano"},
        headers=h_owner,
    )
    assert chat_after_del.status_code == 200
    body_del = chat_after_del.json()
    assert body_del.get("authorized_retrieval", {}).get("prompt_passage_count", 0) == 0
    assert len(body_del.get("sources", [])) == 0
    assert not any("qubits" in json.dumps(req) for req in fake.requests), "Deleted material was still sent to model context!"

    # 4. Revocation test -> upload second document, query successfully, then revoke session
    doc_text_2 = "Superconducting resonators operate at cryogenic temperatures."
    expected_sha_2 = hashlib.sha256(doc_text_2.encode()).hexdigest()

    upload_res_2 = client.post(
        "/api/docs/upload",
        files={"file": ("cryo.txt", doc_text_2.encode(), "text/plain")},
        params={"session_id": sid},
        headers=h_owner,
    )
    assert upload_res_2.status_code == 200
    doc_id_2 = upload_res_2.json()["doc_id"]

    time.sleep(0.15)
    fake.requests.clear()
    chat_doc_2 = client.post(
        "/api/chat",
        json={"message": "What operates at cryogenic temperatures?", "session_id": sid, "model_variant": "nano"},
        headers=h_owner,
    )
    assert chat_doc_2.status_code == 200
    body_2 = chat_doc_2.json()
    assert body_2.get("authorized_retrieval", {}).get("prompt_passage_count", 0) >= 1
    assert any(s.get("doc_id") == doc_id_2 and s.get("content_sha256") == expected_sha_2 for s in body_2.get("sources", []))
    assert any("resonators" in json.dumps(req) for req in fake.requests), "Authorized document material was not sent to model context!"

    # Revoke session authorized index
    revoke_authorized_index(owner_id, sid)

    time.sleep(0.15)
    fake.requests.clear()
    denied_after_revoke = client.post(
        "/api/chat",
        json={"message": "What operates at cryogenic temperatures?", "session_id": sid, "model_variant": "nano"},
        headers=h_owner,
    )
    # Revocation causes authorized retrieval to fail closed (403 retrieval_unauthorized)
    assert denied_after_revoke.status_code == 403
    assert denied_after_revoke.json()["code"] == "retrieval_unauthorized"
    assert not any("resonators" in json.dumps(req) for req in fake.requests), "Revoked material reached model context!"


def test_journey_6_pinning_and_sharing(client, fake, monkeypatch):
    monkeypatch.setenv("ORNEUR_HOME", str(Path.home() / ".orca"))
    owner, _ = _signup(client)
    grantee, grantee_id = _signup(client)
    h_owner = _hdr(owner)
    h_grantee = _hdr(grantee)

    sid = _chat(client, h_owner, "A memorable discussion to pin and share")["session_id"]

    # 1. Pinning
    pin_res = client.post(f"/api/session/{sid}/pin", headers=h_owner)
    assert pin_res.status_code == 200
    assert pin_res.json()["pinned"] is True

    sessions = client.get("/api/sessions", headers=h_owner).json()["sessions"]
    pinned_map = {s["id"]: s.get("pinned") for s in sessions}
    assert pinned_map.get(sid) is True

    # 2. Sharing
    share_res = client.post(
        f"/api/session/{sid}/shares",
        json={"grantee_id": grantee_id, "ttl_seconds": 600},
        headers=h_owner,
    )
    assert share_res.status_code == 200
    share_id = share_res.json()["share_id"]
    assert "session_id" not in share_res.json()

    # Grantee reads shared messages
    shared_msgs = client.get(f"/api/shares/{share_id}/messages", headers=h_grantee)
    assert shared_msgs.status_code == 200
    assert "A memorable discussion to pin and share" in shared_msgs.text
    assert "session_id" not in shared_msgs.json()

    # Grantee incoming shares list
    incoming = client.get("/api/shares/incoming", headers=h_grantee).json()["shares"]
    assert any(s["share_id"] == share_id for s in incoming)

    # Revocation
    revoke_res = client.post(f"/api/shares/{share_id}/revoke", headers=h_owner)
    assert revoke_res.status_code == 200

    # Grantee read after revoke -> 409
    assert client.get(f"/api/shares/{share_id}/messages", headers=h_grantee).status_code == 409
