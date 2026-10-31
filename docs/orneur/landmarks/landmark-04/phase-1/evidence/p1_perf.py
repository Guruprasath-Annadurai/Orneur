"""LANDMARK-04 P1 -- measured performance of the real path: browser -> ORNEUR API -> real Ollama (llama3.2:1b) -> browser.

Run from the repo root with the real Ollama running:  ORNEUR_JOURNEY_MODEL=llama3.2:1b python <this file> <out.json>
Synthetic account and synthetic prompts only. One workstation, one local model: these numbers describe THIS setup and are not a capacity claim.
"""
import json, os, statistics, subprocess, sys, tempfile, threading, time
from pathlib import Path
sys.path.insert(0, ".")
import httpx
from tests.journey.harness import JOURNEY_MODEL, LiveServer, User
from tests.fake_ollama import FakeOllama

OUT = sys.argv[1]
N_SEQ, N_CONC = 12, 4
PROMPTS = ["Explain what a hash table is in two sentences.", "Give me three tips for studying effectively.", "What is the difference between TCP and UDP? Keep it short.",
           "Write a one-paragraph summary of how photosynthesis works.", "Suggest a name for a small bakery and say why.", "What does HTTP status 404 mean?"]


def pct(xs, p):
    xs = sorted(xs)
    return xs[min(len(xs) - 1, int(round((p / 100) * (len(xs) - 1))))]


def stats(xs):
    return {"n": len(xs), "p50": round(pct(xs, 50), 3), "p95": round(pct(xs, 95), 3), "min": round(min(xs), 3), "max": round(max(xs), 3)}


def proc_info(pid):
    fds = len(os.listdir(f"/proc/{pid}/fd"))
    rss = int([l for l in open(f"/proc/{pid}/status") if l.startswith("VmRSS")][0].split()[1]) / 1024
    t = open(f"/proc/{pid}/stat").read().split()
    return {"fds": fds, "rss_mb": round(rss, 1), "cpu_s": round((int(t[13]) + int(t[14])) / os.sysconf("SC_CLK_TCK"), 2)}


def one_stream(u, msg, sid=None):
    t0 = time.time(); first = None; chunks = 0; done = None; err = None
    try:
        with u.http.stream("POST", "/api/stream", json={"message": msg, "session_id": sid, "model_variant": "core"},
                           headers={**u.headers, "Idempotency-Key": os.urandom(8).hex()}) as r:
            if r.status_code != 200:
                r.read(); return {"ok": False, "status": r.status_code, "body": r.text[:120]}
            for line in r.iter_lines():
                if not line.startswith("data: "): continue
                ev = json.loads(line[6:])
                if ev.get("type") == "chunk":
                    chunks += 1
                    first = first or time.time() - t0
                if ev.get("type") == "done": done = ev
                if ev.get("type") == "error": err = ev
    except Exception as e:
        return {"ok": False, "exc": type(e).__name__}
    ok = bool(done) and not err
    return {"ok": ok, "ttft": first, "total": time.time() - t0, "chunks": chunks, "done": done, "err": err}


res = {"hardware": {"cpu": "AMD Ryzen 7 9700X (16 threads)", "ram_gb": 15.2, "os": "WSL2 Linux 6.18", "ollama_model": JOURNEY_MODEL, "model_size_note": "llama3.2:1b local"}}
home = Path(tempfile.mkdtemp(prefix="p1perf-"))
t0 = time.time(); srv = LiveServer(home); srv.wait_ready(); res["server_start_to_livez_s"] = round(time.time() - t0, 2)
u = User(srv.base, "perf")
res["resources_idle"] = proc_info(srv.proc.pid)
httpx.post  # warm
one_stream(u, "Say hello.")                                            # model warm-up (excluded)
seq = []
for i in range(N_SEQ):
    seq.append(one_stream(u, PROMPTS[i % len(PROMPTS)]))
good = [s for s in seq if s["ok"]]
res["sequential"] = {"requests": N_SEQ, "ok": len(good), "ttft_s": stats([s["ttft"] for s in good]), "total_s": stats([s["total"] for s in good]),
                     "chunks_median": statistics.median(s["chunks"] for s in good),
                     "progressive": all(s["chunks"] > 1 for s in good),
                     "sample_done_event_keys": sorted((good[0]["done"] or {}).keys()), "served_identity_sample": {k: good[0]["done"].get(k) for k in ("model", "model_variant", "delivery", "persisted", "provider", "served_model") if k in good[0]["done"]}}
res["resources_after_sequential"] = proc_info(srv.proc.pid)
# concurrency: N_CONC users at once
users = [User(srv.base, f"perfc{i}") for i in range(N_CONC)]
out = [None] * N_CONC
def run(i): out[i] = one_stream(users[i], PROMPTS[i % len(PROMPTS)])
tc = time.time(); ts = [threading.Thread(target=run, args=(i,)) for i in range(N_CONC)]; [t.start() for t in ts]; [t.join(300) for t in ts]
res["concurrent"] = {"streams": N_CONC, "wall_s": round(time.time() - tc, 2), "ok": sum(1 for o in out if o and o["ok"]), "failures": [{k: v for k, v in o.items() if k in ("status", "exc", "body")} for o in out if not (o and o["ok"])],
                     "ttft_s": stats([o["ttft"] for o in out if o and o["ok"]]) if any(o and o["ok"] for o in out) else None, "total_s": stats([o["total"] for o in out if o and o["ok"]]) if any(o and o["ok"] for o in out) else None}
res["resources_after_concurrent"] = proc_info(srv.proc.pid)
# persisted turn check
sid = [e for e in [one_stream(u, "Remember the word kiwi.")] if e["ok"]][0]["done"].get("session_id") or None
srv.stop()
# server restart persistence of the real conversations
srv2 = LiveServer(home); srv2.wait_ready()
u2 = User.__new__(User); u2.base = srv2.base; u2.http = httpx.Client(base_url=srv2.base, timeout=60); u2.email = u.email; u2.login()
sessions = u2.get("/api/sessions").json()["sessions"]
res["restart"] = {"sessions_before": len(u.http.get("/api/sessions", headers=u.headers).json()["sessions"]) if False else None, "sessions_after_restart": len(sessions)}
srv2.stop()

# cancellation cleanup latency (fixture provider so the hang-up is observable exactly)
fake = FakeOllama(models=(JOURNEY_MODEL,), chunks=[f"w{i} " for i in range(40)], reply="x", chunk_delay=0.25); fake.__enter__()
srv3 = LiveServer(Path(tempfile.mkdtemp(prefix="p1cancel-")), extra_env={"ORNEUR_OLLAMA_HOST": fake.host, "OLLAMA_HOST": fake.host}); srv3.wait_ready()
uc = User(srv3.base, "cancel"); lat = []
for _ in range(8):
    a0 = fake.stream_aborts; n = 0
    with uc.http.stream("POST", "/api/stream", json={"message": "long story", "model_variant": "core"}, headers={**uc.headers, "Idempotency-Key": os.urandom(8).hex()}) as r:
        for line in r.iter_lines():
            if line.startswith("data: ") and json.loads(line[6:]).get("type") == "chunk":
                n += 1
                if n == 3: break
    th = time.time()
    while fake.stream_aborts == a0 and time.time() - th < 10: time.sleep(0.01)
    lat.append(time.time() - th)
res["cancellation_provider_hangup_latency_s"] = stats(lat)
res["cancellation_leak_check"] = {"provider_streams_open_after": fake.streams_open, "server_fds": proc_info(srv3.proc.pid)["fds"]}
srv3.stop(); fake.__exit__(None, None, None)

# browser load timings (real Chromium)
tools = Path(os.environ.get("ORNEUR_JOURNEY_TOOLS", "/home/pc/projects/.journey-tools"))
srv4 = LiveServer(Path(tempfile.mkdtemp(prefix="p1load-"))); srv4.wait_ready()
code = f'''
import json
from playwright.sync_api import sync_playwright
out=[]
with sync_playwright() as pw:
    b=pw.chromium.launch()
    for i in range(10):
        c=b.new_context(viewport={{"width":1280,"height":800}}); p=c.new_page()
        p.goto("{srv4.base}/conversation"); p.wait_for_selector("#si-email",state="visible")
        t=p.evaluate("()=>{{const n=performance.getEntriesByType('navigation')[0];return {{dcl:n.domContentLoadedEventEnd,load:n.loadEventEnd,transfer:n.transferSize,interactive:performance.now()}}}}")
        out.append(t); c.close()
    b.close()
print(json.dumps(out))
'''
py = tools / ".venv/bin/python"; libs = tools / "libs/usr/lib/x86_64-linux-gnu"
r = subprocess.run([str(py), "-c", code], capture_output=True, text=True, env=dict(os.environ, LD_LIBRARY_PATH=f"{libs}:{os.environ.get('LD_LIBRARY_PATH','')}"), timeout=300)
rows = json.loads(r.stdout.strip().splitlines()[-1])
res["browser_initial_load_ms"] = {"n": len(rows), "domcontentloaded": stats([x["dcl"] for x in rows]), "load": stats([x["load"] for x in rows]), "signin_form_visible": stats([x["interactive"] for x in rows]), "html_bytes": rows[0]["transfer"]}
srv4.stop()
json.dump(res, open(OUT, "w"), indent=1)
print(json.dumps(res, indent=1))
