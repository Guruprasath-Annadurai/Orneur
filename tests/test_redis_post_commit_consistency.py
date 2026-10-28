"""CTO closeout review, issue 2: Redis consistency after a committed
message edit.

orca/serve/session_store.py's save_session_state() and delete_session()
deliberately never raise on a Redis failure -- correct for their
original purpose (a normal chat turn's persistence should not crash the
request over Redis being down). But orca/serve/api.py's
_replace_visible_copy() (the post-commit live-sync step added for the
PR #111 B11 closeout) called persist_to_redis() for its side effect
only, never inspecting whether the write actually happened. A silently
swallowed write failure there means the OLD, pre-edit value is left
sitting in Redis under its own still-live TTL -- fully readable by any
other application instance in a load-balanced deployment, which would
reconstruct its in-memory session from that stale value and serve
pre-edit content as if it were current, even though the edit genuinely
committed in the authoritative message_versions store.

This file proves the failure mode against a REAL, locally-running Redis
(isolated on db 15, matching tests/test_multiworker_session_and_fault_injection.py's
existing convention -- never a fabricated/mocked Redis client), then
proves the fix: a failed write is now detected, evicts both the local
session cache and the stale Redis entry, is audit-logged, and the edit
response itself still honestly reports the commit succeeded
(never "already-committed edit as failed").

Skips (rather than fabricating a result) if no local Redis is reachable.

Run with: pytest tests/test_redis_post_commit_consistency.py -q
"""
from __future__ import annotations

import importlib
import os

import pytest

from tests.test_g006_tenant_isolation import _hdr, _signup, client  # noqa: F401


def _redis_reachable() -> bool:
    try:
        import redis
        client = redis.from_url("redis://localhost:6379/15", socket_connect_timeout=2)
        client.ping()
        return True
    except Exception:
        return False


pytestmark = pytest.mark.skipif(
    not _redis_reachable(),
    reason="no local Redis reachable at redis://localhost:6379/15 -- this test proves the fix against "
    "a real local Redis, not a fabricated one, so it skips rather than faking a result when unavailable",
)

_TEST_REDIS_URL = "redis://localhost:6379/15"


@pytest.fixture(autouse=True)
def _use_real_redis_db15():
    """Points session_store at a real, isolated local Redis (db 15,
    never the same logical DB a developer's own Orneur install would
    use) for the duration of each test in this file, then restores the
    prior env and reloads the module back to its original (disabled, by
    default in this test suite) state so no other test file is affected."""
    prev = os.environ.get("ORNEUR_REDIS_URL")
    os.environ["ORNEUR_REDIS_URL"] = _TEST_REDIS_URL
    import orca.serve.session_store as ss
    importlib.reload(ss)
    import orca.serve.api as api_module
    importlib.reload(api_module)  # api.py's `from orca.serve import session_store` must see the reloaded module's new REDIS_URL/enabled() state
    ss.get_client().flushdb()  # a clean db 15 for every test -- no cross-test leakage
    yield api_module
    ss.get_client().flushdb()
    if prev is not None:
        os.environ["ORNEUR_REDIS_URL"] = prev
    else:
        os.environ.pop("ORNEUR_REDIS_URL", None)
    importlib.reload(ss)
    importlib.reload(api_module)


# --- Direct reproduction against session_store itself (no HTTP, no app) ---

def test_a_silently_failed_write_leaves_the_old_value_readable_by_another_instance():
    """The raw mechanism, reproduced directly: save_session_state()
    returns False (never raises) on a write failure, and the PREVIOUS
    value -- exactly what "another application instance" would load --
    is still sitting there afterward, unchanged."""
    import orca.serve.session_store as ss

    sid = "redis-consistency-repro-1"
    assert ss.save_session_state(sid, "core", [{"role": "user", "content": "original, pre-edit text"}]) is True

    real_client = ss._client()
    broken = type("BrokenClient", (), {"set": lambda self, *a, **k: (_ for _ in ()).throw(ConnectionError("simulated Redis write failure"))})()
    ss._redis_client = broken
    try:
        ok = ss.save_session_state(sid, "core", [{"role": "user", "content": "EDITED text that should now be current"}])
    finally:
        ss._redis_client = real_client

    assert ok is False, "a genuinely failed write must be reported as failed, not silently treated as success"

    # The exact bug: ANOTHER instance reading this session right now --
    # with no knowledge the write above failed -- gets the STALE,
    # pre-edit value back, not an error, not a cache miss.
    recovered = ss.load_session_state(sid)
    assert recovered is not None
    assert recovered["history"] == [{"role": "user", "content": "original, pre-edit text"}], "reproduces the exact failure: a silently-failed write leaves pre-edit content readable as if it were current"


# --- Full end-to-end reproduction and fix verification through the real HTTP route ---

def _signup_and_chat(client, fake):
    from tests.test_b_conversations import _chat, _msgs
    token, user_id = _signup(client)
    headers = _hdr(token)
    sid = _chat(client, headers, "original text")["session_id"]
    message_id = _msgs(client, headers, sid)["messages"][0]["message_id"]
    return headers, sid, message_id, user_id


@pytest.fixture
def fake(client, monkeypatch):
    from orca.serve import ratelimit
    from tests.fake_ollama import FakeOllama, point_orneur_at
    ratelimit._local_counters.clear()
    with FakeOllama(reply="The answer is 42.", chunks=("The answer ", "is 42.")) as backend:
        point_orneur_at(backend, monkeypatch)
        yield backend


def test_a_committed_edit_with_a_failing_redis_write_never_leaves_a_stale_entry_for_another_instance(client, fake, monkeypatch, _use_real_redis_db15):
    """End-to-end: the real /edits route, a real Redis write failure
    injected at exactly the live-sync step (message_versions.edit()'s
    own commit is untouched), confirms: (1) the edit is still reported
    as committed, never as failed; (2) the response honestly discloses
    live_sync: false; (3) the stale pre-edit Redis entry this session
    had BEFORE the edit does not survive -- proving another instance can
    no longer load it as current."""
    api_module = _use_real_redis_db15
    headers, sid, message_id, _user_id = _signup_and_chat(client, fake)

    # Prime a real Redis entry for this session, as a normal turn would
    # have (persist_to_redis() is called on every chat/stream turn, not
    # only on edits) -- this is the "stale value another instance could
    # load" that must not survive a failed-then-recovered edit.
    import orca.serve.session_store as ss
    ss.save_session_state(sid, "core", [{"role": "user", "content": "original text"}])
    assert ss.load_session_state(sid) is not None

    # Force the underlying Redis client's SET specifically to fail --
    # caught and silently converted to a False return INSIDE
    # save_session_state() itself (the real production failure mode, not
    # an artificially raised exception at a higher layer), WITHOUT
    # touching message_versions.edit()'s own commit path at all. DELETE
    # is deliberately left working on the same client: a realistic
    # single transient write failure (one timed-out SET), not a total,
    # simultaneous Redis outage that would also defeat the eviction's
    # own cleanup attempt moments later.
    real_client = ss._client()

    def _boom(*a, **k):
        raise ConnectionError("simulated Redis write failure during post-commit live sync")
    broken = type("BrokenSetClient", (), {"set": _boom, "delete": lambda self, *a, **k: real_client.delete(*a, **k)})()
    monkeypatch.setattr(ss, "_redis_client", broken)

    r = client.post(f"/api/session/{sid}/messages/{message_id}/edits",
                     json={"content": "edited with a failing Redis write"}, headers=headers)
    assert r.status_code == 200, r.text
    body = r.json()
    assert body["created"] is True, "the version must still be reported as committed"
    assert body["active_content"] == "edited with a failing Redis write"
    assert body["live_sync"] is False, "a genuine Redis write failure during live sync must be honestly disclosed, not hidden behind a successful-looking response"

    # The fail-safe recovery: the stale (pre-edit) Redis entry must be
    # gone, not left for another instance to load. Restore ONLY the
    # patched Redis client (not the whole monkeypatch fixture, which
    # would also undo this test's unrelated tmp-directory/model
    # sandboxing) before reading back.
    monkeypatch.setattr(ss, "_redis_client", real_client)
    recovered = ss.load_session_state(sid)
    assert recovered is None or recovered.get("history") != [{"role": "user", "content": "original text"}], "a failed live sync must not leave the OLD pre-edit value readable by another instance after the fact"
    assert sid not in api_module._sessions, "the local session cache must also be evicted so THIS instance cannot replay stale text either"


def test_a_committed_edit_with_a_working_redis_write_genuinely_updates_the_entry_another_instance_would_load(client, fake, _use_real_redis_db15):
    """Regression guard: when Redis is healthy, a committed edit's
    live-sync step must genuinely write the CURRENT in-memory agent
    history to Redis -- the real invariant another instance depends on
    is that Redis mirrors this process's own live state, not a specific
    content string (which depends on internals of how /api/chat builds
    agent history, not this fix's own concern)."""
    api_module = _use_real_redis_db15
    headers, sid, message_id, _user_id = _signup_and_chat(client, fake)
    import orca.serve.session_store as ss

    r = client.post(f"/api/session/{sid}/messages/{message_id}/edits",
                     json={"content": "edited with a healthy Redis write"}, headers=headers)
    assert r.status_code == 200
    assert r.json()["live_sync"] is True

    recovered = ss.load_session_state(sid)
    assert recovered is not None
    live_history = api_module._sessions[sid].agent.get_history()
    assert recovered["history"] == live_history, "a healthy live sync must leave Redis holding exactly this process's own current in-memory history, so another instance loading it is never behind"

