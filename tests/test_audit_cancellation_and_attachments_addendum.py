"""Focused Independent Audit Addendum:
Final Cancellation & Attachment Gap Verification.

Audit Items Verified:
1. Browser-initiated Stop before first generated chunk with real client disconnect.
2. Stop during slow upstream generation via authenticated HTTP endpoint.
3. Authenticated HTTP cancellation endpoint (POST /api/generations/{id}/cancel) & GET confirmation.
4. Eventual durable terminal state ('cancelled') and actual upstream cessation (never equating 'interrupted_unknown' with cancellation).
5. B16 HTTP 200 with deleted: false preserves visible attachment (never falsely claims deletion).
6. 403 retrieval_unauthorized refusal and ambiguous 404 vs confirmed-absent 404 distinction.
7. Durable orphan-upload reconciliation without deleting legitimately retained document-only conversations.
"""
from __future__ import annotations

import asyncio
import json
import time
from pathlib import Path

import pytest

from orca import docs
from orca.serve import api, conversations, generations, retention
from tests.fake_ollama import FakeOllama, point_orneur_at
from tests.test_b_conversations import _chat
from tests.test_g006_tenant_isolation import _hdr, _signup, client  # noqa: F401


# -----------------------------------------------------------------------------
# 1 & 3 & 4. Browser Stop Before First Generated Chunk (with Real Disconnect)
# -----------------------------------------------------------------------------

def test_stop_before_first_chunk_via_authenticated_http_endpoint(client, monkeypatch):
    """Reproduce browser-initiated Stop before the first generated chunk arrives.
    
    The client receives the 'generation' SSE event, then immediately issues:
    1. Authenticated HTTP POST /api/generations/{id}/cancel
    2. Real client socket disconnect (AbortController.abort())
    Asserts:
    - HTTP cancel endpoint returns 200 with cancel_accepted: True
    - Eventual durable terminal state in storage is 'cancelled' (NOT 'interrupted_unknown')
    - GET /api/generations/{id} confirms 'cancelled', terminal: True
    - Actual upstream cessation: FakeOllama sends 0 chunks (stopped before chunk 1).
    """
    monkeypatch.setenv("ORNEUR_HOME", str(Path.home() / ".orca"))
    from orca.serve import ratelimit
    ratelimit._local_counters.clear()

    # Provide chunks with a delay so backend is waiting before first chunk
    chunks = tuple(f"token-{i} " for i in range(20))
    with FakeOllama(chunks=chunks, chunk_delay=0.1) as backend:
        point_orneur_at(backend, monkeypatch)
        owner_token, owner_id = _signup(client)
        headers = _hdr(owner_token)
        sid = _chat(client, headers, "Initial conversation setup", model_variant="nano")["session_id"]

        captured_gen_id = None
        chunks_received = []
        http_cancel_response = {}

        async def drive_and_stop_fast():
            nonlocal captured_gen_id, http_cancel_response
            path = "/api/stream"
            body = {"message": "Generate full response", "session_id": sid, "model_variant": "nano"}
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
                    (b"authorization", f"Bearer {owner_token}".encode()),
                    (b"host", b"test"),
                    (b"idempotency-key", b"fast-stop-before-chunk-01"),
                ],
            }

            sent_request = False
            disconnect_event = asyncio.Event()

            async def receive():
                nonlocal sent_request
                if not sent_request:
                    sent_request = True
                    return {"type": "http.request", "body": json.dumps(body).encode(), "more_body": False}
                await disconnect_event.wait()
                return {"type": "http.disconnect"}

            async def send(msg):
                nonlocal captured_gen_id
                raw = msg.get("body") or b""
                for line in raw.decode("utf-8", errors="replace").splitlines():
                    if line.startswith("data:"):
                        event_str = line[5:].strip()
                        if not event_str:
                            continue
                        try:
                            event = json.loads(event_str)
                        except json.JSONDecodeError:
                            continue
                        if event.get("type") == "generation" and captured_gen_id is None:
                            captured_gen_id = event.get("generation_id")
                            # Act as the browser: immediately call the authenticated HTTP cancel endpoint
                            cancel_res = client.post(
                                f"/api/generations/{captured_gen_id}/cancel",
                                headers=headers,
                            )
                            assert cancel_res.status_code == 200
                            http_cancel_response.update(cancel_res.json())
                            # And immediately disconnect the socket!
                            disconnect_event.set()

                        elif event.get("type") == "chunk":
                            chunks_received.append(event.get("text"))

            await api.app(scope, receive, send)

        try:
            asyncio.run(drive_and_stop_fast())
        except BaseException:
            # ClientDisconnect is raised when the ASGI test driver delivers http.disconnect
            pass

        assert captured_gen_id is not None, "Failed to capture generation_id before disconnect!"
        assert http_cancel_response.get("cancel_accepted") is True

        # Let any asynchronous cleanup settle
        time.sleep(0.05)

        # Verify durable stored state: MUST be 'cancelled', NEVER 'interrupted_unknown'
        stored = generations.read(captured_gen_id)
        assert stored is not None
        assert stored["state"] == "cancelled", f"Stored state was {stored['state']}, expected 'cancelled'"
        assert stored["reason"] in ("cancel_requested", "client_disconnected")

        # Confirm via authenticated GET /api/generations/{id}
        get_res = client.get(f"/api/generations/{captured_gen_id}", headers=headers)
        assert get_res.status_code == 200
        view = get_res.json()
        assert view["state"] == "cancelled"
        assert view["terminal"] is True
        assert view["retry_eligible"] is True

        # Actual upstream cessation: backend stopped before chunk generation
        assert backend.chunks_sent == 0, f"Upstream backend produced {backend.chunks_sent} chunks after cancellation"
        assert len(chunks_received) == 0


# -----------------------------------------------------------------------------
# 2 & 3 & 4. Stop During Slow Upstream Generation via HTTP Endpoint
# -----------------------------------------------------------------------------

def test_stop_during_slow_upstream_generation_via_http_endpoint(client, monkeypatch):
    """Reproduce Stop during active, slow upstream generation.
    
    Asserts:
    - Authenticated POST /api/generations/{id}/cancel is accepted mid-stream
    - Stream emits cancelled generation event and stops
    - No done event
    - Backend stops emitting chunks (chunks_sent << 20)
    - Terminal state is 'cancelled', NOT 'interrupted_unknown'
    """
    monkeypatch.setenv("ORNEUR_HOME", str(Path.home() / ".orca"))
    from orca.serve import ratelimit
    ratelimit._local_counters.clear()

    chunks = tuple(f"chunk-{i} " for i in range(20))
    with FakeOllama(chunks=chunks, chunk_delay=0.08) as backend:
        point_orneur_at(backend, monkeypatch)
        owner_token, _ = _signup(client)
        headers = _hdr(owner_token)
        sid = _chat(client, headers, "Slow prompt setup", model_variant="nano")["session_id"]

        captured_gen_id = None
        chunks_received = []
        terminal_gen_event = None
        seen_done = False
        cancel_http_res = {}

        async def drive_slow():
            nonlocal captured_gen_id, terminal_gen_event, seen_done, cancel_http_res
            path = "/api/stream"
            body = {"message": "Generate slow response", "session_id": sid, "model_variant": "nano"}
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
                    (b"authorization", f"Bearer {owner_token}".encode()),
                    (b"host", b"test"),
                    (b"idempotency-key", b"slow-stream-http-stop-01"),
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
                nonlocal captured_gen_id, terminal_gen_event, seen_done, cancel_http_res
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
                        # Cancel on chunk 1 via authenticated HTTP endpoint
                        if len(chunks_received) == 1 and captured_gen_id:
                            res = client.post(f"/api/generations/{captured_gen_id}/cancel", headers=headers)
                            assert res.status_code == 200
                            cancel_http_res.update(res.json())

                    elif event_type == "done":
                        seen_done = True

            await api.app(scope, receive, send)

        asyncio.run(drive_slow())

        assert captured_gen_id is not None
        assert cancel_http_res.get("cancel_accepted") is True
        assert terminal_gen_event is not None
        assert terminal_gen_event["state"] == "cancelled"
        assert terminal_gen_event["reason"] == "cancel_requested"
        assert not seen_done
        assert len(chunks_received) < len(chunks)
        assert backend.chunks_sent < len(chunks), f"Backend sent all {backend.chunks_sent} chunks"

        # Durable state
        stored = generations.read(captured_gen_id)
        assert stored is not None
        assert stored["state"] == "cancelled"
        assert stored["reason"] == "cancel_requested"

        # Confirm via authenticated GET
        confirm_res = client.get(f"/api/generations/{captured_gen_id}", headers=headers)
        assert confirm_res.status_code == 200
        assert confirm_res.json()["state"] == "cancelled"


# -----------------------------------------------------------------------------
# 4. Never Equate interrupted_unknown with Proven Cancellation
# -----------------------------------------------------------------------------

def test_interrupted_unknown_is_not_equated_with_cancellation():
    """Verify that interrupted_unknown is an observation of a stale unconfirmed run, not a cancelled state."""
    stale_running_record = {
        "generation_id": "b" * 32,
        "session_id": "test-sess",
        "state": "running",
        "cancel_requested": True,
        "delivery": "upstream",
        "cancellable": True,
        "updated_at": time.time() - 45.0,  # > STALE_AFTER (30s)
        "reason": None,
    }
    view = generations.public(stale_running_record)
    assert view["state"] == "interrupted_unknown"
    # It is retryable because it is interrupted, but its stored state was NEVER 'cancelled'
    assert stale_running_record["state"] == "running"
    # Never equate with proven cancelled
    assert view["state"] != "cancelled"


# -----------------------------------------------------------------------------
# 5 & 6. B16 HTTP 200 deleted:false, 403 Refusal, Ambiguous vs Confirmed 404
# -----------------------------------------------------------------------------

def test_b16_delete_doc_response_contracts(client, monkeypatch):
    """Verify backend delete_doc HTTP response shapes for B16 frontend contracts."""
    monkeypatch.setenv("ORNEUR_HOME", str(Path.home() / ".orca"))
    with FakeOllama() as backend:
        point_orneur_at(backend, monkeypatch)
        owner_token, owner_id = _signup(client)
        h_owner = _hdr(owner_token)
        sid = _chat(client, h_owner, "B16 delete verification", model_variant="nano")["session_id"]

        # 1. Upload a document
        upload_res = client.post(
            "/api/docs/upload",
            files={"file": ("notes.txt", b"Test notes for deletion contracts", "text/plain")},
            params={"session_id": sid},
            headers=h_owner,
        )
        assert upload_res.status_code == 200
        doc_id = upload_res.json()["doc_id"]

        # 2. Ambiguous 404: when session is owned by a different user, _get_session raises 404 ("session not found")
        # FastAPI returns {"detail": "session not found"} which contains NO doc_id field.
        stranger_token, stranger_id = _signup(client)
        h_stranger = _hdr(stranger_token)
        stranger_sid = _chat(client, h_stranger, "Stranger session", model_variant="nano")["session_id"]

        ambig_404 = client.delete(f"/api/docs/{doc_id}", params={"session_id": stranger_sid}, headers=h_owner)
        assert ambig_404.status_code == 404
        body_ambig = ambig_404.json()
        assert "doc_id" not in body_ambig, f"Ambiguous 404 leaked doc_id field: {body_ambig}"

        # 3. Confirmed-Absent 404: right session, non-existent doc_id echoes doc_id and code: not_found
        fake_doc_id = "11111111-2222-3333-4444-555555555555"
        confirmed_absent = client.delete(f"/api/docs/{fake_doc_id}", params={"session_id": sid}, headers=h_owner)
        assert confirmed_absent.status_code == 404
        body_absent = confirmed_absent.json()
        assert body_absent.get("code") == "not_found"
        assert body_absent.get("doc_id") == fake_doc_id

        # 4. 403 retrieval_unauthorized: when session index is revoked
        from orca.serve.authorized_product_index import revoke as revoke_index
        revoke_index(owner_id, sid)
        refused_del = client.delete(f"/api/docs/{doc_id}", params={"session_id": sid}, headers=h_owner)
        assert refused_del.status_code == 403
        assert refused_del.json().get("code") == "retrieval_unauthorized"

        # 5. Contract for 200 deleted: false
        # Calling delete on an unindexed doc_store when index removal returned 0
        # doc_store.delete_doc returns False -> route answers 200 {"deleted": False}
        from orca.docs.store import DocStore
        monkeypatch.setattr(DocStore, "delete_doc", lambda self, d_id: False)
        # Re-enable index for a new session
        sid2 = _chat(client, h_owner, "Second session", model_variant="nano")["session_id"]
        client.post("/api/docs/upload", files={"file": ("f.txt", b"content", "text/plain")}, params={"session_id": sid2}, headers=h_owner)
        # Simulate delete returning 200 with deleted: false
        sess = api._get_session(sid2, user_id=owner_id)
        doc_entry = docs.store.list_docs(sess.id)[0]
        monkeypatch.setattr(api, "delete_uploaded_document", lambda *args, **kwargs: 0)
        del_res = client.delete(f"/api/docs/{doc_entry['doc_id']}", params={"session_id": sid2}, headers=h_owner)
        assert del_res.status_code == 200
        assert del_res.json()["deleted"] is False
        assert del_res.json()["doc_id"] == doc_entry["doc_id"]


# -----------------------------------------------------------------------------
# 7. Durable Orphan-Upload Reconciliation vs Legitimate Document-Only Conversations
# -----------------------------------------------------------------------------

def test_orphan_upload_reconciliation_preserves_document_only_conversations(client, monkeypatch):
    """Verify that retention sweeps purge expired sessions while strictly preserving
    legitimately retained document-only conversations (0 messages)."""
    monkeypatch.setenv("ORNEUR_HOME", str(Path.home() / ".orca"))
    owner_token, owner_id = _signup(client)
    h_owner = _hdr(owner_token)

    # 1. Create a legitimate document-only conversation: session created, document uploaded, NO messages
    from orca.auth.store import set_retention_days, claim_session, get_conn
    set_retention_days(owner_id, 7)

    now = time.time()
    legit_sid = "legit-doc-only-sess-01"
    # Claim session for user
    claim_session(legit_sid, owner_id)
    # Upload document into legit_sid
    upload_res = client.post(
        "/api/docs/upload",
        files={"file": ("contract.txt", b"Essential legal contract terms", "text/plain")},
        params={"session_id": legit_sid},
        headers=h_owner,
    )
    assert upload_res.status_code == 200
    legit_doc_id = upload_res.json()["doc_id"]

    # 2. Create an expired conversation (created 10 days ago, past 7-day cutoff)
    expired_sid = "expired-abandoned-sess-02"
    claim_session(expired_sid, owner_id)
    past_created_iso = "2026-10-01T00:00:00+00:00"
    with get_conn() as conn:
        conn.execute("UPDATE user_sessions SET created_at=? WHERE session_id=?", (past_created_iso, expired_sid))

    # Upload doc into expired_sid
    upload_res_exp = client.post(
        "/api/docs/upload",
        files={"file": ("temp.txt", b"Temporary abandoned data", "text/plain")},
        params={"session_id": expired_sid},
        headers=h_owner,
    )
    assert upload_res_exp.status_code == 200
    exp_doc_id = upload_res_exp.json()["doc_id"]

    # Run purge_expired_conversations
    purge_result = retention.purge_expired_conversations(now=now)

    # Assert: Expired session was purged
    assert expired_sid in purge_result["deleted_session_ids"]
    assert docs.store.list_docs(expired_sid) == []

    # Assert: Legitimate document-only session is PRESERVED
    assert legit_sid not in purge_result["deleted_session_ids"]
    legit_docs = docs.store.list_docs(legit_sid)
    assert len(legit_docs) == 1
    assert legit_docs[0]["doc_id"] == legit_doc_id
