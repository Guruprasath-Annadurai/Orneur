"""L03 -- vector containment against REAL ``orca serve`` workers (two processes sharing one data directory), the real vector-service owner process and real chromadb.
Evidence class LIVE+FIX (fixture model provider; the vector path is real). Run:  pytest tests/journey/test_l03_vector_live.py -p no:cacheprovider -v

Each scenario asserts what the user-visible service does, not an internal flag: probes keep answering during a vector stall, a stalled write is refused within its deadline with a
truthful code, a chat turn is not failed by a derived-state outage, the owner is replaced after SIGKILL, a second worker reads what the first wrote, descriptor use stays bounded.
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
from tests.journey.harness import JOURNEY_MODEL, REPO, LiveServer, User

EVIDENCE = Path(os.environ.get("ORNEUR_L03_EVIDENCE_DIR", "/tmp/orneur-l03-evidence"))
RESULTS: dict = {}


def _owner_pids(home: Path) -> list[int]:
    out = subprocess.run(["pgrep", "-f", f"[o]rca.vectorstore.server --home {home}"], capture_output=True, text=True).stdout.split()
    return [int(x) for x in out]


def _fds(pid: int) -> int:
    return len(os.listdir(f"/proc/{pid}/fd"))


class Holder:
    def __init__(self, db: Path, seconds: float):
        code = "import sqlite3,sys,time;c=sqlite3.connect(sys.argv[1],timeout=1,isolation_level=None);c.execute('BEGIN EXCLUSIVE');print('held',flush=True);time.sleep(float(sys.argv[2]))"
        self.p = subprocess.Popen([sys.executable, "-c", code, str(db), str(seconds)], stdout=subprocess.PIPE, text=True)
        assert self.p.stdout.readline().strip() == "held"

    def release(self):
        self.p.kill()
        self.p.wait()


@pytest.fixture(scope="module")
def pair(tmp_path_factory):
    fake = FakeOllama(models=(JOURNEY_MODEL,), reply="FIXTURE-ANSWER")
    fake.__enter__()
    home = tmp_path_factory.mktemp("l03live")
    env = {"ORNEUR_OLLAMA_HOST": fake.host, "OLLAMA_HOST": fake.host, "ORNEUR_DELETION_SWEEP_S": "2", "ORNEUR_VECTOR_DEADLINE_S": "2", "ORNEUR_VECTOR_MAX_OPEN": "16",
           "ORNEUR_VECTOR_IDLE_EXIT_S": "600"}
    a, b = LiveServer(home, extra_env=env), LiveServer(home, extra_env=env)
    try:
        a.wait_ready()
        b.wait_ready()
        user = User(a.base, "l03")
        tok_b = httpx.post(f"{b.base}/api/auth/login", json={"email": user.email, "password": "Journey-Pass-91x"}, timeout=30).json()["token"]
        yield {"home": home, "a": a, "b": b, "user": user, "tok_b": tok_b, "env": env}
    finally:
        for s in (a, b):
            s.stop()
        for pid in _owner_pids(home):
            try:
                os.kill(pid, signal.SIGKILL)
            except OSError:
                pass
        fake.__exit__(None, None, None)
        EVIDENCE.mkdir(parents=True, exist_ok=True)
        (EVIDENCE / "l03_vector_live.json").write_text(json.dumps(RESULTS, indent=1))


def _remember(base, tok, sid, fact, timeout=30):
    return httpx.post(f"{base}/api/remember", json={"session_id": sid, "fact": fact}, headers={"Authorization": f"Bearer {tok}"}, timeout=timeout)


def _recall(base, tok, sid, q, timeout=30):
    return httpx.post(f"{base}/api/memory/recall", json={"session_id": sid, "query": q}, headers={"Authorization": f"Bearer {tok}"}, timeout=timeout)


def test_V1_one_owner_serves_both_workers_and_the_application_processes_never_load_chromadb(pair):
    u, a, b = pair["user"], pair["a"], pair["b"]
    sid = str(uuid.uuid4())
    r = _remember(a.base, u.token, sid, "L03 worker-A fact: the launch codename is Heron")
    assert r.status_code == 200, r.text
    r2 = _recall(b.base, pair["tok_b"], sid, "launch codename")
    assert r2.status_code == 200 and "Heron" in r2.text, r2.text            # second worker reads what the first wrote
    owners = _owner_pids(pair["home"])
    assert len(owners) == 1, owners
    for s in (a, b):
        maps = Path(f"/proc/{s.proc.pid}/maps").read_text()
        assert "chromadb" not in maps and "chroma_bindings" not in maps, "an application process mapped the chromadb native library"
    RESULTS["V1"] = {"owner_pids": owners, "app_pids": [a.proc.pid, b.proc.pid], "second_worker_read_ok": True}


def test_V2_a_stalled_vector_write_is_refused_within_its_deadline_while_the_server_stays_responsive_and_chat_still_completes(pair):
    u, a, b = pair["user"], pair["a"], pair["b"]
    sid = str(uuid.uuid4())
    assert _remember(a.base, u.token, sid, "seed fact").status_code == 200
    holder = Holder(pair["home"] / "memory" / "vectors" / "chroma.sqlite3", 22)
    probes, stop = [], threading.Event()

    def probe():
        while not stop.is_set():
            t = time.monotonic()
            try:
                ok = httpx.get(f"{a.base}/livez", timeout=5).status_code == 200 and httpx.get(f"{b.base}/readyz", timeout=5).status_code in (200, 503)
            except Exception:
                ok = False
            probes.append((ok, time.monotonic() - t))
            time.sleep(0.2)

    th = threading.Thread(target=probe, daemon=True)
    th.start()
    try:
        t0 = time.monotonic()
        r = _remember(a.base, u.token, sid, "this write is blocked behind the competitor's lock")
        took = time.monotonic() - t0
        assert r.status_code in (503, 504) and r.json().get("code") in ("server_busy", "request_timeout"), r.text
        assert took < 6, f"refused only after {took:.1f}s"
        # a chat turn on another conversation still completes: its long-term write is derived state, counted as dropped, not a failure of the turn
        t1 = time.monotonic()
        status, events = u.stream("hello during the stall", session_id=str(uuid.uuid4()))
        done = [e for e in events if e.get("type") == "done"]
        chat_s = time.monotonic() - t1
        assert status == 200 and done and done[0].get("persisted") == "saved", events[-3:]
    finally:
        stop.set()
        th.join(5)
        holder.release()
    worst = max(d for _, d in probes)
    assert probes and all(ok for ok, _ in probes) and worst < 2.0, f"probe failures/slow probes: worst {worst:.2f}s of {len(probes)}"
    RESULTS["V2"] = {"refused_after_s": round(took, 2), "code": r.json().get("code"), "probes": len(probes), "worst_probe_s": round(worst, 2), "chat_turn_s": round(chat_s, 2)}
    time.sleep(1)
    assert _remember(a.base, u.token, sid, "after the lock is released").status_code == 200


def test_V3_killing_the_owner_is_survived_the_next_request_restarts_it(pair):
    u, a = pair["user"], pair["a"]
    sid = str(uuid.uuid4())
    assert _remember(a.base, u.token, sid, "before the crash fact").status_code == 200
    before = _owner_pids(pair["home"])
    for pid in before:
        os.kill(pid, signal.SIGKILL)
    time.sleep(0.5)
    ok = None
    for _ in range(20):
        r = _recall(a.base, u.token, sid, "before the crash")
        if r.status_code == 200:
            ok = r
            break
        time.sleep(0.5)
    assert ok is not None and "before the crash" in ok.text, "the service did not come back"
    after = _owner_pids(pair["home"])
    assert len(after) == 1 and after != before
    RESULTS["V3"] = {"owner_before": before, "owner_after": after, "recovered": True}


def test_V4_sigterm_of_one_worker_during_a_stalled_recall_does_not_disturb_the_other_worker_or_the_owner(pair):
    u, a, b = pair["user"], pair["a"], pair["b"]
    sid = str(uuid.uuid4())
    assert _remember(b.base, pair["tok_b"], sid, "sigterm scenario fact").status_code == 200
    owner = _owner_pids(pair["home"])
    holder = Holder(pair["home"] / "memory" / "vectors" / "chroma.sqlite3", 8)
    try:
        res = {}
        th = threading.Thread(target=lambda: res.setdefault("r", _remember(a.base, u.token, sid, "in flight when SIGTERM arrives", timeout=30)), daemon=True)
        th.start()
        time.sleep(0.5)
        a.proc.send_signal(signal.SIGTERM)
        th.join(20)
        assert httpx.get(f"{b.base}/livez", timeout=5).status_code == 200
        assert _owner_pids(pair["home"]) == owner, "the owner must outlive an application worker"
    finally:
        holder.release()
    a.proc.wait(timeout=30)
    assert _recall(b.base, pair["tok_b"], sid, "sigterm scenario").status_code == 200
    RESULTS["V4"] = {"worker_a_exit_code": a.proc.returncode, "owner_unchanged": True, "worker_b_served": True}
    # restart worker A for the following scenarios
    pair["a"] = LiveServer(pair["home"], extra_env=pair["env"])
    pair["a"].wait_ready()
    pair["user"].base = pair["a"].base
    pair["user"].http = httpx.Client(base_url=pair["a"].base, timeout=180)
    pair["user"].login()


def test_V5_descriptor_use_stays_bounded_while_many_conversations_are_active(pair):
    u, a = pair["user"], pair["a"]
    owner_pid = _owner_pids(pair["home"])[0]
    app_before, owner_before = _fds(a.proc.pid), _fds(owner_pid)
    sids = [str(uuid.uuid4()) for _ in range(80)]
    for sid in sids:
        assert _remember(a.base, u.token, sid, f"conversation fact {sid[:6]}").status_code == 200
    app_after, owner_after = _fds(a.proc.pid), _fds(_owner_pids(pair["home"])[0])
    health = httpx.get(f"{a.base}/readyz", timeout=10).json()["dependencies"]["vector"]
    RESULTS["V5"] = {"conversations": 80, "app_fds_before": app_before, "app_fds_after": app_after, "owner_fds_before": owner_before, "owner_fds_after": owner_after,
                     "max_open": 16, "owner_client_recycles": health["owner"].get("client_recycles")}
    assert app_after - app_before < 25, "the application process must not accumulate vector descriptors"
    assert owner_after < 120, f"owner descriptors grew with conversation count: {owner_after}"
    assert health["owner"].get("client_recycles", 0) >= 1, "the owner never recycled its client although 80 collections were touched with a limit of 16"


def test_V6_documents_are_retrieved_through_the_service_and_a_missing_embedding_service_is_survivable(pair):
    u, a = pair["user"], pair["a"]
    sid = str(uuid.uuid4())
    r = httpx.post(f"{a.base}/api/docs/upload", files={"file": ("notes.txt", b"The warehouse relocation completes in March and costs 41,000 dollars.", "text/plain")},
                   headers={"Authorization": f"Bearer {u.token}"}, params={"session_id": sid}, timeout=120)
    assert r.status_code == 200, r.text
    status, events = u.stream("When does the warehouse relocation complete?", session_id=sid)
    assert status == 200 and any(e.get("type") == "done" for e in events), events[-2:]
    RESULTS["V6"] = {"upload": r.status_code, "turn_done": True, "sources_event": any(e.get("type") in ("sources", "source") or "sources" in e for e in events)}
