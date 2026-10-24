"""Cancellation is published only after the upstream close has returned.

The known-bad harness below is the old loop order: it stores `cancelled`
while still inside the upstream close. The product tests drive the real
stream route, `aiter_blocking`, and `ModelGateway` against a local HTTP
server.
"""
from __future__ import annotations

import asyncio
import contextlib
import json
import threading
import time
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from types import SimpleNamespace
from unittest.mock import MagicMock

import pytest

from orca.gateway.contracts import InferenceChunk, InferenceRequest
from orca.gateway.deployment import DeploymentHealth
from orca.gateway.gateway import ModelGateway, TimeoutPolicy
from orca.gateway.ollama_runtime import OllamaRuntime
from orca.registry.model_spec import LifecycleState
from orca.serve import api as api_module
from orca.serve import generations
from orca.serve.streaming import aiter_blocking
from tests.test_api_chat_frontier_passthrough import _fake_cognitive_result
from tests.test_gateway_model_gateway import _deployment


class _Probe:
    def __init__(self, *, fail: bool = False):
        self.fail = fail
        self.generation_id = None
        self.saw_state = None
        self.closed = threading.Event()
        self.n = 0

    def __iter__(self):
        return self

    def __next__(self):
        self.n += 1
        if self.n > 4:
            raise StopIteration
        time.sleep(0.02)
        return f"token-{self.n} "

    def close(self):
        if self.generation_id:
            record = generations.read(self.generation_id)
            self.saw_state = None if record is None else record.get("state")
        self.closed.set()
        if self.fail:
            raise RuntimeError("upstream close failed")


def _install_stream(monkeypatch, probe: _Probe):
    monkeypatch.setattr(api_module, "_get_session", lambda *a, **k: _session(probe))
    monkeypatch.setattr(api_module, "check_input", lambda text: MagicMock(action="allow", flagged_categories=[]))

    async def not_direct(message, user, model_variant, session_id=None, **kwargs):
        result = await _fake_cognitive_result(message, user, model_variant, session_id, **kwargs)
        result.output = None
        return result

    monkeypatch.setattr(api_module, "_run_cognitive_kernel", not_direct)
    monkeypatch.setattr(
        api_module,
        "_resolve_backend_for_chat",
        lambda variant: SimpleNamespace(
            backend="ollama", tier="core", model="m", data_left_infrastructure=False, sovereignty_overridden=False
        ),
    )
    monkeypatch.setattr(api_module, "_apply_cost_aware_routing", lambda res, msg: (res, SimpleNamespace(escalated=False, reason="")))
    monkeypatch.setattr(api_module, "_record_shadow_verification", lambda *a, **k: None)


def _session(probe: _Probe):
    trace = SimpleNamespace(plan_action="direct", tool_calls=[], citation_compliance=None)
    agent = SimpleNamespace(stream=lambda enriched, persona: (iter(probe), trace))
    memory = MagicMock()
    memory.recall_context.return_value = ""
    memory.add_turn = lambda *a, **k: None
    memory.short._messages = []
    doc_store = MagicMock()
    doc_store.count.return_value = 0
    return SimpleNamespace(
        id="s-closure-1",
        model_variant="nano",
        memory=memory,
        doc_store=doc_store,
        agent=agent,
        explain_store=MagicMock(),
        knowledge_graph=MagicMock(),
        brain=MagicMock(),
        persist_to_redis=lambda: None,
        _agent=None,
    )


def _drive(probe: _Probe, *, cancel: bool, disconnect_after_chunk: bool = False) -> dict:
    captured = {"id": None, "terminal": None, "chunks": [], "done": False}

    async def drive():
        body = {"message": "Stream this prompt", "session_id": "s-closure-1", "model_variant": "nano"}
        scope = {
            "type": "http",
            "method": "POST",
            "path": "/api/stream",
            "raw_path": b"/api/stream",
            "query_string": b"",
            "headers": [
                (b"content-type", b"application/json"),
                (b"host", b"test"),
                (b"idempotency-key", b"exact-order-stop-01"),
            ],
            "client": ("127.0.0.1", 1234),
            "server": ("test", 80),
            "scheme": "http",
            "http_version": "1.1",
            "root_path": "",
        }
        sent = False
        released = asyncio.Event()

        async def receive():
            nonlocal sent
            if not sent:
                sent = True
                return {"type": "http.request", "body": json.dumps(body).encode(), "more_body": False}
            if disconnect_after_chunk:
                await released.wait()
                return {"type": "http.disconnect"}
            await asyncio.sleep(10)
            return {"type": "http.disconnect"}

        async def send(msg):
            raw = msg.get("body") or b""
            for line in raw.decode("utf-8", errors="replace").splitlines():
                if not line.startswith("data:"):
                    continue
                try:
                    event = json.loads(line[5:].strip())
                except json.JSONDecodeError:
                    continue
                if event.get("type") == "generation" and captured["id"] is None:
                    captured["id"] = event.get("generation_id")
                    probe.generation_id = captured["id"]
                elif event.get("type") == "generation" and event.get("state") != "running":
                    captured["terminal"] = event
                elif event.get("type") == "chunk":
                    captured["chunks"].append(event.get("text"))
                    if len(captured["chunks"]) == 1 and cancel and captured["id"]:
                        generations.request_cancel(captured["id"])
                    if len(captured["chunks"]) == 1 and disconnect_after_chunk:
                        released.set()
                elif event.get("type") == "done":
                    captured["done"] = True

        await api_module.app(scope, receive, send)

    asyncio.run(drive())
    return captured


def test_known_bad_pattern_publishes_cancelled_before_close(tmp_path, monkeypatch):
    import orca.brain.memory as mem

    monkeypatch.setattr(mem, "MEMORY_DIR", tmp_path)
    record, _created = generations.begin(session_id="sess-a", user_id="user-a", delivery="upstream", cancellable=True)
    generations.request_cancel(record["generation_id"])
    probe = _Probe()
    probe.generation_id = record["generation_id"]

    async def bad():
        async with contextlib.aclosing(aiter_blocking(iter(probe))) as chunks:
            await chunks.__anext__()
            generations.end_worker(record["generation_id"], upstream="stopped")
            return

    asyncio.run(bad())
    assert probe.saw_state == "cancelled"
    assert generations.read(record["generation_id"])["state"] == "cancelled"


def test_product_stop_publishes_cancelled_only_after_close_returns(tmp_path, monkeypatch):
    import orca.brain.memory as mem

    monkeypatch.setattr(mem, "MEMORY_DIR", tmp_path)
    probe = _Probe()
    _install_stream(monkeypatch, probe)
    captured = _drive(probe, cancel=True)
    assert probe.closed.is_set()
    assert probe.saw_state == "running"
    assert captured["terminal"]["state"] == "cancelled"
    assert captured["terminal"]["reason"] == "cancel_requested"
    assert captured["done"] is False
    stored = generations.read(captured["id"])
    assert stored["state"] == "cancelled"
    assert stored["upstream"] == "stopped"
    assert stored["upstream_closure"] == "closed"
    assert stored["state"] == captured["terminal"]["state"]


def test_failed_close_stays_unknown_after_an_authenticated_stop(tmp_path, monkeypatch):
    import orca.brain.memory as mem

    monkeypatch.setattr(mem, "MEMORY_DIR", tmp_path)
    probe = _Probe(fail=True)
    _install_stream(monkeypatch, probe)
    captured = _drive(probe, cancel=True)
    assert probe.saw_state == "running"
    stored = generations.read(captured["id"])
    assert stored["state"] == "interrupted_unknown"
    assert stored["cancel_requested"] is True
    assert stored["upstream"] == "unconfirmed"
    assert stored["upstream_closure"] == "close_failed"
    assert captured["terminal"]["state"] == "interrupted_unknown"
    assert captured["done"] is False


def test_disconnect_without_a_stop_is_not_cancelled_even_when_close_returns(tmp_path, monkeypatch):
    import orca.brain.memory as mem

    monkeypatch.setattr(mem, "MEMORY_DIR", tmp_path)
    probe = _Probe()
    _install_stream(monkeypatch, probe)
    captured = _drive(probe, cancel=False, disconnect_after_chunk=True)
    stored = generations.read(captured["id"])
    assert stored["state"] == "interrupted_unknown"
    assert stored["cancel_requested"] is False
    assert stored["upstream"] == "stopped"
    promoted = generations.request_cancel(captured["id"])
    assert promoted["state"] == "cancelled"
    assert promoted["code"] == "cancel_confirmed"


def test_deferred_close_is_not_confirmed_while_a_read_is_in_flight():
    class Hang:
        def __init__(self):
            self.release = threading.Event()
            self.entered = threading.Event()
            self.closed = False

        def __iter__(self):
            return self

        def __next__(self):
            self.entered.set()
            self.release.wait(2)
            return "late"

        def close(self):
            self.closed = True

    hang = Hang()
    box = {}

    async def go():
        agen = aiter_blocking(hang, box)
        task = asyncio.create_task(agen.__anext__())
        for _ in range(200):
            if hang.entered.is_set():
                break
            await asyncio.sleep(0.01)
        assert hang.entered.is_set()
        task.cancel()
        with pytest.raises(asyncio.CancelledError):
            await task
        await agen.aclose()

    asyncio.run(go())
    assert box["confirmed"] is False
    assert box["reason"] == "close_deferred_until_inflight_read_returns"
    assert hang.closed is False
    hang.release.set()


def test_gateway_close_is_confirmed_only_after_the_local_http_stream_is_closed():
    closed = threading.Event()
    started = threading.Event()

    class Handler(BaseHTTPRequestHandler):
        protocol_version = "HTTP/1.1"

        def do_POST(self):
            length = int(self.headers.get("Content-Length") or 0)
            if length:
                self.rfile.read(length)
            payload = b'{"message":{"content":"one"},"done":false}\n'
            self.send_response(200)
            self.send_header("Content-Type", "application/x-ndjson")
            self.send_header("Transfer-Encoding", "chunked")
            self.end_headers()
            try:
                self.wfile.write(f"{len(payload):x}\r\n".encode() + payload + b"\r\n")
                self.wfile.flush()
                started.set()
                self.connection.settimeout(3)
                extra = self.rfile.read(1)
                if extra == b"":
                    closed.set()
            except Exception:
                closed.set()

        def log_message(self, fmt, *args):
            return

    server = ThreadingHTTPServer(("127.0.0.1", 0), Handler)
    thread = threading.Thread(target=server.serve_forever, daemon=True)
    thread.start()
    try:
        host = f"http://127.0.0.1:{server.server_address[1]}"
        runtime = OllamaRuntime(host=host, timeout_s=5)
        gateway = ModelGateway(timeout_policy=TimeoutPolicy(
            first_token_timeout_s=2, stream_idle_timeout_s=2, total_request_timeout_s=5
        ))
        gateway.register_runtime("ollama", runtime)
        gateway.register_deployment(_deployment(
            deployment_id="dep-closure-http",
            runtime="ollama",
            runtime_endpoint=host,
            lifecycle=LifecycleState.PRODUCTION.value,
            health=DeploymentHealth.READY.value,
            warmup_completed=True,
        ))
        request = InferenceRequest(request_id="req-closure-http", model_id="orneur-novus", messages=[{"role": "user", "content": "hi"}], max_tokens=16)

        async def consume():
            async with contextlib.aclosing(gateway.stream(request, allow_experimental=True)) as chunks:
                first = await chunks.__anext__()
                assert first.delta == "one"
                return

        asyncio.run(consume())
        assert request.metadata["upstream_closure"]["confirmed"] is True
        assert request.metadata["upstream_closure"]["reason"] == "closed"
        assert closed.wait(2)
        assert started.is_set()
    finally:
        server.shutdown()
        thread.join(timeout=3)


def test_gateway_close_failure_is_not_confirmed():
    class Broken:
        name = "broken"

        async def stream(self, request):
            try:
                yield InferenceChunk(request_id=request.request_id, sequence=0, delta="x", finish_reason=None)
                await asyncio.sleep(30)
            finally:
                raise RuntimeError("upstream close failed")

        async def cancel(self, request_id: str) -> bool:
            return True

    gateway = ModelGateway()
    gateway.register_runtime("broken", Broken())
    gateway.register_deployment(_deployment(
        deployment_id="dep-closure-broken",
        runtime="broken",
        lifecycle=LifecycleState.PRODUCTION.value,
        health=DeploymentHealth.READY.value,
        warmup_completed=True,
    ))
    request = InferenceRequest(request_id="req-closure-broken", model_id="orneur-novus", messages=[{"role": "user", "content": "hi"}], max_tokens=16)

    async def consume():
        async with contextlib.aclosing(gateway.stream(request, allow_experimental=True)) as chunks:
            await chunks.__anext__()

    asyncio.run(consume())
    assert request.metadata["upstream_closure"]["confirmed"] is False
    assert request.metadata["upstream_closure"]["reason"] == "close_failed"
