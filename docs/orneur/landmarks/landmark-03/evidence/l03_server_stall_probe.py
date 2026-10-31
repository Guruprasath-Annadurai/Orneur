"""L03 -- end-to-end stall probe against a REAL `orca serve` process: how long does the server stop answering when the shared vector database is write-locked by another process?

    L03_REPO=<checkout> python l03_server_stall_probe.py [lock_seconds]

Run against the baseline checkout (38e0d31) and against the changed checkout with the same script. The server is started exactly as in production (`python -m orca.cli serve`), a
synthetic user is created over HTTP, `/api/remember` writes one fact (this creates the conversation's vector collection), a separate process then holds an EXCLUSIVE lock on the
shared chroma.sqlite3, and while it is held the script issues `/api/remember` and `/api/memory/recall` and probes `/livez` and `/readyz` from other threads. No model is needed.
"""
from __future__ import annotations

import json
import os
import platform
import socket
import sqlite3
import subprocess
import sys
import tempfile
import threading
import time
import uuid
from pathlib import Path

import httpx

REPO = Path(os.environ.get("L03_REPO") or subprocess.run(["git", "rev-parse", "--show-toplevel"], cwd=Path(__file__).parent, capture_output=True, text=True).stdout.strip())
HOLD = float(sys.argv[1]) if len(sys.argv) > 1 else 18.0


def free_port():
    with socket.socket() as s:
        s.bind(("127.0.0.1", 0))
        return s.getsockname()[1]


def main():
    home = Path(tempfile.mkdtemp(prefix="stall-", dir="/tmp"))
    port = free_port()
    env = {k: v for k, v in os.environ.items() if not k.startswith(("ORNEUR_", "ORCA_"))}
    env.update({"ORNEUR_HOME": str(home), "PYTHONPATH": str(REPO), "ORNEUR_VECTOR_DEADLINE_S": "5", "ORNEUR_OLLAMA_HOST": "http://127.0.0.1:9"})
    log = open(home / "server.log", "wb")
    srv = subprocess.Popen([sys.executable, "-m", "orca.cli", "serve", "--host", "127.0.0.1", "--port", str(port), "--no-open"], env=env, cwd=REPO, stdout=log, stderr=subprocess.STDOUT)
    base = f"http://127.0.0.1:{port}"
    out = {"product_checkout": str(REPO), "product_sha": subprocess.run(["git", "rev-parse", "HEAD"], cwd=REPO, capture_output=True, text=True).stdout.strip(),
           "lock_seconds": HOLD, "platform": platform.platform(), "recorded_at": time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime())}
    try:
        for _ in range(120):
            try:
                if httpx.get(f"{base}/livez", timeout=2).status_code == 200:
                    break
            except Exception:
                time.sleep(0.5)
        r = httpx.post(f"{base}/api/auth/signup", json={"email": f"stall-{uuid.uuid4().hex[:8]}@example.com", "password": "Journey-Pass-91x", "name": "T"}, timeout=30)
        tok = r.json()["token"]
        h = {"Authorization": f"Bearer {tok}"}
        sid = str(uuid.uuid4())
        out["seed_remember"] = httpx.post(f"{base}/api/remember", json={"session_id": sid, "fact": "seed fact"}, headers=h, timeout=60).status_code
        sid_read = str(uuid.uuid4())
        out["seed_remember_read_conversation"] = httpx.post(f"{base}/api/remember", json={"session_id": sid_read, "fact": "seed fact for reading"}, headers=h, timeout=60).status_code
        db = home / "memory" / "vectors" / "chroma.sqlite3"
        assert db.exists(), "no memory vector database was created by the seed write"
        holder = subprocess.Popen([sys.executable, "-c", "import sqlite3,sys,time;c=sqlite3.connect(sys.argv[1],timeout=1,isolation_level=None);c.execute('BEGIN EXCLUSIVE');print('held',flush=True);time.sleep(float(sys.argv[2]))", str(db), str(HOLD)],
                                  stdout=subprocess.PIPE, text=True)
        holder.stdout.readline()
        probes, stop = [], threading.Event()

        def probe():
            while not stop.is_set():
                t = time.monotonic()
                try:
                    ok = httpx.get(f"{base}/livez", timeout=HOLD + 15).status_code == 200
                except Exception as e:
                    ok = type(e).__name__
                probes.append((round(t - t0, 2), ok, round(time.monotonic() - t, 2)))
                time.sleep(0.25)

        t0 = time.monotonic()
        th = threading.Thread(target=probe, daemon=True)
        th.start()
        time.sleep(1.0)
        results = {}

        def call(name, fn):
            t = time.monotonic()
            try:
                r = fn()
                results[name] = {"status": r.status_code, "code": (r.json().get("code") if r.headers.get("content-type", "").startswith("application/json") else None), "seconds": round(time.monotonic() - t, 2)}
            except Exception as e:
                results[name] = {"error": type(e).__name__, "seconds": round(time.monotonic() - t, 2)}

        new1, new2 = str(uuid.uuid4()), str(uuid.uuid4())
        # (a) a NEW conversation: the server must create its collection, which needs the write lock; (b) the same again in parallel; (c) a read on the already-open conversation;
        # (d) a deletion of the seeded conversation (client construction + delete_collection + VACUUM)
        ths = [threading.Thread(target=call, args=("remember_new_conversation_1", lambda: httpx.post(f"{base}/api/remember", json={"session_id": new1, "fact": "blocked write 1"}, headers=h, timeout=HOLD + 40))),
               threading.Thread(target=call, args=("remember_new_conversation_2", lambda: httpx.post(f"{base}/api/remember", json={"session_id": new2, "fact": "blocked write 2"}, headers=h, timeout=HOLD + 40))),
               threading.Thread(target=call, args=("recall_open_conversation", lambda: httpx.post(f"{base}/api/memory/recall", json={"session_id": sid_read, "query": "seed"}, headers=h, timeout=HOLD + 40))),
               threading.Thread(target=call, args=("delete_seeded_conversation", lambda: httpx.delete(f"{base}/api/session/{sid}", headers=h, timeout=HOLD + 40)))]
        [t.start() for t in ths]
        [t.join(HOLD + 40) for t in ths]
        time.sleep(1.0)
        stop.set()
        th.join(HOLD + 20)
        holder.kill()
        out["requests"] = results
        slow = [p for p in probes if p[2] > 1.0]
        out["livez_probes"] = {"count": len(probes), "worst_seconds": max((p[2] for p in probes), default=None), "slow_over_1s": slow[:10], "failed": [p for p in probes if p[1] is not True][:10]}
    finally:
        srv.terminate()
        try:
            srv.wait(timeout=20)
        except subprocess.TimeoutExpired:
            srv.kill()
        for pid in subprocess.run(["pgrep", "-f", f"[o]rca.vectorstore.server --home {home}"], capture_output=True, text=True).stdout.split():
            try:
                os.kill(int(pid), 9)
            except OSError:
                pass
    print(json.dumps(out, indent=1))


if __name__ == "__main__":
    main()
