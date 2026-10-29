"""L02-01 — authoritative, idempotent, honest conversation deletion (adversarial matrix).

Every test drives the real FastAPI app (TestClient), real SQLite, real stores in an isolated ORNEUR_HOME. Store failures are injected at the store's own
entry point, never by stubbing the route.
"""
from __future__ import annotations

import threading
import uuid

import pytest
from fastapi.testclient import TestClient


def _signup(client):
    from orca.serve import ratelimit

    ratelimit._local_counters.clear()            # signup is limited to 5/h/IP; each test needs its own accounts
    r = client.post("/api/auth/signup", json={"email": f"l02-{uuid.uuid4().hex[:10]}@example.com", "password": "correcthorsebatterystaple", "name": "T"})
    assert r.status_code == 200, r.text
    d = r.json()
    return {"Authorization": f"Bearer {d['token']}"}, d["user"]["id"]


def _commit(sid, uid, user_text="what is my codename?", assistant="Nightingale"):
    from orca.serve import conversations

    tok = uuid.uuid4().hex
    auth = conversations.acquire_authority(sid, uid, tok)
    assert auth is not None
    res = conversations.commit_turn(sid, user_text, assistant, user_id=uid, turn_id=uuid.uuid4().hex, fence_token=tok, epoch=auth.epoch)
    assert res.ok, res.reason
    return tok, auth


@pytest.fixture
def env(isolated_home):
    from orca.serve.api import app
    from orca.auth.store import record_user_session

    client = TestClient(app)
    h, uid = _signup(client)
    sid = str(uuid.uuid4())
    record_user_session(uid, sid)
    return client, h, uid, sid, record_user_session


def _break_vector(monkeypatch):
    """Returns a ``heal()`` callable (``monkeypatch.undo()`` would also undo the isolated-home fixture)."""
    from orca.brain.memory import LongTermMemory

    real = LongTermMemory.__dict__["delete_session"]
    down = {"v": True}

    def maybe(cls, session_id):
        if down["v"]:
            raise RuntimeError("vector store down at /secret/path/chroma")
        return real.__func__(cls, session_id)

    monkeypatch.setattr(LongTermMemory, "delete_session", classmethod(maybe))
    return lambda: down.update(v=False)


def test_complete_deletion_reports_200_and_everything_is_gone(env):
    client, h, uid, sid, _ = env
    _commit(sid, uid)
    r = client.delete(f"/api/session/{sid}", headers=h)
    assert r.status_code == 200, r.text
    body = r.json()
    assert body["deleted"] is True and body["state"] == "complete" and body["access_revoked"] is True
    assert body["deletion_id"]
    # honest about what is NOT claimed
    assert "backups" in body["retention"]["application_backups"].lower()
    assert "not claimed" in body["retention"]["physical_erasure"].lower()
    from orca.serve import conversations

    assert conversations.turns_for_session(sid) == []
    assert client.get(f"/api/session/{sid}/messages", headers=h).status_code == 404


def test_partial_failure_is_not_reported_as_deleted_and_stays_retryable(env, monkeypatch):
    """Baseline defect (reproduced on 9cb864c): a failed vector-store delete returned 200 {deleted:true}, the `*_error` key was filtered out of the response and
    the ownership claim was released, so the owner could never retry (404)."""
    client, h, uid, sid, _ = env
    _commit(sid, uid)
    heal = _break_vector(monkeypatch)
    r = client.delete(f"/api/session/{sid}", headers=h)
    assert r.status_code == 202, r.text
    body = r.json()
    assert body["deleted"] is False and body["state"] == "partial" and body["retryable"] is True
    assert body["access_revoked"] is True
    assert body["stores"]["long_term_vector_memory"] == "failed"
    assert "secret/path" not in r.text and "chroma" not in r.text and "RuntimeError" not in r.text      # no internals in a public response
    from orca.auth.store import get_user_session_ids

    assert sid in get_user_session_ids(uid), "ownership must be kept until every store confirmed, so the owner can retry"
    # access is revoked even though cleanup is unfinished
    assert client.get(f"/api/session/{sid}/messages", headers=h).status_code == 404
    # the store recovers -> the same request finishes the job
    heal()
    r2 = client.delete(f"/api/session/{sid}", headers=h)
    assert r2.status_code == 200 and r2.json()["state"] == "complete" and r2.json()["deletion_id"] == body["deletion_id"]
    assert sid not in get_user_session_ids(uid)


def test_sweep_finishes_an_interrupted_deletion_after_restart(env, monkeypatch):
    client, h, uid, sid, _ = env
    _commit(sid, uid)
    heal = _break_vector(monkeypatch)
    assert client.delete(f"/api/session/{sid}", headers=h).status_code == 202
    heal()
    from orca.serve import deletions

    assert deletions.resume_pending() == 1                      # what the periodic loop / a restarted worker does
    assert deletions.get(sid)["state"] == "complete"
    assert deletions.resume_pending() == 0                      # idempotent


def test_crash_between_tombstone_and_cascade_is_recovered(env):
    client, h, uid, sid, _ = env
    _commit(sid, uid)
    from orca.serve import conversations, deletions

    deletions.begin(sid, uid)                                    # process died right here: tombstone written, nothing cleaned
    assert conversations.turns_for_session(sid) != []
    assert client.get(f"/api/session/{sid}/messages", headers=h).status_code == 404       # already unreachable
    assert deletions.resume_pending() == 1
    assert conversations.turns_for_session(sid) == []
    assert deletions.get(sid)["state"] == "complete"


def test_a_crashed_lease_holder_does_not_block_the_sweep(env, monkeypatch):
    client, h, uid, sid, _ = env
    from orca.serve import conversations, deletions

    deletions.begin(sid, uid)
    assert deletions._lease(sid) is True                         # worker A leases, then dies
    assert deletions._lease(sid) is False                        # worker B is correctly excluded while the lease is live
    conn = conversations._turns_conn()
    try:
        with conn:
            conn.execute("UPDATE session_deletions SET lease_until=? WHERE session_id=?", (0.5, sid))
    finally:
        conn.close()
    assert deletions.resume_pending() == 1
    assert deletions.get(sid)["state"] == "complete"


def test_concurrent_repeated_deletion_is_one_deletion(env):
    client, h, uid, sid, _ = env
    _commit(sid, uid)
    out: list = []

    def go():
        out.append(client.delete(f"/api/session/{sid}", headers=h))

    ts = [threading.Thread(target=go) for _ in range(6)]
    [t.start() for t in ts]
    [t.join() for t in ts]
    codes = sorted(r.status_code for r in out)
    assert all(c in (200, 202, 404) for c in codes), codes
    assert 200 in codes
    ids = {r.json().get("deletion_id") for r in out if r.status_code in (200, 202)}
    assert len(ids) == 1, "one durable deletion identity however many concurrent requests"
    from orca.serve import deletions

    assert deletions.get(sid)["state"] == "complete"


def test_cannot_delete_or_resume_another_users_conversation(env):
    client, h, uid, sid, _ = env
    _commit(sid, uid)
    hb, uidb = _signup(client)
    assert client.delete(f"/api/session/{sid}", headers=hb).status_code == 404
    assert client.delete(f"/api/session/{sid}").status_code == 401
    from orca.serve import conversations, deletions

    assert deletions.get(sid) is None, "a refused delete must not even create a tombstone"
    assert conversations.turns_for_session(sid) != []
    # and a started deletion cannot be driven or observed by a stranger
    deletions.begin(sid, uid)
    assert client.delete(f"/api/session/{sid}", headers=hb).status_code == 404


def test_stale_worker_cannot_commit_or_regain_authority_after_deletion(env):
    """Delete during generation: the in-flight turn holds a valid fence, the user deletes, the worker then tries to commit."""
    client, h, uid, sid, _ = env
    from orca.serve import conversations

    tok = uuid.uuid4().hex
    auth = conversations.acquire_authority(sid, uid, tok)             # generation started
    assert client.delete(f"/api/session/{sid}", headers=h).status_code == 200
    res = conversations.commit_turn(sid, "q", "a", user_id=uid, turn_id=uuid.uuid4().hex, fence_token=tok, epoch=auth.epoch)
    assert res.ok is False and res.reason == "session_deleted"
    assert conversations.turns_for_session(sid) == []
    assert conversations.acquire_authority(sid, uid, uuid.uuid4().hex) is None       # and it cannot take authority again
    assert conversations.turns_for_session(sid) == []


def test_deleted_conversation_cannot_be_streamed_into_or_recreated(env):
    client, h, uid, sid, _ = env
    _commit(sid, uid)
    assert client.delete(f"/api/session/{sid}", headers=h).status_code == 200
    r = client.post("/api/stream", json={"message": "hello again", "session_id": sid}, headers=h)
    assert r.status_code == 404, r.text
    r = client.post("/api/chat", json={"message": "hello again", "session_id": sid}, headers=h)
    assert r.status_code == 404, r.text
    from orca.serve import conversations

    assert conversations.turns_for_session(sid) == []


def test_deleting_twice_is_indistinguishable_from_never_existing(env):
    client, h, uid, sid, _ = env
    _commit(sid, uid)
    assert client.delete(f"/api/session/{sid}", headers=h).status_code == 200
    assert client.delete(f"/api/session/{sid}", headers=h).status_code == 404


def test_deletion_in_progress_is_invisible_in_lists_and_search(env, monkeypatch):
    client, h, uid, sid, _ = env
    _commit(sid, uid, user_text="unique-needle-zebra")
    _break_vector(monkeypatch)
    assert client.delete(f"/api/session/{sid}", headers=h).status_code == 202
    listing = client.get("/api/sessions", headers=h)
    assert listing.status_code == 200
    assert sid not in listing.text
    s = client.get("/api/sessions/search", params={"q": "unique-needle-zebra"}, headers=h)
    assert s.status_code == 200 and s.json()["results"] == []


def test_audit_record_names_the_deletion_not_the_content(env, monkeypatch):
    client, h, uid, sid, _ = env
    _commit(sid, uid, user_text="PRIVATE-CANARY-9931", assistant="PRIVATE-REPLY-7712")
    seen: list = []
    from orca.serve import api

    real = api.audit.log

    def spy(event, **kw):
        seen.append((event, kw))
        return real(event, **kw)

    monkeypatch.setattr(api.audit, "log", spy)
    assert client.delete(f"/api/session/{sid}", headers=h).status_code == 200
    blob = repr(seen)
    assert "conversation_deleted" in blob and "deletion_id" in blob
    assert "PRIVATE-CANARY-9931" not in blob and "PRIVATE-REPLY-7712" not in blob


def test_next_turn_model_context_excludes_deleted_material(env):
    """A *new* conversation by the same user must not see the deleted conversation's text in the model context."""
    client, h, uid, sid, _ = env
    _commit(sid, uid, user_text="my codename is Nightingale-ZX", assistant="noted ZX")
    assert client.delete(f"/api/session/{sid}", headers=h).status_code == 200
    from orca.serve import conversations

    other = str(uuid.uuid4())
    from orca.auth.store import record_user_session

    record_user_session(uid, other)
    _commit(other, uid, user_text="hi", assistant="hello")
    ctx = repr(conversations.turns_for_session(other))
    assert "Nightingale-ZX" not in ctx
