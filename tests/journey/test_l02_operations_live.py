"""L02-06 -- measured operational behaviour of real ``orca serve`` processes on THIS workstation (evidence class: LIVE_API, fixture provider except where stated).

Every figure written to the evidence directory is a measurement on this one machine under these conditions; none is a capacity, throughput, uptime or cost claim.
The hardware/environment block is recorded with each result.

Run:  pytest tests/journey/test_l02_operations_live.py -p no:cacheprovider -v
"""
from __future__ import annotations

import json
import os
import platform
import signal
import socket
import sqlite3
import statistics
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


def env_block():
    mem = next((int(l.split()[1]) // 1024 for l in open("/proc/meminfo") if l.startswith("MemTotal")), None)
    return {"cpu_count": os.cpu_count(), "mem_total_mb": mem, "kernel": platform.release(), "python": platform.python_version(), "wsl2": "microsoft" in platform.release().lower()}


def record(name, data):
    EVIDENCE.mkdir(parents=True, exist_ok=True)
    (EVIDENCE / f"l02_ops_live_{name}.json").write_text(json.dumps({"recorded_at": time.strftime("%Y-%m-%dT%H:%M:%S%z"), "environment": env_block(), **data}, indent=2))


def rss_mb(pid):
    for line in open(f"/proc/{pid}/status"):
        if line.startswith("VmRSS"):
            return int(line.split()[1]) / 1024
    return None


def fds(pid):
    return len(os.listdir(f"/proc/{pid}/fd"))


def threads(pid):
    return len(os.listdir(f"/proc/{pid}/task"))


@pytest.fixture(scope="module")
def fake():
    f = FakeOllama(models=(JOURNEY_MODEL,), reply="FIXTURE-ANSWER")
    f.__enter__()
    yield f
    f.__exit__(None, None, None)


def _server(tmp, fake, **extra):
    env = {"ORNEUR_OLLAMA_HOST": fake.host, "OLLAMA_HOST": fake.host, "ORNEUR_DELETION_SWEEP_S": "3600", **{k: str(v) for k, v in extra.items()}}
    return LiveServer(tmp, extra_env=env)


def _stream(base, token, body, key=None, collect=True):
    t0 = time.monotonic()
    headers = {"Authorization": f"Bearer {token}"}
    if key:
        headers["Idempotency-Key"] = key
    events = []
    try:
        with httpx.Client(base_url=base, timeout=120) as c:
            with c.stream("POST", "/api/stream", json={"model_variant": "core", **body}, headers=headers) as r:
                if r.status_code != 200:
                    r.read()
                    return r.status_code, [{"type": "http", "body": r.text}], time.monotonic() - t0
                for line in r.iter_lines():
                    if collect and line.startswith("data: "):
                        events.append(json.loads(line[6:]))
    except httpx.HTTPError as exc:                                  # the server went away mid-stream: what the client saw is the evidence
        events.append({"type": "connection_lost", "error": type(exc).__name__})
    return 200, events, time.monotonic() - t0


def test_O1_startup_time_to_live_and_ready(tmp_path_factory, fake):
    samples = []
    for i in range(3):
        home = tmp_path_factory.mktemp(f"o1-{i}")
        t0 = time.monotonic()
        srv = _server(home, fake)
        try:
            live = ready = None
            while time.monotonic() - t0 < 120:
                try:
                    if live is None and httpx.get(f"{srv.base}/livez", timeout=1).status_code == 200:
                        live = time.monotonic() - t0
                    if live is not None and httpx.get(f"{srv.base}/readyz", timeout=3).status_code == 200:
                        ready = time.monotonic() - t0
                        break
                except httpx.HTTPError:
                    time.sleep(0.1)
            assert live and ready, f"not ready within 120 s; see {srv.log_path}"
            samples.append({"to_livez_s": round(live, 2), "to_readyz_s": round(ready, 2), "rss_mb_idle": round(rss_mb(srv.proc.pid), 1)})
        finally:
            srv.stop()
    record("O1_startup", {"cold_start_samples": samples, "note": "fresh empty data directory each time; includes Python import and schema creation"})


def test_O2_graceful_shutdown_drains_refuses_new_work_and_never_commits_a_cut_stream(tmp_path_factory, fake):
    fake._chunks = tuple(f"w{i} " for i in range(200))
    fake.chunk_delay = 0.1
    home = tmp_path_factory.mktemp("o2")
    a = _server(home, fake, ORNEUR_SHUTDOWN_GRACE_S=3)
    b = _server(home, fake)
    try:
        a.wait_ready(); b.wait_ready()
        u = User(a.base, "o2")
        tok_b = httpx.post(f"{b.base}/api/auth/login", json={"email": u.email, "password": "Journey-Pass-91x"}, timeout=30).json()["token"]
        k, sid = "k-" + uuid.uuid4().hex, str(uuid.uuid4())
        res = {}
        th = threading.Thread(target=lambda: res.update(r=_stream(a.base, u.token, {"message": "slow", "session_id": sid}, key=k)))
        th.start()
        assert fake.stream_started.wait(15)
        time.sleep(1.0)
        t_sig = time.monotonic()
        a.proc.send_signal(signal.SIGTERM)
        refused = ready_during = None
        for _ in range(20):                                           # watch the drain from outside
            try:
                refused = httpx.post(f"{a.base}/api/stream", json={"message": "new"}, headers={"Authorization": f"Bearer {u.token}"}, timeout=2)
                ready_during = httpx.get(f"{a.base}/readyz", timeout=2).status_code
                break
            except httpx.HTTPError:
                time.sleep(0.1)
        exit_code = a.proc.wait(timeout=30)
        took = time.monotonic() - t_sig
        th.join(timeout=15)
        status, events, _ = res["r"]
        assert took < 12, f"stopped in {took:.1f}s (grace 3 s)"
        assert not any(e.get("type") == "done" for e in events), "a stream cut by shutdown must not be reported as finished"
        c = sqlite3.connect(str(_turns_db(home)))
        try:
            rows = c.execute("SELECT COUNT(*) FROM conversation_turns WHERE session_id=?", (sid,)).fetchone()[0]
            assert c.execute("PRAGMA integrity_check").fetchone()[0] == "ok"
        finally:
            c.close()
        assert rows == 0
        t_out = time.monotonic()
        st = _wait(lambda: (lambda o: o if o["terminal"] else None)(httpx.get(f"{b.base}/api/turns/{k}", headers={"Authorization": f"Bearer {tok_b}"}, timeout=10).json()), timeout=70)
        outcome_wait = time.monotonic() - t_out
        assert st and st["state"] == "not_committed"
        record("O2_graceful_shutdown", {"grace_s": 3, "seconds_from_sigterm_to_exit": round(took, 2), "exit_code": exit_code, "new_work_during_drain": (refused.status_code, refused.json().get("code")) if refused is not None else "listener already closed",
                                        "readyz_during_drain": ready_during, "cut_stream_final_state": st["state"], "cut_stream_reason": st["reason"], "seconds_until_outcome_terminal_after_exit": round(outcome_wait, 2), "turn_rows": rows, "db_integrity": "ok"})
    finally:
        fake.chunk_delay, fake._chunks = 0.0, None
        for s in (a, b):
            try:
                s.stop()
            except Exception:
                pass


def test_O3_concurrent_streams_complete_cleanly_and_release_everything(tmp_path_factory, fake):
    fake._chunks = tuple(f"w{i} " for i in range(30))
    fake.chunk_delay = 0.05
    home = tmp_path_factory.mktemp("o3")
    srv = _server(home, fake)
    try:
        srv.wait_ready()
        users = [User(srv.base, f"o3u{i}") for i in range(3)]          # signup is limited to 5/h/IP (left on): three accounts, many streams each
        pid = srv.proc.pid
        base_rss, base_fds, base_thr = rss_mb(pid), fds(pid), threads(pid)
        N = 24
        out, peak = [], {"rss": base_rss, "fds": base_fds, "thr": base_thr}
        stop = threading.Event()

        def sampler():
            while not stop.is_set():
                peak["rss"] = max(peak["rss"], rss_mb(pid)); peak["fds"] = max(peak["fds"], fds(pid)); peak["thr"] = max(peak["thr"], threads(pid))
                time.sleep(0.1)

        sp = threading.Thread(target=sampler); sp.start()
        def go(i):
            u = users[i % 3]
            out.append(_stream(srv.base, u.token, {"message": f"concurrent {i}", "session_id": str(uuid.uuid4())}))
        ts = [threading.Thread(target=go, args=(i,)) for i in range(N)]
        t0 = time.monotonic()
        [t.start() for t in ts]; [t.join() for t in ts]
        wall = time.monotonic() - t0
        stop.set(); sp.join()
        ok = [e for s, e, d in out if s == 200 and e and e[-1]["type"] == "done" and e[-1]["persisted"] == "saved"]
        busy = [e for s, e, d in out if s != 200 or (e and e[-1]["type"] == "error")]
        time.sleep(1.5)
        after = {"rss": rss_mb(pid), "fds": fds(pid), "thr": threads(pid)}
        in_use = httpx.get(f"{srv.base}/readyz", timeout=5).json()["dependencies"]["streams"]["in_use"]
        lat = sorted(d for s, e, d in out if s == 200)
        refused_codes = sorted({(b[-1].get("code") or b[-1].get("body", "")[:60]) for b in busy})
        assert len(ok) + len(busy) == N and len(ok) >= N - 6, (len(ok), len(busy), [b[-1] for b in busy[:2]])
        assert set(refused_codes) <= {"server_busy"}, f"gateway capacity refusals must be reported truthfully as server_busy, got {refused_codes}"
        assert in_use == 0, "stream admission slots were not released"
        import subprocess
        held = subprocess.run(f"ls -l /proc/{pid}/fd 2>/dev/null | awk '{{print $NF}}'", shell=True, capture_output=True, text=True).stdout.split()
        sem = sum("cache/semantic/cache.db" in h for h in held)
        vec = sum("/memory/vectors/" in h and h.endswith(".bin") for h in held)
        per_conv = (after["fds"] - base_fds) / N
        assert sem <= 40, f"semantic-cache descriptors held: {sem} (was one set per conversation before the fix)"
        assert per_conv <= 6, f"{per_conv:.1f} descriptors per conversation"
        record("O3_concurrent_streams", {"concurrent_streams_attempted": N, "completed_and_saved": len(ok), "refused_or_errored": len(busy), "refusal_codes": refused_codes, "wall_s": round(wall, 2),
                                         "latency_s_median": round(statistics.median(lat), 2) if lat else None, "latency_s_max": round(lat[-1], 2) if lat else None,
                                         "rss_mb": {"idle": round(base_rss, 1), "peak": round(peak["rss"], 1), "after": round(after["rss"], 1)},
                                         "fds": {"idle": base_fds, "peak": peak["fds"], "after": after["fds"]}, "threads": {"idle": base_thr, "peak": peak["thr"], "after": after["thr"]},
                                         "stream_slots_in_use_after": in_use, "semantic_cache_fds_held": sem, "vector_index_fds_held": vec, "fds_per_conversation": round(per_conv, 2), "provider": "fixture (30 chunks x 50 ms)", "note": "one workstation; not a capacity figure"})
    finally:
        fake.chunk_delay, fake._chunks = 0.0, None
        srv.stop()


def test_O4_saturation_is_refused_cleanly_before_any_charge(tmp_path_factory, fake):
    fake._chunks = tuple(f"w{i} " for i in range(40))
    fake.chunk_delay = 0.1
    home = tmp_path_factory.mktemp("o4")
    srv = _server(home, fake, ORNEUR_MAX_CONCURRENT_STREAMS=3)
    try:
        srv.wait_ready()
        u = User(srv.base, "o4")
        out = []
        ts = [threading.Thread(target=lambda i=i: out.append(_stream(srv.base, u.token, {"message": f"sat {i}", "session_id": str(uuid.uuid4())}))) for i in range(10)]
        [t.start() for t in ts]; [t.join() for t in ts]
        done = [e for s, e, d in out if e and e[-1]["type"] == "done"]
        busy = [e for s, e, d in out if e and e[-1]["type"] == "error" and e[-1].get("code") == "server_busy"]
        used = httpx.get(f"{srv.base}/api/auth/me", headers=u.headers, timeout=10).json()["usage"]["messages"]
        assert len(done) >= 3 and len(busy) >= 1 and len(done) + len(busy) == 10, ([e[-1].get("code") for s, e, d in out if e])
        assert used == len(done), f"quota units {used} != completed turns {len(done)}: a refused request was charged"
        record("O4_saturation", {"stream_capacity": 3, "attempted": 10, "completed": len(done), "refused_server_busy": len(busy), "quota_units_spent": used})
    finally:
        fake.chunk_delay, fake._chunks = 0.0, None
        srv.stop()


def test_O5_model_provider_down_is_reported_refused_cleanly_and_recovers(tmp_path_factory):
    home = tmp_path_factory.mktemp("o5")
    f = FakeOllama(models=(JOURNEY_MODEL,), reply="UP")
    f.__enter__()
    srv = LiveServer(home, extra_env={"ORNEUR_OLLAMA_HOST": f.host, "OLLAMA_HOST": f.host, "ORNEUR_DELETION_SWEEP_S": "3600"})
    try:
        srv.wait_ready()
        u = User(srv.base, "o5")
        assert _stream(srv.base, u.token, {"message": "before"})[1][-1]["type"] == "done"
        f.__exit__(None, None, None)                                                      # the provider disappears
        t_gone = time.monotonic()
        t0 = time.monotonic()
        s, ev, d = _stream(srv.base, u.token, {"message": "provider is gone"})
        down_latency = time.monotonic() - t0
        used = httpx.get(f"{srv.base}/api/auth/me", headers=u.headers, timeout=10).json()["usage"]["messages"]
        assert ev[-1]["type"] == "error" and "Traceback" not in json.dumps(ev) and used == 1, ev[-1]
        # readiness reflects the outage once the installed-model list (cached for 15 s) expires: measure how long that takes
        detected = None
        while time.monotonic() - t_gone < 45:
            r = httpx.get(f"{srv.base}/readyz", timeout=10)
            if r.status_code == 503:
                detected = time.monotonic() - t_gone
                break
            time.sleep(1)
        assert detected is not None and r.json()["dependencies"]["model_runtime"]["status"] == "unavailable"
        record("O5_model_unavailable", {"error_event": {k: ev[-1].get(k) for k in ("code", "text")}, "seconds_to_refuse_the_turn": round(down_latency, 2), "readyz_503_after_s": round(detected, 1),
                                        "readiness_cache_ttl_s": 15, "quota_units_after_failed_turn": used,
                                        "note": "the turn fails immediately and uncharged-if-no-output; readiness lags by up to the 15 s model-list cache. Recovery after the provider returns is covered by tests/test_l02_turn_recovery.py (fail then retry same key)"})
    finally:
        try:
            srv.stop()
        except Exception:
            pass


def test_O6_kill_9_mid_turn_then_restart_is_consistent(tmp_path_factory, fake):
    fake._chunks = tuple(f"w{i} " for i in range(100))
    fake.chunk_delay = 0.1
    home = tmp_path_factory.mktemp("o6")
    env = dict(ORNEUR_TURN_AUTHORITY_TTL_S=3, ORNEUR_TURN_HEARTBEAT_S=1)
    a = _server(home, fake, **env)
    try:
        a.wait_ready()
        u = User(a.base, "o6")
        _stream(a.base, u.token, {"message": "committed before the crash", "session_id": (sid0 := str(uuid.uuid4()))}) if False else None
        fake.chunk_delay = 0.0
        s0 = _stream(a.base, u.token, {"message": "committed before the crash", "session_id": (sid0 := str(uuid.uuid4()))})
        assert s0[1][-1]["persisted"] == "saved"
        fake.chunk_delay = 0.1
        k, sid = "k-" + uuid.uuid4().hex, str(uuid.uuid4())
        th = threading.Thread(target=lambda: _stream(a.base, u.token, {"message": "dies mid turn", "session_id": sid}, key=k)); th.start()
        assert fake.stream_started.wait(15); time.sleep(0.8)
        a.proc.send_signal(signal.SIGKILL); th.join(timeout=20); a.proc.wait()
        t0 = time.monotonic()
        b = _server(home, fake, **env)
        try:
            b.wait_ready()
            restart_s = time.monotonic() - t0
            tok = httpx.post(f"{b.base}/api/auth/login", json={"email": u.email, "password": "Journey-Pass-91x"}, timeout=30).json()["token"]
            st = _wait(lambda: (lambda o: o if o["terminal"] else None)(httpx.get(f"{b.base}/api/turns/{k}", headers={"Authorization": f"Bearer {tok}"}, timeout=10).json()), timeout=25)
            conn = sqlite3.connect(str(_turns_db(home)))
            try:
                integrity = conn.execute("PRAGMA integrity_check").fetchone()[0]
                rows_ok = conn.execute("SELECT COUNT(*) FROM conversation_turns WHERE session_id=?", (sid0,)).fetchone()[0]
                rows_dead = conn.execute("SELECT COUNT(*) FROM conversation_turns WHERE session_id=?", (sid,)).fetchone()[0]
            finally:
                conn.close()
            assert integrity == "ok" and rows_ok == 1 and rows_dead == 0 and st and st["state"] == "not_committed"
            fake.chunk_delay = 0.0; fake._chunks = None
            again = _stream(b.base, tok, {"message": "dies mid turn", "session_id": sid}, key=k)
            assert again[1][-1]["persisted"] == "saved"
            record("O6_kill9_restart", {"restart_to_ready_s": round(restart_s, 2), "db_integrity": integrity, "turn_committed_before_crash_survived": rows_ok == 1, "mid_turn_rows": rows_dead,
                                        "mid_turn_outcome": st["state"], "mid_turn_reason": st["reason"], "retry_after_restart": "committed"})
        finally:
            b.stop()
    finally:
        fake.chunk_delay, fake._chunks = 0.0, None
        try:
            a.stop()
        except Exception:
            pass


def test_O7_disk_headroom_refusal_is_visible_in_readiness_and_charges_nothing(tmp_path_factory, fake):
    """Threshold-simulated, not a real full disk: the critical threshold is set above this machine's free space so the server sees a 'full' volume."""
    home = tmp_path_factory.mktemp("o7")
    srv = _server(home, fake, ORNEUR_DISK_CRITICAL_MB=10_000_000)
    try:
        srv.wait_ready() if False else None
        t0 = time.monotonic()
        while time.monotonic() - t0 < 60:
            try:
                if httpx.get(f"{srv.base}/livez", timeout=1).status_code == 200:
                    break
            except httpx.HTTPError:
                time.sleep(0.2)
        r = httpx.get(f"{srv.base}/readyz", timeout=10)
        assert r.status_code == 503 and r.json()["dependencies"]["disk"]["state"] == "critical"
        u = User(srv.base, "o7")
        s, ev, d = _stream(srv.base, u.token, {"message": "refused before any model call"})
        used = httpx.get(f"{srv.base}/api/auth/me", headers=u.headers, timeout=10).json()["usage"]["messages"]
        assert ev[-1]["type"] == "error" and ev[-1]["code"] == "history_unavailable" and used == 0
        record("O7_disk_headroom", {"readyz": r.status_code, "disk": r.json()["dependencies"]["disk"], "turn_refused_code": ev[-1]["code"], "quota_units": used,
                                    "limitation": "threshold simulation; a genuinely full filesystem was not created"})
    finally:
        srv.stop()


def test_O8_redis_interruption_does_not_make_the_server_not_ready(tmp_path_factory, fake):
    box = RedisBox()
    home = tmp_path_factory.mktemp("o8")
    env = {"ORNEUR_OLLAMA_HOST": fake.host, "OLLAMA_HOST": fake.host, "ORNEUR_DELETION_SWEEP_S": "3600"}
    srv = LiveServer(home, redis_url=box.url, extra_env=env)
    try:
        srv.wait_ready()
        u = User(srv.base, "o8")
        up = httpx.get(f"{srv.base}/readyz", timeout=10).json()["dependencies"]["redis"]
        box.down()
        try:
            t0 = time.monotonic()
            during = httpx.get(f"{srv.base}/readyz", timeout=30)
            took = time.monotonic() - t0
            turn = _stream(srv.base, u.token, {"message": "while redis is frozen"})
        finally:
            box.up()
        after = httpx.get(f"{srv.base}/readyz", timeout=10).json()["dependencies"]["redis"]
        assert during.status_code == 200 and during.json()["dependencies"]["redis"]["status"] == "unavailable" and took < 3.0, took
        assert turn[1][-1]["type"] in ("done", "error")
        record("O8_redis_interruption", {"redis_before": up, "readyz_during": during.status_code, "readyz_seconds_during_outage": round(took, 2), "redis_during": during.json()["dependencies"]["redis"],
                                         "turn_during_outage": turn[1][-1]["type"], "turn_persisted": turn[1][-1].get("persisted"), "redis_after": after})
    finally:
        srv.stop()
        box.close()
