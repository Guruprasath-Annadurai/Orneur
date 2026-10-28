"""Inference + Claude Redis fencing. Skips (not passes) without Redis."""

from __future__ import annotations

import json
import os
import subprocess
import sys
import time
import uuid

import pytest

from orca.serve import session_store as ss

REDIS_URL = "redis://localhost:6379/14"


def _reachable() -> bool:
    try:
        import redis

        redis.from_url(REDIS_URL, socket_connect_timeout=2).ping()
        return True
    except Exception:
        return False


_needs_redis = pytest.mark.skipif(not _reachable(), reason="needs real Redis at localhost:6379/14")


@_needs_redis
def test_expired_lease_cannot_cas_save():
    import importlib

    import redis as redis_lib

    redis_lib.from_url(REDIS_URL).flushdb()
    prev = os.environ.get("ORNEUR_REDIS_URL")
    os.environ["ORNEUR_REDIS_URL"] = REDIS_URL
    import orca.serve.session_store as store

    importlib.reload(store)
    try:
        sid = "lease-" + uuid.uuid4().hex[:12]
        assert store.acquire_session_lease(sid, "old-fence", ttl_ms=50)
        time.sleep(0.08)
        assert store.acquire_session_lease(sid, "new-fence", ttl_ms=5_000)
        assert store.save_session_state(sid, "nano", [{"role": "user", "content": "stale"}], expected_revision=None, fence_token="old-fence") is False
        assert store.save_session_state(sid, "nano", [{"role": "user", "content": "fresh"}], expected_revision=None, fence_token="new-fence") is True
        state, _rev = store.load_session_state_with_revision(sid)
        assert state and state["history"][0]["content"] == "fresh"
    finally:
        if prev is None:
            os.environ.pop("ORNEUR_REDIS_URL", None)
        else:
            os.environ["ORNEUR_REDIS_URL"] = prev
        importlib.reload(store)


@_needs_redis
def test_two_os_workers_session_lease_exclusion():
    import redis as redis_lib

    redis_lib.from_url(REDIS_URL).flushdb()
    sid = "inf-" + uuid.uuid4().hex[:12]
    env = dict(os.environ, ORNEUR_REDIS_URL=REDIS_URL)
    cwd = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
    holder = subprocess.Popen(
        [sys.executable, "-m", "tests._session_store_worker"],
        stdin=subprocess.PIPE,
        stdout=subprocess.PIPE,
        text=True,
        env=env,
        cwd=cwd,
    )
    rival = subprocess.Popen(
        [sys.executable, "-m", "tests._session_store_worker"],
        stdin=subprocess.PIPE,
        stdout=subprocess.PIPE,
        text=True,
        env=env,
        cwd=cwd,
    )
    holder.stdin.write(json.dumps({"op": "hold", "sid": sid, "fence": "A", "sleep_s": 1.2, "ttl_ms": 5000}))
    holder.stdin.close()
    time.sleep(0.2)
    rival.stdin.write(json.dumps({"op": "acquire", "sid": sid, "fence": "B", "ttl_ms": 2000}))
    rival.stdin.close()
    rival_out = json.loads(rival.stdout.read())
    holder_out = json.loads(holder.stdout.read())
    holder.wait(timeout=20)
    rival.wait(timeout=20)
    assert holder_out.get("ok") is True
    assert rival_out.get("ok") is False


def test_cross_process_quota_against_shared_sqlite(isolated_home, tmp_path):
    from orca.auth.db import AUTH_DB, init_db
    from orca.auth.store import increment_usage

    init_db()
    uid = "cross-q"
    for _ in range(49):
        increment_usage(uid, "message")
    env = dict(os.environ)
    procs = []
    for i in range(3):
        p = subprocess.Popen(
            [sys.executable, "-m", "tests._quota_worker"],
            stdin=subprocess.PIPE,
            stdout=subprocess.PIPE,
            text=True,
            env=env,
            cwd=os.path.dirname(os.path.dirname(os.path.abspath(__file__))),
        )
        procs.append(p)
        p.stdin.write(json.dumps({"user_id": uid, "request_id": f"cp-{i}"}))
        p.stdin.close()
    bodies = [json.loads(p.stdout.read()) for p in procs]
    for p in procs:
        p.wait(timeout=30)
    assert sum(1 for b in bodies if b.get("ok")) == 1
    AUTH_DB  # keep path used


@_needs_redis
def test_stale_fence_commit_does_not_mutate_jsonl():
    """A3: expired lease cannot append authoritative transcript after Redis CAS refuse."""
    import importlib

    import redis as redis_lib

    from orca.auth.db import init_db
    from orca.auth.store import claim_session
    from orca.serve import conversations
    from orca.serve.turn_commit import TurnCommitError, commit_turn, message_count

    redis_lib.from_url(REDIS_URL).flushdb()
    prev = os.environ.get("ORNEUR_REDIS_URL")
    os.environ["ORNEUR_REDIS_URL"] = REDIS_URL
    import orca.serve.session_store as store

    importlib.reload(store)
    try:
        init_db()
        sid = "jsonl-" + uuid.uuid4().hex[:12]
        claim_session(sid, "redis-owner")
        assert store.acquire_session_lease(sid, "old-fence", ttl_ms=50)
        time.sleep(0.08)
        assert store.acquire_session_lease(sid, "new-fence", ttl_ms=5_000)
        before = message_count(sid)
        with pytest.raises(TurnCommitError) as exc:
            commit_turn(
                user_id="redis-owner",
                session_id=sid,
                user_message="stale-user",
                assistant_message="stale-assistant",
                assistant_meta=None,
                expected_version=before,
                fence_token="old-fence",
                commit_id="stale-commit",
            )
        assert exc.value.code in ("session_busy", "session_conflict")
        assert message_count(sid) == before
        assert all(
            m["content"] not in ("stale-user", "stale-assistant")
            for m in conversations.transcript(sid)["messages"]
        )
        # Fresh fence can commit.
        commit_turn(
            user_id="redis-owner",
            session_id=sid,
            user_message="fresh-user",
            assistant_message="fresh-assistant",
            assistant_meta=None,
            expected_version=before,
            fence_token="new-fence",
            commit_id="fresh-commit",
        )
        assert message_count(sid) == before + 2
    finally:
        if prev is None:
            os.environ.pop("ORNEUR_REDIS_URL", None)
        else:
            os.environ["ORNEUR_REDIS_URL"] = prev
        importlib.reload(store)
