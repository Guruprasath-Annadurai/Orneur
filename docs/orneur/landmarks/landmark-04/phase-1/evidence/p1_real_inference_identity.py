"""Real inference identity probe: browser-equivalent request -> ORNEUR -> recording tap -> REAL Ollama. Prints requested model, served model, first-token time, and the disclosed identity."""
import json, os, sys, tempfile, time
from pathlib import Path
sys.path.insert(0, ".")
import httpx
from tests.journey.harness import OllamaTap, LiveServer, User, JOURNEY_MODEL
tap = OllamaTap()
srv = LiveServer(Path(tempfile.mkdtemp(prefix="p1id-")), extra_env={"ORNEUR_OLLAMA_HOST": tap.url, "OLLAMA_HOST": tap.url}); srv.wait_ready()
u = User(srv.base, "ident")
tags = httpx.get("http://localhost:11434/api/tags").json()["models"]
n0 = len(tap.requests)
s, ev = u.stream("What is 12 times 12? Answer with just the number.")
done = [e for e in ev if e["type"] == "done"][-1]
s2, ev2 = u.stream("Now add 6 to that.", session_id=[e for e in ev if e["type"] == "session"][0]["session_id"])
reqs = tap.requests[n0:]
out = {"ollama_model_installed": [t["name"] for t in tags if t["name"] == JOURNEY_MODEL or t["name"].startswith(JOURNEY_MODEL)],
       "requested_model_sent_to_provider": sorted({r["body"].get("model") for r in reqs}), "provider_calls_for_two_turns": len(reqs),
       "provider_http_paths": sorted({r.get("path", "?") for r in reqs}),
       "turn1_answer": "".join(e.get("text", "") for e in ev if e["type"] == "chunk")[:120], "turn2_answer": "".join(e.get("text", "") for e in ev2 if e["type"] == "chunk")[:160],
       "turn2_request_carried_turn1": any("12 times 12" in c for c in tap.answer_contexts("Now add 6 to that.", since=n0)),
       "disclosed_model_identity": done.get("model_identity"), "delivery": done.get("delivery"), "persisted": done.get("persisted")}
print(json.dumps(out, indent=1)); json.dump(out, open(sys.argv[1], "w"), indent=1)
srv.stop(); tap.close()
