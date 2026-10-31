"""L03 -- the vector-service owner process: containment of blocking vector operations, bounded admission, single-owner, restart and visibility semantics.

Real chromadb, a real owner process, real SQLite locks held by a real competing process. No mock stands in for the integration path. Needs chromadb (the `memory` extra); a missing
chromadb is a FAILURE here (it must never turn into a pass through the keyword fallback)."""
from __future__ import annotations

import json
import os
import signal
import sqlite3
import subprocess
import sys
import tempfile
import threading
import time
from pathlib import Path

import pytest

from orca import vectorstore as V
from orca.vectorstore import paths
from orca.vectorstore.client import ServiceTransport

REPO = Path(__file__).resolve().parents[1]
assert V.available(), "chromadb is required for the L03 vector tests"


@pytest.fixture
def svc(monkeypatch):
    home = Path(tempfile.mkdtemp(prefix="l03-", dir="/tmp"))
    monkeypatch.setenv("ORNEUR_VECTOR_MODE", "service")
    monkeypatch.setenv("ORNEUR_VECTOR_DEADLINE_S", "2")
    monkeypatch.setattr(V, "_home", lambda: home)
    V.reset_for_tests()
    t = V.transport()
    t.owner_env = {"ORNEUR_VECTOR_IDLE_EXIT_S": "120"}
    root = home / "memory" / "vectors"
    yield type("S", (), {"home": home, "root": root, "t": t, "store": V.Store(root)})()
    try:
        t.kill_owner()
    except Exception:
        pass
    V.reset_for_tests()


def _seed(s, name="orca_victim001", n=1):
    col, info = s.store.open_collection(name, binding=V.session_binding(name))
    col.add(documents=[f"seed {i}" for i in range(n)], ids=[str(i) for i in range(n)], metadatas=[{"a": 1}] * n)
    return col


class Holder:
    """A separate process holding an EXCLUSIVE lock on the shared chroma.sqlite3 file."""

    def __init__(self, db: Path, seconds: float):
        code = "import sqlite3,sys,time;c=sqlite3.connect(sys.argv[1],timeout=1,isolation_level=None);c.execute('BEGIN EXCLUSIVE');print('held',flush=True);time.sleep(float(sys.argv[2]))"
        self.p = subprocess.Popen([sys.executable, "-c", code, str(db), str(seconds)], stdout=subprocess.PIPE, text=True)
        assert self.p.stdout.readline().strip() == "held"

    def release(self):
        self.p.kill()
        self.p.wait()


class Beat:
    """A heartbeat thread in THIS (application) process: its largest gap proves whether the interpreter was frozen."""

    def __init__(self):
        self.max, self.stop = 0.0, False
        threading.Thread(target=self._run, daemon=True).start()

    def _run(self):
        last = time.monotonic()
        while not self.stop:
            time.sleep(0.02)
            n = time.monotonic()
            self.max = max(self.max, n - last - 0.02)
            last = n


# ── basics ────────────────────────────────────────────────────────────────────────────────────────────────────────────────────

def test_roundtrip_through_the_service_and_the_application_process_never_imports_chromadb(svc):
    col = _seed(svc, n=3)
    assert col.count() == 3 and col.query(query_texts=["seed 1"], n_results=1)["documents"][0][0].startswith("seed")
    code = ("import os,sys;os.environ['ORNEUR_VECTOR_MODE']='service'\nfrom pathlib import Path\nfrom orca import vectorstore as V\n"
            "V._home=lambda: Path(os.environ['H'])\nV.Store(Path(os.environ['H'])/'memory'/'vectors').open_collection('orca_victim001')[0].count()\nprint('chromadb' in sys.modules)")
    p = subprocess.run([sys.executable, "-c", code], env={**os.environ, "H": str(svc.home), "PYTHONPATH": str(REPO)}, capture_output=True, text=True, timeout=60)
    assert p.stdout.strip() == "False", p.stderr[-500:]


def test_only_one_owner_ever_runs_per_data_directory_even_when_many_processes_start_together(svc):
    code = ("import os,sys,json;os.environ['ORNEUR_VECTOR_MODE']='service'\nfrom pathlib import Path\nfrom orca import vectorstore as V\nV._home=lambda: Path(os.environ['H'])\n"
            "t=V.transport(); r=t.owner_stats(); t.ensure_owner(); print(json.dumps({'pid': (t.owner_stats() or {}).get('pid')}))")
    procs = [subprocess.Popen([sys.executable, "-c", code], env={**os.environ, "H": str(svc.home), "PYTHONPATH": str(REPO)}, stdout=subprocess.PIPE, text=True) for _ in range(6)]
    pids = {json.loads(p.communicate(timeout=90)[0].strip().splitlines()[-1])["pid"] for p in procs}
    assert len(pids) == 1 and None not in pids
    owners = subprocess.run(["pgrep", "-f", f"[o]rca.vectorstore.server --home {svc.home}"], capture_output=True, text=True).stdout.split()
    assert len(owners) == 1


def test_a_request_without_the_token_or_with_a_path_outside_the_data_directory_is_refused(svc):
    _seed(svc)
    import socket
    from orca.vectorstore import protocol

    s = socket.socket(socket.AF_UNIX)
    s.settimeout(5)
    s.connect(str(paths.sock_path(svc.home)))
    protocol.send(s, {"op": "call", "token": "wrong", "root": str(svc.root), "collection": "orca_victim001", "method": "count", "kwargs": {}})
    assert protocol.recv(s)["error"] == "auth"
    s.close()
    with pytest.raises(V.VectorUnavailable):
        svc.t.call({"op": "call", "root": "/etc", "collection": "orca_victim001", "method": "count", "kwargs": {}})
    assert (paths.sock_path(svc.home).stat().st_mode & 0o777) == 0o600 and (paths.run_dir(svc.home).stat().st_mode & 0o777) == 0o700


# ── containment (the L02-06a finding) ─────────────────────────────────────────────────────────────────────────────────────────

def test_a_write_blocked_behind_a_held_lock_is_released_at_its_deadline_and_the_application_never_freezes(svc):
    col = _seed(svc)
    other = _seed(svc, "orca_other0002")
    holder = Holder(svc.root / "chroma.sqlite3", 25)
    beat = Beat()
    try:
        t0 = time.monotonic()
        with pytest.raises((V.VectorTimeout, V.VectorUnavailable)):
            col.add(documents=["blocked"], ids=["x"], metadatas=[{"a": 1}])
        took = time.monotonic() - t0
        beat.stop = True
        assert took < 3.5, f"released after {took:.1f}s for a 2s deadline"
        assert beat.max < 0.5, f"the application's own interpreter stalled for {beat.max:.1f}s"
        # the baseline (embedded) behaviour for the same fault was a 12-20 s freeze of the whole process; here the next unrelated read is served once the owner is healthy
        deadline = time.monotonic() + 25
        ok = None
        while time.monotonic() < deadline:
            try:
                ok = other.count()
                break
            except V.VectorError:
                time.sleep(0.5)
        assert ok == 1, "the service did not recover for unrelated reads while the lock was still held"
    finally:
        beat.stop = True
        holder.release()


def test_a_stalled_owner_that_cannot_answer_a_ping_is_killed_and_replaced(svc):
    col = _seed(svc)
    pid0 = svc.t.owner_pid()
    os.kill(pid0, signal.SIGSTOP)                       # a frozen interpreter: alive, holds every lock, answers nothing
    t0 = time.monotonic()
    with pytest.raises(V.VectorError):
        col.count()
    assert time.monotonic() - t0 < 4.0
    deadline = time.monotonic() + 20
    while time.monotonic() < deadline:
        try:
            if col.count() == 1:
                break
        except V.VectorError:
            time.sleep(0.4)
    else:
        pytest.fail("no replacement owner answered")
    assert svc.t.owner_pid() not in (None, pid0) and svc.t.counters["owner_kills"] >= 1
    with pytest.raises(ProcessLookupError):
        os.kill(pid0, 0)


def test_admission_is_bounded_a_flood_during_a_stall_is_refused_or_timed_out_not_queued(svc, monkeypatch):
    col = _seed(svc)
    holder = Holder(svc.root / "chroma.sqlite3", 20)
    t = svc.t
    t.max_inflight, t.max_waiting, t.queue_wait_s = 3, 4, 0.3
    t._sem = threading.BoundedSemaphore(3)
    outcomes, lock = [], threading.Lock()

    def one(i):
        t0 = time.monotonic()
        try:
            col.add(documents=[f"f{i}"], ids=[f"f{i}"], metadatas=[{"a": 1}])
            r = "ok"
        except V.VectorBusy:
            r = "busy"
        except V.VectorTimeout:
            r = "timeout"
        except V.VectorUnavailable:
            r = "unavailable"
        with lock:
            outcomes.append((r, time.monotonic() - t0))

    try:
        ths = [threading.Thread(target=one, args=(i,)) for i in range(40)]
        t0 = time.monotonic()
        [x.start() for x in ths]
        [x.join(30) for x in ths]
        assert time.monotonic() - t0 < 12 and len(outcomes) == 40, "a caller was left hanging"
        kinds = {k for k, _ in outcomes}
        assert "busy" in kinds, outcomes[:5]
        assert max(d for k, d in outcomes if k == "busy") < 1.5, "a refusal must be immediate, not after waiting in a queue"
    finally:
        holder.release()


def test_one_conversation_cannot_monopolise_the_service(svc):
    """Per-collection in-flight cap: a conversation hammering the service is refused ('busy') while another conversation keeps being served."""
    hot = _seed(svc, "orca_hot00001", n=50)
    quiet = _seed(svc, "orca_quiet001")
    stop, refused, served = threading.Event(), [0], [0]

    def hammer():
        while not stop.is_set():
            try:
                hot.query(query_texts=["seed"], n_results=10)
            except V.VectorBusy:
                refused[0] += 1
            except V.VectorError:
                pass

    ths = [threading.Thread(target=hammer, daemon=True) for _ in range(8)]
    [t.start() for t in ths]
    time.sleep(0.5)
    for _ in range(10):
        quiet.query(query_texts=["seed"], n_results=1)
        served[0] += 1
    stop.set()
    [t.join(5) for t in ths]
    st = svc.t.owner_stats()
    assert served[0] == 10 and (refused[0] + sum(st["refused"].values())) > 0, (refused, st["refused"])


# ── restart, crash and visibility ─────────────────────────────────────────────────────────────────────────────────────────────

def test_killing_the_owner_mid_indexing_leaves_a_consistent_store_and_the_next_call_restarts_it(svc):
    col = _seed(svc)
    stop = threading.Event()

    def writer():
        i = 0
        while not stop.is_set():
            try:
                col.add(documents=[f"bulk {i}" * 20], ids=[f"b{i}"], metadatas=[{"i": i}])
            except V.VectorError:
                time.sleep(0.05)
            i += 1

    th = threading.Thread(target=writer, daemon=True)
    th.start()
    time.sleep(1.2)
    os.kill(svc.t.owner_pid(), signal.SIGKILL)
    time.sleep(0.5)
    stop.set()
    th.join(10)
    c = sqlite3.connect(str(svc.root / "chroma.sqlite3"))
    try:
        assert c.execute("PRAGMA integrity_check").fetchone()[0] == "ok"
    finally:
        c.close()
    n = None
    for _ in range(40):
        try:
            n = col.count()
            break
        except V.VectorError:
            time.sleep(0.3)
    assert n is not None and n >= 1
    col.add(documents=["after the crash"], ids=["after"], metadatas=[{"a": 1}])
    assert col.count() == n + 1


def test_a_second_application_worker_sees_what_the_first_wrote_immediately_and_after_the_first_exits(svc):
    _seed(svc, "orca_shared001", n=2)
    code = ("import os,sys,json;os.environ['ORNEUR_VECTOR_MODE']='service'\nfrom pathlib import Path\nfrom orca import vectorstore as V\nV._home=lambda: Path(os.environ['H'])\n"
            "st=V.Store(Path(os.environ['H'])/'memory'/'vectors'); c,i=st.open_collection('orca_shared001', binding=V.session_binding('orca_shared001'))\n"
            "c.add(documents=['written by worker B'], ids=['B'], metadatas=[{'a':1}]); print(json.dumps({'status': i['status'], 'count': c.count()}))")
    r = subprocess.run([sys.executable, "-c", code], env={**os.environ, "H": str(svc.home), "PYTHONPATH": str(REPO)}, capture_output=True, text=True, timeout=90)
    assert json.loads(r.stdout.strip().splitlines()[-1]) == {"status": "ok", "count": 3}, r.stderr[-400:]
    col = V.Store(svc.root).open_collection("orca_shared001", binding=V.session_binding("orca_shared001"))[0]
    assert col.count() == 3 and "worker B" in json.dumps(col.get(ids=["B"]))


def test_a_graceful_stop_releases_the_data_directory_and_a_later_call_starts_a_fresh_owner(svc):
    col = _seed(svc)
    pid0 = svc.t.owner_pid()
    assert svc.t.stop_owner() is True and svc.t.owner_pid() is None
    assert col.count() == 1 and svc.t.owner_pid() not in (None, pid0)


def test_the_owner_exits_by_itself_when_idle_so_a_stopped_application_leaves_nothing_holding_the_directory(svc):
    svc.t.owner_env = {"ORNEUR_VECTOR_IDLE_EXIT_S": "2"}
    _seed(svc)
    svc.t.kill_owner()
    svc.t.counters["owner_starts"] = 0
    _seed(svc, "orca_idle00001")
    pid = svc.t.owner_pid()
    assert pid is not None
    end = time.monotonic() + 15
    while time.monotonic() < end and svc.t.owner_pid() is not None:
        time.sleep(0.5)
    assert svc.t.owner_pid() is None, "the idle owner did not exit"


def test_an_owner_whose_memory_passes_its_limit_leaves_when_idle_and_the_next_call_starts_a_fresh_one_with_the_data_intact(svc):
    svc.t.owner_env = {"ORNEUR_VECTOR_MAX_RSS_MB": "150", "ORNEUR_VECTOR_IDLE_EXIT_S": "120"}         # the embedder alone is larger than this
    col = _seed(svc, n=2)
    pid0 = svc.t.owner_pid()
    end = time.monotonic() + 20
    while time.monotonic() < end and svc.t.owner_pid() == pid0:
        time.sleep(0.3)
    assert svc.t.owner_pid() != pid0, "the over-limit owner did not recycle"
    assert col.count() == 2 and svc.t.owner_pid() not in (None, pid0)
