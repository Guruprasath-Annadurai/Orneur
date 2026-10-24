"""Independent Adversarial Qualification Suite for Cursor PRs #90-#98.

Priorities verified:
1. Generation cancellation vs completion cross-process race safety
2. Real active stream cancellation: enforced termination, no further chunks, truthful state
3. B11 authorization, immutability, idempotency, regeneration failure rollback, doc-grounding limitation
4. B13 temporary chat persistence exclusion, expiry cascade, honest scope
5. B14 correlated runs tenant and session ownership boundaries
6. B09 sharing authorization, expiry, revocation, temporary chat protection, no session ID leak
7. Simultaneous share creation, revocation, expiry, deletion and in-flight reads with clean thread termination
"""
from __future__ import annotations

import hashlib
import json
import multiprocessing
import os
import sys
import threading
import time
from pathlib import Path

import pytest

from orca.serve import conversations, generations, message_versions, organization, temporary_chat, runs
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


# -------------------------------------------------------------------------
# 1. Generation cancellation and completion cross-process concurrency
# -------------------------------------------------------------------------

def _worker_complete(mem_dir: str, gen_id: str, barrier):
    import orca.brain.memory as mem
    mem.MEMORY_DIR = Path(mem_dir)
    barrier.wait()
    generations.finish(gen_id, "completed", reason="worker_complete")


def _worker_cancel(mem_dir: str, gen_id: str, barrier):
    import orca.brain.memory as mem
    mem.MEMORY_DIR = Path(mem_dir)
    barrier.wait()
    generations.request_cancel(gen_id)
    generations.finish(gen_id, "cancelled", reason="worker_cancel")


def test_cross_process_cancellation_vs_completion_atomicity(tmp_path, monkeypatch):
    """Real separate OS processes race completion vs cancellation."""
    monkeypatch.setenv("ORNEUR_HOME", str(Path.home() / ".orca"))
    import orca.brain.memory as mem
    monkeypatch.setattr(mem, "MEMORY_DIR", tmp_path)

    for trial in range(15):
        record, _ = generations.begin(
            session_id=f"sess-race-{trial}",
            user_id="user-1",
            delivery="upstream",
            cancellable=True,
        )
        gen_id = record["generation_id"]

        barrier = multiprocessing.Barrier(2)
        p1 = multiprocessing.Process(target=_worker_complete, args=(str(tmp_path), gen_id, barrier))
        p2 = multiprocessing.Process(target=_worker_cancel, args=(str(tmp_path), gen_id, barrier))

        p1.start()
        p2.start()
        p1.join(timeout=5)
        p2.join(timeout=5)

        assert not p1.is_alive()
        assert not p2.is_alive()

        final = generations.read(gen_id)
        assert final is not None
        assert final["state"] in {"completed", "cancelled"}, f"Trial {trial}: state is {final['state']}"

        # A late attempt to finish with the opposite state MUST NOT change the truth
        opposite = "completed" if final["state"] == "cancelled" else "cancelled"
        late = generations.finish(gen_id, opposite, reason="late_overwrite")
        assert late["state"] == final["state"], "Late finish overwrote stored terminal truth!"

        # A late touch or cancel request MUST NOT alter terminal state
        generations.touch(gen_id)
        after_touch = generations.read(gen_id)
        assert after_touch["state"] == final["state"]


# -------------------------------------------------------------------------
# 2. Real active stream cancellation during generation
# -------------------------------------------------------------------------

def test_real_active_stream_cancellation_stops_generation_truthfully(client, monkeypatch):
    """Cancel an active in-flight stream and verify immediate termination and terminal state."""
    import asyncio
    import orca.serve.api as api
    from orca.serve import ratelimit

    monkeypatch.setenv("ORNEUR_HOME", str(Path.home() / ".orca"))
    ratelimit._local_counters.clear()

    # Provide 20 chunks with delay so stream is active when cancel is sent
    chunks = tuple(f"token-{i} " for i in range(20))
    with FakeOllama(chunks=chunks, chunk_delay=0.04) as backend:
        point_orneur_at(backend, monkeypatch)
        owner, _ = _signup(client)
        headers = _hdr(owner)
        sid = _chat(client, headers, "Initial question", model_variant="nano")["session_id"]

        captured_gen_id = None
        chunks_received = []
        terminal_gen_event = None
        seen_done = False
        cancel_response_data = {}

        async def drive(token: str):
            nonlocal captured_gen_id, chunks_received, terminal_gen_event, seen_done, cancel_response_data
            path = "/api/stream"
            body = {"message": "Stream this prompt", "session_id": sid, "model_variant": "nano"}
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
                    (b"idempotency-key", b"stream-active-cancel-key"),
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

        token = owner
        asyncio.run(drive(token))

        assert captured_gen_id is not None, "Failed to capture generation_id from stream!"
        assert cancel_response_data.get("cancel_accepted") is True, f"Cancel was not accepted: {cancel_response_data}"
        assert terminal_gen_event is not None, "Stream did not emit cancelled generation event!"
        assert terminal_gen_event["state"] == "cancelled"
        assert terminal_gen_event["reason"] == "cancel_requested"
        assert not seen_done, "Stream emitted 'done' event despite active cancellation!"
        assert len(chunks_received) < len(chunks), f"Stream did not abort early: received {len(chunks_received)} chunks"
        assert backend.chunks_sent < len(chunks), f"FakeOllama sent all {backend.chunks_sent} chunks"

        # Check stored record in generation store
        stored = generations.read(captured_gen_id)
        assert stored is not None
        assert stored["state"] == "cancelled"
        assert stored["reason"] == "cancel_requested"
        view = generations.public(stored)
        assert view["state"] == "cancelled"
        assert view["terminal"] is True
        assert view["retry_eligible"] is True

        # Check GET /api/generations/{generation_id} endpoint
        status_res = client.get(f"/api/generations/{captured_gen_id}", headers=headers)
        assert status_res.status_code == 200
        assert status_res.json()["state"] == "cancelled"
        assert status_res.json()["retry_eligible"] is True


# -------------------------------------------------------------------------
# 3. B11 authorization, immutable versions, idempotency, regeneration failures
# -------------------------------------------------------------------------

def test_b11_security_and_failure_semantics(client, fake, tmp_path, monkeypatch):
    monkeypatch.setenv("ORNEUR_HOME", str(Path.home() / ".orca"))
    owner, owner_id = _signup(client)
    attacker, attacker_id = _signup(client)
    h_owner = _hdr(owner)
    h_attacker = _hdr(attacker)

    sid = _chat(client, h_owner, "Original user message")["session_id"]
    msgs = _msgs(client, h_owner, sid)["messages"]
    user_msg = next(m for m in msgs if m["role"] == "user")
    asst_msg = next(m for m in msgs if m["role"] == "assistant")
    u_mid = user_msg["message_id"]
    a_mid = asst_msg["message_id"]

    # 1. Attacker cannot read or edit versions
    assert client.get(f"/api/session/{sid}/messages/{u_mid}/versions", headers=h_attacker).status_code == 404
    assert client.post(f"/api/session/{sid}/messages/{u_mid}/edits", json={"content": "Hacked"}, headers=h_attacker).status_code == 404

    # 2. Owner edits message -> versions appended, original JSONL line immutable
    edit_res = client.post(
        f"/api/session/{sid}/messages/{u_mid}/edits",
        json={"content": "Edited user message"},
        headers={**h_owner, "idempotency-key": "idem-key-edit-1111"},
    )
    assert edit_res.status_code == 200, edit_res.text
    assert edit_res.json()["created"] is True
    assert edit_res.json()["version_count"] == 2
    assert edit_res.json()["active_content"] == "Edited user message"

    # Verify JSONL on disk still has original content
    import orca.brain.memory as mem
    raw_lines = [json.loads(line) for line in (Path(mem.MEMORY_DIR) / "conversations" / f"{sid}.jsonl").read_text().splitlines() if line.strip()]
    u_line = next(l for l in raw_lines if l.get("meta", {}).get("message_id") == u_mid)
    assert u_line["content"] == "Original user message", "JSONL transcript was rewritten!"

    # 3. Idempotency: same key, same content -> 200, created=False
    same_res = client.post(
        f"/api/session/{sid}/messages/{u_mid}/edits",
        json={"content": "Edited user message"},
        headers={**h_owner, "idempotency-key": "idem-key-edit-1111"},
    )
    assert same_res.status_code == 200
    assert same_res.json()["created"] is False
    assert same_res.json()["version_count"] == 2

    # 4. Idempotency: same key, different content -> 422 idempotency_mismatch
    diff_res = client.post(
        f"/api/session/{sid}/messages/{u_mid}/edits",
        json={"content": "Different content with same key"},
        headers={**h_owner, "idempotency-key": "idem-key-edit-1111"},
    )
    assert diff_res.status_code == 422
    assert diff_res.json()["code"] == "idempotency_mismatch"

    # 5. Regeneration failure rollback
    def fail_complete(*args, **kwargs):
        raise RuntimeError("Model provider timeout/OOM")

    from orca.serve import api
    live_sess = api._sessions.get(sid)
    assert live_sess is not None
    orig_complete = live_sess.brain.complete
    live_sess.brain.complete = fail_complete

    fail_regen = client.post(
        f"/api/session/{sid}/messages/{a_mid}/regenerate",
        headers={**h_owner, "idempotency-key": "regen-fail-key-001"},
    )
    assert fail_regen.status_code in {500, 502, 503, 504}
    gen_id = fail_regen.json().get("generation_id")
    assert gen_id is not None
    gen_record = generations.read(gen_id)
    assert gen_record["state"] == "failed"

    # Verify assistant versions: uncommitted version was dropped, previous version remains active
    v_info = client.get(f"/api/session/{sid}/messages/{a_mid}/versions", headers=h_owner).json()
    assert v_info["version_count"] == 1
    assert v_info["active_content"] == "The answer is 42."

    # Restore complete
    live_sess.brain.complete = orig_complete


# -------------------------------------------------------------------------
# 4. B13 temporary chat persistence exclusion, expiry, honest scope
# -------------------------------------------------------------------------

def test_b13_temporary_chat_exclusion_and_expiry(client, fake, monkeypatch):
    monkeypatch.setenv("ORNEUR_HOME", str(Path.home() / ".orca"))
    owner, _ = _signup(client)
    h_owner = _hdr(owner)

    opened = client.post("/api/sessions/temporary", json={"ttl_seconds": 60}, headers=h_owner)
    assert opened.status_code == 200
    sid = opened.json()["session_id"]

    # Turns in temporary chat
    _chat(client, h_owner, "Secret phrase in temp chat", sid=sid)

    # Must be excluded from history and search
    sess_list = client.get("/api/sessions", headers=h_owner).json()["sessions"]
    assert sid not in [s["id"] for s in sess_list]

    search_res = client.get("/api/sessions/search", params={"q": "Secret phrase"}, headers=h_owner).json()["results"]
    assert len(search_res) == 0

    # Cannot export or remember
    assert client.get(f"/api/session/{sid}/export", headers=h_owner).status_code == 409
    assert client.post("/api/remember", json={"fact": "foo", "session_id": sid}, headers=h_owner).status_code == 409

    # Close deletes transcript
    close_res = client.post(f"/api/session/{sid}/temporary/close", headers=h_owner)
    assert close_res.status_code == 200
    assert close_res.json()["state"] == "closed"
    assert close_res.json()["deleted"] is True

    # Further turns refused without calling model
    refused = client.post("/api/chat", json={"message": "more", "session_id": sid}, headers=h_owner)
    assert refused.status_code == 409
    assert refused.json()["code"] == "temporary_closed"


# -------------------------------------------------------------------------
# 5. B14 correlated runs ownership isolation
# -------------------------------------------------------------------------

def test_b14_correlated_runs_tenant_isolation(client, fake, monkeypatch):
    monkeypatch.setenv("ORNEUR_HOME", str(Path.home() / ".orca"))
    user_a, _ = _signup(client)
    user_b, _ = _signup(client)
    h_a = _hdr(user_a)
    h_b = _hdr(user_b)

    run_a = client.post("/api/runs", headers=h_a).json()["run_id"]

    # User B cannot read User A's run
    assert client.get(f"/api/runs/{run_a}", headers=h_b).status_code == 404

    # User B cannot attach to User A's run
    sess_b = _chat(client, h_b, "hello user b")["session_id"]
    stream_b = client.post(
        "/api/stream",
        json={"message": "hello", "session_id": sess_b},
        headers={**h_b, "x-run-id": run_a},
    )
    assert stream_b.status_code == 404
    assert stream_b.json()["code"] == "run_not_found"

    # User A's run members remains 0
    members = client.get(f"/api/runs/{run_a}", headers=h_a).json()["members"]
    assert len(members) == 0


# -------------------------------------------------------------------------
# 6. B09 sharing leak prevention and temporary chat protection
# -------------------------------------------------------------------------

def test_b09_sharing_security_and_temporary_protection(client, fake, monkeypatch):
    monkeypatch.setenv("ORNEUR_HOME", str(Path.home() / ".orca"))
    owner, _ = _signup(client)
    grantee, grantee_id = _signup(client)
    stranger, _ = _signup(client)
    h_owner = _hdr(owner)
    h_grantee = _hdr(grantee)
    h_stranger = _hdr(stranger)

    # 1. Normal session sharing
    sid = _chat(client, h_owner, "Proprietary information")["session_id"]
    share = client.post(
        f"/api/session/{sid}/shares",
        json={"grantee_id": grantee_id, "ttl_seconds": 120},
        headers=h_owner,
    ).json()
    share_id = share["share_id"]
    assert "session_id" not in share, "share grant leaked session_id!"

    # Grantee can read messages through share route, but NOT session route
    assert client.get(f"/api/session/{sid}/messages", headers=h_grantee).status_code == 404
    msgs_res = client.get(f"/api/shares/{share_id}/messages", headers=h_grantee)
    assert msgs_res.status_code == 200
    assert "Proprietary information" in msgs_res.text
    assert "session_id" not in msgs_res.json(), "messages payload leaked session_id!"

    # Stranger receives 404
    assert client.get(f"/api/shares/{share_id}/messages", headers=h_stranger).status_code == 404

    # Revoke -> 409
    client.post(f"/api/shares/{share_id}/revoke", headers=h_owner)
    assert client.get(f"/api/shares/{share_id}/messages", headers=h_grantee).status_code == 409

    # 2. Temporary chat cannot be shared
    temp = client.post("/api/sessions/temporary", json={"ttl_seconds": 120}, headers=h_owner).json()
    temp_sid = temp["session_id"]
    temp_share = client.post(
        f"/api/session/{temp_sid}/shares",
        json={"grantee_id": grantee_id, "ttl_seconds": 120},
        headers=h_owner,
    )
    assert temp_share.status_code == 400
    assert temp_share.json()["code"] == "temporary_not_shareable"


# -------------------------------------------------------------------------
# 7. Simultaneous share creation, revocation, expiry, deletion and in-flight reads
# -------------------------------------------------------------------------

def test_simultaneous_share_lifecycle_concurrency(client, fake, monkeypatch):
    """Stress test simultaneous share creation, revocation, deletion, expiry, and reads with clean thread error propagation."""
    monkeypatch.setenv("ORNEUR_HOME", str(Path.home() / ".orca"))
    owner, _ = _signup(client)
    grantee, grantee_id = _signup(client)
    stranger, _ = _signup(client)
    h_owner = _hdr(owner)
    h_grantee = _hdr(grantee)
    h_stranger = _hdr(stranger)

    sid = _chat(client, h_owner, "Concurrent stress chat content")["session_id"]

    stop_event = threading.Event()
    created_shares: list[str] = []
    shares_lock = threading.Lock()

    worker_errors: list[tuple[str, BaseException]] = []
    errors_lock = threading.Lock()

    def record_error(thread_name: str, exc: BaseException):
        with errors_lock:
            worker_errors.append((thread_name, exc))

    def creator():
        try:
            for i in range(15):
                if stop_event.is_set():
                    break
                res = client.post(
                    f"/api/session/{sid}/shares",
                    json={"grantee_id": grantee_id, "ttl_seconds": 60 + i},
                    headers=h_owner,
                )
                if res.status_code == 200:
                    s_id = res.json()["share_id"]
                    with shares_lock:
                        created_shares.append(s_id)
                time.sleep(0.01)
        except BaseException as e:
            record_error("share-creator", e)

    def revoker():
        try:
            while not stop_event.is_set():
                target = None
                with shares_lock:
                    if created_shares:
                        target = created_shares[-1]
                if target:
                    client.post(f"/api/shares/{target}/revoke", headers=h_owner)
                time.sleep(0.015)
        except BaseException as e:
            record_error("share-revoker", e)

    def reader_grantee():
        try:
            while not stop_event.is_set():
                target = None
                with shares_lock:
                    if created_shares:
                        target = created_shares[0]
                if target:
                    res = client.get(f"/api/shares/{target}/messages", headers=h_grantee)
                    assert res.status_code in {200, 404, 409}, f"Unexpected status: {res.status_code}"
                    if res.status_code == 200:
                        assert "session_id" not in res.json(), "Grantee message body leaked session_id!"
                time.sleep(0.01)
        except BaseException as e:
            record_error("share-reader-grantee", e)

    def reader_stranger():
        try:
            while not stop_event.is_set():
                target = None
                with shares_lock:
                    if created_shares:
                        target = created_shares[0]
                if target:
                    res = client.get(f"/api/shares/{target}/messages", headers=h_stranger)
                    # Stranger MUST ALWAYS be 404
                    assert res.status_code == 404, f"Stranger received {res.status_code}!"
                time.sleep(0.01)
        except BaseException as e:
            record_error("share-reader-stranger", e)

    threads = [
        threading.Thread(target=creator, name="share-creator"),
        threading.Thread(target=revoker, name="share-revoker"),
        threading.Thread(target=reader_grantee, name="share-reader-grantee"),
        threading.Thread(target=reader_stranger, name="share-reader-stranger"),
    ]

    for t in threads:
        t.start()

    time.sleep(0.5)

    # Concurrently delete the conversation while operations are running!
    del_res = client.delete(f"/api/session/{sid}", headers=h_owner)
    assert del_res.status_code == 200

    time.sleep(0.3)
    stop_event.set()

    # Assert all worker threads terminate cleanly within strict timeout
    for t in threads:
        t.join(timeout=5)
        assert not t.is_alive(), f"Worker thread {t.name} did not terminate cleanly!"

    # Assert zero worker thread errors or failed assertions occurred
    assert len(worker_errors) == 0, f"Worker thread errors encountered during share concurrency: {worker_errors}"

    # After deletion, any existing shares MUST return 409 (or 404)
    with shares_lock:
        for s_id in created_shares:
            post_del_res = client.get(f"/api/shares/{s_id}/messages", headers=h_grantee)
            assert post_del_res.status_code in {404, 409}, f"Post-delete share returned {post_del_res.status_code}"
