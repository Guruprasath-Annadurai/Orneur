"""L02-03 -- outcome truth under REAL failures (evidence class: LIVE_API: real ``orca serve`` processes, shared SQLite, real Redis in a dedicated container).

Model provider: FakeOllama (fixture) so timing is deterministic. Everything on the ORNEUR side - HTTP, SSE, SQLite fencing, Redis leases, process death - is real.
The recurring invariant: whatever the connection did, ``GET /api/turns/<key>`` agrees with the transcript, and one request key never yields more than one stored turn.

Run:  pytest tests/journey/test_l02_recovery_live.py -p no:cacheprovider -v
"""
from __future__ import annotations

import json
import os
import random
import signal
import sqlite3
import threading
import time
import uuid
from pathlib import Path

import httpx
import pytest

from tests.fake_ollama import FakeOllama
from tests.journey.harness import JOURNEY_MODEL, LiveServer, User
from tests.journey.test_l02_deletion_live import RedisBox, _turns_db, _wait

EVIDENCE = Path(os.environ.get("ORNEUR_L02_EVIDENCE_DIR", "/tmp/orneur-l02-evidence"))


def record(name, data):
    EVIDENCE.mkdir(parents=True, exist_ok=True)
    (EVIDENCE / f"l02_recovery_live_{name}.json").write_text(json.dumps({"recorded_at": time.strftime("%Y-%m-%dT%H:%M:%S%z"), **data}, indent=2))


@pytest.fixture(scope="module")
def cluster(tmp_path_factory):
    box = RedisBox()
    fake = FakeOllama(models=(JOURNEY_MODEL,), reply="FIXTURE-ANSWER")
    fake.__enter__()
    home = tmp_path_factory.mktemp("l02-rec-home")
    env = {"ORNEUR_OLLAMA_HOST": fake.host, "OLLAMA_HOST": fake.host, "ORNEUR_TURN_AUTHORITY_TTL_S": "3", "ORNEUR_TURN_HEARTBEAT_S": "1",
           "ORNEUR_TURN_LEASE_MS": "4000", "ORNEUR_DELETION_SWEEP_S": "3600"}
    a, b = LiveServer(home, redis_url=box.url, extra_env=env), LiveServer(home, redis_url=box.url, extra_env=env)
    try:
        a.wait_ready()
        b.wait_ready()
        user = User(a.base, "l02rec")
        user.token_b = httpx.post(f"{b.base}/api/auth/login", json={"email": user.email, "password": "Journey-Pass-91x"}, timeout=30).json()["token"]
        yield {"box": box, "fake": fake, "home": home, "env": env, "a": a, "b": b, "user": user}
    finally:
        for s in (a, b):
            try:
                s.stop()
            except Exception:
                pass
        fake.__exit__(None, None, None)
        box.close()


def _reset(fake):
    fake.pre_response_delay, fake.chunk_delay, fake._chunks, fake.reply = 0.0, 0.0, None, "FIXTURE-ANSWER"
    fake.fail_status = fake.truncate_after = None


def _key():
    return "k-" + uuid.uuid4().hex


def _post_stream(base, token, k, body, *, stop_after=None, abort_after_done_text=False):
    """Returns (events, aborted). With ``stop_after`` the client walks away after that many chunk events (a dropped connection, not a Stop)."""
    events, n = [], 0
    with httpx.Client(base_url=base, timeout=120) as c:
        with c.stream("POST", "/api/stream", json={"model_variant": "core", **body}, headers={"Authorization": f"Bearer {token}", "Idempotency-Key": k}) as r:
            for line in r.iter_lines():
                if line.startswith("data: "):
                    ev = json.loads(line[6:])
                    events.append(ev)
                    n += ev["type"] == "chunk"
                    if stop_after and n >= stop_after:
                        return events, True
    return events, False


def _outcome(base, token, k):
    r = httpx.get(f"{base}/api/turns/{k}", headers={"Authorization": f"Bearer {token}"}, timeout=30)
    return r.status_code, r.json()


def _rows(home, sid):
    c = sqlite3.connect(str(_turns_db(home)))
    try:
        return c.execute("SELECT COUNT(*) FROM conversation_turns WHERE session_id=?", (sid,)).fetchone()[0]
    finally:
        c.close()


def _units(user, base=None):
    return httpx.get(f"{base or user.base}/api/auth/me", headers=user.headers, timeout=30).json()["usage"]["messages"]


def test_R1_outcome_is_readable_from_the_other_worker_while_running_and_after_commit(cluster):
    fake, user, a, b = cluster["fake"], cluster["user"], cluster["a"], cluster["b"]
    _reset(fake)
    fake._chunks = tuple(f"w{i} " for i in range(12))
    fake.chunk_delay = 0.25
    k, sid = _key(), str(uuid.uuid4())
    res = {}
    th = threading.Thread(target=lambda: res.update(r=_post_stream(a.base, user.token, k, {"message": "slow one", "session_id": sid})))
    th.start()
    seen = set()
    end = time.time() + 20
    while time.time() < end and th.is_alive():
        seen.add(_outcome(b.base, user.token_b, k)[1]["state"])
        time.sleep(0.2)
    th.join()
    final = _outcome(b.base, user.token_b, k)[1]
    assert "running" in seen and final["state"] == "committed" and _rows(cluster["home"], sid) == 1
    record("R1_cross_worker", {"states_seen_from_worker_b": sorted(seen), "final": final["state"]})


def test_R2_dropped_connection_mid_generation_is_not_committed_and_a_retry_commits_once(cluster):
    fake, user, a, b = cluster["fake"], cluster["user"], cluster["a"], cluster["b"]
    _reset(fake)
    fake._chunks = tuple(f"w{i} " for i in range(30))
    fake.chunk_delay = 0.1
    k, sid = _key(), str(uuid.uuid4())
    u0 = _units(user)
    events, aborted = _post_stream(a.base, user.token, k, {"message": "drop me", "session_id": sid}, stop_after=3)
    assert aborted
    st = _wait(lambda: (lambda o: o if o["terminal"] else None)(_outcome(b.base, user.token_b, k)[1]), timeout=15)
    assert st and st["state"] == "not_committed" and st["reason"] == "client_disconnected" and st["safe_to_retry"] is True
    assert _rows(cluster["home"], sid) == 0
    _reset(fake)
    again, _ = _post_stream(b.base, user.token_b, k, {"message": "drop me", "session_id": sid})
    assert again[-1]["type"] == "done" and again[-1]["persisted"] == "saved"
    assert _outcome(a.base, user.token, k)[1]["state"] == "committed" and _rows(cluster["home"], sid) == 1
    record("R2_drop_then_retry", {"first_attempt": st["state"], "reason": st["reason"], "units_spent": _units(user) - u0,
                                  "note": "the first attempt produced output before the drop, so its unit stays spent (policy); the retry is a second generation the user chose"})


def test_R3_stop_endpoint_cancels_across_workers_and_is_confirmed(cluster):
    fake, user, a, b = cluster["fake"], cluster["user"], cluster["a"], cluster["b"]
    _reset(fake)
    fake._chunks = tuple(f"w{i} " for i in range(80))
    fake.chunk_delay = 0.1
    k, sid = _key(), str(uuid.uuid4())
    res = {}
    th = threading.Thread(target=lambda: res.update(r=_post_stream(a.base, user.token, k, {"message": "stop me", "session_id": sid})))
    th.start()
    assert fake.stream_started.wait(15)
    time.sleep(0.6)
    t0 = time.time()
    c = httpx.post(f"{b.base}/api/turns/{k}/cancel", headers={"Authorization": f"Bearer {user.token_b}"}, timeout=30)       # Stop is sent to the OTHER worker
    assert c.status_code in (200, 202)
    th.join(timeout=20)
    took = time.time() - t0
    assert not th.is_alive()
    st = _outcome(b.base, user.token_b, k)[1]
    assert st["state"] == "cancelled" and st["reason"] == "user_stop" and _rows(cluster["home"], sid) == 0
    assert fake.stream_aborted.wait(5)
    record("R3_stop_cross_worker", {"seconds_from_cancel_to_stream_end": round(took, 2), "final": st["state"], "turn_rows": 0})


def test_R4_commit_race_every_round_is_coherent_and_idempotent(cluster):
    """Drop the connection at randomised points around the commit, 12 rounds (the per-IP request limit of 60/min stays on). Whatever happens, outcome == transcript, and a retry never duplicates."""
    fake, user, a, b = cluster["fake"], cluster["user"], cluster["a"], cluster["b"]
    _reset(fake)
    fake._chunks = tuple(f"p{i} " for i in range(6))
    fake.chunk_delay = 0.02
    rng = random.Random(1234)
    committed = not_committed = 0
    for i in range(12):
        k, sid = _key(), str(uuid.uuid4())
        events, aborted = _post_stream(a.base, user.token, k, {"message": f"race {i}", "session_id": sid}, stop_after=rng.choice([4, 5, 6, 6, 6]))
        st = _wait(lambda: (lambda o: o if o["terminal"] else None)(_outcome(b.base, user.token_b, k)[1]), timeout=15)
        assert st, f"round {i}: never terminal"
        rows = _rows(cluster["home"], sid)
        assert (st["state"] == "committed") == (rows == 1), (i, st, rows)
        assert rows in (0, 1)
        retry, _ = _post_stream(b.base, user.token_b, k, {"message": f"race {i}", "session_id": sid})
        assert retry[-1]["type"] == "done", (i, st, retry[-1])
        assert _rows(cluster["home"], sid) == 1, f"round {i}: retry duplicated or lost the turn"
        assert _outcome(a.base, user.token, k)[1]["state"] == "committed"
        committed += st["state"] == "committed"
        not_committed += st["state"] != "committed"
    record("R4_commit_race", {"rounds": 12, "first_attempt_committed": committed, "first_attempt_not_committed": not_committed, "duplicates": 0})


def test_R5_worker_killed_mid_generation_resolves_not_committed_and_a_retry_succeeds_on_the_other_worker(cluster):
    fake, user, b = cluster["fake"], cluster["user"], cluster["b"]
    _reset(fake)
    victim = LiveServer(cluster["home"], redis_url=cluster["box"].url, extra_env=cluster["env"])
    victim.wait_ready()
    token_v = httpx.post(f"{victim.base}/api/auth/login", json={"email": user.email, "password": "Journey-Pass-91x"}, timeout=30).json()["token"]
    fake._chunks = tuple(f"w{i} " for i in range(80))
    fake.chunk_delay = 0.1
    k, sid = _key(), str(uuid.uuid4())
    th = threading.Thread(target=lambda: _post_stream_safe(victim.base, token_v, k, {"message": "kill the worker", "session_id": sid}))
    th.start()
    assert fake.stream_started.wait(15)
    time.sleep(0.8)
    victim.proc.send_signal(signal.SIGKILL)                                    # the process dies without any cleanup
    th.join(timeout=20)
    mid = _outcome(b.base, user.token_b, k)[1]
    st = _wait(lambda: (lambda o: o if o["terminal"] else None)(_outcome(b.base, user.token_b, k)[1]), timeout=20)
    assert st and st["state"] == "not_committed" and st["reason"] == "worker_lost" and _rows(cluster["home"], sid) == 0
    _reset(fake)
    again, _ = _post_stream(b.base, user.token_b, k, {"message": "kill the worker", "session_id": sid})
    assert again[-1]["type"] == "done" and again[-1]["persisted"] == "saved" and _rows(cluster["home"], sid) == 1, again[-2:]
    record("R5_worker_killed", {"state_right_after_kill": mid["state"], "resolved": st["state"], "reason": st["reason"], "retry": "committed once on the surviving worker"})


def _post_stream_safe(*a, **k):
    try:
        return _post_stream(*a, **k)
    except Exception:
        return None


def test_R6_restart_after_commit_keeps_the_outcome(cluster):
    user = cluster["user"]
    _reset(cluster["fake"])
    solo = LiveServer(cluster["home"], redis_url=cluster["box"].url, extra_env=cluster["env"])
    solo.wait_ready()
    tok = httpx.post(f"{solo.base}/api/auth/login", json={"email": user.email, "password": "Journey-Pass-91x"}, timeout=30).json()["token"]
    k, sid = _key(), str(uuid.uuid4())
    ev, _ = _post_stream(solo.base, tok, k, {"message": "survive restart", "session_id": sid})
    assert ev[-1]["persisted"] == "saved"
    solo.stop()
    fresh = LiveServer(cluster["home"], redis_url=cluster["box"].url, extra_env=cluster["env"])
    try:
        fresh.wait_ready()
        tok2 = httpx.post(f"{fresh.base}/api/auth/login", json={"email": user.email, "password": "Journey-Pass-91x"}, timeout=30).json()["token"]
        st = _outcome(fresh.base, tok2, k)[1]
        assert st["state"] == "committed" and st["message_id"] == ev[-1]["message_id"]
        n0 = len(cluster["fake"].requests)
        again, _ = _post_stream(fresh.base, tok2, k, {"message": "survive restart", "session_id": sid})
        assert again[-1].get("idempotent_replay") is True and len(cluster["fake"].requests) == n0 and _rows(cluster["home"], sid) == 1
    finally:
        fresh.stop()
    record("R6_restart", {"outcome_after_restart": st["state"], "replayed_without_model_call": True})


def test_R7_slow_commit_outcome_reads_stay_prompt_and_truthful_while_the_commit_waits(cluster):
    """The transcript database is write-locked by another process for ~3 s while a turn tries to commit (a slow final commit). Readers are not blocked (WAL): the
    outcome endpoint answers promptly with ``running`` - the truth, nothing is committed yet - and ``committed`` once the commit lands."""
    fake, user, a, b = cluster["fake"], cluster["user"], cluster["a"], cluster["b"]
    _reset(fake)
    fake._chunks = tuple(f"w{i} " for i in range(10))
    fake.chunk_delay = 0.2
    k, sid = _key(), str(uuid.uuid4())
    res = {}
    th = threading.Thread(target=lambda: res.update(r=_post_stream(a.base, user.token, k, {"message": "slow commit", "session_id": sid})))
    th.start()
    assert fake.stream_started.wait(15)
    time.sleep(0.8)
    lock = sqlite3.connect(str(_turns_db(cluster["home"])), timeout=0.1, isolation_level=None)
    lock.execute("BEGIN IMMEDIATE")
    held_since, reads = time.time(), []
    try:
        while time.time() - held_since < 3.2:
            t0 = time.time()
            code, body = _outcome(b.base, user.token_b, k)
            reads.append((code, body["state"], round(time.time() - t0, 2)))
            time.sleep(0.3)
    finally:
        lock.execute("ROLLBACK")
        lock.close()
    th.join(timeout=40)
    final = _outcome(b.base, user.token_b, k)[1]
    assert all(c == 200 and st in ("running", "admitted") and dt < 2 for c, st, dt in reads), reads
    assert final["state"] == "committed" and res["r"][0][-1]["persisted"] == "saved" and _rows(cluster["home"], sid) == 1
    record("R7_slow_commit", {"reads_during_lock": reads, "final": final["state"]})


def test_R8_redis_outage_during_a_turn_still_commits_and_reports_committed(cluster):
    fake, user, a, box = cluster["fake"], cluster["user"], cluster["a"], cluster["box"]
    _reset(fake)
    fake._chunks = tuple(f"w{i} " for i in range(20))
    fake.chunk_delay = 0.15
    k, sid = _key(), str(uuid.uuid4())
    res = {}
    th = threading.Thread(target=lambda: res.update(r=_post_stream(a.base, user.token, k, {"message": "redis dies mid turn", "session_id": sid})))
    th.start()
    assert fake.stream_started.wait(15)
    box.down()
    try:
        th.join(timeout=60)
    finally:
        box.up()
    ev = res["r"][0]
    st = _outcome(a.base, user.token, k)[1]
    assert ev[-1]["type"] in ("done", "error")
    assert (st["state"] == "committed") == (_rows(cluster["home"], sid) == 1), (st, ev[-1])
    record("R8_redis_outage", {"final_event": ev[-1]["type"], "persisted": ev[-1].get("persisted"), "outcome": st["state"], "turn_rows": _rows(cluster["home"], sid)})
