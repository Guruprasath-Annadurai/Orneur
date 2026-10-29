"""A tiny controllable Ollama stand-in for end-to-end *lifecycle* tests.

It is a TEST DOUBLE: it proves how ORNEUR's own request path (routing, sessions, streaming, errors, limits, storage) behaves around a model. It says
nothing about any model's quality or capability, and nothing here may be presented as a working model.
"""
from __future__ import annotations

import json
import threading
import time
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer


class FakeOllama:
    def __init__(self, models=("orca-nano", "orca-core", "orca-ultra"), reply="FAKE-REPLY", chunks=("FAKE-", "REPLY"), chunk_delay=0.0):
        self.models = list(models)
        self._reply = reply
        self.chunks = list(chunks)
        self.chunk_delay = chunk_delay
        self.fail_status: int | None = None          # when set, /api/chat answers with this HTTP status
        self.requests: list[dict] = []                # every /api/chat payload received
        self.chunks_sent = 0
        self.malformed = False                        # answer /api/chat with a 200 whose body is not Ollama JSON at all
        self.truncate_after: int | None = None        # streaming only: hang up after N chunks WITHOUT the final {"done": true} line
        self.pre_response_delay = 0.0                 # seconds to hold EVERY /api/chat request before answering (slow-generation scenarios)
        self.stream_aborted = threading.Event()       # set when a client hangs up mid-stream
        fake = self

        class H(BaseHTTPRequestHandler):
            protocol_version = "HTTP/1.1"

            def log_message(self, *a):
                pass

            def _json(self, status, body):
                data = json.dumps(body).encode()
                self.send_response(status)
                self.send_header("Content-Type", "application/json")
                self.send_header("Content-Length", str(len(data)))
                self.end_headers()
                self.wfile.write(data)

            def do_GET(self):
                if self.path == "/api/tags":
                    return self._json(200, {"models": [{"name": m, "digest": "sha256:" + "ab" * 32} for m in fake.models]})
                self._json(404, {"error": "not found"})

            def do_POST(self):
                payload = json.loads(self.rfile.read(int(self.headers.get("Content-Length", 0))) or b"{}")
                if self.path != "/api/chat":
                    return self._json(404, {"error": "not found"})
                fake.requests.append(payload)
                if fake.pre_response_delay:
                    time.sleep(fake.pre_response_delay)
                if fake.fail_status:
                    return self._json(fake.fail_status, {"error": "fake backend failure"})
                if fake.malformed:
                    junk = b"<html>this is not ollama</html>"
                    self.send_response(200)
                    self.send_header("Content-Type", "text/html")
                    self.send_header("Content-Length", str(len(junk)))
                    self.end_headers()
                    self.wfile.write(junk)
                    return
                model = payload.get("model", "orca-core")
                if not payload.get("stream", True):
                    return self._json(200, {"model": model, "message": {"role": "assistant", "content": fake.reply}, "done": True,
                                            "prompt_eval_count": 7, "eval_count": 3})
                self.send_response(200)
                self.send_header("Content-Type", "application/x-ndjson")
                self.send_header("Transfer-Encoding", "chunked")
                self.end_headers()
                try:
                    for n, piece in enumerate(fake.chunks):
                        if fake.truncate_after is not None and n >= fake.truncate_after:
                            self.close_connection = True
                            return
                        line = json.dumps({"model": model, "message": {"role": "assistant", "content": piece}, "done": False}).encode() + b"\n"
                        self.wfile.write(f"{len(line):x}\r\n".encode() + line + b"\r\n")
                        self.wfile.flush()
                        fake.chunks_sent += 1
                        time.sleep(fake.chunk_delay)
                    last = json.dumps({"model": model, "message": {"role": "assistant", "content": ""}, "done": True, "prompt_eval_count": 7, "eval_count": 3}).encode() + b"\n"
                    self.wfile.write(f"{len(last):x}\r\n".encode() + last + b"\r\n0\r\n\r\n")
                    self.wfile.flush()
                except (BrokenPipeError, ConnectionResetError):
                    fake.stream_aborted.set()

        self._srv = ThreadingHTTPServer(("127.0.0.1", 0), H)
        self._srv.daemon_threads = True
        self.host = f"http://127.0.0.1:{self._srv.server_address[1]}"
        self._t = threading.Thread(target=self._srv.serve_forever, daemon=True)

    @property
    def reply(self) -> str:
        return self._reply

    @reply.setter
    def reply(self, value: str) -> None:
        """Keep stream chunks coherent: Kernel-direct /api/stream (B-01) reads
        ``chunks`` via ModelGateway.stream(), while generate() reads ``reply``.
        Tests that only assign ``.reply`` must still observe that text on stream."""
        self._reply = value
        self.chunks = [value]

    def __enter__(self):
        self._t.start()
        return self

    def __exit__(self, *a):
        self._srv.shutdown()
        self._srv.server_close()


def point_orneur_at(fake: "FakeOllama", monkeypatch) -> None:
    """Make every module's CONFIG (the test fixture reloads orca.config, so modules hold different copies) and every cached runtime use the fake."""
    import sys

    seen = set()
    for name, mod in list(sys.modules.items()):
        if not name.startswith("orca") or mod is None:
            continue
        cfg = getattr(mod, "CONFIG", None)
        ollama = getattr(cfg, "ollama", None)
        if ollama is not None and id(ollama) not in seen and hasattr(ollama, "host"):
            seen.add(id(ollama))
            monkeypatch.setattr(ollama, "host", fake.host)
    import orca.serve.registry as reg
    from orca.cognitive import wiring as cwiring
    from orca.gateway import wiring as gwiring

    monkeypatch.setattr(reg, "_tags_cache", None)
    gwiring.reset_for_tests()
    cwiring.reset_for_tests()
