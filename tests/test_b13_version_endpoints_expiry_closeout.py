"""PR #111 closeout, Priority 2: version-history reads and message edits
after GENUINE temporary-chat expiry.

The real gap (confirmed by reading the code, not assumed): expiry is
LAZY -- temporary_chat.enforce() is what actually transitions an
active-but-past-its-TTL record to `expired` and runs the full deletion
cascade (conversations transcript, message_versions store, docs,
knowledge graph, long-term vector memory -- see
account_delete._delete_session_data()). _temporary_block() is the one
and only call site for enforce() in orca/serve/api.py. Before this
fix, message_version_history() (GET .../versions), edit_session_message()
(POST .../edits), and regenerate_session_message() (POST .../regenerate)
never called it at all -- only ownership (`_owned_session_or_404`) was
checked, never the terminal state. A temporary chat whose TTL had
genuinely passed in real time, but that nobody had yet touched through
ANY OTHER route (chat, doc upload/delete, memory), would never actually
expire or delete its content as long as only these three routes were
used -- an un-enforced, indefinite retention gap for exactly the kind
of content the product promises is temporary.

Run with: pytest tests/test_b13_version_endpoints_expiry_closeout.py -q
"""
from __future__ import annotations

import json
import time
from pathlib import Path

import pytest

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


def _open_temporary(client, headers, ttl_seconds=60):
    r = client.post("/api/sessions/temporary", json={"ttl_seconds": ttl_seconds}, headers=headers)
    assert r.status_code == 200, r.text
    return r.json()["session_id"]


def _force_ttl_elapsed_without_triggering_enforce(sid: str):
    """Make this temporary chat's TTL genuinely due, WITHOUT calling
    anything that would itself trigger the lazy expiry/deletion this test
    exists to verify (no expire_due(), no _temporary_block(), no route
    call). Rewrites only the stored record's own expires_at field,
    exactly the field temporary_chat.enforce() itself compares against
    time.time() -- this reproduces "real time has genuinely passed the
    TTL" without mocking the global clock (which would perturb auth
    tokens, rate limiting, and every other time.time() call in the same
    process)."""
    import orca.brain.memory as mem
    path = Path(mem.MEMORY_DIR) / "temporary_chats" / f"{sid}.json"
    record = json.loads(path.read_text())
    assert record["state"] == "active"
    record["expires_at"] = time.time() - 5
    path.write_text(json.dumps(record))


def _versions_dir(sid: str) -> Path:
    import orca.brain.memory as mem
    return Path(mem.MEMORY_DIR) / "message_versions" / sid


def _transcript_path(sid: str) -> Path:
    import orca.brain.memory as mem
    return Path(mem.MEMORY_DIR) / "conversations" / f"{sid}.jsonl"


def test_version_history_read_is_refused_after_genuine_expiry_and_actually_triggers_the_real_deletion(client, fake):
    token, _user = _signup(client)
    headers = _hdr(token)
    sid = _open_temporary(client, headers)
    _chat(client, headers, "temp content before expiry", sid=sid)
    message_id = _msgs(client, headers, sid)["messages"][0]["message_id"]
    assert _versions_dir(sid).exists() and _transcript_path(sid).exists()

    _force_ttl_elapsed_without_triggering_enforce(sid)

    # Before the Priority 2 fix, this route never consulted the terminal
    # state at all: it would have returned 200 with the still-undeleted
    # version history, and -- just as importantly -- never triggered the
    # lazy expiry/deletion cascade that is supposed to run once the TTL
    # is due.
    r = client.get(f"/api/session/{sid}/messages/{message_id}/versions", headers=headers)
    assert r.status_code == 409, r.text
    assert r.json()["code"] == "temporary_expired"
    # The refusal must be a REAL side effect of genuine expiry/deletion
    # firing, not just a status-code check bolted on top of otherwise
    # still-live content.
    assert not _versions_dir(sid).exists(), "hitting the version-history route past the TTL must itself trigger the real deletion cascade, not just refuse while leaving the content intact"
    assert not _transcript_path(sid).exists()


def test_editing_a_message_is_refused_after_genuine_expiry_and_creates_no_new_version(client, fake):
    token, _user = _signup(client)
    headers = _hdr(token)
    sid = _open_temporary(client, headers)
    _chat(client, headers, "temp content before expiry", sid=sid)
    message_id = _msgs(client, headers, sid)["messages"][0]["message_id"]

    _force_ttl_elapsed_without_triggering_enforce(sid)

    r = client.post(f"/api/session/{sid}/messages/{message_id}/edits",
                     json={"content": "an edit attempted on expired content"}, headers=headers)
    assert r.status_code == 409, r.text
    assert r.json()["code"] == "temporary_expired"
    assert not _versions_dir(sid).exists(), "an edit attempt on an expired temporary chat must not resurrect or create version data for content the product has already deleted"


def test_regenerating_an_assistant_message_is_refused_after_genuine_expiry(client, fake):
    token, _user = _signup(client)
    headers = _hdr(token)
    sid = _open_temporary(client, headers)
    _chat(client, headers, "temp content before expiry", sid=sid)
    assistant_id = next(m["message_id"] for m in _msgs(client, headers, sid)["messages"] if m["role"] == "assistant")

    _force_ttl_elapsed_without_triggering_enforce(sid)

    r = client.post(f"/api/session/{sid}/messages/{assistant_id}/regenerate", headers=headers)
    assert r.status_code == 409, r.text
    assert r.json()["code"] == "temporary_expired"


def test_a_legitimate_not_yet_expired_temporary_chat_still_reads_and_edits_normally(client, fake):
    """Regression guard: the fix must not refuse an ACTIVE temporary chat
    whose TTL has not elapsed -- only genuine expiry is enforced."""
    token, _user = _signup(client)
    headers = _hdr(token)
    sid = _open_temporary(client, headers, ttl_seconds=3600)
    _chat(client, headers, "still well within the TTL", sid=sid)
    message_id = _msgs(client, headers, sid)["messages"][0]["message_id"]

    history = client.get(f"/api/session/{sid}/messages/{message_id}/versions", headers=headers)
    assert history.status_code == 200, history.text
    assert history.json()["active_content"] == "still well within the TTL"

    edit = client.post(f"/api/session/{sid}/messages/{message_id}/edits",
                        json={"content": "edited well within the TTL"}, headers=headers)
    assert edit.status_code == 200, edit.text
    assert edit.json()["active_content"] == "edited well within the TTL"


def test_an_ordinary_non_temporary_session_is_completely_unaffected_by_this_boundary(client, fake):
    """Regression guard: _temporary_block() is documented as a no-op for
    a session that was never a temporary chat -- confirm the version/edit
    routes still behave exactly as before for the overwhelmingly common
    (non-temporary) case."""
    token, _user = _signup(client)
    headers = _hdr(token)
    sid = _chat(client, headers, "an ordinary, permanent conversation")["session_id"]
    message_id = _msgs(client, headers, sid)["messages"][0]["message_id"]

    history = client.get(f"/api/session/{sid}/messages/{message_id}/versions", headers=headers)
    assert history.status_code == 200
    edit = client.post(f"/api/session/{sid}/messages/{message_id}/edits",
                        json={"content": "edited normally"}, headers=headers)
    assert edit.status_code == 200
    assert edit.json()["active_content"] == "edited normally"


def test_cross_user_access_to_version_endpoints_is_refused_both_before_and_after_expiry(client, fake):
    """Priority 2's own explicit requirement: 'cross-user access is
    refused.' Ownership (_owned_session_or_404, pre-existing) and the
    new terminal-state check are independent layers -- a foreign user
    must be refused regardless of which one would otherwise fire first."""
    owner_token, _owner = _signup(client)
    owner_headers = _hdr(owner_token)
    other_token, _other = _signup(client)
    other_headers = _hdr(other_token)

    sid = _open_temporary(client, owner_headers)
    _chat(client, owner_headers, "owner's temporary content", sid=sid)
    message_id = _msgs(client, owner_headers, sid)["messages"][0]["message_id"]

    foreign_before = client.get(f"/api/session/{sid}/messages/{message_id}/versions", headers=other_headers)
    assert foreign_before.status_code == 404, "a foreign user must never learn this session exists, before expiry"

    _force_ttl_elapsed_without_triggering_enforce(sid)

    foreign_after = client.get(f"/api/session/{sid}/messages/{message_id}/versions", headers=other_headers)
    assert foreign_after.status_code == 404, "a foreign user must never learn this session exists, after expiry either -- ownership is checked before the terminal-state check, so expiry must never leak existence to a non-owner"

    # The owner themself still correctly gets the real refusal, not a 404.
    owner_after = client.get(f"/api/session/{sid}/messages/{message_id}/versions", headers=owner_headers)
    assert owner_after.status_code == 409 and owner_after.json()["code"] == "temporary_expired"


def test_expired_content_cannot_be_recovered_via_version_read_even_via_a_concurrent_race_with_another_route(client, fake):
    """Direct test of Priority 2's closing sentence: 'expired sessions
    cannot recover deleted content through version endpoints.' Simulates
    the realistic order where some OTHER guarded route (chat) is the one
    that happens to trigger the lazy expiry first -- then confirms the
    version endpoint, hit immediately after, sees the already-deleted
    state and cannot read back anything, rather than racing to read
    stale content before its own deletion check catches up."""
    token, _user = _signup(client)
    headers = _hdr(token)
    sid = _open_temporary(client, headers)
    _chat(client, headers, "content that must not survive expiry", sid=sid)
    message_id = _msgs(client, headers, sid)["messages"][0]["message_id"]

    _force_ttl_elapsed_without_triggering_enforce(sid)

    # A different already-guarded route (temp status) triggers the real
    # expiry first.
    status = client.get(f"/api/session/{sid}/temporary", headers=headers)
    assert status.json()["state"] == "expired"
    assert not _versions_dir(sid).exists()

    # The version endpoint must now see the SAME terminal state, not a
    # stale, pre-expiry view.
    r = client.get(f"/api/session/{sid}/messages/{message_id}/versions", headers=headers)
    assert r.status_code == 409
    assert r.json()["code"] == "temporary_expired"
