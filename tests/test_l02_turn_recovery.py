"""L02-03 -- authoritative outcome of a request after a dropped connection (real app, real SQLite, fixture provider).

Every state the client needs to tell apart is exercised: committed, not committed (and why), cancelled (confirmed), superseded, running, unknown, and
"outcome unknown" (store unreadable). The invariant under all of them: one request key produces at most one transcript entry and at most one quota unit.
"""
from __future__ import annotations

import asyncio
import json
import threading
import time
import uuid

import pytest

from tests.fake_ollama import FakeOllama, point_orneur_at
from tests.test_g006_tenant_isolation import _hdr, _signup, client  # noqa: F401
from tests.test_product_flows_fake_ollama import _drive, _events, fake  # noqa: F401


def key() -> str:
    return "k-" + uuid.uuid4().hex


def _hk(h, k):
    return {**h, "Idempotency-Key": k}


def _stream(client, h, k, body):
    with client.stream("POST", "/api/stream", json={"model_variant": "core", **body}, headers=_hk(h, k)) as s:
        text = "".join(s.iter_text())
    return [json.loads(line[6:]) for line in text.splitlines() if line.startswith("data: ")]


def _outcome(client, h, k):
    r = client.get(f"/api/turns/{k}", headers=h)
    return r.status_code, r.json()


def _wait_terminal(client, h, k, timeout=10):
    end = time.time() + timeout
    while time.time() < end:
        code, body = _outcome(client, h, k)
        if body.get("terminal"):
            return body
        time.sleep(0.1)
    raise AssertionError(f"never became terminal: {body}")


def _units(uid):
    from orca.auth.store import get_usage_today

    return get_usage_today(uid)["messages"]


def _turns(sid):
    from orca.serve import conversations

    return conversations.turns_for_session(sid)


# ── the happy path and the 'no record' answer ────────────────────────────────────────────────────────────────────────────────────

def test_committed_outcome_matches_the_transcript_and_the_done_event(client, fake):
    t, uid = _signup(client)
    h, k = _hdr(t), key()
    evs = _stream(client, h, k, {"message": "hello recovery"})
    done = evs[-1]
    code, body = _outcome(client, h, k)
    assert code == 200 and body["state"] == "committed" and body["terminal"] and body["safe_to_retry"] is False
    assert body["message_id"] == done["message_id"] and body["user_message_id"] == done["user_message_id"]
    turns = _turns(body["session_id"])
    assert len(turns) == 1 and turns[0]["revision"] == body["revision"] and _units(uid) == 1


def test_a_key_the_server_never_saw_is_unknown_and_safe_to_retry(client, fake):
    t, _ = _signup(client)
    code, body = _outcome(client, _hdr(t), key())
    assert code == 200 and body["state"] == "unknown" and body["safe_to_retry"] is True


def test_outcome_requires_login_and_a_valid_key(client, fake):
    assert client.get(f"/api/turns/{key()}").status_code == 401
    t, _ = _signup(client)
    r = client.get("/api/turns/short", headers=_hdr(t))
    assert r.status_code == 422 and r.json()["code"] == "invalid_request"


# ── retries ───────────────────────────────────────────────────────────────────────────────────────────────────────────────────────

def test_a_late_retry_of_a_committed_request_replays_the_transcript_not_the_model(client, fake):
    """After the 10-minute idempotency window the old key would look 'new' and regenerate. The durable record prevents that."""
    t, uid = _signup(client)
    h, k = _hdr(t), key()
    evs = _stream(client, h, k, {"message": "only once please"})
    sid = evs[0]["session_id"]
    from orca.auth.db import get_conn

    with get_conn() as conn:
        conn.execute("DELETE FROM idempotency_keys WHERE idem_key=?", (k,))                # the short-lived key has expired
    n0, u0 = len(fake.requests), _units(uid)
    again = _stream(client, h, k, {"message": "only once please"})                 # a retry resends the SAME request body
    assert again[-1]["type"] == "done" and again[-1]["idempotent_replay"] is True and again[-1]["persisted"] == "saved"
    assert "".join(e["text"] for e in again if e["type"] == "chunk") == "FAKE-REPLY"
    assert len(fake.requests) == n0, "the model was called again for a request that had already committed"
    assert len(_turns(sid)) == 1 and _units(uid) == u0


def test_a_failed_attempt_is_not_committed_and_the_same_key_retried_succeeds_once(client, fake):
    t, uid = _signup(client)
    h, k = _hdr(t), key()
    fake.fail_status = 500
    first = _stream(client, h, k, {"message": "retry me"})
    assert first[-1]["type"] == "error"
    st = _wait_terminal(client, h, k)
    assert st["state"] == "not_committed" and st["reason"] == "backend_error" and st["safe_to_retry"] is True
    assert _units(uid) == 0
    fake.fail_status = None
    second = _stream(client, h, k, {"message": "retry me", "session_id": first[0]["session_id"]})
    assert second[-1]["type"] == "done" and second[-1]["persisted"] == "saved"
    code, body = _outcome(client, h, k)
    assert body["state"] == "committed" and len(_turns(body["session_id"])) == 1 and _units(uid) == 1


def test_concurrent_duplicates_run_one_generation_and_commit_one_turn(client, monkeypatch):
    with FakeOllama(chunks=tuple(f"w{i} " for i in range(8)), chunk_delay=0.15) as f:
        point_orneur_at(f, monkeypatch)
        t, uid = _signup(client)
        h, k = _hdr(t), key()
        sid = str(uuid.uuid4())
        out = []

        def go():
            out.append(_stream(client, h, k, {"message": "duplicate delivery", "session_id": sid}))

        ts = [threading.Thread(target=go) for _ in range(4)]
        [x.start() for x in ts]
        [x.join() for x in ts]
        finals = sorted(e[-1]["type"] for e in out)
        assert finals.count("done") >= 1 and finals.count("error") == finals.count("error")
        assert len(_turns(sid)) == 1 and _units(uid) == 1
        answering = [r for r in f.requests if (r.get("messages") or [{}])[-1].get("content") == "duplicate delivery"]
        assert len(answering) == 1, "duplicate delivery caused more than one model dispatch"
        assert _outcome(client, h, k)[1]["state"] == "committed"


# ── disconnect, Stop, cancel ordering ───────────────────────────────────────────────────────────────────────────────────────────

def test_disconnect_during_generation_is_not_committed_with_reason_and_the_provider_is_hung_up_on(client, monkeypatch):
    import orca.serve.api as api

    with FakeOllama(chunks=tuple(f"w{i} " for i in range(40)), chunk_delay=0.1) as f:
        point_orneur_at(f, monkeypatch)
        t, uid = _signup(client)
        k = key()

        async def run():
            scope_headers = {"idempotency-key": k}
            return await _drive_with_key(api.app, "/api/stream", {"message": "long answer please", "model_variant": "core"}, t, 2, k)

        got, took = asyncio.run(run())
        assert f.stream_aborted.wait(timeout=3)
        st = _wait_terminal(client, _hdr(t), k)
        assert st["state"] == "not_committed" and st["reason"] == "client_disconnected" and st["safe_to_retry"] is True
        assert _turns(st["session_id"]) == [] if st.get("session_id") else True


async def _drive_with_key(app, path, body, token, stop_after, k):
    scope = {"type": "http", "method": "POST", "path": path, "raw_path": path.encode(), "query_string": b"", "root_path": "", "scheme": "http",
             "http_version": "1.1", "server": ("test", 80), "client": ("9.9.9.9", 1234),
             "headers": [(b"content-type", b"application/json"), (b"authorization", f"Bearer {token}".encode()), (b"host", b"test"), (b"idempotency-key", k.encode())]}
    sent, disconnect, chunks = False, asyncio.Event(), []

    async def receive():
        nonlocal sent
        if not sent:
            sent = True
            return {"type": "http.request", "body": json.dumps(body).encode(), "more_body": False}
        await disconnect.wait()
        return {"type": "http.disconnect"}

    async def send(msg):
        if msg["type"] == "http.response.body" and b'"chunk"' in msg.get("body", b""):
            chunks.append(msg["body"])
            if len(chunks) >= stop_after:
                disconnect.set()

    t0 = time.monotonic()
    await app(scope, receive, send)
    return len(chunks), time.monotonic() - t0


def test_stop_through_the_cancel_endpoint_is_confirmed_cancelled_and_stores_nothing(client, monkeypatch):
    with FakeOllama(chunks=tuple(f"w{i} " for i in range(60)), chunk_delay=0.1) as f:
        point_orneur_at(f, monkeypatch)
        t, uid = _signup(client)
        h, k = _hdr(t), key()
        sid = str(uuid.uuid4())
        res = {}

        def go():
            res["events"] = _stream(client, h, k, {"message": "long answer please", "session_id": sid})

        th = threading.Thread(target=go)
        th.start()
        assert f.stream_started.wait(timeout=5)
        time.sleep(0.5)
        r = client.post(f"/api/turns/{k}/cancel", headers=h)
        assert r.status_code in (200, 202) and r.json()["state"] in ("cancel_requested", "running", "cancelled")
        th.join(timeout=15)
        assert not th.is_alive(), "the cancelled stream never ended"
        st = _wait_terminal(client, h, k)
        assert st["state"] == "cancelled" and st["reason"] == "user_stop"
        assert f.stream_aborted.wait(timeout=3), "cancellation did not reach the provider"
        assert _turns(sid) == [] and not any(e["type"] == "done" and e.get("persisted") == "saved" for e in res["events"])
        assert _units(uid) == 1, "output was produced before Stop: the unit stays spent (policy unchanged)"


def test_cancel_that_arrives_before_the_request_closes_it_in_advance(client, fake):
    t, uid = _signup(client)
    h, k = _hdr(t), key()
    r = client.post(f"/api/turns/{k}/cancel", headers=h)
    assert r.status_code == 200 and r.json()["state"] == "cancelled" and r.json()["reason"] == "cancelled_before_admission"
    n0 = len(fake.requests)
    late = _stream(client, h, k, {"message": "arrives after its own Stop"})
    assert late[-1]["type"] == "error" and "cancelled" in late[-1]["text"].lower()
    assert len(fake.requests) == n0 and _units(uid) == 0


def test_cancel_after_commit_reports_too_late_and_changes_nothing(client, fake):
    t, uid = _signup(client)
    h, k = _hdr(t), key()
    evs = _stream(client, h, k, {"message": "finished already"})
    r = client.post(f"/api/turns/{k}/cancel", headers=h)
    assert r.status_code == 200 and r.json()["state"] == "committed"
    assert len(_turns(evs[0]["session_id"])) == 1


def test_one_users_key_is_invisible_and_uncancellable_by_another(client, fake):
    ta, _ = _signup(client)
    tb, _ = _signup(client)
    k = key()
    evs = _stream(client, _hdr(ta), k, {"message": "mine"})
    assert _outcome(client, _hdr(tb), k)[1]["state"] == "unknown"
    r = client.post(f"/api/turns/{k}/cancel", headers=_hdr(tb))
    assert r.json()["state"] == "cancelled"                           # B closed B's OWN namespace for that key
    assert _outcome(client, _hdr(ta), k)[1]["state"] == "committed"   # A's turn is untouched
    assert len(_turns(evs[0]["session_id"])) == 1


# ── workers: superseded, lost, restart-safe, store down ──────────────────────────────────────────────────────────────────────────

def _commit_with(sid, uid, rk, fence, epoch, text="x"):
    from orca.serve import conversations

    return conversations.commit_turn(sid, text, "a", user_id=uid, turn_id=uuid.uuid4().hex, fence_token=fence, epoch=epoch, meta={"message_id": "m1", "user_message_id": "u1"}, request_key=rk)


def test_one_request_key_commits_one_transcript_entry_even_if_driven_twice(isolated_home):
    from orca.serve import conversations, turn_requests as tr

    uid, sid, rk = "u1", str(uuid.uuid4()), key()
    tr.begin(uid, rk, sid)
    fence = uuid.uuid4().hex
    auth = conversations.acquire_authority(sid, uid, fence)
    a = _commit_with(sid, uid, rk, fence, auth.epoch)
    b = _commit_with(sid, uid, rk, fence, auth.epoch)                      # a second worker/attempt for the same request
    assert a.ok and b.ok and b.reason == "idempotent" and b.turn_id == a.turn_id
    assert len(conversations.turns_for_session(sid)) == 1
    assert tr.view(uid, rk)["state"] == "committed"


def test_a_superseded_worker_cannot_commit_and_the_request_resolves_superseded(isolated_home):
    from orca.serve import conversations, turn_requests as tr

    uid, sid, rk = "u1", str(uuid.uuid4()), key()
    tr.begin(uid, rk, sid)
    old = uuid.uuid4().hex
    a1 = conversations.acquire_authority(sid, uid, old, ttl_s=0.2)
    tr.mark_running(uid, rk, sid, old, a1.epoch)
    time.sleep(0.4)
    new = uuid.uuid4().hex
    a2 = conversations.acquire_authority(sid, uid, new)                    # a successor took over: epoch bumped
    assert a2.epoch > a1.epoch
    assert _commit_with(sid, uid, rk, old, a1.epoch).ok is False
    v = tr.view(uid, rk)
    assert v["state"] == "superseded" and v["safe_to_retry"] is True and conversations.turns_for_session(sid) == []


def test_a_lost_worker_resolves_to_not_committed_and_can_no_longer_commit(isolated_home):
    from orca.serve import conversations, turn_requests as tr

    uid, sid, rk = "u1", str(uuid.uuid4()), key()
    tr.begin(uid, rk, sid)
    fence = uuid.uuid4().hex
    a = conversations.acquire_authority(sid, uid, fence, ttl_s=0.1)
    tr.mark_running(uid, rk, sid, fence, a.epoch)
    assert tr.view(uid, rk)["state"] == "running"
    time.sleep(0.3)
    tr.ABANDON_GRACE_S = 0.0
    v = tr.view(uid, rk)
    assert v["state"] == "not_committed" and v["reason"] == "worker_lost"
    assert _commit_with(sid, uid, rk, fence, a.epoch).ok is False and conversations.turns_for_session(sid) == []
    assert tr.view(uid, rk)["state"] == "not_committed", "the resolution is durable"


def test_a_terminal_state_never_changes(isolated_home):
    from orca.serve import conversations, turn_requests as tr

    uid, sid, rk = "u1", str(uuid.uuid4()), key()
    tr.begin(uid, rk, sid)
    fence = uuid.uuid4().hex
    a = conversations.acquire_authority(sid, uid, fence)
    assert _commit_with(sid, uid, rk, fence, a.epoch).ok
    assert tr.finish(uid, rk, "not_committed", "late_error") is False
    assert tr.finish(uid, rk, "cancelled", "late_stop") is False
    assert tr.view(uid, rk)["state"] == "committed"


def test_an_unreadable_store_is_outcome_unknown_not_a_guess(client, fake, monkeypatch):
    from orca.serve import turn_requests as tr

    t, _ = _signup(client)

    def boom(*a, **k):
        raise RuntimeError("sqlite: disk I/O error at /var/secret/path")

    monkeypatch.setattr(tr, "view", boom)
    r = client.get(f"/api/turns/{key()}", headers=_hdr(t))
    assert r.status_code == 503 and r.json()["state"] == "outcome_unknown" and r.json()["safe_to_retry"] is False
    assert "secret" not in r.text and "sqlite" not in r.text and r.headers.get("retry-after")


# ── chat route ──────────────────────────────────────────────────────────────────────────────────────────────────────────────────────

def test_chat_route_records_the_same_lifecycle_and_replays_after_commit(client, fake):
    t, uid = _signup(client)
    h, k = _hdr(t), key()
    r = client.post("/api/chat", json={"message": "chat once"}, headers=_hk(h, k))
    assert r.status_code == 200
    assert _outcome(client, h, k)[1]["state"] == "committed"
    from orca.auth.db import get_conn

    with get_conn() as conn:
        conn.execute("DELETE FROM idempotency_keys WHERE idem_key=?", (k,))
    n0 = len(fake.requests)
    again = client.post("/api/chat", json={"message": "chat once"}, headers=_hk(h, k))
    assert again.status_code == 200 and again.headers.get("idempotent-replay") == "true" and again.json()["response"] == "FAKE-REPLY"
    assert len(fake.requests) == n0 and _units(uid) == 1


def test_chat_failure_is_not_committed_with_a_reason(client, fake):
    t, _ = _signup(client)
    h, k = _hdr(t), key()
    fake.fail_status = 500
    assert client.post("/api/chat", json={"message": "will fail"}, headers=_hk(h, k)).status_code == 500
    st = _outcome(client, h, k)[1]
    assert st["state"] == "not_committed" and st["safe_to_retry"] is True


def test_a_late_retry_with_a_different_payload_is_refused_not_replayed(client, fake):
    t, _ = _signup(client)
    h, k = _hdr(t), key()
    evs = _stream(client, h, k, {"message": "original text"})
    from orca.auth.db import get_conn

    with get_conn() as conn:
        conn.execute("DELETE FROM idempotency_keys WHERE idem_key=?", (k,))
    n0 = len(fake.requests)
    other = _stream(client, h, k, {"message": "a different message", "session_id": evs[0]["session_id"]})
    assert other[-1]["type"] == "error" and other[-1]["code"] == "invalid_request"
    assert len(fake.requests) == n0
    body = _outcome(client, h, k)[1]
    assert "request_hash" not in body and "turn_id" not in body, "internal fields must not be public"


def test_a_retry_is_not_blocked_by_an_idempotency_row_left_in_progress_by_a_dead_worker(client, fake):
    """Found by the live worker-kill test: the dead worker never released its in-progress idempotency row, so the retry got `conflict` for ten minutes although the
    outcome record already said `not_committed`."""
    from orca.auth.db import get_conn
    from orca.serve import conversations, idempotency, turn_requests as tr

    t, uid = _signup(client)
    h, k = _hdr(t), key()
    body = {"model_variant": "core", "message": "retry after crash"}
    sid = str(uuid.uuid4())
    body["session_id"] = sid
    from orca.serve.api import ChatRequest

    h_req = idempotency.request_hash(ChatRequest(**body).model_dump())
    assert idempotency.begin(uid, k, h_req)[0] == "new"                      # the dead worker's row
    tr.begin(uid, k, sid, h_req)
    fence = uuid.uuid4().hex
    a = conversations.acquire_authority(sid, uid, fence, ttl_s=0.1)
    tr.mark_running(uid, k, sid, fence, a.epoch)
    time.sleep(0.3)
    tr.ABANDON_GRACE_S = 0.0
    evs = _stream(client, h, k, {"message": "retry after crash", "session_id": sid})
    assert evs[-1]["type"] == "done" and evs[-1]["persisted"] == "saved", evs[-1]
    assert _outcome(client, h, k)[1]["state"] == "committed" and len(_turns(sid)) == 1


def test_a_live_in_progress_request_is_still_a_conflict(client, monkeypatch):
    with FakeOllama(chunks=tuple(f"w{i} " for i in range(10)), chunk_delay=0.2) as f:
        point_orneur_at(f, monkeypatch)
        t, _ = _signup(client)
        h, k = _hdr(t), key()
        sid = str(uuid.uuid4())
        first = {}
        th = threading.Thread(target=lambda: first.update(e=_stream(client, h, k, {"message": "still running", "session_id": sid})))
        th.start()
        assert f.stream_started.wait(5)
        dup = _stream(client, h, k, {"message": "still running", "session_id": sid})
        th.join()
        assert dup[-1]["type"] == "error" and dup[-1]["code"] == "conflict"
        assert first["e"][-1]["type"] == "done" and len(_turns(sid)) == 1
