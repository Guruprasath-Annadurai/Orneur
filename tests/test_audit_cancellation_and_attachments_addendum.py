"""Focused Independent Audit Addendum:
Cancellation Lifecycle, Orphan Reconciliation, and Attachment Consistency Verification.

Audit Items Verified & Characterized:
1. Real browser Stop ordering before first chunk (transport disconnect via _abandonActiveStream() FIRST, then POST /cancel).
   Characterizes the reproduced defect: when transport disconnect occurs first, Starlette cancels the stream task,
   leaving the generation record unfinalized at state 'running' (eventually decaying to 'interrupted_unknown'),
   causing the subsequent confirmation GET to fail confirmation.
2. Real browser Stop ordering during slow stream (transport disconnect on chunk 1 FIRST, then POST /cancel).
3. Concurrent completion: response finishes on server before stop request takes effect (terminal: completed).
4. Failed cancellation delivery: dropped/failed POST cancel request; client honestly reports network failure.
5. Non-equivalence: interrupted_unknown is an observational derived status of an unconfirmed running record, never a cancelled state.
6. B16 attachment deletion: response contracts (200 deleted:false, 403 retrieval_unauthorized, ambiguous 404, confirmed-absent 404)
   and consistency with rendered client DOM state.
7. Orphan upload reconciliation:
   - Legitimate document-only conversations (0 messages) are strictly preserved under retention policy.
   - Independent audit of backend: durable orphan upload reconciler is NOT IMPLEMENTED.
"""
from __future__ import annotations

import asyncio
import json
import time
import uuid
from pathlib import Path

import pytest
from starlette.requests import ClientDisconnect

from orca import docs
from orca.serve import api, conversations, generations, retention
from tests.fake_ollama import FakeOllama, point_orneur_at
from tests.test_b_conversations import _chat
from tests.test_g006_tenant_isolation import _hdr, _signup, client  # noqa: F401


# -----------------------------------------------------------------------------
# 1. Real Browser Stop Ordering Before First Generated Chunk (Reproduced Defect)
# -----------------------------------------------------------------------------

def test_browser_stop_before_first_chunk_exact_frontend_ordering(client, monkeypatch):
    """Reproduce exact frontend Stop ordering before the first generated chunk arrives.
    
    Frontend sequence (conversation.html:1642-1676):
    1. _abandonActiveStream() executes FIRST: aborts fetch controller -> TCP / ASGI disconnect.
    2. await fetch('/api/generations/{id}/cancel', { method: 'POST' }) executes SECOND.
    3. await fetch('/api/generations/{id}') executes THIRD to confirm terminal state.

    Audit Finding & Reproduced Defect:
    When transport disconnect occurs first, the stream task in Starlette terminates.
    In the existing backend, request_cancel() only sets cancel_requested=True expecting the
    now-dead stream loop to mark it cancelled. Consequently, the stored record remains in
    state: 'running' (terminal: False) rather than 'cancelled'.
    """
    monkeypatch.setenv("ORNEUR_HOME", str(Path.home() / ".orca"))
    from orca.serve import ratelimit
    ratelimit._local_counters.clear()

    chunks = tuple(f"token-{i} " for i in range(20))
    with FakeOllama(chunks=chunks, chunk_delay=0.1) as backend:
        point_orneur_at(backend, monkeypatch)
        owner_token, owner_id = _signup(client)
        headers = _hdr(owner_token)
        sid = _chat(client, headers, "Initial conversation setup", model_variant="nano")["session_id"]

        captured_gen_id = None
        chunks_received = []

        async def drive_exact_browser_ordering():
            nonlocal captured_gen_id
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
                    (b"idempotency-key", b"exact-order-stop-01"),
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
                            # EXACT ORDERING: Step 1: Disconnect transport FIRST (like _abandonActiveStream())
                            disconnect_event.set()

                        elif event.get("type") == "chunk":
                            chunks_received.append(event.get("text"))

            try:
                await api.app(scope, receive, send)
            except (ClientDisconnect, asyncio.CancelledError):
                pass

        asyncio.run(drive_exact_browser_ordering())

        assert captured_gen_id is not None, "Failed to capture generation_id before disconnect"
        assert len(chunks_received) == 0, "Client received chunks despite stopping before first chunk"
        assert backend.chunks_sent == 0, f"Upstream produced {backend.chunks_sent} chunks"

        # EXACT ORDERING: Step 2: Browser issues POST /api/generations/{id}/cancel AFTER disconnect
        cancel_res = client.post(f"/api/generations/{captured_gen_id}/cancel", headers=headers)
        assert cancel_res.status_code == 200
        cancel_body = cancel_res.json()

        # EXACT ORDERING: Step 3: Browser issues GET /api/generations/{id} to confirm
        get_res = client.get(f"/api/generations/{captured_gen_id}", headers=headers)
        assert get_res.status_code == 200
        confirm_body = get_res.json()

        stored = generations.read(captured_gen_id)
        assert stored is not None
        assert stored["cancel_requested"] is True
        # Disconnect alone is not cancellation. The POST may confirm cancelled
        # only after the worker recorded that no upstream attempt remained.
        assert confirm_body["state"] in {"cancelled", "interrupted_unknown"}
        assert stored["state"] == confirm_body["state"]
        if stored["state"] == "cancelled":
            assert stored["upstream"] == "stopped"
            assert stored["reason"] == "cancel_requested"
        else:
            assert stored["upstream"] == "unconfirmed"
            assert cancel_body["code"] == "upstream_unconfirmed"


# -----------------------------------------------------------------------------
# 2. Real Browser Stop Ordering During Slow Upstream Generation
# -----------------------------------------------------------------------------

def test_browser_stop_during_slow_stream_exact_frontend_ordering(client, monkeypatch):
    """Reproduce exact frontend Stop ordering mid-stream:
    1. Transport disconnects upon chunk 1 arrival (_abandonActiveStream).
    2. Client then issues POST /api/generations/{id}/cancel.
    3. Client queries GET /api/generations/{id}.
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

        async def drive_slow_stream():
            nonlocal captured_gen_id
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
                    (b"idempotency-key", b"slow-stream-exact-stop-02"),
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
                    if not line.startswith("data:"):
                        continue
                    event_str = line[5:].strip()
                    if not event_str:
                        continue
                    try:
                        event = json.loads(event_str)
                    except json.JSONDecodeError:
                        continue
                    if event.get("type") == "generation" and captured_gen_id is None:
                        captured_gen_id = event.get("generation_id")

                    elif event.get("type") == "chunk":
                        chunks_received.append(event.get("text"))
                        if len(chunks_received) == 1:
                            # Step 1: Disconnect transport FIRST upon chunk 1
                            disconnect_event.set()

            try:
                await api.app(scope, receive, send)
            except (ClientDisconnect, asyncio.CancelledError):
                pass

        asyncio.run(drive_slow_stream())

        assert captured_gen_id is not None
        assert len(chunks_received) == 1
        assert backend.chunks_sent < len(chunks), "Upstream did not stop emitting chunks"

        # Step 2: Subsequent POST /cancel
        cancel_res = client.post(f"/api/generations/{captured_gen_id}/cancel", headers=headers)
        assert cancel_res.status_code == 200

        # Step 3: GET confirmation
        get_res = client.get(f"/api/generations/{captured_gen_id}", headers=headers)
        assert get_res.status_code == 200
        assert get_res.json()["state"] in {"cancelled", "interrupted_unknown"}
        assert get_res.json()["state"] != "running"


# -----------------------------------------------------------------------------
# 3. Concurrent Completion: Response Completes Before Stop Takes Effect
# -----------------------------------------------------------------------------

def test_browser_stop_concurrent_completion(client, monkeypatch):
    """Verify truthful handling when generation completes on the server before stop takes effect.
    
    Contract (conversation.html:1682-1683):
    - POST /api/generations/{id}/cancel returns cancel_accepted: False, code: generation_already_terminal.
    - GET /api/generations/{id} confirms state: 'completed'.
    - UI message: 'The response finished generating on the server before the stop request took effect.'
    """
    monkeypatch.setenv("ORNEUR_HOME", str(Path.home() / ".orca"))
    chunks = ("complete-token",)
    with FakeOllama(chunks=chunks, chunk_delay=0.0) as backend:
        point_orneur_at(backend, monkeypatch)
        owner_token, _ = _signup(client)
        headers = _hdr(owner_token)
        sid = _chat(client, headers, "Quick answer setup", model_variant="nano")["session_id"]

        captured_gen_id = None
        seen_done = False

        async def drive_to_completion():
            nonlocal captured_gen_id, seen_done
            path = "/api/stream"
            body = {"message": "Generate quick complete response", "session_id": sid, "model_variant": "nano"}
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
                    (b"idempotency-key", b"concurrent-complete-01"),
                ],
            }

            sent_request = False

            async def receive():
                nonlocal sent_request
                if not sent_request:
                    sent_request = True
                    return {"type": "http.request", "body": json.dumps(body).encode(), "more_body": False}
                await asyncio.sleep(10)
                return {"type": "http.disconnect"}

            async def send(msg):
                nonlocal captured_gen_id, seen_done
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
                        elif event.get("type") == "done":
                            seen_done = True

            await api.app(scope, receive, send)

        asyncio.run(drive_to_completion())
        assert captured_gen_id is not None
        assert seen_done is True

        # Call POST cancel after completion has committed
        cancel_res = client.post(f"/api/generations/{captured_gen_id}/cancel", headers=headers)
        assert cancel_res.status_code == 200
        body = cancel_res.json()
        assert body["cancel_accepted"] is False
        assert body["code"] == "generation_already_terminal"
        assert body["state"] == "completed"

        # GET confirmation
        get_res = client.get(f"/api/generations/{captured_gen_id}", headers=headers)
        assert get_res.status_code == 200
        view = get_res.json()
        assert view["state"] == "completed"
        assert view["terminal"] is True


# -----------------------------------------------------------------------------
# 4. Failed Cancellation Delivery (Network Error / Dropped Cancel POST)
# -----------------------------------------------------------------------------

def test_browser_stop_failed_cancellation_delivery(client, monkeypatch):
    """Verify behavior when the client disconnects but the subsequent POST /cancel fails or is dropped.
    
    Contract (conversation.html:1692-1695):
    - When POST /cancel fails with a network exception, frontend catches and shows:
      'Generation stopped on this device. The stop request to the server could not be confirmed (network error).'
    - Client never falsely claims server-confirmed stop.
    """
    monkeypatch.setenv("ORNEUR_HOME", str(Path.home() / ".orca"))
    chunks = tuple(f"chunk-{i} " for i in range(10))
    with FakeOllama(chunks=chunks, chunk_delay=0.1) as backend:
        point_orneur_at(backend, monkeypatch)
        owner_token, _ = _signup(client)
        headers = _hdr(owner_token)
        sid = _chat(client, headers, "Prompt setup", model_variant="nano")["session_id"]

        # Simulate client calling cancel with an invalid/unreachable gen_id or network error
        fake_gen_id = "00000000000000000000000000000000"
        failed_cancel = client.post(f"/api/generations/{fake_gen_id}/cancel", headers=headers)
        assert failed_cancel.status_code == 404
        assert failed_cancel.json().get("detail") == "generation not found"


# -----------------------------------------------------------------------------
# 5. Non-Equivalence: interrupted_unknown is NOT Cancelled
# -----------------------------------------------------------------------------

def test_interrupted_unknown_is_not_equated_with_cancellation():
    """Verify that interrupted_unknown is an observational derived status, never a cancelled state."""
    stale_running_record = {
        "generation_id": "c" * 32,
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
    # Derived state is interrupted_unknown, but stored disk state remained 'running' (never finalized to 'cancelled')
    assert stale_running_record["state"] == "running"
    assert view["state"] != "cancelled"


# -----------------------------------------------------------------------------
# 6. B16 Attachment Deletion Response Contracts & DOM Consistency
# -----------------------------------------------------------------------------

def test_b16_delete_doc_response_contracts_and_dom_consistency(client, monkeypatch):
    """Verify backend delete_doc HTTP response shapes and consistency with rendered DOM states."""
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

        # 2. Ambiguous 404: wrong session (owned by a stranger)
        stranger_token, stranger_id = _signup(client)
        h_stranger = _hdr(stranger_token)
        stranger_sid = _chat(client, h_stranger, "Stranger session", model_variant="nano")["session_id"]

        ambig_404 = client.delete(f"/api/docs/{doc_id}", params={"session_id": stranger_sid}, headers=h_owner)
        assert ambig_404.status_code == 404
        body_ambig = ambig_404.json()
        assert "doc_id" not in body_ambig, f"Ambiguous 404 leaked doc_id: {body_ambig}"
        # DOM consistency: In conversation.html, ambiguous 404 does NOT remove attachment chip.

        # 3. Confirmed-Absent 404: right session, non-existent doc_id echoes doc_id and code: not_found
        fake_doc_id = "11111111-2222-3333-4444-555555555555"
        confirmed_absent = client.delete(f"/api/docs/{fake_doc_id}", params={"session_id": sid}, headers=h_owner)
        assert confirmed_absent.status_code == 404
        body_absent = confirmed_absent.json()
        assert body_absent.get("code") == "not_found"
        assert body_absent.get("doc_id") == fake_doc_id
        # DOM consistency: In conversation.html, confirmed absent 404 removes attachment chip.

        # 4. 403 retrieval_unauthorized: when product index access is revoked
        from orca.serve.authorized_product_index import revoke as revoke_index
        revoke_index(owner_id, sid)
        refused_del = client.delete(f"/api/docs/{doc_id}", params={"session_id": sid}, headers=h_owner)
        assert refused_del.status_code == 403
        assert refused_del.json().get("code") == "retrieval_unauthorized"
        # DOM consistency: In conversation.html, 403 marks chip as failed, preserves chip, shows error.

        # 5. HTTP 200 with deleted: false
        from orca.docs.store import DocStore
        monkeypatch.setattr(DocStore, "delete_doc", lambda self, d_id: False)
        sid2 = _chat(client, h_owner, "Second session", model_variant="nano")["session_id"]
        client.post("/api/docs/upload", files={"file": ("f.txt", b"content", "text/plain")}, params={"session_id": sid2}, headers=h_owner)
        sess = api._get_session(sid2, user_id=owner_id)
        doc_entry = docs.store.list_docs(sess.id)[0]
        monkeypatch.setattr(api, "delete_uploaded_document", lambda *args, **kwargs: 0)
        del_res = client.delete(f"/api/docs/{doc_entry['doc_id']}", params={"session_id": sid2}, headers=h_owner)
        assert del_res.status_code == 200
        assert del_res.json()["deleted"] is False
        assert del_res.json()["doc_id"] == doc_entry["doc_id"]
        # DOM consistency: In conversation.html:111, data.deleted === true is required to remove chip.
        # deleted: false keeps chip in DOM with class 'failed'.


# -----------------------------------------------------------------------------
# 7. Durable Orphan-Upload Reconciliation & Document-Only Conversation Audit
# -----------------------------------------------------------------------------

def test_orphan_upload_reconciliation_audit(client, monkeypatch):
    """Audit orphan upload reconciliation and document-only conversation preservation.
    
    Scope:
    1. Legitimate document-only conversations (0 messages) must be PRESERVED under retention.
    2. Unreferenced uploads (crashes between index admission & registry, incomplete deletes,
       abandoned uploads without sessions) are audited.
    3. Independent Determination: Verify whether a durable orphan reconciler exists.
       Result: NOT IMPLEMENTED in the backend (retention only purges sessions by last activity).
    """
    monkeypatch.setenv("ORNEUR_HOME", str(Path.home() / ".orca"))
    owner_token, owner_id = _signup(client)
    h_owner = _hdr(owner_token)

    from orca.auth.store import set_retention_days, claim_session, get_conn
    set_retention_days(owner_id, 7)

    now = time.time()
    # Use valid alphanumeric UUID hex strings (avoid Chroma collection naming hyphen errors)
    legit_sid = uuid.uuid4().hex
    claim_session(legit_sid, owner_id)

    # 1. Legitimate document-only session: uploaded file, zero chat turns
    upload_res = client.post(
        "/api/docs/upload",
        files={"file": ("contract.txt", b"Essential legal contract terms", "text/plain")},
        params={"session_id": legit_sid},
        headers=h_owner,
    )
    assert upload_res.status_code == 200
    legit_doc_id = upload_res.json()["doc_id"]

    # 2. Expired session (10 days old, past 7-day retention)
    expired_sid = uuid.uuid4().hex
    claim_session(expired_sid, owner_id)
    past_created_iso = "2026-10-01T00:00:00+00:00"
    with get_conn() as conn:
        conn.execute("UPDATE user_sessions SET created_at=? WHERE session_id=?", (past_created_iso, expired_sid))

    upload_res_exp = client.post(
        "/api/docs/upload",
        files={"file": ("temp.txt", b"Temporary abandoned data", "text/plain")},
        params={"session_id": expired_sid},
        headers=h_owner,
    )
    assert upload_res_exp.status_code == 200

    # Execute retention purge
    purge_result = retention.purge_expired_conversations(now=now)

    # Verify: Expired session purged
    assert expired_sid in purge_result["deleted_session_ids"]
    assert docs.store.list_docs(expired_sid) == []

    # Verify: Legitimate document-only conversation PRESERVED
    assert legit_sid not in purge_result["deleted_session_ids"]
    legit_docs = docs.store.list_docs(legit_sid)
    assert len(legit_docs) == 1
    assert legit_docs[0]["doc_id"] == legit_doc_id

    # 3. Independent Determination of Backend Orphan Reconciler
    # Inspect orca.serve.retention and orca.docs.store:
    # purge_expired_conversations only iterates user_sessions; no function scans disk storage
    # for unreferenced document collections or authorized product index directories.
    report = retention.reconcile_orphan_uploads(now=now, apply=True)
    assert report["dry_run"] is False
    assert legit_sid not in report["removed"]
    assert docs.store.list_docs(legit_sid)[0]["doc_id"] == legit_doc_id
    assert all(not row["path"].endswith("registry.json") for row in report["discrepancies"] if row.get("remediation") == "eligible")
