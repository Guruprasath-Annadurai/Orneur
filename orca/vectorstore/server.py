"""The vector-service OWNER process: the only process that runs chromadb for one data directory.

    python -m orca.vectorstore.server --home <ORNEUR_HOME>

* single owner: an exclusive ``flock`` on ``owner.lock`` is held for the process's life; a second instance exits immediately (so two owners can never exist).
* bounded: ``workers`` execution threads, a bounded job queue (``queue_max``), a bounded number of client connections, and a per-collection in-flight limit. Anything beyond is
  answered ``busy`` at once - never queued without bound.
* a stalled native call freezes THIS process only. Clients enforce their own deadlines on the socket and a supervisor kills and restarts a stalled owner; SQLite makes that safe.
* local only: a Unix socket in a private directory (mode 0600) and a random token checked in constant time on every request. No pickle: frames are JSON.
* exits by itself after ``idle_exit_s`` without requests, releasing every descriptor (so a stopped server leaves nothing holding the data directory).
"""
from __future__ import annotations

import argparse
import fcntl
import hmac
import os
import queue
import signal
import socket
import sys
import threading
import time
from pathlib import Path

from orca.vectorstore import paths, protocol
from orca.vectorstore.host import ChromaHost


class Owner:
    def __init__(self, home: Path, *, workers=4, queue_max=32, max_conns=64, per_collection=2, idle_exit_s=300.0, max_open=32):
        self.home = Path(home).resolve()
        self.host = ChromaHost(max_open=max_open)
        self.jobs: queue.Queue = queue.Queue(maxsize=queue_max)
        self.workers, self.max_conns, self.per_collection, self.idle_exit_s = workers, max_conns, per_collection, idle_exit_s
        self.conns = 0
        self.conn_lock = threading.Lock()
        self.inflight_by_collection: dict[str, int] = {}
        self.coll_lock = threading.Lock()
        self.last_activity = time.monotonic()
        self.stop = threading.Event()
        self.running: dict[int, float] = {}
        self.run_lock = threading.Lock()
        self.refused = {"busy_queue": 0, "busy_connections": 0, "busy_collection": 0, "expired": 0}
        self.token = paths.token_path(self.home).read_text().strip()

    # ── request handling ─────────────────────────────────────────────────────────────────────────────────────────────
    def _valid_root(self, req: dict) -> bool:
        root = req.get("root")
        if root is None:
            return True
        try:
            Path(root).resolve().relative_to(self.home)
            return True
        except (ValueError, OSError):
            return False

    def _worker(self):
        while not self.stop.is_set():
            try:
                conn, req, deadline = self.jobs.get(timeout=0.5)
            except queue.Empty:
                continue
            key = f'{req.get("root")}|{req.get("collection")}' if req.get("collection") else None
            try:
                if time.monotonic() > deadline:
                    self.refused["expired"] += 1
                    resp = {"ok": False, "error": "expired"}              # the client already gave up: do not do the work
                else:
                    tid = threading.get_ident()
                    with self.run_lock:
                        self.running[tid] = time.monotonic()
                    try:
                        resp = {"ok": True, **self.host.execute(req)}
                    except Exception as exc:                              # type name only: messages can quote user content
                        name = type(exc).__name__
                        resp = {"ok": False, "error": "not_found" if "NotFound" in name or "does not exist" in str(exc).lower() else "op_failed", "type": name}
                    finally:
                        with self.run_lock:
                            self.running.pop(tid, None)
                try:
                    protocol.send(conn, resp)
                except OSError:
                    pass
            finally:
                if key:
                    with self.coll_lock:
                        self.inflight_by_collection[key] = max(0, self.inflight_by_collection.get(key, 1) - 1)
                try:
                    conn.close()
                except OSError:
                    pass
                self.last_activity = time.monotonic()

    def _handle(self, conn: socket.socket):
        try:
            req = protocol.recv(conn, time.monotonic() + 10)
        except Exception:
            conn.close()
            with self.conn_lock:
                self.conns -= 1
            return
        with self.conn_lock:
            self.conns -= 1
        try:
            if not hmac.compare_digest(str(req.get("token", "")), self.token):
                protocol.send(conn, {"ok": False, "error": "auth"})
                conn.close()
                return
            self.last_activity = time.monotonic()
            if req.get("op") == "ping":                                    # answered inline: liveness must not wait behind the work queue
                protocol.send(conn, {"ok": True, "pong": True, "pid": os.getpid()})
                conn.close()
                return
            if req.get("op") == "stats":                                   # also inline, so diagnostics work while the queue is saturated
                protocol.send(conn, {"ok": True, **self.stats()})
                conn.close()
                return
            if not self._valid_root(req):
                protocol.send(conn, {"ok": False, "error": "bad_root"})
                conn.close()
                return
            key = f'{req.get("root")}|{req.get("collection")}' if req.get("collection") else None
            if key:
                with self.coll_lock:
                    n = self.inflight_by_collection.get(key, 0)
                    if n >= self.per_collection:
                        self.refused["busy_collection"] += 1
                        protocol.send(conn, {"ok": False, "error": "busy", "scope": "collection"})
                        conn.close()
                        return
                    self.inflight_by_collection[key] = n + 1
            deadline = time.monotonic() + max(0.05, float(req.get("deadline_ms", 5000)) / 1000.0)
            try:
                self.jobs.put_nowait((conn, req, deadline))
            except queue.Full:
                if key:
                    with self.coll_lock:
                        self.inflight_by_collection[key] = max(0, self.inflight_by_collection.get(key, 1) - 1)
                self.refused["busy_queue"] += 1
                protocol.send(conn, {"ok": False, "error": "busy", "scope": "queue"})
                conn.close()
        except Exception:
            try:
                conn.close()
            except OSError:
                pass

    def serve(self):
        sp = paths.sock_path(self.home)
        if sp.exists() or sp.is_symlink():
            sp.unlink()                                                    # stale: we hold the owner lock, so nobody else is serving it
        srv = socket.socket(socket.AF_UNIX, socket.SOCK_STREAM)
        old = os.umask(0o177)
        try:
            srv.bind(str(sp))
        finally:
            os.umask(old)
        os.chmod(sp, 0o600)
        srv.listen(64)
        srv.settimeout(0.5)
        for _ in range(self.workers):
            threading.Thread(target=self._worker, daemon=True).start()
        while not self.stop.is_set():
            if time.monotonic() - self.last_activity > self.idle_exit_s and self.jobs.empty():
                break
            try:
                conn, _ = srv.accept()
            except socket.timeout:
                continue
            with self.conn_lock:
                if self.conns >= self.max_conns:
                    self.refused["busy_connections"] += 1
                    try:
                        protocol.send(conn, {"ok": False, "error": "busy", "scope": "connections"})
                    finally:
                        conn.close()
                    continue
                self.conns += 1
            threading.Thread(target=self._handle, args=(conn,), daemon=True).start()
        srv.close()
        try:
            sp.unlink()
        except OSError:
            pass
        self.host.close()

    def stats(self) -> dict:
        with self.run_lock:
            oldest = round(time.monotonic() - min(self.running.values()), 2) if self.running else 0.0
            running = len(self.running)
        return {**self.host.stats(), "queue_depth": self.jobs.qsize(), "connections": self.conns, "refused": dict(self.refused), "workers": self.workers, "running": running,
                "oldest_running_s": oldest}


def main(argv=None) -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--home", required=True)
    a = ap.parse_args(argv)
    home = Path(a.home)
    lock_fd = os.open(str(paths.owner_lock_path(home)), os.O_RDWR | os.O_CREAT, 0o600)
    try:
        fcntl.flock(lock_fd, fcntl.LOCK_EX | fcntl.LOCK_NB)
    except OSError:
        return 0                                                           # another owner is running: exactly one per data directory
    paths.pid_path(home).write_text(str(os.getpid()))
    env = os.environ.get
    owner = Owner(home, workers=int(env("ORNEUR_VECTOR_WORKERS", "4")), queue_max=int(env("ORNEUR_VECTOR_QUEUE_MAX", "32")), max_conns=int(env("ORNEUR_VECTOR_MAX_CONNS", "64")),
                  per_collection=int(env("ORNEUR_VECTOR_PER_COLLECTION", "2")), idle_exit_s=float(env("ORNEUR_VECTOR_IDLE_EXIT_S", "300")), max_open=int(env("ORNEUR_VECTOR_MAX_OPEN", "32")))

    signal.signal(signal.SIGTERM, lambda *_: owner.stop.set())
    owner.serve()
    return 0


if __name__ == "__main__":
    sys.exit(main())
