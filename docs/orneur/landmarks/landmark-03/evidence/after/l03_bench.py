"""L03 Phase C -- resource benchmark. The SAME workload as the baseline lab (E3_E8 in evidence/baseline/l03_baseline_lab.py): for N sessions, construct LongTermMemory(sid), store one
item, recall once; measure open descriptors, RSS and the per-session latency distribution. Run here against the changed code in `service` mode (application process + owner process
are measured separately) and `embedded` mode. Same workstation, same python/chromadb/sqlite versions as the baseline run recorded in that file's environment block.

    python l03_bench.py [N ...]
"""
from __future__ import annotations

import json
import os
import platform
import resource
import signal
import subprocess
import sys
import tempfile
import time
from pathlib import Path

REPO = Path(os.environ.get("L03_REPO") or subprocess.run(["git", "rev-parse", "--show-toplevel"], cwd=Path(__file__).parent, capture_output=True, text=True).stdout.strip())      # the product checkout under test
PY = sys.executable

CODE = """
import json, os, sys, time
sys.path.insert(0, os.environ["PYTHONPATH"])
from orca import vectorstore as V
from orca.brain import memory as M
def fds(): return len(os.listdir('/proc/self/fd'))
def rss(): return int(open('/proc/self/statm').read().split()[1]) * 4096 // 1048576
n = int(sys.argv[1]); base_fd, base_rss = fds(), rss(); lat = []; errs = 0
for i in range(n):
    sid = f"fd{i:06d}"
    t = time.monotonic()
    try:
        m = M.LongTermMemory(sid); m.store("L03-BENCH-" + sid, {"a": 1}, strict=True); m.recall("quarterly", 1, strict=True)
    except Exception as e:
        errs += 1
    lat.append(time.monotonic() - t)
lat.sort()
out = {"sessions": n, "errors": errs, "app_fd_base": base_fd, "app_fd_after": fds(), "app_rss_mb_base": base_rss, "app_rss_mb_after": rss(),
       "latency_p50_s": round(lat[len(lat)//2], 3), "latency_p95_s": round(lat[max(0, int(len(lat)*0.95)-1)], 3), "latency_max_s": round(lat[-1], 3),
       "chromadb_loaded_in_app_process": "chromadb" in sys.modules}
if V.mode() == "service":
    o = V.transport().owner_stats() or {}
    out.update({"owner_fds": o.get("fds"), "owner_rss_mb": o.get("rss_mb"), "owner_open_collections": sum(v["open_collections"] for v in o.get("stores", {}).values()),
                "owner_client_recycles": sum(v["recycles"] for v in o.get("stores", {}).values()), "owner_refused": o.get("refused")})
    V.transport().stop_owner()
else:
    h = V.stats()["owner"]
    out.update({"owner_fds": "(same process)", "open_collections": sum(v["open_collections"] for v in h["stores"].values()), "client_recycles": sum(v["recycles"] for v in h["stores"].values())})
print(json.dumps(out))
"""


def run(mode: str, n: int) -> dict:
    home = Path(tempfile.mkdtemp(prefix=f"bench-{mode}-", dir="/tmp"))
    (home / "memory").mkdir(parents=True)
    env = {k: v for k, v in os.environ.items() if not k.startswith(("ORNEUR_", "ORCA_"))}
    env.update({"ORNEUR_HOME": str(home), "PYTHONPATH": str(REPO), "ORNEUR_VECTOR_MODE": mode, "ORNEUR_VECTOR_IDLE_EXIT_S": "60"})
    p = subprocess.run([PY, "-c", CODE, str(n)], env=env, capture_output=True, text=True, timeout=900, cwd=REPO)
    try:
        return json.loads(p.stdout.strip().splitlines()[-1])
    except Exception:
        return {"error": p.stderr[-300:]}


def main():
    ns = [int(x) for x in sys.argv[1:]] or [10, 50, 100, 200]
    import chromadb
    sha = subprocess.run(["git", "rev-parse", "HEAD"], cwd=REPO, capture_output=True, text=True).stdout.strip()
    probe = subprocess.run([PY, "-c", "import orca;print(orca.__file__)"], env={**os.environ, "PYTHONPATH": str(REPO)}, capture_output=True, text=True, cwd=REPO).stdout.strip()
    assert probe.startswith(str(REPO)), f"would import product code from {probe}"
    rep = {"environment": {"product_checkout": str(REPO), "product_sha": sha, "orca_module": probe, "python": platform.python_version(), "chromadb": chromadb.__version__, "platform": platform.platform(), "cpus": os.cpu_count(),
                           "soft_fd_limit": resource.getrlimit(resource.RLIMIT_NOFILE)[0], "recorded_at": time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime())}, "runs": {}}
    for mode in ("service", "embedded"):
        rep["runs"][mode] = {str(n): run(mode, n) for n in ns}
        print(mode, json.dumps(rep["runs"][mode])[:300], file=sys.stderr, flush=True)
    print(json.dumps(rep, indent=1))


if __name__ == "__main__":
    main()
