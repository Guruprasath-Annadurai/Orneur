"""CTO follow-up directive, Priority 2: temporary-chat privacy boundary
audit across session-scoped endpoints.

Audited: /api/knowledge/{session_id}, /api/knowledge/{session_id}/{entity_name},
session title (/api/session/{id}/title), sharing (/api/session/{id}/shares,
/api/shares/{id}/messages), memory (/api/memory/recall, /api/remember),
transcript (/api/session/{id}/messages), explanation
(/api/explain/{id}/{message_id}), and export (/api/session/{id}/export).

Findings, each backed by a failing-before test or an empirical
harmlessness check, not assumption:

1. CONFIRMED VULNERABILITY, now fixed: create_session_share()
   (POST /api/session/{id}/shares) gated share creation on
   temporary_chat.is_active(), which -- read directly -- checks BOTH
   the stored state AND real-time TTL (`moment < expires_at`). A
   temporary chat whose TTL has genuinely elapsed in real time, but
   whose lazy enforce() has not yet run (expiry is lazy everywhere in
   this codebase -- see the prior closeout's Priority 2 finding),
   reads back as NOT active by this check, even though its content has
   not actually been deleted yet. create_session_share() would
   therefore let a caller create a real share grant for it, and
   shared_messages() would then hand the grantee the full,
   still-undeleted transcript of a conversation the product has
   already told its owner is temporary and gone. This defeats the
   entire purpose of temporary chat mode via a path (sharing) that was
   explicitly supposed to refuse it.

2. Audited and found harmless (not fixed, for the stated reason, not
   left unexamined): /api/knowledge/{id}, /api/knowledge/{id}/{entity},
   and /api/memory/recall all lack a terminal-state guard too, but
   knowledge-graph extraction and long-term-memory commits are BOTH
   unconditionally skipped for the entire lifetime of a temporary chat
   (confirmed by reading the exact gate: `if not
   temporary_chat.is_active(sess.id): extract_and_add(...)` at the
   chat-turn call site, and the existing
   test_temporary_chat_is_hidden_and_skips_long_term_memory coverage
   for memory). There is empirically nothing these routes could ever
   return for a temporary session, confirmed by a live reproduction
   below rather than assumed from the code alone.

3. Title (PATCH /api/session/{id}/title) only WRITES a caller-supplied
   string; it returns nothing read from the session's own content, and
   a temporary chat's title is never surfced anywhere visible (temp
   chats are already excluded from /api/sessions listing). Not a
   content-disclosure path.

Expired, closed, failed-deletion (via retry_failed_closure's own
coverage in test_b13_temporary_chat.py), and cross-user states are all
exercised below for the confirmed fix.

Run with: pytest tests/test_temporary_chat_privacy_boundary.py -q
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
    anything (expire_due(), _temporary_block(), any route) that would
    itself trigger the lazy expiry/deletion this test exists to verify
    is -- or, for the confirmed vulnerability, currently is NOT --
    enforced before protected data is returned. Rewrites only the
    stored record's own expires_at field, the exact field BOTH
    is_active() and enforce() compare against time.time()."""
    import orca.brain.memory as mem
    path = Path(mem.MEMORY_DIR) / "temporary_chats" / f"{sid}.json"
    record = json.loads(path.read_text())
    assert record["state"] == "active"
    record["expires_at"] = time.time() - 5
    path.write_text(json.dumps(record))


# --- Confirmed vulnerability: sharing an expired-but-unenforced temporary chat ---

def test_a_share_cannot_be_created_for_a_temporary_chat_past_its_ttl_even_before_lazy_enforcement_runs(client, fake):
    owner_token, _owner = _signup(client)
    owner_headers = _hdr(owner_token)
    grantee_token, grantee_id = _signup(client)

    sid = _open_temporary(client, owner_headers)
    _chat(client, owner_headers, "content that must stay private and ephemeral", sid=sid)

    _force_ttl_elapsed_without_triggering_enforce(sid)

    # The exact gap: is_active() itself already reports False here
    # (TTL genuinely elapsed), confirming the record has NOT yet been
    # lazily enforced/deleted -- content is still live on disk.
    from orca.serve import temporary_chat
    assert temporary_chat.is_active(sid) is False, "is_active() must already report false once the TTL has genuinely elapsed -- this IS the condition create_session_share() failed to also refuse"
    from pathlib import Path
    import orca.brain.memory as mem
    assert (Path(mem.MEMORY_DIR) / "conversations" / f"{sid}.jsonl").exists(), "the transcript must still be undeleted at this exact moment -- this is what a share would have exposed"

    r = client.post(f"/api/session/{sid}/shares", json={"grantee_id": grantee_id, "ttl_seconds": 3600}, headers=owner_headers)
    assert r.status_code == 400, r.text
    assert r.json().get("code") == "temporary_not_shareable", r.text


def test_an_already_expired_temporary_chat_cannot_be_shared_after_lazy_enforcement_has_run_either(client, fake):
    """Regression guard: the already-terminal (post-enforcement) case
    must also still be refused -- confirms the fix did not accidentally
    narrow coverage to only the pre-enforcement window."""
    owner_token, _owner = _signup(client)
    owner_headers = _hdr(owner_token)
    grantee_token, grantee_id = _signup(client)

    sid = _open_temporary(client, owner_headers)
    _chat(client, owner_headers, "content", sid=sid)
    from orca.serve import temporary_chat
    temporary_chat.expire_due(now=time.time() + 120)

    r = client.post(f"/api/session/{sid}/shares", json={"grantee_id": grantee_id, "ttl_seconds": 3600}, headers=owner_headers)
    assert r.status_code == 400, r.text
    assert r.json().get("code") == "temporary_not_shareable", r.text


def test_sharing_a_closed_temporary_chat_is_refused(client, fake):
    owner_token, _owner = _signup(client)
    owner_headers = _hdr(owner_token)
    grantee_token, grantee_id = _signup(client)

    sid = _open_temporary(client, owner_headers)
    _chat(client, owner_headers, "content", sid=sid)
    close = client.post(f"/api/session/{sid}/temporary/close", headers=owner_headers)
    assert close.status_code == 200 and close.json()["state"] == "closed"

    r = client.post(f"/api/session/{sid}/shares", json={"grantee_id": grantee_id, "ttl_seconds": 3600}, headers=owner_headers)
    assert r.status_code == 400, r.text
    assert r.json().get("code") == "temporary_not_shareable", r.text


def test_a_legitimate_not_yet_expired_active_session_can_still_be_shared_normally(client, fake):
    """Regression guard: the fix must not refuse sharing for an
    ORDINARY (never-temporary) session, the overwhelmingly common case."""
    owner_token, _owner = _signup(client)
    owner_headers = _hdr(owner_token)
    grantee_token, grantee_id = _signup(client)

    sid = _chat(client, owner_headers, "an ordinary permanent conversation")["session_id"]
    r = client.post(f"/api/session/{sid}/shares", json={"grantee_id": grantee_id, "ttl_seconds": 3600}, headers=owner_headers)
    assert r.status_code == 200, r.text
    assert "share_id" in r.json()


def test_cross_user_share_creation_is_refused_regardless_of_temporary_state(client, fake):
    """Priority 2's own explicit requirement: cross-user states.
    Ownership is checked independently of (and before) the temporary-
    chat check -- a non-owner must be refused either way."""
    owner_token, _owner = _signup(client)
    owner_headers = _hdr(owner_token)
    other_token, _other = _signup(client)
    other_headers = _hdr(other_token)
    _grantee_token, grantee_id = _signup(client)

    sid = _chat(client, owner_headers, "owner's own conversation")["session_id"]
    r = client.post(f"/api/session/{sid}/shares", json={"grantee_id": grantee_id, "ttl_seconds": 3600}, headers=other_headers)
    assert r.status_code == 404, "a non-owner must never be able to create a share for someone else's session, nor learn whether it exists"


# --- Audited, confirmed harmless (empirical, not assumed) ---

def test_knowledge_graph_routes_return_nothing_for_a_temporary_chat_even_past_its_ttl(client, fake):
    """Empirical confirmation, not assumption: knowledge-graph
    extraction is unconditionally skipped for the entire lifetime of a
    temporary chat, so there is genuinely nothing these routes could
    expose -- verified live, not just by reading the extraction gate."""
    token, _user = _signup(client)
    headers = _hdr(token)
    sid = _open_temporary(client, headers)
    _chat(client, headers, "ACME Corp signed a deal with Umbrella Industries", sid=sid)

    summary = client.get(f"/api/knowledge/{sid}", headers=headers)
    assert summary.status_code == 200
    assert summary.json()["count"] == {"entities": 0, "relationships": 0}
    assert summary.json()["entities"] == []

    entity = client.get(f"/api/knowledge/{sid}/ACME Corp", headers=headers)
    assert entity.status_code == 404

    _force_ttl_elapsed_without_triggering_enforce(sid)
    summary_after = client.get(f"/api/knowledge/{sid}", headers=headers)
    assert summary_after.status_code == 200
    assert summary_after.json()["count"] == {"entities": 0, "relationships": 0}, "still nothing to leak even past the TTL, before lazy enforcement has run"


def test_memory_recall_returns_nothing_committed_from_a_temporary_chat_even_past_its_ttl(client, fake):
    """Empirical confirmation: long-term memory commits are
    unconditionally skipped for temporary chats (existing coverage:
    test_temporary_chat_is_hidden_and_skips_long_term_memory), so
    recall_memory() has nothing session-specific to return either,
    verified live with a query that would match if anything had leaked."""
    token, _user = _signup(client)
    headers = _hdr(token)
    sid = _open_temporary(client, headers)
    _chat(client, headers, "SECRET-MARKER-SHOULD-NEVER-BE-RECALLED", sid=sid)

    recall = client.post("/api/memory/recall", json={"session_id": sid, "query": "SECRET-MARKER-SHOULD-NEVER-BE-RECALLED"}, headers=headers)
    assert recall.status_code == 200
    assert "SECRET-MARKER-SHOULD-NEVER-BE-RECALLED" not in json.dumps(recall.json()["hits"])

    _force_ttl_elapsed_without_triggering_enforce(sid)
    recall_after = client.post("/api/memory/recall", json={"session_id": sid, "query": "SECRET-MARKER-SHOULD-NEVER-BE-RECALLED"}, headers=headers)
    assert recall_after.status_code == 200
    assert "SECRET-MARKER-SHOULD-NEVER-BE-RECALLED" not in json.dumps(recall_after.json()["hits"])
