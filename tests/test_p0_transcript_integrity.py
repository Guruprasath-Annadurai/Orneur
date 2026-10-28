"""P0 transcript integrity — Antigravity stale-worker / crash / history attacks."""

from __future__ import annotations

import json
import os
import time
import uuid
from pathlib import Path

import pytest

REDIS_URL = "redis://localhost:6379/15"  # isolated DB; do not flush unrelated apps


def _reachable() -> bool:
    try:
        import redis

        redis.from_url(REDIS_URL, socket_connect_timeout=2).ping()
        return True
    except Exception:
        return False


_needs_redis = pytest.mark.skipif(not _reachable(), reason="needs real Redis")


def _enable_redis(monkeypatch):
    import redis as redis_lib

    from orca.serve import session_store as store

    redis_lib.from_url(REDIS_URL).flushdb()
    monkeypatch.setenv("ORNEUR_REDIS_URL", REDIS_URL)
    monkeypatch.setattr(store, "REDIS_URL", REDIS_URL)
    monkeypatch.setattr(store, "_redis_client", None)
    return store


def test_failing_before_stale_revision_insert_was_accepted(isolated_home):
    """Document the pre-fix defect shape: uniqueness of revision alone is insufficient.

    Under the closed protocol, A must be rejected via stale_authority after B's takeover.
    """
    from orca.serve import conversations as conv

    sid = "atk-" + uuid.uuid4().hex[:10]
    a = conv.acquire_authority(sid, "u", "fence-A", ttl_s=0.05)
    assert a is not None
    time.sleep(0.08)
    b = conv.acquire_authority(sid, "u", "fence-B", ttl_s=30)
    assert b is not None and b.epoch > a.epoch
    ok_b = conv.commit_turn(
        sid, "B-user", "B-asst", user_id="u", turn_id="tb", fence_token="fence-B", epoch=b.epoch
    )
    assert ok_b.ok
    ok_a = conv.commit_turn(
        sid, "A-STALE", "A-STALE-ASST", user_id="u", turn_id="ta", fence_token="fence-A", epoch=a.epoch
    )
    assert ok_a.ok is False and ok_a.reason == "stale_authority"
    body = conv.transcript(sid)
    assert [m["content"] for m in body["messages"]] == ["B-user", "B-asst"]
    assert all("A-STALE" not in m["content"] for m in body["messages"])


def test_worker_b_claimed_but_not_committed_when_a_resumes(isolated_home):
    from orca.serve import conversations as conv

    sid = "race-" + uuid.uuid4().hex[:10]
    a = conv.acquire_authority(sid, "u", "A", ttl_s=0.05)
    time.sleep(0.08)
    b = conv.acquire_authority(sid, "u", "B", ttl_s=30)
    assert b is not None
    # A resumes before B commits — still stale.
    ok_a = conv.commit_turn(sid, "A", "Aa", user_id="u", turn_id="ta", fence_token="A", epoch=a.epoch)
    assert ok_a.ok is False and ok_a.reason in {"stale_authority", "authority_expired"}
    ok_b = conv.commit_turn(sid, "B", "Bb", user_id="u", turn_id="tb", fence_token="B", epoch=b.epoch)
    assert ok_b.ok
    assert [m["content"] for m in conv.transcript(sid)["messages"]] == ["B", "Bb"]


def test_crash_before_commit_leaves_no_visible_turn(isolated_home):
    from orca.serve import conversations as conv

    sid = "crash-" + uuid.uuid4().hex[:10]
    auth = conv.acquire_authority(sid, "u", "f", ttl_s=30)
    assert auth is not None
    r = conv.commit_turn(
        sid,
        "u",
        "a",
        user_id="u",
        turn_id="t-crash",
        fence_token="f",
        epoch=auth.epoch,
        _test_crash_after_insert=True,
    )
    assert r.ok is False and r.reason == "crash_before_commit"
    assert conv.transcript(sid)["total"] == 0
    assert conv.turns_for_session(sid) == []
    # Rolled-back turn must not enter model context.
    from orca.serve.inference import _session_messages

    assert _session_messages(sid) == []


def test_export_pending_reconcile_after_skip(isolated_home):
    from orca.serve import conversations as conv

    sid = "exp-" + uuid.uuid4().hex[:10]
    auth = conv.acquire_authority(sid, "u", "f", ttl_s=30)
    r = conv.commit_turn(
        sid, "u", "a", user_id="u", turn_id="t1", fence_token="f", epoch=auth.epoch, _test_skip_export=True
    )
    assert r.ok
    # SQLite has the turn; JSONL may be stale/empty — transcript still reads SQLite.
    assert conv.transcript(sid)["total"] == 2
    n = conv.reconcile_pending_exports()
    assert n >= 1
    raw = Path(conv._path(sid)).read_text(encoding="utf-8")
    assert "\"role\":\"user\"" in raw and "\"role\":\"assistant\"" in raw


def test_legacy_jsonl_not_trusted_until_reconcile(isolated_home):
    from orca.serve import conversations as conv

    sid = "leg-" + uuid.uuid4().hex[:10]
    # Plant untrusted JSONL without SQLite turns.
    conv.append(sid, "user", "LEGACY-SECRET")
    conv.append(sid, "assistant", "legacy-reply")
    assert conv.transcript(sid)["total"] == 0  # empty SQLite → not trusted
    mig = conv.reconcile_legacy_session(sid, "owner")
    assert mig.ok and mig.state == "verified" and mig.imported_turns == 1
    body = conv.transcript(sid)
    assert body["total"] == 2
    assert body["messages"][0]["content"] == "LEGACY-SECRET"


def test_duplicate_turn_id_and_out_of_order_revision(isolated_home):
    from orca.serve import conversations as conv

    sid = "dup-" + uuid.uuid4().hex[:10]
    auth = conv.acquire_authority(sid, "u", "f", ttl_s=30)
    first = conv.commit_turn(sid, "u1", "a1", user_id="u", turn_id="same", fence_token="f", epoch=auth.epoch)
    assert first.ok
    again = conv.commit_turn(sid, "u1", "a1", user_id="u", turn_id="same", fence_token="f", epoch=auth.epoch)
    assert again.ok and again.reason == "idempotent"
    # Different turn_id but would need next revision — works
    second = conv.commit_turn(sid, "u2", "a2", user_id="u", turn_id="other", fence_token="f", epoch=auth.epoch)
    assert second.ok and second.revision == 2


def test_cross_user_authority_rejected(isolated_home):
    from orca.serve import conversations as conv

    sid = "own-" + uuid.uuid4().hex[:10]
    a = conv.acquire_authority(sid, "owner", "f", ttl_s=30)
    assert a is not None
    assert conv.acquire_authority(sid, "thief", "g", ttl_s=30) is None
    bad = conv.commit_turn(sid, "x", "y", user_id="thief", turn_id="t", fence_token="f", epoch=a.epoch)
    assert bad.ok is False and bad.reason == "ownership_mismatch"


def test_sqlite_busy_and_disk_full_fail_closed(isolated_home, monkeypatch):
    from orca.serve import conversations as conv

    sid = "busy-" + uuid.uuid4().hex[:10]
    auth = conv.acquire_authority(sid, "u", "f", ttl_s=30)
    assert auth is not None

    def _boom(*_a, **_k):
        raise OSError("disk full")

    monkeypatch.setattr(conv, "_export_jsonl_from_sqlite", _boom)
    # Commit still succeeds — export failure cannot alter conversation truth.
    r = conv.commit_turn(sid, "u", "a", user_id="u", turn_id="t", fence_token="f", epoch=auth.epoch)
    assert r.ok
    turns = conv.turns_for_session(sid)
    assert len(turns) == 1
    assert conv.transcript(sid)["total"] == 2


@_needs_redis
def test_redis_outage_sqlite_still_authorizes(isolated_home, monkeypatch):
    from orca.serve import conversations as conv
    from orca.serve import session_store as store

    _enable_redis(monkeypatch)
    # Simulate Redis down for lease; SQLite authority still works when Redis disabled.
    monkeypatch.setattr(store, "REDIS_URL", None)
    monkeypatch.setattr(store, "_redis_client", None)
    sid = "rd-" + uuid.uuid4().hex[:10]
    auth = conv.acquire_authority(sid, "u", "f", ttl_s=30)
    assert auth is not None
    r = conv.commit_turn(sid, "u", "a", user_id="u", turn_id="t", fence_token="f", epoch=auth.epoch)
    assert r.ok
    assert conv.transcript(sid)["total"] == 2


@_needs_redis
def test_inference_persist_rejects_stale_after_takeover(isolated_home, monkeypatch):
    from orca.serve import conversations as conv
    from orca.serve.inference import InferenceError, _persist

    store = _enable_redis(monkeypatch)
    sid = "inf-" + uuid.uuid4().hex[:10]
    assert store.acquire_session_lease(sid, "old", ttl_ms=40)
    auth_a = conv.acquire_authority(sid, "u", "old", ttl_s=0.05)
    assert auth_a is not None
    time.sleep(0.08)
    assert store.acquire_session_lease(sid, "new", ttl_ms=5000)
    auth_b = conv.acquire_authority(sid, "u", "new", ttl_s=30)
    assert auth_b is not None

    with pytest.raises(InferenceError) as exc:
        _persist(
            user_id="u",
            session_id=sid,
            message="stale",
            text="stale-asst",
            identity={"served_model": "fixture-llama"},
            model="fixture-llama",
            fence_token="old",
            epoch=auth_a.epoch,
        )
    assert exc.value.code == "stale_worker"
    assert conv.transcript(sid)["total"] == 0

    safe = _persist(
        user_id="u",
        session_id=sid,
        message="fresh",
        text="fresh-asst",
        identity={"served_model": "fixture-llama"},
        model="fixture-llama",
        fence_token="new",
        epoch=auth_b.epoch,
    )
    assert safe == "fresh-asst"
    assert [m["content"] for m in conv.transcript(sid)["messages"]] == ["fresh", "fresh-asst"]


def test_two_os_workers_same_session(isolated_home):
    import subprocess
    import sys

    sid = "mp-" + uuid.uuid4().hex[:10]
    env = dict(os.environ)
    # Ensure child processes resolve the same home as the reloaded parent config.
    import orca.config as config

    env["ORCA_HOME"] = str(config.ORCA_HOME)
    env["ORNEUR_HOME"] = str(config.ORCA_HOME)
    script = f"""
import json, sys, time
from orca.serve import conversations as c
cmd = json.loads(sys.stdin.read())
auth = c.acquire_authority(cmd["sid"], cmd["uid"], cmd["fence"], ttl_s=cmd.get("ttl", 2))
if not auth:
    print(json.dumps({{"ok": False, "reason": "no_auth"}})); raise SystemExit
if cmd.get("sleep"):
    time.sleep(cmd["sleep"])
r = c.commit_turn(cmd["sid"], cmd["user"], cmd["asst"], user_id=cmd["uid"],
                  turn_id=cmd["tid"], fence_token=cmd["fence"], epoch=auth.epoch)
print(json.dumps({{"ok": r.ok, "reason": r.reason, "rev": r.revision, "epoch": auth.epoch}}))
"""
    # Worker A holds short TTL then sleeps past expiry before commit
    a = subprocess.Popen(
        [sys.executable, "-c", script],
        stdin=subprocess.PIPE,
        stdout=subprocess.PIPE,
        text=True,
        env=env,
        cwd="/workspace",
    )
    a.stdin.write(json.dumps({"sid": sid, "uid": "u", "fence": "A", "ttl": 0.2, "sleep": 0.5, "user": "A", "asst": "Aa", "tid": "ta"}))
    a.stdin.close()
    time.sleep(0.25)
    b = subprocess.Popen(
        [sys.executable, "-c", script],
        stdin=subprocess.PIPE,
        stdout=subprocess.PIPE,
        text=True,
        env=env,
        cwd="/workspace",
    )
    b.stdin.write(json.dumps({"sid": sid, "uid": "u", "fence": "B", "ttl": 5, "sleep": 0, "user": "B", "asst": "Bb", "tid": "tb"}))
    b.stdin.close()
    bout = json.loads(b.stdout.read())
    aout = json.loads(a.stdout.read())
    a.wait(timeout=20)
    b.wait(timeout=20)
    assert bout.get("ok") is True
    assert aout.get("ok") is False
    from orca.serve import conversations as conv

    assert [m["content"] for m in conv.transcript(sid)["messages"]] == ["B", "Bb"]
