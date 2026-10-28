"""Transactional turn commit — stale fence must not mutate JSONL."""

from __future__ import annotations

import uuid

import pytest

from orca.auth.db import init_db
from orca.auth.store import User, claim_session
from orca.serve import conversations
from orca.serve.inference import InferenceError, _persist, complete
from orca.serve.turn_commit import TurnCommitError, commit_turn, message_count, recover_pending


def _user(uid="turn-u"):
    return User(id=uid, email=f"{uid}@example.com", name=uid, tier="free", verified=True)


def test_commit_turn_is_atomic_user_assistant(isolated_home):
    init_db()
    sid = "turn" + uuid.uuid4().hex[:12]
    uid = "turn-owner"
    claim_session(sid, uid)
    assert message_count(sid) == 0
    commit_turn(
        user_id=uid,
        session_id=sid,
        user_message="hi",
        assistant_message="hello",
        assistant_meta={"model_identity": {"served_model": "x"}},
        expected_version=0,
        fence_token=None,
        commit_id="c1",
    )
    body = conversations.transcript(sid)
    assert body["total"] == 2
    assert body["messages"][0]["role"] == "user"
    assert body["messages"][1]["role"] == "assistant"


def test_stale_version_does_not_mutate_jsonl(isolated_home):
    init_db()
    sid = "ver" + uuid.uuid4().hex[:12]
    uid = "ver-owner"
    claim_session(sid, uid)
    commit_turn(
        user_id=uid,
        session_id=sid,
        user_message="a",
        assistant_message="b",
        assistant_meta=None,
        expected_version=0,
        fence_token=None,
        commit_id="c-a",
    )
    before = conversations.transcript(sid)["total"]
    with pytest.raises(TurnCommitError) as exc:
        commit_turn(
            user_id=uid,
            session_id=sid,
            user_message="stale",
            assistant_message="poison",
            assistant_meta=None,
            expected_version=0,  # stale — already at 2
            fence_token=None,
            commit_id="c-stale",
        )
    assert exc.value.code == "session_conflict"
    assert conversations.transcript(sid)["total"] == before
    assert all(m["content"] != "poison" for m in conversations.transcript(sid)["messages"])


def test_foreign_owner_cannot_commit(isolated_home):
    init_db()
    sid = "own" + uuid.uuid4().hex[:12]
    claim_session(sid, "alice")
    with pytest.raises(TurnCommitError) as exc:
        commit_turn(
            user_id="bob",
            session_id=sid,
            user_message="x",
            assistant_message="y",
            assistant_meta=None,
            expected_version=0,
            fence_token=None,
            commit_id="c-bob",
        )
    assert exc.value.code == "session_not_found"
    assert message_count(sid) == 0


def test_idempotent_retry_same_commit_id(isolated_home):
    init_db()
    sid = "idem" + uuid.uuid4().hex[:12]
    uid = "idem-u"
    claim_session(sid, uid)
    commit_turn(
        user_id=uid,
        session_id=sid,
        user_message="once",
        assistant_message="only",
        assistant_meta=None,
        expected_version=0,
        fence_token=None,
        commit_id="same-commit",
    )
    # Retry with same commit_id must not double-append.
    commit_turn(
        user_id=uid,
        session_id=sid,
        user_message="once",
        assistant_message="only",
        assistant_meta=None,
        expected_version=0,
        fence_token=None,
        commit_id="same-commit",
    )
    assert message_count(sid) == 2


def test_persist_refuses_when_cas_fence_lost(isolated_home, monkeypatch):
    init_db()
    sid = "fence" + uuid.uuid4().hex[:12]
    uid = "fence-u"
    claim_session(sid, uid)

    monkeypatch.setattr("orca.serve.session_store.enabled", lambda: True)
    monkeypatch.setattr("orca.serve.session_store.lease_held", lambda *_a, **_k: False)
    monkeypatch.setattr(
        "orca.serve.session_store.load_session_state_with_revision",
        lambda *_a, **_k: (None, 1),
    )
    monkeypatch.setattr("orca.serve.session_store.save_session_state", lambda *_a, **_k: False)
    monkeypatch.setattr("orca.serve.session_store.touch_session", lambda *_a, **_k: None)

    with pytest.raises(InferenceError) as exc:
        _persist(
            user_id=uid,
            session_id=sid,
            message="user",
            text="assistant",
            identity={"served_model": "x"},
            model="fixture-llama",
            fence_token="stale-fence",
            commit_id="will-fail",
        )
    assert exc.value.code in ("session_busy", "session_conflict")
    assert message_count(sid) == 0


def test_recover_pending_completes_or_discards(isolated_home):
    init_db()
    sid = "rec" + uuid.uuid4().hex[:12]
    uid = "rec-u"
    claim_session(sid, uid)
    # No pending → missing
    assert recover_pending(sid, "nope") == "missing"
    commit_turn(
        user_id=uid,
        session_id=sid,
        user_message="a",
        assistant_message="b",
        assistant_meta=None,
        expected_version=0,
        fence_token=None,
        commit_id="rec-1",
    )
    assert recover_pending(sid, "rec-1") == "committed"


def test_complete_persist_writes_transcript(isolated_home, ollama_fixture):
    init_db()
    sid = "cmp" + uuid.uuid4().hex[:12]
    complete(
        user=_user("cmp-u"),
        message="ping",
        model="fixture-llama",
        host=ollama_fixture,
        session_id=sid,
        synthetic_provider=True,
    )
    rows = conversations.transcript(sid)["messages"]
    assert len(rows) == 2
    assert rows[0]["content"] == "ping"
