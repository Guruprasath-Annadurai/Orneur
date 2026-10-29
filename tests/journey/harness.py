"""Harness for the first real chatbot journey (A-F).

Everything here talks to a REAL ``orca serve`` process over HTTP, with a REAL
Ollama behind it. Nothing is patched in-process, no fake model backend.

Evidence classes (every journey test states exactly one in its docstring):

  LIVE_API   real server subprocess + real Ollama, driven over HTTP (httpx)
  BROWSER    real Chromium (Playwright) driving the approved /conversation page
             against that same real server + real Ollama
  MOCKED     in-process TestClient and/or FakeOllama (NOT used in this folder;
             listed so the journey report can contrast it with the existing suite)

A capability that is missing makes the test FAIL with a message naming the
capability. Nothing here skips: a skipped journey step reads as green.
"""
from __future__ import annotations

import json
import os
import socket
import subprocess
import sys
import time
import urllib.error
import urllib.request
import uuid
from contextlib import contextmanager
from pathlib import Path

import httpx

REPO = Path(__file__).resolve().parents[2]
OLLAMA_HOST = os.environ.get("ORNEUR_JOURNEY_OLLAMA_HOST", "http://localhost:11434")
# Ollama tag the journey serves. A bare name (resolves to ``<name>:latest``) is
# used because colon-bearing tags currently crash the gateway (see
# test_blocker_colon_tags_stream in test_journey_api_live.py).
JOURNEY_MODEL = os.environ.get("ORNEUR_JOURNEY_MODEL", "orneur-journey")
JOURNEY_PASSWORD = "Journey-Pass-91x"


class CapabilityMissing(AssertionError):
    """Raised (as a test FAILURE, never a skip) when the journey cannot run."""


def require_ollama() -> None:
    try:
        tags = json.load(urllib.request.urlopen(f"{OLLAMA_HOST}/api/tags", timeout=5))["models"]
    except Exception as exc:
        raise CapabilityMissing(f"capability missing: Ollama not reachable at {OLLAMA_HOST} ({exc!r})")
    names = {m["name"] for m in tags}
    if f"{JOURNEY_MODEL}:latest" not in names and JOURNEY_MODEL not in names:
        raise CapabilityMissing(
            f"capability missing: Ollama has no model '{JOURNEY_MODEL}'. Create a local alias (no download): "
            f"`ollama cp llama3.2:1b {JOURNEY_MODEL}`. Installed: {sorted(names)}"
        )


def _free_port() -> int:
    with socket.socket() as s:
        s.bind(("127.0.0.1", 0))
        return s.getsockname()[1]


class LiveServer:
    """The canonical entry point: ``python -m orca.cli serve`` (== ``orca serve``,
    the Dockerfile CMD), i.e. uvicorn over ``orca.serve.api.create_app()``."""

    def __init__(self, home: Path, *, redis_url: str | None = None, extra_env: dict | None = None):
        self.home = home
        self.port = _free_port()
        self.base = f"http://127.0.0.1:{self.port}"
        env = dict(os.environ)
        for k in list(env):  # a clean, isolated deployment: no inherited ORNEUR_/ORCA_ state
            if k.startswith(("ORNEUR_", "ORCA_")):
                del env[k]
        env.update({
            "ORNEUR_HOME": str(home),
            "ORNEUR_CORE_MODEL": JOURNEY_MODEL, "ORNEUR_NANO_MODEL": JOURNEY_MODEL, "ORNEUR_ULTRA_MODEL": JOURNEY_MODEL,
            "ORNEUR_OLLAMA_HOST": OLLAMA_HOST, "OLLAMA_HOST": OLLAMA_HOST,
            "PYTHONPATH": str(REPO),
        })
        if redis_url:
            env["ORNEUR_REDIS_URL"] = redis_url
        env.update(extra_env or {})
        self.log_path = home / "server.log"
        self._log = open(self.log_path, "wb")
        self.proc = subprocess.Popen(
            [sys.executable, "-m", "orca.cli", "serve", "--host", "127.0.0.1", "--port", str(self.port), "--no-open"],
            cwd=REPO, env=env, stdout=self._log, stderr=subprocess.STDOUT,
        )

    def wait_ready(self, timeout: float = 180.0) -> None:
        end = time.time() + timeout
        while time.time() < end:
            if self.proc.poll() is not None:
                raise CapabilityMissing(f"server exited early (code {self.proc.returncode}); see {self.log_path}")
            try:
                if httpx.get(f"{self.base}/livez", timeout=2).status_code == 200:
                    return
            except httpx.HTTPError:
                time.sleep(0.5)
        raise CapabilityMissing(f"server not live within {timeout}s; see {self.log_path}")

    def stop(self) -> None:
        self.proc.terminate()
        try:
            self.proc.wait(timeout=15)
        except subprocess.TimeoutExpired:
            self.proc.kill()
        self._log.close()

    def log_tail(self, n: int = 40) -> str:
        return "\n".join(self.log_path.read_text(errors="replace").splitlines()[-n:])


@contextmanager
def live_server(home: Path, **kw):
    require_ollama()
    srv = LiveServer(home, **kw)
    try:
        srv.wait_ready()
        yield srv
    finally:
        srv.stop()


class User:
    """A signed-up account driving the server over real HTTP."""

    def __init__(self, base: str, label: str):
        self.base = base
        self.email = f"{label}-{uuid.uuid4().hex[:8]}@example.com"
        self.http = httpx.Client(base_url=base, timeout=180)
        r = self.http.post("/api/auth/signup", json={"email": self.email, "password": JOURNEY_PASSWORD, "name": label})
        r.raise_for_status()
        self.token = None
        self.login()

    def login(self) -> str:
        r = self.http.post("/api/auth/login", json={"email": self.email, "password": JOURNEY_PASSWORD})
        r.raise_for_status()
        self.token = r.json()["token"]
        return self.token

    @property
    def headers(self) -> dict:
        return {"Authorization": f"Bearer {self.token}"}

    def stream(self, message: str, session_id: str | None = None, *, token: str | None = None, **extra):
        """POST /api/stream exactly as conversation.html does. Returns (status, events)."""
        headers = {"Authorization": f"Bearer {token or self.token}", "Idempotency-Key": str(uuid.uuid4())}
        body = {"message": message, "session_id": session_id, "model_variant": "core", **extra}
        events: list[dict] = []
        with self.http.stream("POST", "/api/stream", json=body, headers=headers) as resp:
            if resp.status_code != 200 or "text/event-stream" not in resp.headers.get("content-type", ""):
                resp.read()
                return resp.status_code, [{"type": "http_body", "body": resp.text[:500]}]
            for line in resp.iter_lines():
                if line.startswith("data: "):
                    events.append(json.loads(line[6:]))
        return 200, events

    def get(self, path: str, **kw):
        return self.http.get(path, headers=self.headers, **kw)

    def post(self, path: str, **kw):
        return self.http.post(path, headers=self.headers, **kw)


def answer_of(events: list[dict]) -> str:
    done = [e for e in events if e.get("type") == "done"]
    if done and done[-1].get("response"):
        return done[-1]["response"]
    return "".join(e.get("text", "") for e in events if e.get("type") == "chunk")


def session_id_of(events: list[dict]) -> str:
    return next(e["session_id"] for e in events if e.get("type") == "session")


class OllamaTap:
    """Pass-through recorder between the ORNEUR server and the REAL Ollama.

    It forwards every request unchanged (streaming included) and records the
    JSON body of each ``/api/chat`` and ``/api/generate`` call. This gives
    evidence of what conversation context the model was actually *sent*,
    independent of what a 1B model happens to say. It is not an inference
    runtime and never answers a request itself.
    """

    def __init__(self, upstream: str = OLLAMA_HOST):
        import threading
        from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer

        self.upstream = upstream.rstrip("/")
        self.requests: list[dict] = []
        self.relayed_lines = 0          # NDJSON lines (generated pieces) relayed from Ollama to ORNEUR
        self.client_aborts = 0          # times ORNEUR hung up on a response that was still streaming (evidence that it stopped the model call)
        self.open_streams = 0
        self.embed_calls = 0            # L02: /api/embeddings and /api/embed requests (proof that real embedding weights were used)
        self.abort_log: list[dict] = []
        tap = self

        class H(BaseHTTPRequestHandler):
            protocol_version = "HTTP/1.1"

            def log_message(self, *a):
                pass

            def _forward(self):
                n = int(self.headers.get("content-length") or 0)
                body = self.rfile.read(n) if n else None
                if self.command == "POST" and self.path in ("/api/embeddings", "/api/embed"):
                    tap.embed_calls += 1
                if self.command == "POST" and self.path in ("/api/chat", "/api/generate") and body:
                    try:
                        tap.requests.append({"path": self.path, "body": json.loads(body)})
                    except ValueError:
                        pass
                req = urllib.request.Request(tap.upstream + self.path, data=body, method=self.command,
                                             headers={"Content-Type": self.headers.get("Content-Type", "application/json")})
                try:
                    resp = urllib.request.urlopen(req, timeout=300)
                    status, headers = resp.status, resp.headers
                except urllib.error.HTTPError as e:
                    resp, status, headers = e, e.code, e.headers
                self.send_response(status)
                self.send_header("Content-Type", headers.get("Content-Type", "application/json"))
                self.send_header("Transfer-Encoding", "chunked")
                self.end_headers()
                tap.open_streams += 1
                try:
                    while True:
                        chunk = resp.read1(65536) if hasattr(resp, "read1") else resp.read(65536)
                        if not chunk:
                            break
                        tap.relayed_lines += chunk.count(b"\n")
                        self.wfile.write(f"{len(chunk):x}\r\n".encode() + chunk + b"\r\n")
                        self.wfile.flush()
                    self.wfile.write(b"0\r\n\r\n")
                except (BrokenPipeError, ConnectionResetError):
                    # ORNEUR closed its connection while Ollama was still generating. Closing the upstream response here is what tells Ollama to stop.
                    tap.client_aborts += 1
                    tap.abort_log.append({"at": time.time(), "lines_relayed": tap.relayed_lines})
                    try:
                        resp.close()
                    except Exception:
                        pass
                finally:
                    tap.open_streams -= 1

            do_GET = do_POST = do_DELETE = _forward

        self._srv = ThreadingHTTPServer(("127.0.0.1", 0), H)
        self.url = f"http://127.0.0.1:{self._srv.server_address[1]}"
        threading.Thread(target=self._srv.serve_forever, daemon=True).start()

    def close(self):
        self._srv.shutdown()

    def answer_contexts(self, prompt: str, since: int = 0) -> list[str]:
        """Flattened messages of the model call(s) that ANSWER ``prompt`` (final user message ==
        prompt). Excludes side calls such as knowledge-graph extraction, which quote earlier
        turns and would make a context assertion pass for the wrong reason."""
        out = []
        for r in self.requests[since:]:
            msgs = r["body"].get("messages") or []
            if msgs and msgs[-1].get("role") == "user" and msgs[-1].get("content", "").strip() == prompt.strip():
                out.append("\n".join(f"{m.get('role')}: {m.get('content')}" for m in msgs))
        return out

    def contexts(self) -> list[str]:
        """Flattened text of each recorded model call's messages/prompt."""
        out = []
        for r in self.requests:
            b = r["body"]
            msgs = b.get("messages")
            out.append("\n".join(f"{m.get('role')}: {m.get('content')}" for m in msgs) if msgs else str(b.get("prompt", "")))
        return out
