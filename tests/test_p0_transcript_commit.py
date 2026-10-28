"""P0-3: SQLite-authoritative transcript integrity under lease expiry, crash, and contamination."""

from __future__ import annotations

import json
import os
import subprocess
import sys
import time
import uuid

import pytest

REDIS_URL = "redis://localhost:6379/14"


def _reachable() -> bool:
    try:
        import redis

        redis.from_url(REDIS_URL, socket_connect_timeout=2).ping()
        return True
    except Exception:
        return False


_needs_redis = pytest.mark.skipif(not _reachable(), reason="needs real Redis at localhost:6379/14")


def _enable_redis(monkeypatch):
    """Point session_store at a real Redis DB without reloading inference."""
    import redis as redis_lib

    from orca.serve import session_store as store

    # Prefer a dedicated DB; flush only keys we create via a unique prefix session.
    redis_lib.from_url(REDIS_URL).flushdb()
    monkeypatch.setenv("ORNEUR_REDIS_URL", REDIS_URL)
    monkeypatch.setattr(store, "REDIS_URL", REDIS_URL)
    monkeypatch.setattr(store, "_redis_client", None)
    return store


@_needs_redis
def test_stale_worker_cannot_commit_after_lease_expiry(isolated_home, monkeypatch):
    from orca.serve import conversations
    from orca.serve.inference import InferenceError, _persist

    store = _enable_redis(monkeypatch)
    sid = "lease-" + uuid.uuid4().hex[:10]
    assert store.acquire_session_lease(sid, "old-fence", ttl_ms=40)
    time.sleep(0.06)
    assert store.acquire_session_lease(sid, "new-fence", ttl_ms=5_000)

    with pytest.raises(InferenceError) as exc:
        _persist(
            user_id="u-stale",
            session_id=sid,
            message="stale-user",
            text="stale-asst",
            identity={"served_model": "fixture-llama"},
            model="fixture-llama",
            fence_token="old-fence",
        )
    assert exc.value.code == "stale_worker"
    assert conversations.transcript(sid, source="committed")["total"] == 0
    assert conversations.turns_for_session(sid) == []

    safe = _persist(
        user_id="u-new",
        session_id=sid,
        message="fresh-user",
        text="fresh-asst",
        identity={"served_model": "fixture-llama"},
        model="fixture-llama",
        fence_token="new-fence",
    )
    assert safe == "fresh-asst"
    body = conversations.transcript(sid, source="committed")
    assert body["total"] == 2
    assert [m["content"] for m in body["messages"]] == ["fresh-user", "fresh-asst"]
    turns = conversations.turns_for_session(sid)
    assert len(turns) == 1 and turns[0]["user_content"] == "fresh-user"
    state, rev = store.load_session_state_with_revision(sid)
    assert state is not None and rev is not None


@_needs_redis
def test_preclaimed_ticket_cannot_write_after_successor_lease(isolated_home, monkeypatch):
    """Worker A claims, lease expires, B commits; A's later persist must not land."""
    from orca.serve import conversations
    from orca.serve.inference import InferenceError, _persist

    store = _enable_redis(monkeypatch)
    sid = "race-" + uuid.uuid4().hex[:10]
    assert store.acquire_session_lease(sid, "fence-a", ttl_ms=40)
    _state, rev = store.load_session_state_with_revision(sid)
    ticket = store.claim_turn_commit(sid, "fence-a", rev)
    assert ticket is not None

    time.sleep(0.06)
    assert store.acquire_session_lease(sid, "fence-b", ttl_ms=5_000)
    assert _persist(
        user_id="u-b",
        session_id=sid,
        message="from-B",
        text="reply-B",
        identity={"served_model": "fixture"},
        model="fixture",
        fence_token="fence-b",
    ) == "reply-B"

    with pytest.raises(InferenceError) as exc:
        _persist(
            user_id="u-a",
            session_id=sid,
            message="from-A-STALE",
            text="reply-A-STALE",
            identity={"served_model": "fixture"},
            model="fixture",
            fence_token="fence-a",
        )
    assert exc.value.code == "stale_worker"
    users = [t["user_content"] for t in conversations.turns_for_session(sid)]
    assert users == ["from-B"]
    # Planted JSONL must not contaminate committed view / prompts.
    conversations.append(sid, "user", "PHANTOM")
    from orca.serve import inference

    assert [m["content"] for m in inference._session_messages(sid)] == ["from-B", "reply-B"]


@_needs_redis
def test_multiprocess_lease_expiry_only_successor_commits(isolated_home, monkeypatch):
    import orca.brain.memory as brain_memory

    store = _enable_redis(monkeypatch)
    sid = "mp-" + uuid.uuid4().hex[:10]
    assert store.acquire_session_lease(sid, "fence-a", ttl_ms=80)

    # Autouse isolation patches MEMORY_DIR to tmp_path/memory; workers must
    # share that same tree (not isolated_home's separate ORCA_HOME tempfile).
    shared_home = str(brain_memory.MEMORY_DIR.parent)
    env = dict(os.environ)
    env["ORCA_HOME"] = shared_home
    env["ORNEUR_HOME"] = shared_home
    env["ORNEUR_REDIS_URL"] = REDIS_URL
    env.pop("ORCA_DATABASE_URL", None)
    env.pop("ORNEUR_DATABASE_URL", None)
    root = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
    worker = [sys.executable, "-m", "tests._transcript_lease_worker"]

    time.sleep(0.1)  # let fence-a expire
    assert store.acquire_session_lease(sid, "fence-b", ttl_ms=5_000)

    def _run_worker(fence: str, msg: str) -> dict:
        p = subprocess.Popen(
            worker,
            stdin=subprocess.PIPE,
            stdout=subprocess.PIPE,
            stderr=subprocess.PIPE,
            text=True,
            env=env,
            cwd=root,
        )
        p.stdin.write(
            json.dumps(
                {
                    "redis_url": REDIS_URL,
                    "session_id": sid,
                    "user_id": f"u-{fence}",
                    "message": msg,
                    "text": f"reply-{msg}",
                    "fence": fence,
                }
            )
        )
        p.stdin.close()
        out = p.stdout.read()
        err = p.stderr.read()
        p.wait(timeout=30)
        assert out, f"worker {fence} produced no stdout; stderr={err!r}"
        return json.loads(out)

    # Real multi-process: stale worker after lease takeover must fail; successor commits.
    stale = _run_worker("fence-a", "stale-mp")
    fresh = _run_worker("fence-b", "fresh-mp")
    assert stale.get("ok") is False
    assert stale.get("code") == "stale_worker"
    assert fresh.get("ok") is True

    from orca.serve import conversations

    users = [t["user_content"] for t in conversations.turns_for_session(sid)]
    assert users == ["fresh-mp"]

    # Concurrent retry of the stale fence after a successful successor commit.
    again = _run_worker("fence-a", "stale-again")
    assert again.get("ok") is False and again.get("code") == "stale_worker"
    assert [t["user_content"] for t in conversations.turns_for_session(sid)] == ["fresh-mp"]


def test_complete_turn_is_atomic_user_assistant_pair(isolated_home, ollama_fixture, monkeypatch):
    from orca.auth.db import init_db
    from orca.auth.store import User
    from orca.serve import conversations
    from orca.serve.inference import complete

    _enable_redis(monkeypatch) if _reachable() else None
    init_db()
    sid = "pair-" + uuid.uuid4().hex[:10]
    user = User(id="pair-u", email="pair@example.com", name="p", tier="free", verified=True)
    out = complete(
        user=user,
        message="hello pair",
        model="fixture-llama",
        host=ollama_fixture,
        session_id=sid,
        synthetic_provider=True,
    )
    assert out["text"]
    body = conversations.transcript(sid, source="committed")
    assert body["total"] == 2
    assert body["messages"][0]["role"] == "user"
    assert body["messages"][1]["role"] == "assistant"
    assert len(conversations.turns_for_session(sid)) == 1


def test_commit_turn_idempotent_and_no_split_pair(isolated_home):
    from orca.serve import conversations

    sid = "idem-" + uuid.uuid4().hex[:10]
    first = conversations.commit_turn(
        sid, "u", "a", user_id="u1", turn_id="t1", revision=1, meta={"k": 1}
    )
    assert first.ok
    second = conversations.commit_turn(
        sid, "u", "a", user_id="u1", turn_id="t1", revision=1, meta={"k": 1}
    )
    assert second.ok and second.reason == "idempotent"
    conflict = conversations.commit_turn(
        sid, "x", "y", user_id="u1", turn_id="t2", revision=1, meta={}
    )
    assert conflict.ok is False and conflict.reason == "revision_conflict"
    assert conversations.transcript(sid, source="committed")["total"] == 2


def test_jsonl_not_written_inside_uncommitted_sqlite_txn(isolated_home):
    """If authority fails inside the IMMEDIATE txn, JSONL must remain untouched."""
    from orca.serve import conversations

    sid = "txn-" + uuid.uuid4().hex[:10]
    path = conversations._path(sid)
    assert not path.exists()
    denied = conversations.commit_turn(
        sid,
        "u",
        "a",
        user_id="u1",
        turn_id="t-deny",
        revision=None,
        authority_check=lambda: False,
    )
    assert denied.ok is False and denied.reason == "stale_worker"
    assert conversations.turns_for_session(sid) == []
    assert not path.exists()


def test_crash_safe_export_reconcile_and_no_prompt_poison(isolated_home):
    from orca.serve import conversations, inference

    sid = "recon-" + uuid.uuid4().hex[:10]
    assert conversations.commit_turn(
        sid, "real-user", "real-asst", user_id="u1", turn_id="t-real", revision=1
    ).ok
    # Plant phantom JSONL that is not in SQLite.
    conversations.append(sid, "user", "PHANTOM_POISON")
    conversations.append(sid, "assistant", "PHANTOM_ASST")
    # Committed view / prompts ignore phantoms.
    committed = conversations.transcript(sid, source="committed")
    assert [m["content"] for m in committed["messages"]] == ["real-user", "real-asst"]
    assert [m["content"] for m in inference._session_messages(sid)] == ["real-user", "real-asst"]
    # Reconcile rewrites export from SQLite.
    out = conversations.reconcile_export(sid)
    assert out["exported_turns"] == 1
    raw = conversations._path(sid).read_text(encoding="utf-8")
    assert "real-user" in raw and "PHANTOM_POISON" not in raw


def test_uncommitted_jsonl_never_enters_llm_prompt(isolated_home):
    from orca.serve import conversations, inference

    sid = "poison-" + uuid.uuid4().hex[:10]
    conversations.append(sid, "user", "UNCOMMITTED_SECRET_PROMPT_POISON")
    conversations.append(sid, "assistant", "nope")
    assert conversations.turns_for_session(sid) == []
    assert inference._session_messages(sid) == []
    # Empty SQLite must not fall back for committed reads.
    assert conversations.transcript(sid, source="committed")["total"] == 0


def test_explicit_legacy_migration_required(isolated_home):
    from orca.serve import conversations, inference

    sid = "legacy-" + uuid.uuid4().hex[:10]
    conversations.append(sid, "user", "old-user")
    conversations.append(sid, "assistant", "old-asst")
    assert inference._session_messages(sid) == []
    migrated = conversations.migrate_legacy_jsonl(sid, user_id="u-legacy")
    assert migrated["imported"] == 1
    assert [m["content"] for m in inference._session_messages(sid)] == ["old-user", "old-asst"]
    again = conversations.migrate_legacy_jsonl(sid, user_id="u-legacy")
    assert again["reason"] == "already_migrated"


def test_rollback_retry_allocates_monotonic_revision(isolated_home):
    from orca.serve import conversations

    sid = "retry-" + uuid.uuid4().hex[:10]
    # First attempt refused by authority — no revision consumed.
    assert conversations.commit_turn(
        sid, "a", "b", user_id="u", turn_id="t-fail", authority_check=lambda: False
    ).reason == "stale_worker"
    first = conversations.commit_turn(
        sid, "a", "b", user_id="u", turn_id="t-ok1", authority_check=lambda: True
    )
    second = conversations.commit_turn(
        sid, "c", "d", user_id="u", turn_id="t-ok2", authority_check=lambda: True
    )
    assert first.ok and second.ok
    assert first.revision == 1 and second.revision == 2
    revs = [t["revision"] for t in conversations.turns_for_session(sid)]
    assert revs == [1, 2]


def test_sqlite_unavailable_does_not_fall_back_to_jsonl(isolated_home, monkeypatch):
    from orca.serve import conversations

    sid = "unavail-" + uuid.uuid4().hex[:10]
    conversations.append(sid, "user", "secret-jsonl")
    conversations.append(sid, "assistant", "secret-asst")

    def boom(*_a, **_k):
        raise conversations.TurnsUnavailable("forced")

    monkeypatch.setattr(conversations, "turns_for_session", boom)
    body = conversations.transcript(sid, source="auto")
    assert body["total"] == 0
    assert body["source"] == "sqlite_unavailable"
