"""Application-side transport to the vector-service owner, plus the supervisor that contains a stalled owner.

Guarantees (each is tested against a real owner process and real chromadb):
* the calling thread is released at its deadline whatever the owner is doing - the deadline is enforced on the SOCKET, not by waiting on a thread, so a native call that holds the
  owner's GIL cannot hold the application's;
* bounded admission: at most ``max_inflight`` calls run and at most ``max_waiting`` wait (for at most ``queue_wait_s``); anything more is refused at once (``VectorBusy``);
* a timeout makes the supervisor probe the owner; one that cannot answer a ping is killed (SIGKILL, after verifying the pid really is our owner) and the next call starts a new
  one. In-flight work on a killed owner fails; nothing is reported as done that was not confirmed;
* exactly one owner per data directory (flock); starting is serialised by a spawn lock so many application workers starting together create one.
"""
from __future__ import annotations

import fcntl
import json
import os
import secrets
import signal
import socket
import subprocess
import sys
import threading
import time
from pathlib import Path

from orca.vectorstore import paths, protocol
from orca.vectorstore.errors import VectorBusy, VectorNotFound, VectorTimeout, VectorUnavailable

REPO_ROOT = Path(__file__).resolve().parents[2]


def _alive(pid: int) -> bool:
    try:
        os.kill(pid, 0)
        state = Path(f"/proc/{pid}/stat").read_text().rsplit(")", 1)[1].split()[0]
    except (OSError, IndexError):
        return False
    return state != "Z"                                                  # a zombie is dead; it only awaits its parent's wait()


class _NotDelivered(OSError):
    """The request never reached an owner (connection refused / no socket): safe to retry once after making sure an owner is running."""


class ServiceTransport:
    def __init__(self, home: Path, *, max_inflight=8, max_waiting=16, queue_wait_s=2.0, default_deadline_s=5.0, start_timeout_s=20.0, stuck_after_s=8.0, owner_env=None):
        self.home = Path(home).resolve()
        self.max_inflight, self.max_waiting, self.queue_wait_s, self.default_deadline_s, self.start_timeout_s = max_inflight, max_waiting, queue_wait_s, default_deadline_s, start_timeout_s
        self.stuck_after_s = stuck_after_s
        self.owner_env = owner_env or {}
        self._sem = threading.BoundedSemaphore(max_inflight)                        # read lane
        self.max_write_inflight = max(1, min(max_inflight, int(os.environ.get("ORNEUR_VECTOR_MAX_WRITE_INFLIGHT", "3"))))
        self._wsem = threading.BoundedSemaphore(self.max_write_inflight)             # write lane: writes are what block behind a database lock, so they get their own, smaller budget
        self._waiting = 0
        self._wlock = threading.Lock()
        self._probe_lock = threading.Lock()
        self._probing = False
        self.counters = {"calls": 0, "ok": 0, "timeouts": 0, "busy_local": 0, "busy_remote": 0, "unavailable": 0, "owner_starts": 0, "owner_kills": 0, "errors": 0}
        self.lat_ms: list[float] = []
        self._latlock = threading.Lock()

    # ── owner lifecycle ──────────────────────────────────────────────────────────────────────────────────────────────
    def _token(self) -> str:
        p = paths.token_path(self.home)
        if not p.exists():
            fd = os.open(str(p), os.O_WRONLY | os.O_CREAT | os.O_EXCL, 0o600) if not p.exists() else None
            if fd is not None:
                with os.fdopen(fd, "w") as f:
                    f.write(secrets.token_hex(32))
        return p.read_text().strip()

    def _raw(self, req: dict, timeout: float) -> dict:
        s = socket.socket(socket.AF_UNIX, socket.SOCK_STREAM)
        deadline = time.monotonic() + timeout
        try:
            s.settimeout(timeout)
            try:
                s.connect(str(paths.sock_path(self.home)))
            except (ConnectionRefusedError, FileNotFoundError) as exc:
                raise _NotDelivered(str(exc)) from None
            protocol.send(s, {**req, "token": self._token()})
            return protocol.recv(s, deadline)
        finally:
            s.close()

    def owner_pid(self) -> int | None:
        try:
            pid = int(paths.pid_path(self.home).read_text().strip())
        except (OSError, ValueError):
            return None
        try:
            cmd = Path(f"/proc/{pid}/cmdline").read_bytes().split(b"\0")
        except OSError:
            return None
        return pid if b"orca.vectorstore.server" in cmd and str(self.home).encode() in cmd else None     # never signal a pid that merely reused our number

    def ping(self, timeout=1.0) -> bool:
        try:
            return bool(self._raw({"op": "ping"}, timeout).get("pong"))
        except Exception:
            return False

    def _spawn(self) -> None:
        self._token()
        env = {k: v for k, v in os.environ.items()}
        env.update({"ORNEUR_HOME": str(self.home), "PYTHONPATH": str(REPO_ROOT) + os.pathsep + env.get("PYTHONPATH", ""), **self.owner_env})
        log = open(paths.log_path(self.home), "ab")
        proc = subprocess.Popen([sys.executable, "-m", "orca.vectorstore.server", "--home", str(self.home)], env=env, stdin=subprocess.DEVNULL, stdout=log, stderr=log,
                                start_new_session=True, close_fds=True, cwd=str(REPO_ROOT))
        log.close()
        threading.Thread(target=proc.wait, daemon=True, name="vector-owner-reaper").start()      # reap it when it exits, so a replaced owner never lingers as a zombie
        self.counters["owner_starts"] += 1

    def ensure_owner(self, budget_s: float | None = None) -> None:
        end = time.monotonic() + (budget_s if budget_s is not None else self.start_timeout_s)
        if self.ping(max(0.1, min(1.0, end - time.monotonic()))):
            return
        fd = os.open(str(paths.spawn_lock_path(self.home)), os.O_RDWR | os.O_CREAT, 0o600)
        try:
            fcntl.flock(fd, fcntl.LOCK_EX)                                   # one starter at a time, across every application process
            last_spawn = 0.0
            while time.monotonic() < end:
                if self.ping(max(0.1, min(0.5, end - time.monotonic()))):
                    return
                # No live owner process (never started, or killed by the supervisor): start one. A previous owner that is merely FROZEN still holds the owner lock, and a new
                # instance would exit at once, so only spawn when none is alive, and retry while waiting (the supervisor may kill the frozen one a moment from now).
                if self.owner_pid() is None and time.monotonic() - last_spawn > 1.0:
                    self._spawn()
                    last_spawn = time.monotonic()
                time.sleep(0.1)
            raise VectorUnavailable("vector service did not start")
        finally:
            os.close(fd)

    def kill_owner(self, wait_s=5.0) -> bool:
        pid = self.owner_pid()
        if pid is None:
            return False
        os.kill(pid, signal.SIGKILL)
        self.counters["owner_kills"] += 1
        end = time.monotonic() + wait_s
        while time.monotonic() < end:
            if not _alive(pid):
                return True
            time.sleep(0.05)
        return False

    def stop_owner(self, wait_s=10.0) -> bool:
        """Graceful: SIGTERM and wait for the owner to release the data directory."""
        pid = self.owner_pid()
        if pid is None:
            return True
        os.kill(pid, signal.SIGTERM)
        end = time.monotonic() + wait_s
        while time.monotonic() < end:
            if not _alive(pid):
                return True
            time.sleep(0.05)
        return False

    def _suspect(self) -> None:
        """A call timed out. Probe once off the request path; an owner that cannot answer a trivial ping is stalled -> kill it so the next call gets a fresh one."""
        with self._probe_lock:
            if self._probing:
                return
            self._probing = True

        def probe():
            try:
                time.sleep(0.2)
                if not (self.ping(1.5) or self.ping(1.5)):
                    self.kill_owner()                                          # cannot answer a trivial ping: its interpreter is frozen
                    return
                st = self.owner_stats() or {}
                if float(st.get("oldest_running_s", 0)) >= self.stuck_after_s:
                    self.kill_owner()                                          # answers pings but a worker has been inside one native call for too long: capacity is being lost
            finally:
                self._probing = False
        threading.Thread(target=probe, daemon=True, name="vector-supervisor").start()

    # ── calls ────────────────────────────────────────────────────────────────────────────────────────────────────────
    def call(self, req: dict, deadline_s: float | None = None) -> dict:
        deadline_s = float(deadline_s or self.default_deadline_s)
        self.counters["calls"] += 1
        is_read = req.get("op") in ("list_collections", "collection_info", "binding_report", "ping", "stats") or (req.get("op") == "call" and req.get("method") in ("query", "get", "peek", "count"))
        sem = self._sem if is_read else self._wsem
        with self._wlock:
            if self._waiting >= self.max_waiting:
                self.counters["busy_local"] += 1
                raise VectorBusy("vector operations are at capacity")
            self._waiting += 1
        try:
            if not sem.acquire(timeout=self.queue_wait_s):
                self.counters["busy_local"] += 1
                raise VectorBusy("vector operations are at capacity")
        finally:
            with self._wlock:
                self._waiting -= 1
        t0 = time.monotonic()
        try:
            return self._do(req, deadline_s, t0)
        finally:
            sem.release()
            with self._latlock:
                self.lat_ms.append((time.monotonic() - t0) * 1000)
                if len(self.lat_ms) > 2000:
                    del self.lat_ms[:1000]

    def _do(self, req: dict, deadline_s: float, t0: float) -> dict:
        try:
            self.ensure_owner(budget_s=min(self.start_timeout_s, max(0.5, deadline_s - (time.monotonic() - t0))))
        except VectorUnavailable:
            self.counters["unavailable"] += 1
            self._suspect()                                              # an owner that is alive but never answers is exactly what the supervisor exists for
            raise
        left = deadline_s - (time.monotonic() - t0)
        if left <= 0:
            self.counters["timeouts"] += 1
            raise VectorTimeout("vector operation deadline passed before it started")
        try:
            try:
                resp = self._raw({**req, "deadline_ms": int(left * 1000)}, left)
            except _NotDelivered:                                          # e.g. the owner just exited to recycle its memory: start one and send once more
                self.ensure_owner(budget_s=max(0.5, deadline_s - (time.monotonic() - t0)))
                left = deadline_s - (time.monotonic() - t0)
                if left <= 0:
                    raise socket.timeout("deadline") from None
                resp = self._raw({**req, "deadline_ms": int(left * 1000)}, left)
        except socket.timeout:
            self.counters["timeouts"] += 1
            self._suspect()
            raise VectorTimeout("vector operation exceeded its deadline") from None
        except (OSError, protocol.FrameError, VectorUnavailable):
            self.counters["unavailable"] += 1
            self._suspect()
            raise VectorUnavailable("vector service unavailable") from None
        if resp.get("ok"):
            self.counters["ok"] += 1
            return resp
        err = resp.get("error")
        if err == "busy":
            self.counters["busy_remote"] += 1
            raise VectorBusy("vector operations are at capacity")
        if err == "expired":
            self.counters["timeouts"] += 1
            raise VectorTimeout("vector operation expired in the queue")
        if err == "not_found":
            raise VectorNotFound("no such collection")
        self.counters["errors"] += 1
        raise VectorUnavailable(f"vector operation failed ({resp.get('type') or err})")

    def stats(self) -> dict:
        with self._latlock:
            lat = sorted(self.lat_ms)
        pct = lambda p: round(lat[min(len(lat) - 1, int(len(lat) * p))], 1) if lat else None
        return {"client": dict(self.counters), "latency_ms": {"p50": pct(0.5), "p95": pct(0.95), "p99": pct(0.99), "n": len(lat)}, "max_inflight": self.max_inflight,
                "max_write_inflight": self.max_write_inflight, "max_waiting": self.max_waiting}

    def owner_stats_quick(self, max_age_s: float = 2.0) -> dict | None:
        """Owner statistics for a readiness probe: a half-second budget, no spawning, and the answer (or the failure) is reused for ``max_age_s`` so a probe storm does not turn
        into a storm of half-second waits on a stalled owner."""
        now = time.monotonic()
        cached = getattr(self, "_quick", None)
        if cached and now - cached[0] < max_age_s:
            return cached[1]
        try:
            r = self._raw({"op": "stats"}, 0.5)
            val = r if r.get("ok") else None
        except Exception:
            val = None
        self._quick = (time.monotonic(), val)
        return val

    def owner_stats(self) -> dict | None:
        try:
            r = self._raw({"op": "stats"}, 1.5)
            return r if r.get("ok") else None
        except Exception:
            return None
