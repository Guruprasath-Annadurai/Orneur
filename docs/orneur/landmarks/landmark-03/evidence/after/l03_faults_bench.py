"""L03 Phase C/F -- measured failure behaviour of the changed code: crash recovery time, frozen-owner replacement time, deadline release time under a held lock, and refusal counts
under a read flood. One workstation, real chromadb, real owner process; numbers describe THIS run, they are not capacity or availability claims."""
from __future__ import annotations

import json
import os
import platform
import signal
import statistics
import subprocess
import sys
import tempfile
import threading
import time
from pathlib import Path

REPO = Path(os.environ.get("L03_REPO") or subprocess.run(["git", "rev-parse", "--show-toplevel"], cwd=Path(__file__).parent, capture_output=True, text=True).stdout.strip())
sys.path.insert(0, str(REPO))
from orca import vectorstore as V  # noqa: E402


def setup(deadline="3"):
    home = Path(tempfile.mkdtemp(prefix="fb-", dir="/tmp"))
    os.environ.update(ORNEUR_VECTOR_MODE="service", ORNEUR_VECTOR_DEADLINE_S=deadline)
    V._home = lambda: home
    V.reset_for_tests()
    t = V.transport()
    t.owner_env = {"ORNEUR_VECTOR_IDLE_EXIT_S": "300"}
    root = home / "memory" / "vectors"
    col, _ = V.Store(root).open_collection("orca_bench0001")
    col.add(documents=["seed"], ids=["0"], metadatas=[{"a": 1}])
    return home, t, root, col


def until_ok(fn, limit=40.0):
    t0 = time.monotonic()
    while time.monotonic() - t0 < limit:
        try:
            fn()
            return round(time.monotonic() - t0, 2)
        except V.VectorError:
            time.sleep(0.1)
    return None


def pct(xs, p):
    xs = sorted(xs)
    return round(xs[min(len(xs) - 1, int(len(xs) * p))], 3) if xs else None


def main():
    out = {"environment": {"product_sha": subprocess.run(["git", "rev-parse", "HEAD"], cwd=REPO, capture_output=True, text=True).stdout.strip(), "platform": platform.platform(),
                           "cpus": os.cpu_count(), "recorded_at": time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime())}}
    home, t, root, col = setup()
    kills = []
    for _ in range(8):
        os.kill(t.owner_pid(), signal.SIGKILL)
        time.sleep(0.2)
        kills.append(until_ok(col.count))
    out["sigkill_owner_to_first_success_s"] = {"trials": kills, "median": statistics.median(k for k in kills if k), "max": max(k for k in kills if k)}
    stops = []
    for _ in range(3):
        os.kill(t.owner_pid(), signal.SIGSTOP)
        stops.append(until_ok(col.count))
    out["sigstop_frozen_owner_to_first_success_s"] = {"trials": stops, "note": "the supervisor probes after a failed call, kills the unresponsive owner and the next call starts a new one"}
    holds = []
    for _ in range(5):
        h = subprocess.Popen([sys.executable, "-c", "import sqlite3,sys,time;c=sqlite3.connect(sys.argv[1],timeout=1,isolation_level=None);c.execute('BEGIN EXCLUSIVE');print('held',flush=True);time.sleep(9)", str(root / "chroma.sqlite3")], stdout=subprocess.PIPE, text=True)
        h.stdout.readline()
        t0 = time.monotonic()
        try:
            col.add(documents=["blocked"], ids=[f"b{time.time()}"], metadatas=[{"a": 1}])
            r = "ok"
        except V.VectorError as e:
            r = type(e).__name__
        holds.append({"released_after_s": round(time.monotonic() - t0, 2), "outcome": r, "deadline_s": 3})
        h.kill()
        h.wait()
        until_ok(col.count, 30)
    out["held_lock_write_release"] = holds
    lat, outcomes, lock = [], {"ok": 0, "busy": 0, "timeout": 0, "unavailable": 0}, threading.Lock()
    stop = time.monotonic() + 6

    def flood():
        while time.monotonic() < stop:
            t0 = time.monotonic()
            try:
                col.query(query_texts=["seed"], n_results=1)
                k = "ok"
            except V.VectorBusy:
                k = "busy"
            except V.VectorTimeout:
                k = "timeout"
            except V.VectorError:
                k = "unavailable"
            with lock:
                outcomes[k] += 1
                lat.append(time.monotonic() - t0)

    ths = [threading.Thread(target=flood) for _ in range(64)]
    [x.start() for x in ths]
    [x.join(30) for x in ths]
    st = t.owner_stats() or {}
    out["read_flood_64_threads_6s"] = {"outcomes": outcomes, "latency_s": {"p50": pct(lat, 0.5), "p95": pct(lat, 0.95), "p99": pct(lat, 0.99), "max": round(max(lat), 3)},
                                      "owner_refused": st.get("refused"), "client_caps": {"max_inflight": t.max_inflight, "max_waiting": t.max_waiting}}
    t.kill_owner()
    print(json.dumps(out, indent=1))


if __name__ == "__main__":
    main()
