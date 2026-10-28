"""LANDMARK-01: regression tests for defects found while integrating #129 (product lineage) with #130 (SQLite-authoritative transcript).

Each test names the defect it pins; they were written failing-first against the unmodified integration where that was possible.
"""
from __future__ import annotations

import os
import sqlite3
import uuid

import pytest

from orca.serve import conversations


def _turn(sid, uid, n, rev_fence=None):
    fence = rev_fence or uuid.uuid4().hex
    auth = conversations.acquire_authority(sid, uid, fence, ttl_s=30.0)
    assert auth is not None
    res = conversations.commit_turn(sid, f"q{n}", f"a{n}", user_id=uid, turn_id=uuid.uuid4().hex, fence_token=fence, epoch=auth.epoch)
    conversations.release_authority(sid, fence, auth.epoch)
    return res


def test_authority_row_created_over_existing_turns_continues_the_revision_sequence(isolated_home):
    """A session with committed turns but no authority row (older database / removed row) used to get committed_revision=0, so every later commit
    collided with revision 1 (revision_conflict) forever."""
    sid, uid = "seedrev01-test", "u-seed"
    assert _turn(sid, uid, 1).ok and _turn(sid, uid, 2).ok
    conn = conversations._turns_conn()
    with conn:
        conn.execute("DELETE FROM session_authority WHERE session_id=?", (sid,))
    conn.close()
    third = _turn(sid, uid, 3)
    assert third.ok, third.reason
    assert third.revision == 3
    assert [t["revision"] for t in conversations.turns_for_session(sid)] == [1, 2, 3]


def test_jsonl_export_is_not_truncated_by_short_writes(isolated_home, monkeypatch):
    sid, uid = "shortwr01-test", "u-short"
    real_write = os.write

    def trickle(fd, data):
        return real_write(fd, bytes(data[:7]))          # the kernel accepted only 7 bytes

    for n in range(1, 4):
        assert _turn(sid, uid, n).ok
    with monkeypatch.context() as m:                     # NOT monkeypatch.undo(): that would also revert the suite's storage isolation
        m.setattr(os, "write", trickle)
        conversations._export_jsonl_from_sqlite(sid)
    lines = conversations._path(sid).read_text().splitlines()
    assert len(lines) == 6 and lines[0].startswith("{") and lines[-1].endswith("}"), lines[-1]


def test_a_read_never_takes_authority_and_a_real_legacy_import_releases_it(isolated_home):
    sid, uid = "readauth01-test", "u-read"
    assert _turn(sid, uid, 1).ok
    for _ in range(3):
        assert conversations.reconcile_legacy_session(sid, uid).reason == "already_verified"
    conn = conversations._turns_conn()
    row = conn.execute("SELECT fence_token, expires_at FROM session_authority WHERE session_id=?", (sid,)).fetchone()
    conn.close()
    assert not str(row["fence_token"]).startswith("migrate-"), "a read took over the session's authority"
    # a genuine import releases what it took
    legacy = "legacy0001-test"
    conversations.append(legacy, "user", "old q")
    conversations.append(legacy, "assistant", "old a")
    res = conversations.reconcile_legacy_session(legacy, uid)
    assert res.ok and res.reason == "migrated" and res.imported_turns == 1
    nxt = _turn(legacy, uid, 2)
    assert nxt.ok and nxt.revision == 2


def test_inference_prompt_assembly_failure_refunds_the_reservation(isolated_home, ollama_fixture, monkeypatch):
    """Assembling history ran AFTER the quota reservation but BEFORE the refund-on-failure block, so a failure there left the unit reserved."""
    from orca.auth.store import User, get_usage_today
    from orca.serve import inference

    uid = "u-refund-" + uuid.uuid4().hex[:6]
    user = User(id=uid, email=f"{uid}@example.com", name=uid, tier="free", verified=True)
    monkeypatch.setattr(inference, "_prompt_with_session", lambda *a, **k: (_ for _ in ()).throw(RuntimeError("history store exploded")))
    with pytest.raises(RuntimeError):
        inference.complete(user=user, message="hello", model="fixture-llama", host=ollama_fixture, session_id=uuid.uuid4().hex)
    assert get_usage_today(uid)["messages"] == 0


def test_inference_proceeds_on_sqlite_authority_when_redis_is_unreachable(isolated_home, ollama_fixture, monkeypatch):
    from orca.auth.store import User
    from orca.serve import inference, session_store

    monkeypatch.setattr(session_store, "REDIS_URL", "redis://127.0.0.1:1/0")
    monkeypatch.setattr(session_store, "_redis_client", None)
    assert session_store.enabled()
    uid = "u-noredis-" + uuid.uuid4().hex[:6]
    user = User(id=uid, email=f"{uid}@example.com", name=uid, tier="free", verified=True)
    out = inference.complete(user=user, message="hello", model="fixture-llama", host=ollama_fixture, session_id=uuid.uuid4().hex)
    assert out["text"]
