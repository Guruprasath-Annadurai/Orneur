"""PR #111 closeout, Priority 1: the message_versions.edit() /
_replace_visible_copy() boundary in orca/serve/api.py.

message_versions.edit() durably commits a new, immutable version under a
real per-message lock -- that commit is authoritative the instant it
returns. _replace_visible_copy() runs AFTER it, purely to keep the
CURRENT live session's in-memory agent._history / memory.short._messages
(what the model uses as context for its NEXT reply in this same process)
in step with that commit. Before this fix, an exception inside
_replace_visible_copy() propagated unguarded out of edit_session_message(),
producing an unhandled 500 for an edit that had already committed --
and nothing repaired the in-memory window, so a later crash-free request
in the SAME process could still see stale pre-edit text.

These tests reproduce that failure directly (by making the in-memory
sync step fail, via a patched session_store.save_session_state) and
verify the documented properties: no duplicate immutable version, a
same-key retry stays idempotent, the persisted active version stays
authoritative, the live conversation is rebuilt (not merely not-crashed)
from that authoritative version on next access, the route never reports
an uncommitted edit as committed or a committed edit as a definitive
rejection, and the failure is audit-visible rather than silently
swallowed.

Run with: pytest tests/test_b11_post_commit_live_sync.py -q
"""
from __future__ import annotations

import pytest

from orca.serve import api as api_module
from orca.serve import message_versions, session_store
from tests.fake_ollama import FakeOllama, point_orneur_at
from tests.test_b_conversations import _chat, _msgs
from tests.test_g006_tenant_isolation import _hdr, _signup, client  # noqa: F401


@pytest.fixture
def fake(client, monkeypatch):
    from orca.serve import ratelimit
    ratelimit._local_counters.clear()
    with FakeOllama(reply="The answer is 42.", chunks=("The answer ", "is 42.")) as f:
        point_orneur_at(f, monkeypatch)
        yield f


def _setup_message(client, fake):
    """A real, persisted user message via the actual chat route -- not a
    hand-seeded fixture -- so the edit route under test operates on
    genuine transcript/session state exactly as production would."""
    token, user_id = _signup(client)
    headers = _hdr(token)
    sid = _chat(client, headers, "original message text")["session_id"]
    transcript = _msgs(client, headers, sid)
    user_line = next(m for m in transcript["messages"] if m["role"] == "user")
    return headers, sid, user_line["message_id"], user_id


def _force_live_sync_failure(monkeypatch):
    """The realistic failure this boundary must survive: the in-memory
    sync step (which calls sess.persist_to_redis() -> session_store.
    save_session_state()) throws. Nothing about message_versions.edit()
    itself is touched -- the commit path is untouched by this patch."""
    def _boom(*a, **k):
        raise RuntimeError("synthetic live-sync failure (Redis unreachable)")
    monkeypatch.setattr(session_store, "save_session_state", _boom)


def test_a_live_sync_failure_after_commit_does_not_turn_into_a_500(client, fake, monkeypatch):
    headers, sid, message_id, user_id = _setup_message(client, fake)
    # Touch the session once first so an in-memory agent actually exists
    # for _replace_visible_copy() to try (and fail) to patch.
    client.get(f"/api/session/{sid}/messages", headers=headers)
    assert sid in api_module._sessions
    api_module._sessions[sid].agent  # force lazy agent resolution

    _force_live_sync_failure(monkeypatch)
    r = client.post(f"/api/session/{sid}/messages/{message_id}/edits",
                     json={"content": "edited after a live-sync failure"}, headers=headers)
    assert r.status_code == 200, r.text
    body = r.json()
    assert body["created"] is True, "the version must still be reported as committed -- the commit itself never touched the failing code path"
    assert body["active_content"] == "edited after a live-sync failure"
    assert body["live_sync"] is False, "the route must honestly disclose that the in-memory window could not be kept in step, not silently claim success"


def test_the_commit_is_not_duplicated_by_a_post_failure_live_sync(client, fake, monkeypatch):
    headers, sid, message_id, user_id = _setup_message(client, fake)
    client.get(f"/api/session/{sid}/messages", headers=headers)
    api_module._sessions[sid].agent

    _force_live_sync_failure(monkeypatch)
    r = client.post(f"/api/session/{sid}/messages/{message_id}/edits",
                     json={"content": "edited exactly once"}, headers=headers)
    assert r.status_code == 200
    first_version_id = r.json()["version_id"]
    assert r.json()["version_count"] == 2, "exactly one new version -- the live-sync failure must not somehow create a second"

    # Read the authoritative store directly -- independent of whatever
    # the (possibly evicted) in-process session object currently holds.
    active = message_versions.active_view(sid, message_id)
    assert active["content"] == "edited exactly once"
    assert active["version_id"] == first_version_id
    assert active["version_count"] == 2


def test_a_same_key_retry_after_a_live_sync_failure_remains_idempotent_no_duplicate_version(client, fake, monkeypatch):
    headers, sid, message_id, user_id = _setup_message(client, fake)
    client.get(f"/api/session/{sid}/messages", headers=headers)
    api_module._sessions[sid].agent

    _force_live_sync_failure(monkeypatch)
    key = "closeout-retry-key-1"
    first = client.post(f"/api/session/{sid}/messages/{message_id}/edits",
                         json={"content": "retried edit content"}, headers={**headers, "Idempotency-Key": key})
    assert first.status_code == 200 and first.json()["created"] is True

    # The SAME key, same content, retried -- exactly the scenario a
    # client would produce retrying after seeing live_sync: false (or
    # any ambiguous outcome). This must reuse the existing version, not
    # mint a second one, regardless of the live-sync failure on the
    # first attempt.
    second = client.post(f"/api/session/{sid}/messages/{message_id}/edits",
                          json={"content": "retried edit content"}, headers={**headers, "Idempotency-Key": key})
    assert second.status_code == 200
    assert second.json()["created"] is False, "a same-key, same-content retry must be recognized as the already-committed attempt, not a new one"
    assert second.json()["version_id"] == first.json()["version_id"]
    assert second.json()["version_count"] == 2, "still exactly one new version after both the original attempt and its retry"


def test_the_live_sync_failure_evicts_cached_session_state_so_the_next_access_cannot_replay_stale_text(client, fake, monkeypatch):
    headers, sid, message_id, user_id = _setup_message(client, fake)
    client.get(f"/api/session/{sid}/messages", headers=headers)
    api_module._sessions[sid].agent
    assert sid in api_module._sessions

    _force_live_sync_failure(monkeypatch)
    client.post(f"/api/session/{sid}/messages/{message_id}/edits",
                json={"content": "the real edit"}, headers=headers)

    # The whole point: a divergence between the in-memory window and the
    # authoritative store must not be left silently observable. The
    # failure path evicts the cached session rather than leaving it
    # holding pre-edit text.
    assert sid not in api_module._sessions, "a failed live sync must evict the stale cached session, not leave it silently serving pre-edit content"


def test_the_live_conversation_is_rebuilt_from_the_authoritative_active_version_on_next_access(client, fake, monkeypatch):
    headers, sid, message_id, user_id = _setup_message(client, fake)
    client.get(f"/api/session/{sid}/messages", headers=headers)
    api_module._sessions[sid].agent

    real_save_session_state = session_store.save_session_state
    _force_live_sync_failure(monkeypatch)
    client.post(f"/api/session/{sid}/messages/{message_id}/edits",
                json={"content": "the rebuilt edit"}, headers=headers)
    assert sid not in api_module._sessions

    # Restore ONLY the sync path (not the whole monkeypatch fixture,
    # which would also undo this test's unrelated tmp-directory/model
    # sandboxing) -- this test is about REBUILD correctness, not about
    # surviving a second failure.
    monkeypatch.setattr(session_store, "save_session_state", real_save_session_state)

    # Any subsequent access reconstructs the session from scratch.
    # Because Redis was never the source of truth here (save_session_state
    # never succeeded for this session), _Session.__init__ must fall
    # through to conversations.transcript() -- which resolves every line
    # through message_versions.active_view() -- rather than replaying the
    # stale pre-edit text or an imprecise long-term-memory summary.
    r = client.get(f"/api/session/{sid}/messages", headers=headers)
    assert r.status_code == 200
    rebuilt_transcript = r.json()
    edited_line = next(m for m in rebuilt_transcript["messages"] if m.get("message_id") == message_id)
    assert edited_line["content"] == "the rebuilt edit", "a reload must show the authoritative active version regardless of the earlier live-sync failure"

    sess = api_module._get_session(sid, user_id=user_id)
    live_history_texts = [m.get("content") for m in sess.agent.get_history()]
    assert "the rebuilt edit" in live_history_texts, "the rebuilt in-memory agent history (not just the HTTP transcript response) must reflect the authoritative edit"
    assert "original message text" not in live_history_texts, "the rebuilt in-memory history must not carry the stale pre-edit text forward"


def test_a_genuine_pre_commit_rejection_is_unaffected_by_this_boundary_change(client, fake):
    """Regression guard: the live-sync machinery above must not have
    widened what counts as a 'committed' edit -- a real validation
    failure (empty content) still never reaches message_versions.edit()
    at all, so it is still reported exactly as before: a definitive
    4xx, not a committed edit, and no live_sync field (nothing was
    committed, so nothing needed syncing)."""
    headers, sid, message_id, user_id = _setup_message(client, fake)
    r = client.post(f"/api/session/{sid}/messages/{message_id}/edits",
                     json={"content": ""}, headers=headers)
    assert r.status_code in (400, 422), r.text
    assert "live_sync" not in r.json()


def test_the_live_sync_failure_is_audit_logged_not_silently_swallowed(client, fake, monkeypatch):
    calls = []
    monkeypatch.setattr(api_module.audit, "log", lambda event, **kw: calls.append((event, kw)))
    headers, sid, message_id, user_id = _setup_message(client, fake)
    client.get(f"/api/session/{sid}/messages", headers=headers)
    api_module._sessions[sid].agent

    _force_live_sync_failure(monkeypatch)
    client.post(f"/api/session/{sid}/messages/{message_id}/edits",
                json={"content": "audited edit"}, headers=headers)

    matching = [c for c in calls if c[0] == "message_edit_live_sync_failed"]
    assert matching, "a live-sync failure after a committed edit must produce an audit-visible record, not just a swallowed exception"
    assert matching[0][1]["detail"]["session_id"] == sid


def test_save_session_state_treats_redis_disabled_as_a_no_op_not_a_failure():
    """Direct regression guard for a real bug this fix itself introduced
    and caught, in this session, via the broader regression suite (not
    by this file's own Redis-enabled tests, which never exercise the
    disabled path): session_store.save_session_state() must return True
    when Redis is simply not configured (REDIS_URL unset -- the default
    for this whole test suite, and for any single-instance deployment),
    never False. Conflating "nothing to worry about, no shared cache in
    play" with "a write genuinely failed" would make EVERY edit on a
    Redis-disabled deployment trip the live-sync failure path -- evicting
    the session, disclosing live_sync: false -- for a condition that was
    never actually a problem."""
    import orca.serve.session_store as ss
    assert ss.enabled() is False, "this test asserts the DEFAULT (disabled) state -- it is not inside the real-Redis fixture used by the rest of this file"
    assert ss.save_session_state("disabled-redis-sid", "core", [{"role": "user", "content": "x"}]) is True


def test_a_plain_edit_with_redis_disabled_is_not_treated_as_a_live_sync_failure(client, fake):
    """End-to-end version of the same regression: the overwhelmingly
    common case (no Redis configured at all) must report live_sync: true
    and must NOT evict the session -- exactly the scenario that broke in
    test_audit_cursor_backend_adversarial.py::test_b11_security_and_failure_semantics
    before this fix."""
    import orca.serve.api as api_module
    assert api_module.session_store.enabled() is False
    headers, sid, message_id, _user_id = _setup_message(client, fake)

    r = client.post(f"/api/session/{sid}/messages/{message_id}/edits",
                     json={"content": "edited with no Redis configured at all"}, headers=headers)
    assert r.status_code == 200, r.text
    assert r.json()["live_sync"] is True, "Redis simply not being configured must never be reported as a live-sync failure"
    assert sid in api_module._sessions, "the session must NOT be evicted when there was never a shared cache to worry about in the first place"
