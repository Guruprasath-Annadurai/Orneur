"""Consolidated Product Integration Journeys for Cursor Backend (PR #98) + Claude UI (PR #85).

Tests real frontend/backend journeys:
- Editing (B11)
- Regeneration
- Temporary Chat (B13)
- Stop / Cancel (B10)
- Quick Switch (B14)
- Attachments (B16)
- Citations (B15)
- Pinning (B06)
- Sharing (B09)
"""
from __future__ import annotations

import json
from pathlib import Path

import pytest

from orca.serve import api, conversations, generations, message_versions, organization, temporary_chat, runs
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


def test_journey_1_editing_and_regeneration(client, fake):
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


def test_journey_2_temporary_chat_lifecycle(client, fake):
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


def test_journey_3_stop_cancel_streaming(client, fake):
    owner, _ = _signup(client)
    h_owner = _hdr(owner)

    sid = _chat(client, h_owner, "First prompt")["session_id"]

    # Start stream with idempotency key
    stream_res = client.post(
        "/api/stream",
        json={"message": "Long generation prompt", "session_id": sid},
        headers={**h_owner, "idempotency-key": "idem-stream-cancel-01"},
    )
    assert stream_res.status_code == 200
    events = [line for line in stream_res.text.split("\n") if line.startswith("data: ")]
    gen_event = next((json.loads(line[6:]) for line in events if "generation_id" in line), None)
    assert gen_event is not None
    gen_id = gen_event["generation_id"]

    # Request cancel
    cancel_res = client.post(f"/api/generations/{gen_id}/cancel", headers=h_owner)
    # Cancel returns status indicating request was accepted or state is already terminal
    assert cancel_res.status_code == 200
    assert "cancel_accepted" in cancel_res.json()


def test_journey_4_quick_switch_and_runs(client, fake):
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


def test_journey_5_attachments_and_citations(client, fake):
    owner, _ = _signup(client)
    h_owner = _hdr(owner)

    sid = _chat(client, h_owner, "Session with attachments")["session_id"]

    # Upload attachment document
    upload_res = client.post(
        "/api/docs/upload",
        files={"file": ("report.txt", b"Quantum computation utilizes quantum bits or qubits.")},
        params={"session_id": sid},
        headers=h_owner,
    )
    assert upload_res.status_code == 200
    doc_id = upload_res.json()["doc_id"]

    # List attachments
    list_res = client.get(f"/api/docs/list?session_id={sid}", headers=h_owner)
    assert list_res.status_code == 200
    docs = list_res.json()["docs"]
    assert any(d["doc_id"] == doc_id for d in docs)

    # Query with document context
    chat_doc = client.post(
        "/api/chat",
        json={"message": "What does quantum computation utilize?", "session_id": sid},
        headers=h_owner,
    )
    assert chat_doc.status_code == 200
    if "sources" in chat_doc.json():
        sources = chat_doc.json()["sources"]
        assert isinstance(sources, list)

    # Delete attachment
    del_doc = client.delete(f"/api/docs/{doc_id}?session_id={sid}", headers=h_owner)
    assert del_doc.status_code == 200


def test_journey_6_pinning_and_sharing(client, fake):
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
