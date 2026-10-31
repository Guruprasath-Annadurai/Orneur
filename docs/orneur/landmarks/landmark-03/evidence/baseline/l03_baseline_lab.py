"""L03 Phase A -- baseline reproduction lab. Runs against the UNMODIFIED product (orca.brain.memory.LongTermMemory, orca.docs.store.DocStore) and real chromadb in disposable
data directories. Nothing here changes product code. Each experiment runs in its own child interpreter (a stalled experiment cannot hide another) and prints one JSON line.

    python l03_baseline_lab.py            # all experiments, JSON to stdout
    python l03_baseline_lab.py E1 E9      # selected
Synthetic data only. Needs chromadb (the project's `memory` extra) and its cached ONNX default embedder; no network is used.
"""
from __future__ import annotations

import json
import os
import platform
import signal
import sqlite3
import subprocess
import sys
import tempfile
import time
from pathlib import Path

REPO = Path(os.environ.get("L03_REPO") or subprocess.run(["git", "rev-parse", "--show-toplevel"], cwd=Path(__file__).parent, capture_output=True, text=True).stdout.strip())      # the product checkout under test
PY = sys.executable
CANARY = "L03-CANARY-TEXT-"


def child(code: str, home: Path, timeout: float, extra_env=None):
    env = {k: v for k, v in os.environ.items() if not k.startswith(("ORNEUR_", "ORCA_"))}
    env.update({"ORNEUR_HOME": str(home), "PYTHONPATH": str(REPO), **(extra_env or {})})
    t = time.time()
    try:
        p = subprocess.run([PY, "-c", code], env=env, capture_output=True, text=True, timeout=timeout, cwd=REPO)
        out = p.stdout.strip().splitlines()
        try:
            res = json.loads(out[-1]) if out else {}
        except ValueError:
            res = {"unparsed": out[-3:]}
        return {"exit": p.returncode, "wall_s": round(time.time() - t, 2), **res, **({"stderr_tail": p.stderr[-400:]} if p.returncode else {})}
    except subprocess.TimeoutExpired:
        return {"exit": "TIMEOUT", "wall_s": round(time.time() - t, 2)}


HOLD = """
import sqlite3, sys, time
c = sqlite3.connect(sys.argv[1], timeout=1, isolation_level=None)
c.execute("BEGIN EXCLUSIVE")
print("held", flush=True)
time.sleep(float(sys.argv[2]))
"""


def hold_lock(db: Path, seconds: float):
    p = subprocess.Popen([PY, "-c", HOLD, str(db), str(seconds)], stdout=subprocess.PIPE, text=True)
    assert p.stdout.readline().strip() == "held"
    return p


PRELUDE = """
import json, os, sys, threading, time, resource
sys.path.insert(0, os.environ["PYTHONPATH"])
from orca.brain import memory as M
from orca.config import ORCA_HOME
def fds(): return len(os.listdir('/proc/self/fd'))
def rss(): return int(open('/proc/self/statm').read().split()[1]) * 4096 // 1048576
class Beat:
    def __init__(self): self.max=0.0; self.n=0; self.stop=False; threading.Thread(target=self.run,daemon=True).start()
    def run(self):
        last=time.monotonic()
        while not self.stop:
            time.sleep(0.02); now=time.monotonic(); self.max=max(self.max,now-last-0.02); last=now; self.n+=1
"""


def seed(home: Path, sessions=("seed0001",), n=3):
    code = PRELUDE + f"""
for sid in {list(sessions)!r}:
    m = M.LongTermMemory(sid)
    for i in range({n}):
        m.store("{CANARY}"+sid+"-"+str(i)+" quarterly numbers", {{"k": i}})
print(json.dumps({{"seeded": len({list(sessions)!r})}}))
"""
    return child(code, home, 120)


def vdb(home: Path) -> Path:
    return home / "memory" / "vectors" / "chroma.sqlite3"


def E1_held_lock_gil_stall(home):
    """A competing process holds an EXCLUSIVE lock on the shared chroma.sqlite3 for 14 s. Does the serving process keep running (heartbeat thread gap) while a vector operation blocks?
    Two shapes, 3 trials each: (a) the operation includes client construction (what LongTermMemory.__init__ does per session); (b) the client/collection already exist and only
    add() runs. The first full run of this lab saw a 19.55 s whole-interpreter freeze for (a) and a later run saw none, so the distribution is recorded rather than one sample."""
    out = {"a_construct_then_write": [], "b_write_on_existing_collection": []}
    for shape in out:
        for trial in range(3):
            h2 = Path(tempfile.mkdtemp(prefix="e1-", dir=home))
            (h2 / "memory").mkdir(parents=True, exist_ok=True)
            seed(h2)
            pre = "" if shape.startswith("a_") else "m = M.LongTermMemory('seed0001'); m.store('warm', {'a': 1})\n"
            op = "m = M.LongTermMemory('seed0001'); m.store('x', {'a': 1})" if shape.startswith("a_") else "m.store('x', {'a': 1})"
            h = hold_lock(vdb(h2), 14)
            try:
                code = PRELUDE + pre + """
b = Beat(); time.sleep(0.2)
res = {}
def op():
    t = time.monotonic()
    try:
        %s; res["op"] = "ok"
    except Exception as e: res["op"] = type(e).__name__
    res["op_s"] = round(time.monotonic() - t, 2)
th = threading.Thread(target=op, daemon=True); th.start(); th.join(10)
b.stop = True
print(json.dumps({"op_finished_within_10s": not th.is_alive(), "op": res.get("op"), "op_s": res.get("op_s"), "heartbeat_max_gap_s": round(b.max, 2)}))
""" % op
                out[shape].append(child(code, h2, 60))
            finally:
                h.kill()
    out["finding"] = "heartbeat_max_gap_s close to the lock duration = the whole interpreter (GIL) was frozen by a native call; ~0 = only the calling thread blocked"
    return out


def E4_delete_budget_overshoot(home):
    """Product deletion path with a 5 s budget against a real 20 s held lock: wall time to return, result."""
    seed(home)
    h = hold_lock(vdb(home), 20)
    try:
        code = PRELUDE + """
b = Beat(); time.sleep(0.2)
t = time.monotonic(); r = M.LongTermMemory.delete_session("seed0001"); el = time.monotonic() - t
b.stop = True
print(json.dumps({"budget_s": M._DELETE_REQUEST_BUDGET_S, "delete_session_returned_after_s": round(el, 2), "logical_deleted": r.logical_deleted, "physical": r.physical_reclamation, "heartbeat_max_gap_s": round(b.max, 2)}))
"""
        r = child(code, home, 90)
    finally:
        h.kill()
    return r


def E5_head_of_line_blocking(home):
    """One stalled vector operation (cancelled by the caller, but its thread keeps running) holds the process-wide _CHROMA_LOCK: how long is an UNRELATED session's request delayed?"""
    seed(home, sessions=("aaaa0001", "bbbb0002"))
    h = hold_lock(vdb(home), 12)
    try:
        code = PRELUDE + """
import asyncio
async def main():
    # request 1: recall on session A; the caller gives up (cancels) after 1 s -- the worker thread cannot be cancelled
    loop = asyncio.get_running_loop()
    t1 = loop.run_in_executor(None, lambda: M.LongTermMemory("aaaa0001").store("blocked writer", {"a": 1}))      # a WRITE: needs the file lock the competitor holds
    tt = time.monotonic()
    try: await asyncio.wait_for(t1, 1.0)
    except asyncio.TimeoutError: pass
    gave_up_after = round(time.monotonic() - tt, 2)                # the event loop itself must be free for this 1.0 s timeout to fire
    await asyncio.sleep(0.1)
    # request 2: an unrelated session B tries to store; measure how long it waits
    t0 = time.monotonic()
    t2 = loop.run_in_executor(None, lambda: M.LongTermMemory("bbbb0002").recall("quarterly", 1))                  # an unrelated READ (reads alone do not need the file lock)
    try:
        await asyncio.wait_for(t2, 20); ok = True
    except Exception as e: ok = type(e).__name__
    return round(time.monotonic() - t0, 2), ok, gave_up_after
w, ok, gave = asyncio.run(main())
print(json.dumps({"unrelated_read_waited_s": w, "unrelated_read_result": ok, "asked_to_give_up_after_s": 1.0, "actually_gave_up_after_s": gave}))
"""
        r = child(code, home, 90)
    finally:
        h.kill()
    return r


def E2_concurrent_create_delete(home):
    code = PRELUDE + """
import collections
errs = collections.Counter(); ok = [0]
def w(i):
    for j in range(8):
        sid = f"s{i:03d}{j:03d}x"
        try:
            m = M.LongTermMemory(sid); m.store("c", {"a": 1}); m.recall("c", 1)
            r = M.LongTermMemory.delete_session(sid)
            if r.logical_deleted: ok[0] += 1
            else: errs["not_deleted:" + r.physical_reclamation] += 1
        except Exception as e: errs[type(e).__name__] += 1
ts = [threading.Thread(target=w, args=(i,)) for i in range(8)]
t = time.monotonic(); [x.start() for x in ts]; [x.join(120) for x in ts]
print(json.dumps({"ops": 64, "completed_ok": ok[0], "errors": dict(errs), "wall_s": round(time.monotonic() - t, 2)}))
"""
    return child(code, home, 150)


def E3_E8_many_sessions_fd_rss(home):
    out = {}
    for n in (10, 50, 100, 200):
        code = PRELUDE + f"""
base_fd, base_rss = fds(), rss()
lat = []
for i in range({n}):
    sid = f"fd{{i:06d}}"
    t = time.monotonic(); m = M.LongTermMemory(sid); m.store("{CANARY}"+sid, {{"a": 1}}); m.recall("quarterly", 1); lat.append(time.monotonic() - t)
lat.sort()
print(json.dumps({{"sessions": {n}, "fd_base": base_fd, "fd_after": fds(), "fd_per_session": round((fds() - base_fd) / {n}, 2), "rss_mb_base": base_rss, "rss_mb_after": rss(), "latency_p50_s": round(lat[len(lat)//2], 3), "latency_p95_s": round(lat[int(len(lat)*0.95)-1], 3), "soft_fd_limit": resource.getrlimit(resource.RLIMIT_NOFILE)[0]}}))
"""
        out[str(n)] = child(code, Path(tempfile.mkdtemp(prefix="fd", dir=home)), 300)
    return out


def E6_crash_during_indexing(home):
    code = PRELUDE + """
m = M.LongTermMemory("crash001")
print("ready", flush=True)
i = 0
while True:
    m.store("bulk " + str(i) * 50, {"i": i}); i += 1
"""
    env = {k: v for k, v in os.environ.items() if not k.startswith(("ORNEUR_", "ORCA_"))}
    env.update({"ORNEUR_HOME": str(home), "PYTHONPATH": str(REPO)})
    p = subprocess.Popen([PY, "-c", code], env=env, stdout=subprocess.PIPE, text=True, cwd=REPO)
    p.stdout.readline()
    time.sleep(1.5)
    os.kill(p.pid, signal.SIGKILL)
    p.wait()
    c = sqlite3.connect(str(vdb(home)))
    integ = c.execute("PRAGMA integrity_check").fetchone()[0]
    c.close()
    after = child(PRELUDE + """
m = M.LongTermMemory("crash001")
try: n = m._collection.count(); err = None
except Exception as e: n = None; err = type(e).__name__ + ": " + str(e)[:160]
try: r = m.recall("bulk", 3); rec = len(r)
except Exception as e: rec = type(e).__name__ + ": " + str(e)[:160]
try: m.store("after crash", {"a": 1}); st = "ok"
except Exception as e: st = type(e).__name__ + ": " + str(e)[:160]
print(json.dumps({"count": n, "count_error": err, "recall": rec, "store_after": st}))
""", home, 90)
    return {"sqlite_integrity": integ, "after_restart": after}


def E7_interrupted_deletion_restart(home):
    seed(home, sessions=("intr0001", "keep0002"))
    h = hold_lock(vdb(home), 12)
    code = PRELUDE + """
print("start", flush=True)
M.LongTermMemory.delete_session("intr0001")
"""
    env = {k: v for k, v in os.environ.items() if not k.startswith(("ORNEUR_", "ORCA_"))}
    env.update({"ORNEUR_HOME": str(home), "PYTHONPATH": str(REPO)})
    p = subprocess.Popen([PY, "-c", code], env=env, stdout=subprocess.PIPE, text=True, cwd=REPO)
    p.stdout.readline()
    time.sleep(2.0)
    os.kill(p.pid, signal.SIGKILL)                 # the worker dies mid-deletion
    p.wait()
    h.kill()
    time.sleep(0.5)
    after = child(PRELUDE + """
r = M.LongTermMemory("intr0001").recall("quarterly", 5)
pend_l = M._load_pending_logical_deletions(); pend_r = M._load_pending_reclamations()
print(json.dumps({"deleted_session_still_retrievable_texts": len(r), "pending_logical_ledger": len(pend_l), "pending_reclaim_ledger": len(pend_r), "other_session_intact": len(M.LongTermMemory("keep0002").recall("quarterly", 5))}))
""", home, 90)
    return {"killed_mid_deletion": True, "after_restart": after,
            "finding": "a worker killed mid-deletion leaves the data retrievable by the memory layer and records NOTHING durable at this layer; only the conversation-level tombstone (session_deletions) revokes access and its sweep re-runs the cascade"}


def E9_cross_process_visibility(home):
    out = {}
    # (a) P1 creates + populates and EXITS; P2 opens fresh
    child(PRELUDE + """
m = M.LongTermMemory("xproc001"); m.store("created by process one", {"a": 1}); print(json.dumps({"ok": 1}))
""", home, 60)
    out["a_fresh_process_after_creator_exit"] = child(PRELUDE + """
try: r = M.LongTermMemory("xproc001").recall("created", 3); print(json.dumps({"hits": len(r)}))
except Exception as e: print(json.dumps({"error": type(e).__name__ + ": " + str(e)[:200]}))
""", home, 60)
    # (b) P1 stays alive holding its client; P2 creates a NEW collection; P1 (existing client) reads it by name; and the reverse
    code1 = PRELUDE + """
m = M.LongTermMemory("xproc010")
print("p1-ready", flush=True)
sys.stdin.readline()
res = {}
for name in ("orca_xproc020",):
    try: res["p1_sees_p2_collection"] = m._client.get_collection(name).count()
    except Exception as e: res["p1_sees_p2_collection"] = type(e).__name__ + ": " + str(e)[:160]
try: res["p1_recall_p2_session"] = len(M.LongTermMemory("xproc020").recall("process two", 3))
except Exception as e: res["p1_recall_p2_session"] = type(e).__name__ + ": " + str(e)[:160]
print(json.dumps(res))
"""
    env = {k: v for k, v in os.environ.items() if not k.startswith(("ORNEUR_", "ORCA_"))}
    env.update({"ORNEUR_HOME": str(home), "PYTHONPATH": str(REPO)})
    p1 = subprocess.Popen([PY, "-c", code1], env=env, stdout=subprocess.PIPE, stdin=subprocess.PIPE, text=True, cwd=REPO)
    p1.stdout.readline()
    child(PRELUDE + """
m = M.LongTermMemory("xproc020"); m.store("written by process two", {"a": 1}); print(json.dumps({"ok": 1}))
""", home, 60)
    out_b = p1.communicate("go\n", timeout=60)[0].strip().splitlines()
    out["b_existing_client_reads_collection_created_later_by_other_process"] = json.loads(out_b[-1]) if out_b else {}
    # (c) two processes append to the SAME collection concurrently; count from each
    writers = [subprocess.Popen([PY, "-c", PRELUDE + f"""
m = M.LongTermMemory("xproc030")
for i in range(40): m.store("w{w} "+str(i), {{"a": 1}})
print(json.dumps({{"c": m._collection.count()}}))
"""], env=env, stdout=subprocess.PIPE, text=True, cwd=REPO) for w in "AB"]
    counts = [json.loads(w.communicate(timeout=120)[0].strip().splitlines()[-1])["c"] for w in writers]
    final = child(PRELUDE + """
print(json.dumps({"final_count": M.LongTermMemory("xproc030")._collection.count()}))
""", home, 60)
    out["c_two_writers_same_collection"] = {"counts_seen_by_each_writer_at_exit": counts, **final, "expected_total": 80}
    return out


def E10_deleted_bytes_on_disk(home):
    code = PRELUDE + f"""
a = M.LongTermMemory("dead0001"); b = M.LongTermMemory("live0002")
for i in range(5):
    a.store("{CANARY}DELETED-"+str(i)+" secret", {{"i": i}}); b.store("{CANARY}KEPT-"+str(i), {{"i": i}})
r = M.LongTermMemory.delete_session("dead0001")
root = ORCA_HOME / "memory" / "vectors"
found = {{}}
for p in root.rglob("*"):
    if p.is_file():
        data = p.read_bytes()
        if b"{CANARY}DELETED" in data: found[str(p.relative_to(root))] = data.count(b"{CANARY}DELETED")
dirs = sorted(d.name for d in root.iterdir() if d.is_dir())
print(json.dumps({{"logical": r.logical_deleted, "physical": r.physical_reclamation, "deleted_text_found_in": found, "segment_dirs_after_delete": len(dirs), "kept_still_readable": len(M.LongTermMemory("live0002").recall("KEPT", 5))}}))
"""
    r = child(code, home, 120)
    return r


def E11_session_prefix_collision(home):
    code = PRELUDE + f"""
victim = M.LongTermMemory("deadbeef-1111-victim-session")
victim.store("{CANARY}VICTIM-PRIVATE quarterly forecast is confidential", {{"owner": "victim"}})
attacker = M.LongTermMemory("deadbeef-2222-attacker-session")      # a different session id (accepted by the API: ^[A-Za-z0-9_-]{{1,64}}$) with the same first 8 characters
got = attacker.recall("quarterly forecast", 5)
res_a = [h["text"] for h in got]
r = M.LongTermMemory.delete_session("deadbeef-2222-attacker-session")      # the attacker deletes THEIR session ...
still = len(M.LongTermMemory("deadbeef-1111-victim-session").recall("quarterly forecast", 5))
print(json.dumps({{"attacker_recalls_victims_text": any("VICTIM-PRIVATE" in t for t in res_a), "attacker_deletion_logical": r.logical_deleted, "victim_hits_after_attackers_delete": still}}))
"""
    r = child(code, home, 120)
    r["also_docs"] = child(PRELUDE + """
from orca.docs.store import DocStore
a = DocStore("deadbeef-1111-aaaa"); b = DocStore("deadbeef-2222-bbbb")
print(json.dumps({"doc_collection_a": a._col_name, "doc_collection_b": b._col_name, "same_collection": a._col_name == b._col_name}))
""", home, 60)
    return r


EXPERIMENTS = {"E1": E1_held_lock_gil_stall, "E2": E2_concurrent_create_delete, "E3_E8": E3_E8_many_sessions_fd_rss, "E4": E4_delete_budget_overshoot, "E5": E5_head_of_line_blocking,
               "E6": E6_crash_during_indexing, "E7": E7_interrupted_deletion_restart, "E9": E9_cross_process_visibility, "E10": E10_deleted_bytes_on_disk, "E11": E11_session_prefix_collision}


def main():
    import chromadb
    names = sys.argv[1:] or list(EXPERIMENTS)
    probe = subprocess.run([PY, "-c", "import orca,sys;print(orca.__file__)"], env={**os.environ, "PYTHONPATH": str(REPO)}, capture_output=True, text=True, cwd=REPO).stdout.strip()
    assert probe.startswith(str(REPO)), f"the lab would import product code from {probe}, not from {REPO}"
    sha = subprocess.run(["git", "rev-parse", "HEAD"], cwd=REPO, capture_output=True, text=True).stdout.strip()
    report = {"environment": {"product_checkout": str(REPO), "product_sha": sha, "orca_module": probe, "python": platform.python_version(), "chromadb": chromadb.__version__, "sqlite": sqlite3.sqlite_version, "platform": platform.platform(), "cpus": os.cpu_count(),
                              "recorded_at": time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime())}, "experiments": {}}
    for n in names:
        home = Path(tempfile.mkdtemp(prefix=f"l03-{n}-", dir=os.environ.get("L03_LAB_DIR", "/tmp")))
        (home / "memory").mkdir(parents=True, exist_ok=True)
        t = time.time()
        try:
            res = EXPERIMENTS[n](home)
        except Exception as exc:                        # an experiment that cannot run is reported, not hidden
            res = {"lab_error": f"{type(exc).__name__}: {exc}"}
        report["experiments"][n] = {"result": res, "lab_seconds": round(time.time() - t, 1)}
        print(f"[{n}] {json.dumps(res)[:300]}", file=sys.stderr, flush=True)
    print(json.dumps(report, indent=1))


if __name__ == "__main__":
    main()
