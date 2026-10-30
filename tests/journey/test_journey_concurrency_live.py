"""Journeys H / I / reliability -- REAL multi-process behaviour (evidence class: LIVE_API + FIXTURE provider).

Two (or more) real ``orca serve`` processes share one ORNEUR_HOME (SQLite) and one real Redis. The model provider is a controllable FakeOllama so that
timing (a slow or hung generation) is deterministic; everything ORNEUR-side -- auth, quota, Redis leases, SQLite fencing, DLP, persistence -- is the real
code in real processes. Pass/fail never depends on what a model says: assertions are on HTTP/SSE results, on what the provider was SENT, and on the
bytes in the shared stores.

Run:  pytest tests/journey/test_journey_concurrency_live.py -m journey_live -p no:cacheprovider -v
"""
from __future__ import annotations

import json
import os
import signal
import sqlite3
import subprocess
import sys
import threading
import time
import uuid
from pathlib import Path

import httpx
import pytest

from tests.fake_ollama import FakeOllama
from tests.journey.harness import JOURNEY_MODEL, REPO, CapabilityMissing, LiveServer, User

REDIS_URL = "redis://localhost:6379/12"
SECRET = "sk-" + "a1B2c3D4e5F6g7H8i9J0k1L2"
AWS = "AKIAIOSFODNN7EXAMPLE"


def _redis():
    import redis

    try:
        client = redis.from_url(REDIS_URL, socket_connect_timeout=2)
        client.ping()
        return client
    except Exception as exc:
        raise CapabilityMissing(f"capability missing: Redis at {REDIS_URL} ({exc!r})")


def _scrub_redis(client) -> None:
    for pattern in ("orca:session:*", "orca:ratelimit:*"):               # only ORNEUR keys, only in the dedicated test DB (never a FLUSHDB)
        for key in client.scan_iter(match=pattern, count=500):
            client.delete(key)


def _events(user: User, body: dict, key: str | None = None, token: str | None = None, base: str | None = None):
    headers = {"Authorization": f"Bearer {token or user.token}"}
    if key:
        headers["Idempotency-Key"] = key
    out = []
    with httpx.Client(base_url=base or user.base, timeout=180) as c:
        with c.stream("POST", "/api/stream", json={"model_variant": "core", **body}, headers=headers) as r:
            if r.status_code != 200:
                r.read()
                return [{"type": "http", "status": r.status_code, "body": r.text[:300]}]
            for line in r.iter_lines():
                if line.startswith("data: "):
                    out.append(json.loads(line[6:]))
    return out


def _login(base: str, user: User) -> str:
    return httpx.post(f"{base}/api/auth/login", json={"email": user.email, "password": "Journey-Pass-91x"}, timeout=30).json()["token"]


def _transcript(base: str, token: str, sid: str):
    r = httpx.get(f"{base}/api/session/{sid}/messages", headers={"Authorization": f"Bearer {token}"}, timeout=30)
    assert r.status_code == 200, r.text
    return [(m["role"], m["content"]) for m in r.json()["messages"]]


def _answering_call(fake: FakeOllama, prompt: str):
    for req in reversed(fake.requests):
        msgs = req.get("messages") or []
        if msgs and msgs[-1].get("role") == "user" and msgs[-1].get("content", "").strip() == prompt.strip():
            return "\n".join(f"{m['role']}: {m['content']}" for m in msgs)
    return None


@pytest.fixture(scope="module")
def cluster(tmp_path_factory):
    """FIXTURE provider + two ORNEUR workers (shared home, shared real Redis, short turn timings so a hung-worker takeover takes seconds)."""
    client = _redis()
    _scrub_redis(client)
    fake = FakeOllama(models=(JOURNEY_MODEL,), reply="FIXTURE-ANSWER")       # (the streamed pieces follow `reply` unless a test sets `chunks`)
    fake.__enter__()
    home = tmp_path_factory.mktemp("cluster-home")
    env = {
        "ORNEUR_OLLAMA_HOST": fake.host, "OLLAMA_HOST": fake.host,
        "ORNEUR_TURN_AUTHORITY_TTL_S": "3", "ORNEUR_TURN_HEARTBEAT_S": "1", "ORNEUR_TURN_LEASE_MS": "4000",
    }
    a = LiveServer(home, redis_url=REDIS_URL, extra_env=env)
    b = LiveServer(home, redis_url=REDIS_URL, extra_env=env)
    try:
        a.wait_ready()
        b.wait_ready()
        yield {"fake": fake, "a": a, "b": b, "home": home, "env": env, "redis": client}
    finally:
        for s in (a, b):
            try:
                s.proc.send_signal(signal.SIGCONT)
            except Exception:
                pass
            s.stop()
        fake.__exit__(None, None, None)


def _reset_provider(fake: FakeOllama) -> None:
    fake.pre_response_delay, fake.chunk_delay, fake._chunks, fake.reply = 0.0, 0.0, None, "FIXTURE-ANSWER"
    fake.fail_status = fake.truncate_after = None


def _fresh_user(cluster, label: str) -> User:
    u = User(cluster["a"].base, label)
    u.token_b = _login(cluster["b"].base, u)
    _reset_provider(cluster["fake"])
    return u


@pytest.fixture(scope="module")
def shared_user(cluster):
    """One signed-up account for the H-series (signup is rate limited to 5/h/IP, a control we leave on)."""
    return _fresh_user(cluster, "conc")


@pytest.fixture
def user(cluster, shared_user):
    _reset_provider(cluster["fake"])
    return shared_user


# ------------------------------------------------------------------------------------------------ H: concurrency

def test_H1_overlapping_turns_across_workers_are_serialised_not_interleaved(cluster, user):
    fake = cluster["fake"]
    sid = str(uuid.uuid4())
    fake.pre_response_delay = 3.0
    fake.reply = "SLOW-ONE"
    result = {}
    t = threading.Thread(target=lambda: result.setdefault("a", _events(user, {"message": "turn on A", "session_id": sid})))
    t.start()
    time.sleep(1.0)                                              # A is mid-generation and holds the turn (Redis lease + SQLite epoch)
    fake.pre_response_delay = 0.0
    on_b = _events(user, {"message": "turn on B", "session_id": sid}, token=user.token_b, base=cluster["b"].base)
    t.join(timeout=60)
    assert any(e.get("code") == "session_busy" for e in on_b), on_b
    done_a = [e for e in result["a"] if e["type"] == "done"]
    assert done_a and done_a[0]["persisted"] == "saved", result["a"]
    assert _transcript(cluster["b"].base, user.token_b, sid) == [("user", "turn on A"), ("assistant", "SLOW-ONE")]
    # once A finished, B is no longer blocked and sees A's turn
    fake.reply = "B-ANSWER"
    after = _events(user, {"message": "turn on B again", "session_id": sid}, token=user.token_b, base=cluster["b"].base)
    assert [e for e in after if e["type"] == "done"][0]["persisted"] == "saved"
    ctx = _answering_call(fake, "turn on B again")
    assert ctx and "turn on A" in ctx and "SLOW-ONE" in ctx


def test_H2_hung_worker_is_superseded_and_cannot_write_after_a_successor_commits(cluster, user):
    """SIGSTOP worker A mid-generation (a hung / partitioned worker), let its authority lapse, let worker B take the conversation over and commit,
    then SIGCONT A. A's stale commit must be refused, nothing of it may be published, and the next prompt must contain B's turn but not A's."""
    fake, a, b = cluster["fake"], cluster["a"], cluster["b"]
    sid = str(uuid.uuid4())
    fake.reply = "A-STALE-ANSWER"
    fake.pre_response_delay = 14.0
    before = len(fake.requests)
    result = {}
    t = threading.Thread(target=lambda: result.setdefault("a", _events(user, {"message": "stale question", "session_id": sid})))
    t.start()
    for _ in range(100):                                          # wait until A's request actually reached the provider
        if len(fake.requests) > before:
            break
        time.sleep(0.1)
    assert len(fake.requests) > before, "worker A never reached the provider"
    fake.pre_response_delay = 0.0
    a.proc.send_signal(signal.SIGSTOP)                            # A hangs: no heartbeat, no lease renewal
    try:
        time.sleep(6.0)                                           # > SQLite authority TTL (3s) and Redis lease (4s)
        fake.reply = "B-SUCCESSOR-ANSWER"
        on_b = _events(user, {"message": "successor question", "session_id": sid}, token=user.token_b, base=b.base)
        done_b = [e for e in on_b if e["type"] == "done"]
        assert done_b and done_b[0]["persisted"] == "saved", on_b
    finally:
        a.proc.send_signal(signal.SIGCONT)
    t.join(timeout=60)
    events_a = result["a"]
    assert not any(e["type"] == "done" and e.get("persisted") == "saved" for e in events_a), f"the superseded worker reported its turn as saved: {events_a}"
    assert any(e.get("code") == "turn_superseded" or (e["type"] == "done" and e.get("persisted") == "failed") for e in events_a), events_a
    assert _transcript(b.base, user.token_b, sid) == [("user", "successor question"), ("assistant", "B-SUCCESSOR-ANSWER")]
    # the next turn, served by the formerly hung worker, is built from the authoritative transcript
    fake.reply = "A-RECOVERED"
    nxt = _events(user, {"message": "what happened before?", "session_id": sid})
    assert [e for e in nxt if e["type"] == "done"][0]["persisted"] == "saved", nxt
    ctx = _answering_call(fake, "what happened before?")
    assert ctx and "successor question" in ctx and "B-SUCCESSOR-ANSWER" in ctx
    assert "stale question" not in ctx and "A-STALE-ANSWER" not in ctx, f"the superseded turn leaked into the next prompt:\n{ctx}"


def test_H3_duplicate_delivery_across_workers_replays_once(cluster, user):
    fake = cluster["fake"]
    sid = str(uuid.uuid4())
    key = "cross-worker-" + uuid.uuid4().hex[:12]
    fake.reply = "ONCE"
    first = _events(user, {"message": "deliver me once", "session_id": sid}, key=key)
    assert [e for e in first if e["type"] == "done"][0]["persisted"] == "saved"
    def answering_calls():
        # count only the calls that ANSWER this message: the first turn's knowledge-graph extraction is a background side-call that may land late
        return [r for r in fake.requests if (r.get("messages") or [{}])[-1].get("content", "") == "deliver me once"]

    n = len(answering_calls())
    assert n == 1, "the first delivery should have produced exactly one answering call"
    again = _events(user, {"message": "deliver me once", "session_id": sid}, key=key, token=user.token_b, base=cluster["b"].base)
    assert [e for e in again if e["type"] == "done"][0].get("idempotent_replay") is True, again
    assert len(answering_calls()) == n, "the duplicate reached the model"
    assert _transcript(cluster["a"].base, user.token, sid) == [("user", "deliver me once"), ("assistant", "ONCE")]


def test_H4_redis_restart_mid_conversation_loses_nothing_committed(cluster, user):
    fake = cluster["fake"]
    sid = str(uuid.uuid4())
    fake.reply = "BEFORE-RESTART"
    assert [e for e in _events(user, {"message": "before the restart", "session_id": sid}) if e["type"] == "done"][0]["persisted"] == "saved"
    # The command is configurable because the Redis under test is a local container on a workstation and a service container in CI.
    cmd = os.environ.get("ORNEUR_JOURNEY_REDIS_RESTART_CMD", "docker restart orneur-redis-test")
    res = subprocess.run(cmd, shell=True, capture_output=True, text=True, timeout=180)
    assert res.returncode == 0, f"{cmd!r}: {res.stderr}"
    for _ in range(60):
        try:
            _redis()
            break
        except CapabilityMissing:
            time.sleep(0.5)
    fake.reply = "AFTER-RESTART"
    after = _events(user, {"message": "after the restart", "session_id": sid}, token=user.token_b, base=cluster["b"].base)
    done = [e for e in after if e["type"] == "done"]
    assert done and done[0]["persisted"] == "saved", after
    assert _transcript(cluster["a"].base, user.token, sid) == [
        ("user", "before the restart"), ("assistant", "BEFORE-RESTART"), ("user", "after the restart"), ("assistant", "AFTER-RESTART"),
    ]
    ctx = _answering_call(fake, "after the restart")
    assert ctx and "before the restart" in ctx and "BEFORE-RESTART" in ctx


def test_H5_redis_unavailable_degrades_to_sqlite_authority_and_is_honest(cluster, tmp_path_factory):
    """A worker whose Redis is unreachable still serves signed-in conversations through the durable SQLite fence (Redis is advisory)."""
    fake = cluster["fake"]
    home = tmp_path_factory.mktemp("no-redis-home")
    srv = LiveServer(home, redis_url="redis://localhost:6399/0",
                     extra_env={"ORNEUR_OLLAMA_HOST": fake.host, "OLLAMA_HOST": fake.host})
    try:
        srv.wait_ready()
        u = User(srv.base, "noredis")
        sid = str(uuid.uuid4())
        fake.reply = "NO-REDIS-OK"
        ev = _events(u, {"message": "hello without redis", "session_id": sid})
        done = [e for e in ev if e["type"] == "done"]
        assert done and done[0]["persisted"] == "saved", ev
        r = u.post("/api/chat", json={"message": "second", "session_id": sid, "model_variant": "core"})
        assert r.status_code == 200 and r.json()["context_freshness"] in {"rebuilt_authoritative", "unconfirmed"}, r.json().get("context_freshness")
        assert len(_transcript(srv.base, u.token, sid)) == 4
    finally:
        srv.stop()


def test_H6_server_restart_keeps_committed_conversations(cluster, tmp_path_factory):
    fake = cluster["fake"]
    home = tmp_path_factory.mktemp("restart-home")
    env = {"ORNEUR_OLLAMA_HOST": fake.host, "OLLAMA_HOST": fake.host}
    s1 = LiveServer(home, extra_env=env)
    try:
        s1.wait_ready()
        u = User(s1.base, "restart")
        sid = str(uuid.uuid4())
        fake.reply = "SURVIVES"
        assert [e for e in _events(u, {"message": "remember the pomelo", "session_id": sid}) if e["type"] == "done"][0]["persisted"] == "saved"
        s1.proc.kill()                                                # no graceful shutdown: a crash
        s1.proc.wait(timeout=15)
    finally:
        if s1.proc.poll() is None:
            s1.proc.kill()
        s1._log.close()
    s2 = LiveServer(home, extra_env=env)
    try:
        s2.wait_ready()
        token = _login(s2.base, u)
        assert _transcript(s2.base, token, sid) == [("user", "remember the pomelo"), ("assistant", "SURVIVES")]
        listing = httpx.get(f"{s2.base}/api/sessions", headers={"Authorization": f"Bearer {token}"}, timeout=30).json()
        assert sid in json.dumps(listing)
        fake.reply = "STILL-HERE"
        ev = _events(u, {"message": "what did I ask you to remember?", "session_id": sid}, token=token, base=s2.base)
        assert [e for e in ev if e["type"] == "done"][0]["persisted"] == "saved"
        ctx = _answering_call(fake, "what did I ask you to remember?")
        assert ctx and "pomelo" in ctx
    finally:
        s2.stop()


# ------------------------------------------------------------------------------------------------ I: quota + DLP

def _spend(home: Path, user_id: str, n: int) -> None:
    code = (
        "from orca.auth.store import increment_usage\n"
        f"[increment_usage({user_id!r}, 'message') for _ in range({n})]\n"
    )
    env = {k: v for k, v in os.environ.items() if not k.startswith(("ORNEUR_", "ORCA_"))}
    env.update({"ORNEUR_HOME": str(home), "PYTHONPATH": str(REPO)})
    subprocess.run([sys.executable, "-c", code], env=env, check=True, cwd=REPO, timeout=60)


def test_I1_exhausted_user_concurrent_race_across_two_workers_admits_exactly_one(cluster):
    user = _fresh_user(cluster, "quota")
    fake = cluster["fake"]
    uid = httpx.get(f"{cluster['a'].base}/api/auth/me", headers=user.headers, timeout=30).json()["user"]["id"]
    _spend(cluster["home"], uid, 49)
    fake.reply = "LAST-ONE"
    before = len(fake.requests)
    outcomes, lock, barrier = [], threading.Lock(), threading.Barrier(10)

    def fire(i):
        base, token = (cluster["a"].base, user.token) if i % 2 == 0 else (cluster["b"].base, user.token_b)
        barrier.wait()
        ev = _events(user, {"message": f"race {i}", "session_id": str(uuid.uuid4())}, token=token, base=base)
        with lock:
            outcomes.append("done" if any(e["type"] == "done" for e in ev) else ("quota" if any(e.get("code") == "quota_exceeded" for e in ev) else f"other:{ev[-1]}"))

    threads = [threading.Thread(target=fire, args=(i,)) for i in range(10)]
    [t.start() for t in threads]
    [t.join(timeout=120) for t in threads]
    assert outcomes.count("done") == 1 and outcomes.count("quota") == 9, outcomes
    kernel_calls = [r for r in fake.requests[before:] if (r.get("messages") or [{}])[-1].get("content", "").startswith("race ")]
    assert len(kernel_calls) == 1, f"{len(kernel_calls)} model dispatches for 1 admitted request"
    replay = _events(user, {"message": "replay after exhaustion", "session_id": str(uuid.uuid4())})
    assert any(e.get("code") == "quota_exceeded" for e in replay)


def test_I2_secret_split_across_provider_chunks_never_reaches_wire_or_disk(cluster):
    user = _fresh_user(cluster, "dlp")
    fake, a = cluster["fake"], cluster["a"]
    sid = str(uuid.uuid4())
    up = httpx.post(f"{a.base}/api/docs/upload", params={"session_id": sid}, headers=user.headers,
                    files={"file": ("n.txt", b"Orneur is a fictional architecture used in tests.", "text/plain")}, timeout=120)
    assert up.status_code == 200, up.text
    reply = f"here: {SECRET} and {AWS} done"
    cut = reply.index(SECRET) + 9
    fake.chunks, fake.reply = [reply[:cut], reply[cut:cut + 6], reply[cut + 6:]], reply
    try:
        ev = _events(user, {"message": "show keys", "session_id": sid})
    finally:
        fake._chunks = None
    wire = json.dumps(ev)
    assert SECRET not in wire and AWS not in wire, "a credential split across chunks reached the browser"
    assert [e for e in ev if e["type"] == "done"][0]["persisted"] == "saved"
    needle_hits = []
    for p in Path(cluster["home"]).rglob("*"):
        if p.is_file():
            try:
                data = p.read_bytes()
            except OSError:
                continue
            if SECRET.encode() in data or AWS.encode() in data:
                needle_hits.append(str(p.relative_to(cluster["home"])))
    assert needle_hits == [], f"credential bytes on disk: {needle_hits}"
    for key in cluster["redis"].scan_iter(match="orca:session:*", count=500):
        val = cluster["redis"].get(key) if cluster["redis"].type(key) == b"string" else b""
        assert SECRET.encode() not in (val or b"") and AWS.encode() not in (val or b""), f"credential in Redis key {key!r}"


# ------------------------------------------------------------------------------------------------ G: session security across workers

def test_G3_logout_all_on_one_worker_revokes_every_device_token_on_every_worker(cluster):
    _scrub_redis(cluster["redis"])                     # login is rate limited (a control we keep ON); earlier tests in this module used the budget
    u = _fresh_user(cluster, "logoutall")
    a, b = cluster["a"].base, cluster["b"].base
    device2 = _login(a, u)
    device3 = _login(b, u)
    for base, tok in ((a, u.token), (b, u.token_b), (a, device2), (b, device3)):
        assert httpx.get(f"{base}/api/auth/me", headers={"Authorization": f"Bearer {tok}"}, timeout=30).status_code == 200
    assert httpx.post(f"{a}/api/auth/logout-all", headers={"Authorization": f"Bearer {device2}"}, timeout=30).status_code == 200
    before = len(cluster["fake"].requests)
    for base, tok in ((a, u.token), (b, u.token_b), (a, device2), (b, device3)):
        for method, path in (("get", "/api/auth/me"), ("get", "/api/sessions"), ("post", "/api/chat")):
            r = httpx.request(method, f"{base}{path}", headers={"Authorization": f"Bearer {tok}"},
                              json={"message": "should never run", "model_variant": "core"} if method == "post" else None, timeout=30)
            assert r.status_code == 401, f"{base}{path} accepted a revoked device token: {r.status_code}"
        ev = _events(u, {"message": "never", "session_id": str(uuid.uuid4())}, token=tok, base=base)
        assert ev and ev[0].get("status") == 401, ev
    assert len(cluster["fake"].requests) == before, "a revoked token caused a model dispatch"
    fresh = _login(a, u)
    assert httpx.get(f"{b}/api/auth/me", headers={"Authorization": f"Bearer {fresh}"}, timeout=30).status_code == 200


# ------------------------------------------------------------------------------------------------ B-01: the streamed default path across workers

def _stream_until(base: str, token: str, body: dict, *, stop_after_chunks: int | None = None, on_chunk=None):
    """Stream from ``base``; call ``on_chunk(n)`` after each chunk and optionally hang up after ``stop_after_chunks``. Returns the events seen."""
    events, n = [], 0
    headers = {"Authorization": f"Bearer {token}", "Idempotency-Key": str(uuid.uuid4())}
    with httpx.Client(base_url=base, timeout=180) as c:
        with c.stream("POST", "/api/stream", json={"model_variant": "core", **body}, headers=headers) as r:
            for line in r.iter_lines():
                if line.startswith("data: "):
                    ev = json.loads(line[6:])
                    events.append(ev)
                    if ev["type"] == "chunk":
                        n += 1
                        if on_chunk:
                            on_chunk(n)
                        if stop_after_chunks and n >= stop_after_chunks:
                            break
    return events


def test_S12_worker_stalled_MID_STREAM_cannot_commit_after_a_successor_took_over(cluster, user):
    """B-01 / S12. Worker A is streaming real provider deltas to the client when it hangs (SIGSTOP) after the 2nd chunk. Its authority lapses, worker B takes
    the conversation and commits, A resumes and finishes reading the provider. A must NOT commit (SQLite epoch fence), must tell its client the turn was not
    saved, and the next prompt must be built from B's turn only."""
    fake, a, b = cluster["fake"], cluster["a"], cluster["b"]
    sid = str(uuid.uuid4())
    fake.chunks, fake.chunk_delay = [f"A{i} " for i in range(14)], 0.5
    result = {}

    def stall(n):
        if n == 2 and "stopped" not in result:
            result["stopped"] = True
            a.proc.send_signal(signal.SIGSTOP)                    # A hangs mid-stream: no heartbeat, no lease renewal

    def run_a():
        result["a"] = _stream_until(a.base, user.token, {"message": "mid stream question", "session_id": sid}, on_chunk=stall)

    t = threading.Thread(target=run_a)
    t.start()
    for _ in range(100):
        if result.get("stopped"):
            break
        time.sleep(0.1)
    assert result.get("stopped"), "worker A never streamed two chunks"
    try:
        time.sleep(6.0)                                           # > SQLite authority TTL (3s) and Redis lease (4s)
        fake.chunks = ["B-", "SUCCESSOR"]
        on_b = _events(user, {"message": "successor question", "session_id": sid}, token=user.token_b, base=b.base)
        done_b = [e for e in on_b if e["type"] == "done"]
        assert done_b and done_b[0]["persisted"] == "saved", on_b
    finally:
        a.proc.send_signal(signal.SIGCONT)
    t.join(timeout=90)
    events_a = result["a"]
    assert sum(e["type"] == "chunk" for e in events_a) >= 2, "A had streamed real chunks to its client before it stalled"
    assert not any(e["type"] == "done" and e.get("persisted") == "saved" for e in events_a), f"the superseded streaming worker reported its turn as saved: {events_a[-3:]}"
    assert any(e.get("code") == "turn_superseded" or (e["type"] == "done" and e.get("persisted") == "failed") for e in events_a), events_a[-3:]
    assert _transcript(b.base, user.token_b, sid) == [("user", "successor question"), ("assistant", "B-SUCCESSOR")]
    fake.chunks = ["RECOVERED"]
    nxt = _events(user, {"message": "what do you remember?", "session_id": sid})
    assert [e for e in nxt if e["type"] == "done"][0]["persisted"] == "saved", nxt
    ctx = _answering_call(fake, "what do you remember?")
    assert ctx and "successor question" in ctx and "B-SUCCESSOR" in ctx
    assert "mid stream question" not in ctx and "A0 A1" not in ctx, f"the superseded turn leaked into the next prompt:\n{ctx}"


def test_S5_Stop_on_one_worker_frees_the_conversation_for_the_other_worker_at_once(cluster, user):
    fake, a, b = cluster["fake"], cluster["a"], cluster["b"]
    sid = str(uuid.uuid4())
    fake.chunks, fake.chunk_delay = [f"S{i} " for i in range(40)], 0.2
    fake.stream_aborted.clear()
    ev_a = _stream_until(a.base, user.token, {"message": "long one", "session_id": sid}, stop_after_chunks=3)
    assert sum(e["type"] == "chunk" for e in ev_a) == 3
    t0 = time.monotonic()
    fake.chunks, fake.chunk_delay = ["PROMPT-", "OK"], 0.0
    on_b = _events(user, {"message": "immediately on B", "session_id": sid}, token=user.token_b, base=b.base)
    assert not any(e.get("code") == "session_busy" for e in on_b), "the other worker still saw the conversation as busy after Stop"
    assert [e for e in on_b if e["type"] == "done"][0]["persisted"] == "saved"
    assert time.monotonic() - t0 < 5
    assert fake.stream_aborted.wait(5), "the provider was never told to stop"
    assert _transcript(b.base, user.token_b, sid) == [("user", "immediately on B"), ("assistant", "PROMPT-OK")]
