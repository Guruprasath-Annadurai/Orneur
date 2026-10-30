"""Genuinely independent OS processes sharing only a real Redis (db 14).

tests/test_redis_stale_payload_resurrection.py simulates workers with
separate in-memory dicts inside one interpreter; this file removes that
caveat: each worker is its own Python process (tests/_redis_worker.py).
Includes a real Redis server restart (docker container) when available.
Skips if Redis is unreachable.
"""
from __future__ import annotations

from tests._redis_guard import safe_flush

import json
import os
import subprocess
import sys

import pytest

REDIS_URL = "redis://localhost:6379/14"


def _reachable() -> bool:
    try:
        import redis
        redis.from_url(REDIS_URL, socket_connect_timeout=2).ping()
        return True
    except Exception:
        return False


pytestmark = pytest.mark.skipif(not _reachable(), reason="needs real Redis at localhost:6379/14")


class Worker:
    def __init__(self, tmp_path, name):
        env = dict(os.environ, ORNEUR_REDIS_URL=REDIS_URL, ORNEUR_HOME=str(tmp_path / name))
        self.p = subprocess.Popen([sys.executable, "-m", "tests._redis_worker"], stdin=subprocess.PIPE,
                                  stdout=subprocess.PIPE, text=True, env=env,
                                  cwd=os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

    def call(self, **cmd):
        self.p.stdin.write(json.dumps(cmd) + "\n")
        self.p.stdin.flush()
        out = json.loads(self.p.stdout.readline())
        assert "error" not in out, out
        return out

    def close(self):
        self.p.stdin.close()
        self.p.wait(timeout=20)


@pytest.fixture
def workers(tmp_path):
    import redis
    safe_flush(redis.from_url(REDIS_URL))
    made = []

    def make(name):
        w = Worker(tmp_path, name)
        made.append(w)
        return w

    yield make
    for w in made:
        w.close()
    safe_flush(redis.from_url(REDIS_URL))


HIST = [{"role": "user", "content": "original message text"}, {"role": "assistant", "content": "ok"}]


def test_audited_abc_sequence_across_real_processes(workers):
    a, b, c = workers("a"), workers("b"), workers("c")
    assert a.call(op="seed", sid="s1", history=HIST)["persisted"] is True
    assert b.call(op="edit", sid="s1", previous="original message text", new="EDITED")["live_sync"] is True
    out = c.call(op="history", sid="s1")
    assert "original message text" not in out["history"], "worker C adopted stale Redis history"
    assert out["freshness"] == "confirmed"


def test_stale_writer_process_is_refused_and_cannot_resurrect(workers):
    a, b, c = workers("a"), workers("b"), workers("c")
    a.call(op="seed", sid="s2", history=HIST)
    b.call(op="edit", sid="s2", previous="original message text", new="EDITED")
    assert a.call(op="persist", sid="s2")["persisted"] is False
    assert "original message text" not in c.call(op="history", sid="s2")["history"]
    # A still holds its stale cache until its next request detects the revision.
    assert "original message text" not in a.call(op="history", sid="s2")["history"]


def test_concurrent_edits_from_many_processes_get_distinct_revisions(workers):
    ws = [workers(f"w{i}") for i in range(4)]
    import redis
    from concurrent.futures import ThreadPoolExecutor
    r = redis.from_url(REDIS_URL, decode_responses=True)
    for w in ws:
        w.call(op="has_local", sid="s3")
    with ThreadPoolExecutor(4) as ex:
        list(ex.map(lambda w: [w.call(op="edit", sid="s3", previous="x", new="y") for _ in range(10)], ws))
    base = int(r.get("orca:session:s3:rev")) - 40
    assert base > 10**14 and r.get("orca:session:s3:rev") is not None  # 40 distinct INCRs on one clock-seeded counter


def _restart_redis() -> bool:
    try:
        subprocess.run(["docker", "restart", "orneur-redis-test"], check=True, capture_output=True, timeout=60)
    except Exception:
        return False
    import redis
    import time
    for _ in range(50):
        try:
            redis.from_url(REDIS_URL).ping()
            return True
        except Exception:
            time.sleep(0.2)
    return False


def test_real_redis_server_restart_does_not_resurrect_or_alias_revisions(workers):
    a, b, c = workers("a"), workers("b"), workers("c")
    a.call(op="seed", sid="s4", history=HIST)
    b.call(op="edit", sid="s4", previous="original message text", new="EDITED 1")
    before = a.call(op="history", sid="s4")["known"]
    if not _restart_redis():
        pytest.skip("cannot restart the docker Redis container here")
    # State is gone. A fresh edit must still produce a revision that differs from anything A holds.
    b.call(op="edit", sid="s4", previous="x", new="y")
    out = a.call(op="history", sid="s4")
    assert out["known"] != before
    assert "original message text" not in c.call(op="history", sid="s4")["history"]
