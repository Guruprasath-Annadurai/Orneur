"""CTO follow-up directive, Priority 1: cross-worker message-edit
consistency.

_replace_visible_copy() (orca/serve/api.py) used to return True whenever
`_sessions.get(session_id)` was None -- the worker handling the edit had
nothing local to patch, so it did nothing at all, including nothing to
the SHARED Redis state. A committed, authoritative message edit could
therefore happen with zero observable effect on any OTHER worker: a
worker (A) with this session already cached in its own process memory
would keep serving pre-edit content to its next inference turn
indefinitely, and nothing would ever tell it to stop.

Two genuinely independent worker-local `_sessions` dicts are simulated
in-process (swapping `orca.serve.api._sessions` for the module-global
dict every call site reads by name, confirmed to work since none of
them capture it as a bound default or closure variable) against one
real, locally-running Redis (db 15, isolated, same convention as
tests/test_multiworker_session_and_fault_injection.py -- skips rather
than fakes a result if unreachable).

Fix under test: session_store.bump_revision()/get_revision(), an
atomic, monotonic, Redis-backed per-session counter. Every committed,
content-changing edit bumps it unconditionally, regardless of whether
the worker handling it has anything local to patch. Every
_get_session() call compares its own cached session's last-known
revision against the counter and evicts-and-rebuilds (from the
authoritative conversations.transcript(), not a second cache) when
behind.

Run with: pytest tests/test_multiworker_edit_consistency.py -q
"""
from __future__ import annotations

from tests._redis_guard import safe_flush

import importlib
import os

import pytest

from tests.test_g006_tenant_isolation import _hdr, _signup, client  # noqa: F401


def _redis_reachable() -> bool:
    try:
        import redis
        c = redis.from_url("redis://localhost:6379/15", socket_connect_timeout=2)
        c.ping()
        return True
    except Exception:
        return False


pytestmark = pytest.mark.skipif(
    not _redis_reachable(),
    reason="no local Redis reachable at redis://localhost:6379/15 -- this file proves cross-worker "
    "consistency against a real local Redis, not a fabricated one, so it skips rather than faking a "
    "result when unavailable",
)

_TEST_REDIS_URL = "redis://localhost:6379/15"


@pytest.fixture
def two_workers(client, monkeypatch):
    """Points session_store at a real, isolated Redis (db 15) and
    returns a small helper object for simulating two independent
    worker-local _sessions dicts sharing it. Restores everything
    afterward so no other test file is affected."""
    prev = os.environ.get("ORNEUR_REDIS_URL")
    os.environ["ORNEUR_REDIS_URL"] = _TEST_REDIS_URL
    import orca.serve.session_store as ss
    importlib.reload(ss)
    import orca.serve.api as api_module
    importlib.reload(api_module)
    safe_flush(ss.get_client())

    class TwoWorkers:
        def __init__(self):
            self.api = api_module
            self.ss = ss
            self._worker_a_sessions = None

        def as_worker_a(self):
            """Switch to worker A's own _sessions dict (creating it on
            first use)."""
            if self._worker_a_sessions is None:
                self._worker_a_sessions = {}
            self.api._sessions = self._worker_a_sessions

        def as_worker_b(self, fresh=True):
            """Switch to worker B's own, genuinely separate _sessions
            dict -- fresh (nothing cached, simulating a different
            process that never saw this session) unless told otherwise."""
            if fresh or not hasattr(self, "_worker_b_sessions"):
                self._worker_b_sessions = {}
            self.api._sessions = self._worker_b_sessions

    yield TwoWorkers()

    safe_flush(ss.get_client())
    if prev is not None:
        os.environ["ORNEUR_REDIS_URL"] = prev
    else:
        os.environ.pop("ORNEUR_REDIS_URL", None)
    importlib.reload(ss)
    importlib.reload(api_module)


@pytest.fixture
def fake(client, monkeypatch):
    from orca.serve import ratelimit
    from tests.fake_ollama import FakeOllama, point_orneur_at
    ratelimit._local_counters.clear()
    with FakeOllama(reply="The answer is 42.", chunks=("The answer ", "is 42.")) as backend:
        point_orneur_at(backend, monkeypatch)
        yield backend


def _signup_and_chat(client, fake, content="original message text"):
    from tests.test_b_conversations import _chat, _msgs
    token, user_id = _signup(client)
    headers = _hdr(token)
    sid = _chat(client, headers, content)["session_id"]
    message_id = _msgs(client, headers, sid)["messages"][0]["message_id"]
    return headers, sid, message_id, user_id


# --- Scenario 1 + 6: edit on worker B while worker A has the session cached; worker A's next inference must not use stale content ---

def test_an_edit_on_worker_b_is_detected_by_worker_a_before_its_next_inference_turn(client, fake, two_workers):
    two_workers.as_worker_a()
    headers, sid, message_id, user_id = _signup_and_chat(client, fake)

    # Worker A resolves its own agent now (as a real inference turn
    # would) and seed its in-memory history with a known pre-edit marker
    # -- the exact mechanism under test is revision-based eviction, which
    # does not depend on exactly how /api/chat happens to populate
    # agent._history internally, only on whether a cached copy with
    # STALE content survives past the point it should be evicted.
    worker_a_session = two_workers.api._sessions[sid]
    worker_a_session.agent.load_history([{"role": "user", "content": "original message text"}])
    assert any(m.get("content") == "original message text" for m in worker_a_session.agent.get_history())

    # Worker B -- a genuinely different, empty _sessions dict -- handles
    # the edit. It has nothing local to patch.
    two_workers.as_worker_b()
    assert sid not in two_workers.api._sessions, "worker B must start with nothing cached, simulating a different process"
    r = client.post(f"/api/session/{sid}/messages/{message_id}/edits",
                     json={"content": "EDITED on worker B"}, headers=headers)
    assert r.status_code == 200, r.text
    assert r.json()["created"] is True
    assert r.json()["live_sync"] is True, "the revision bump must be reported as a successful cross-worker sync, even with nothing local to patch"

    # Back to worker A's own (still-cached, now-stale) dict. The FIX
    # under test: worker A's next request must detect it is behind the
    # shared revision and rebuild before any new inference could use it.
    two_workers.as_worker_a()
    two_workers.api._sessions[sid] = worker_a_session  # worker A's dict still has its own stale copy
    assert sid in two_workers.api._sessions

    refreshed = two_workers.api._get_session(sid, user_id=user_id)
    live_texts = [m.get("content") for m in refreshed.agent.get_history()]
    assert "EDITED on worker B" in live_texts, "worker A's next inference must see the edit, not stale pre-edit content"
    assert "original message text" not in live_texts, "worker A's next inference must not carry the stale pre-edit text forward"


# --- Scenario 2: edit on a worker with no cached local session still bumps the shared revision ---

def test_an_edit_with_no_local_session_still_publishes_a_revision_bump(client, fake, two_workers):
    two_workers.as_worker_b()
    headers, sid, message_id, user_id = _signup_and_chat(client, fake)
    # Simulate "no local cache at all" by dropping it right before the edit.
    two_workers.api._sessions.pop(sid, None)
    before = two_workers.ss.get_revision(sid)

    r = client.post(f"/api/session/{sid}/messages/{message_id}/edits",
                     json={"content": "edited with no local session cached"}, headers=headers)
    assert r.status_code == 200
    assert r.json()["live_sync"] is True

    after = two_workers.ss.get_revision(sid)
    assert after is not None and before is not None
    assert after > before, "a committed edit must advance the shared revision counter even when the handling worker had nothing local to patch -- this is the exact defect being fixed"


# --- Scenario 3: Redis successfully written, but another worker's in-memory history is stale until it re-checks ---

def test_redis_is_updated_immediately_but_a_stale_worker_only_catches_up_on_its_next_request(client, fake, two_workers):
    two_workers.as_worker_a()
    headers, sid, message_id, user_id = _signup_and_chat(client, fake)
    worker_a_session = two_workers.api._sessions[sid]
    worker_a_session.agent

    two_workers.as_worker_b()
    r = client.post(f"/api/session/{sid}/messages/{message_id}/edits",
                     json={"content": "edited, worker A has not re-checked yet"}, headers=headers)
    assert r.status_code == 200

    # Redis already reflects the edit's revision immediately...
    assert two_workers.ss.get_revision(sid) >= 1
    # ...but worker A's own in-memory copy, until it makes its OWN next
    # request, is honestly still the old one -- this function does not
    # claim telepathic, zero-latency propagation, only that the NEXT
    # request-driven check catches it.
    two_workers.as_worker_a()
    two_workers.api._sessions[sid] = worker_a_session
    stale_texts = [m.get("content") for m in worker_a_session.agent.get_history()]
    assert "edited, worker A has not re-checked yet" not in stale_texts

    refreshed = two_workers.api._get_session(sid, user_id=user_id)
    fresh_texts = [m.get("content") for m in refreshed.agent.get_history()]
    assert "edited, worker A has not re-checked yet" in fresh_texts


# --- Scenario 4: Redis unavailable during both write and eviction -- honest limitation, not a false claim ---

def test_redis_unavailable_during_the_edit_is_reported_as_unconfirmed_not_silently_successful(client, fake, two_workers, monkeypatch):
    two_workers.as_worker_b()
    headers, sid, message_id, user_id = _signup_and_chat(client, fake)
    two_workers.api._sessions.pop(sid, None)  # no local session -- the exact path that used to silently return True

    real_client = two_workers.ss._client()

    def _boom(*a, **k):
        raise ConnectionError("simulated total Redis outage")
    broken = type("BrokenClient", (), {"incr": _boom, "get": _boom, "set": _boom, "delete": _boom, "expire": _boom})()
    # Set directly (not via monkeypatch.setattr): the two_workers
    # fixture's own teardown (which flushes this same client) runs
    # BEFORE monkeypatch's teardown restores it (two_workers depends on
    # monkeypatch, so it tears down first) -- restore manually below
    # instead of relying on monkeypatch's automatic restoration order.
    two_workers.ss._redis_client = broken

    try:
        r = client.post(f"/api/session/{sid}/messages/{message_id}/edits",
                         json={"content": "edited during a total Redis outage"}, headers=headers)
        assert r.status_code == 200, r.text
        assert r.json()["created"] is True, "the version must still be reported as committed -- Redis being down must never block or fail the authoritative commit"
        assert r.json()["live_sync"] is False, "with no local session AND no confirmed Redis signal, cross-worker consistency genuinely could not be established -- this must be disclosed, never claimed"
    finally:
        two_workers.ss._redis_client = real_client


# --- Scenario 5: recovery after Redis becomes available again ---

def test_consistency_resumes_once_redis_recovers_after_an_outage(client, fake, two_workers, monkeypatch):
    two_workers.as_worker_a()
    headers, sid, message_id, user_id = _signup_and_chat(client, fake)
    worker_a_session = two_workers.api._sessions[sid]
    worker_a_session.agent

    two_workers.as_worker_b()

    # First edit happens during a total outage -- no fencing signal can
    # be published (scenario 4's own finding, re-confirmed here as the
    # starting condition for recovery).
    real_client = two_workers.ss._client()

    def _boom(*a, **k):
        raise ConnectionError("simulated outage")
    broken = type("BrokenClient", (), {"incr": _boom, "get": _boom, "set": _boom, "delete": _boom, "expire": _boom})()
    monkeypatch.setattr(two_workers.ss, "_redis_client", broken)
    outage_edit = client.post(f"/api/session/{sid}/messages/{message_id}/edits",
                               json={"content": "edited during the outage, never confirmed"}, headers=headers)
    assert outage_edit.json()["live_sync"] is False

    # Redis recovers. Restore ONLY the patched client (not the whole
    # monkeypatch fixture, which would also undo this test's unrelated
    # tmp-directory/model sandboxing from the client/fake fixtures).
    monkeypatch.setattr(two_workers.ss, "_redis_client", real_client)

    # A SECOND edit, now that Redis is healthy again, must successfully
    # publish a fencing signal -- consistency resumes going forward, even
    # though the outage window itself genuinely had none (architecturally
    # impossible without a working shared channel -- not claimed otherwise).
    recovered_edit = client.post(f"/api/session/{sid}/messages/{message_id}/edits",
                                  json={"content": "edited after Redis recovered"}, headers=headers)
    assert recovered_edit.status_code == 200
    assert recovered_edit.json()["live_sync"] is True

    two_workers.as_worker_a()
    two_workers.api._sessions[sid] = worker_a_session
    refreshed = two_workers.api._get_session(sid, user_id=user_id)
    fresh_texts = [m.get("content") for m in refreshed.agent.get_history()]
    assert "edited after Redis recovered" in fresh_texts, "once Redis recovers, the next committed edit must still correctly propagate to a worker that was stale from before the outage"
