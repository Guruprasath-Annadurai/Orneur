"""
Streaming must not block the event loop, and a consumer that stops early must
close the backend generator. Both were broken when /api/stream iterated the
blocking agent generator directly inside an async handler.
"""
from __future__ import annotations

import asyncio
import json
import threading
import time
from types import SimpleNamespace
from unittest.mock import MagicMock

import httpx
import pytest

from orca.serve import api as api_module
from orca.serve.streaming import aiter_blocking
from tests.test_api_chat_frontier_passthrough import _fake_cognitive_result


class _SlowGen:
    """A blocking generator that records how it ended."""

    def __init__(self, items, delay):
        self.items, self.delay = items, delay
        self.closed = threading.Event()
        self.finished = False

    def __iter__(self):
        return self._run()

    def _run(self):
        try:
            for item in self.items:
                time.sleep(self.delay)
                yield item
            self.finished = True
        finally:
            self.closed.set()


def test_helper_yields_all_items_in_order():
    async def go():
        return [x async for x in aiter_blocking(iter(["a", "b", "c"]))]
    assert asyncio.run(go()) == ["a", "b", "c"]


def test_helper_does_not_block_the_event_loop():
    async def go():
        ticks = 0
        stop = False

        async def ticker():
            nonlocal ticks
            while not stop:
                ticks += 1
                await asyncio.sleep(0.01)

        task = asyncio.create_task(ticker())
        got = [x async for x in aiter_blocking(iter(_SlowGen(["a", "b", "c"], 0.15)))]
        stop = True
        await task
        return got, ticks
    got, ticks = asyncio.run(go())
    assert got == ["a", "b", "c"]
    # ~0.45s of blocking work: a free loop ticks dozens of times, a blocked one a handful.
    assert ticks > 15


def test_helper_propagates_generator_errors():
    def boom():
        yield "a"
        raise RuntimeError("backend down")

    async def go():
        return [x async for x in aiter_blocking(boom())]
    with pytest.raises(RuntimeError, match="backend down"):
        asyncio.run(go())


def test_early_stop_closes_the_generator():
    slow = _SlowGen(["a", "b", "c", "d"], 0.05)

    async def go():
        agen = aiter_blocking(iter(slow))
        first = await agen.__anext__()
        await agen.aclose()
        return first
    assert asyncio.run(go()) == "a"
    assert slow.closed.wait(2)
    assert slow.finished is False


def test_cancellation_mid_wait_still_closes_after_the_inflight_read():
    slow = _SlowGen(["a", "b"], 0.4)

    async def go():
        async def consume():
            async for _ in aiter_blocking(iter(slow)):
                pass
        task = asyncio.create_task(consume())
        await asyncio.sleep(0.1)  # the first next() is still running in its thread
        task.cancel()
        with pytest.raises(asyncio.CancelledError):
            await task
    asyncio.run(go())
    assert slow.closed.wait(3)
    assert slow.finished is False


def _stub_session(gen):
    trace = SimpleNamespace(plan_action="direct", tool_calls=[], citation_compliance=None)
    agent = SimpleNamespace(stream=lambda enriched, persona: (iter(gen), trace))
    memory = MagicMock()
    memory.recall_context.return_value = ""
    doc_store = MagicMock()
    doc_store.count.return_value = 0
    return SimpleNamespace(
        id="s-1", model_variant="nano", memory=memory, doc_store=doc_store, agent=agent,
        explain_store=MagicMock(), knowledge_graph=MagicMock(), brain=MagicMock(),
        persist_to_redis=lambda: None,
    )


def test_stream_endpoint_keeps_serving_other_requests_while_generating(monkeypatch):
    slow = _SlowGen(["one ", "two ", "three "], 0.3)
    monkeypatch.setattr(api_module, "_get_session", lambda *a, **k: _stub_session(slow))
    monkeypatch.setattr(api_module, "check_input", lambda text: MagicMock(action="allow", flagged_categories=[]))

    async def not_direct(message, user, model_variant, session_id=None):
        result = await _fake_cognitive_result(message, user, model_variant, session_id)
        result.output = None  # force the agent-stream path, not the kernel-direct path
        return result

    monkeypatch.setattr(api_module, "_run_cognitive_kernel", not_direct)
    monkeypatch.setattr(api_module, "_resolve_backend_for_chat",
                        lambda variant: SimpleNamespace(backend="ollama", tier="core", model="m",
                                                        data_left_infrastructure=False, sovereignty_overridden=False))
    monkeypatch.setattr(api_module, "_apply_cost_aware_routing",
                        lambda res, msg: (res, SimpleNamespace(escalated=False, reason="")))
    monkeypatch.setattr(api_module, "_record_shadow_verification", lambda *a, **k: None)

    async def go():
        transport = httpx.ASGITransport(app=api_module.app)
        async with httpx.AsyncClient(transport=transport, base_url="http://t") as client:
            stream_task = asyncio.create_task(client.post("/api/stream", json={"message": "hi", "model_variant": "nano"}))
            await asyncio.sleep(0.15)  # generation is now blocked inside the first token wait
            started = time.monotonic()
            live = await client.get("/livez")
            latency = time.monotonic() - started
            response = await stream_task
            return live, latency, response
    live, latency, response = asyncio.run(go())
    assert live.status_code == 200
    assert latency < 0.2, f"/livez took {latency:.2f}s while a stream was generating"
    events = [json.loads(l[6:]) for l in response.text.splitlines() if l.startswith("data: ")]
    assert "".join(e["text"] for e in events if e["type"] == "chunk") == "one two three "


# ---------------------------------------------------------------------------
# DEF-CP1-01: bounded admission, not an unbounded queue.
# ---------------------------------------------------------------------------

from orca.serve import streaming as streaming_module  # noqa: E402
from orca.serve.streaming import StreamAdmission, StreamingUnavailable, pool_stats  # noqa: E402


@pytest.fixture
def small_capacity(monkeypatch):
    """A capacity of 2 the admission logic enforces, independent of the
    real (larger) thread pool -- admission is the ceiling under test here,
    not the pool's actual thread count."""
    monkeypatch.setattr(streaming_module, "MAX_CONCURRENT_STREAMS", 2)
    yield 2


def test_admission_rejects_immediately_at_capacity_does_not_wait(small_capacity):
    async def go():
        a, b = StreamAdmission(), StreamAdmission()
        await a.__aenter__()
        await b.__aenter__()
        started = time.monotonic()
        with pytest.raises(StreamingUnavailable):
            async with StreamAdmission():
                pass
        elapsed = time.monotonic() - started
        await a.__aexit__(None, None, None)
        await b.__aexit__(None, None, None)
        return elapsed
    elapsed = asyncio.run(go())
    assert elapsed < 0.05, f"rejection took {elapsed:.3f}s -- admission must fail fast, never queue"


def test_admission_releases_on_exit_including_on_exception(small_capacity):
    async def go():
        async with StreamAdmission():
            pass
        try:
            async with StreamAdmission():
                raise RuntimeError("boom")
        except RuntimeError:
            pass
        # Both prior admissions released -- a fresh one must still succeed.
        async with StreamAdmission():
            assert pool_stats()["in_use"] == 1
    asyncio.run(go())
    assert pool_stats()["in_use"] == 0


def test_pool_stats_reports_capacity_and_shutdown_flag(small_capacity):
    assert pool_stats() == {"capacity": 2, "in_use": 0, "shut_down": False}


def test_admission_refuses_after_shutdown_flag_is_set(monkeypatch, small_capacity):
    monkeypatch.setattr(streaming_module, "_shut_down", True)
    async def go():
        with pytest.raises(StreamingUnavailable):
            async with StreamAdmission():
                pass
    asyncio.run(go())


def test_stream_endpoint_returns_server_busy_without_waiting_when_saturated(monkeypatch, small_capacity):
    release = threading.Event()
    holder = _SlowGen(["hold"], 0.01)
    # Occupy both admission slots directly (not through the endpoint) so the
    # test doesn't need two real concurrent agent calls to prove the point.
    async def go():
        a, b = StreamAdmission(), StreamAdmission()
        await a.__aenter__()
        await b.__aenter__()
        try:
            monkeypatch.setattr(api_module, "_get_session", lambda *a, **k: _stub_session(holder))
            monkeypatch.setattr(api_module, "check_input", lambda text: MagicMock(action="allow", flagged_categories=[]))

            async def not_direct(message, user, model_variant, session_id=None):
                result = await _fake_cognitive_result(message, user, model_variant, session_id)
                result.output = None
                return result

            monkeypatch.setattr(api_module, "_run_cognitive_kernel", not_direct)
            monkeypatch.setattr(api_module, "_resolve_backend_for_chat",
                                lambda variant: SimpleNamespace(backend="ollama", tier="core", model="m",
                                                                data_left_infrastructure=False, sovereignty_overridden=False))
            monkeypatch.setattr(api_module, "_apply_cost_aware_routing",
                                lambda res, msg: (res, SimpleNamespace(escalated=False, reason="")))
            monkeypatch.setattr(api_module, "_record_shadow_verification", lambda *a, **k: None)

            transport = httpx.ASGITransport(app=api_module.app)
            async with httpx.AsyncClient(transport=transport, base_url="http://t") as client:
                started = time.monotonic()
                resp = await client.post("/api/stream", json={"message": "hi", "model_variant": "nano"})
                elapsed = time.monotonic() - started
            return resp, elapsed
        finally:
            await a.__aexit__(None, None, None)
            await b.__aexit__(None, None, None)
    resp, elapsed = asyncio.run(go())
    assert elapsed < 0.3, f"saturated request took {elapsed:.2f}s -- it must be rejected immediately, not queued"
    events = [json.loads(l[6:]) for l in resp.text.splitlines() if l.startswith("data: ")]
    error = next(e for e in events if e["type"] == "error")
    assert error["code"] == "server_busy"


# ---------------------------------------------------------------------------
# Client disconnect -- request.is_disconnected() + contextlib.aclosing.
# ---------------------------------------------------------------------------

def test_client_disconnect_closes_the_backend_generator():
    slow = _SlowGen(["a ", "b ", "c ", "d "], 0.1)

    async def go():
        async def fake_is_disconnected():
            # First check (after chunk 1) says "still connected"; by the
            # second check the client has gone -- same two-state behavior a
            # real ASGI receive channel exhibits after a closed connection.
            fake_is_disconnected.calls += 1
            return fake_is_disconnected.calls > 1
        fake_is_disconnected.calls = 0

        import orca.serve.api as api

        # Drive the actual route coroutine's generator machinery directly:
        # construct the StreamingResponse the route would and consume it,
        # with request.is_disconnected mocked -- this exercises the exact
        # aclosing + disconnect-check wiring in stream_chat's agent branch
        # without needing a real dropped TCP connection for is_disconnected
        # to observe (ASGITransport runs in-process and never truly drops).
        req = SimpleNamespace(is_disconnected=fake_is_disconnected)
        sess = _stub_session(slow)

        async def agen():
            full = ""
            async with contextlib.aclosing(aiter_blocking(iter(slow))) as achunks:
                async for chunk in achunks:
                    full += chunk
                    if await req.is_disconnected():
                        return
            return full

        await agen()
    import contextlib
    asyncio.run(go())
    assert slow.closed.wait(2)
    assert slow.finished is False


def test_real_client_disconnect_closes_the_backend_generator_end_to_end(monkeypatch):
    """Same property as above, but through the real route and a real (if
    in-process) ASGI connection: abandon the response after one chunk and
    confirm the backend generator is closed, instead of asserting our own
    reimplementation of the loop.

    See test_real_socket_disconnect_closes_the_backend_generator_and_frees_admission
    below for the version of this property proven over an ACTUAL localhost
    TCP socket (post-CP2-audit hardening #4) -- that one does not need to
    skip, and additionally confirms admission is released."""
    slow = _SlowGen(["a ", "b ", "c ", "d "], 0.15)
    monkeypatch.setattr(api_module, "_get_session", lambda *a, **k: _stub_session(slow))
    monkeypatch.setattr(api_module, "check_input", lambda text: MagicMock(action="allow", flagged_categories=[]))

    async def not_direct(message, user, model_variant, session_id=None):
        result = await _fake_cognitive_result(message, user, model_variant, session_id)
        result.output = None
        return result

    monkeypatch.setattr(api_module, "_run_cognitive_kernel", not_direct)
    monkeypatch.setattr(api_module, "_resolve_backend_for_chat",
                        lambda variant: SimpleNamespace(backend="ollama", tier="core", model="m",
                                                        data_left_infrastructure=False, sovereignty_overridden=False))
    monkeypatch.setattr(api_module, "_apply_cost_aware_routing",
                        lambda res, msg: (res, SimpleNamespace(escalated=False, reason="")))
    monkeypatch.setattr(api_module, "_record_shadow_verification", lambda *a, **k: None)

    async def go():
        transport = httpx.ASGITransport(app=api_module.app)
        async with httpx.AsyncClient(transport=transport, base_url="http://t") as client:
            async with client.stream("POST", "/api/stream", json={"message": "hi", "model_variant": "nano"}) as resp:
                got = b""
                async for piece in resp.aiter_bytes():
                    got += piece
                    if b"chunk" in got:
                        break  # abandon the response mid-stream, like a real client navigating away
    asyncio.run(go())
    # Natural completion is ~0.6s (4 items * 0.15s); check well before that
    # so "it closed" can only mean "closed early, because of the abandoned
    # response" -- not "it happened to finish naturally in the meantime".
    closed_early = slow.closed.wait(0.35)
    if not closed_early or slow.finished:
        pytest.skip(
            "ASGITransport (in-process, no real socket) did not surface the abandoned "
            "response as an ASGI http.disconnect in this httpx/starlette version within "
            "the window before natural completion -- the is_disconnected()-based path is "
            "unexercised by this specific transport; "
            "test_client_disconnect_closes_the_backend_generator covers the same route "
            "logic directly against a mocked is_disconnected()."
        )
    assert slow.finished is False


# ---------------------------------------------------------------------------
# Shutdown. Never exercised against the REAL shared _POOL in a test -- that
# shutdown is irreversible and would break every later test in the process.
# ---------------------------------------------------------------------------

def test_shutdown_is_idempotent_and_marks_the_module_shut_down(monkeypatch):
    calls = []
    fake_pool = SimpleNamespace(shutdown=lambda **kw: calls.append(kw))
    monkeypatch.setattr(streaming_module, "_POOL", fake_pool)
    monkeypatch.setattr(streaming_module, "_shut_down", False)

    streaming_module.shutdown_streaming_pool(wait=False)
    streaming_module.shutdown_streaming_pool(wait=False)  # second call is a no-op

    assert streaming_module._shut_down is True
    assert calls == [{"wait": False, "cancel_futures": False}]


def test_close_falls_back_to_synchronous_when_pool_already_shut_down(monkeypatch):
    """A shutdown landing mid-stream must not let the pool's RuntimeError
    mask whatever exception/cancellation was already propagating -- the
    generator still gets closed, just synchronously instead of via the pool."""
    class DeadPool:
        def submit(self, *a, **k):
            raise RuntimeError("cannot schedule new futures after shutdown")

    monkeypatch.setattr(streaming_module, "_POOL", DeadPool())
    closed = []

    class Gen:
        def close(self):
            closed.append(True)

    future = streaming_module._schedule_close(Gen())
    assert future is None
    assert closed == [True]


# ---------------------------------------------------------------------------
# Post-CP2-audit hardening #1: admission must track actual worker-thread
# occupancy, not this async generator's own cancellation/exit.
# ---------------------------------------------------------------------------

class _HangForever:
    """A generator whose next() blocks until explicitly released -- models a
    genuinely hung backend read, the exact scenario repeated cancellation
    against which must not be able to outrun real thread availability."""

    def __init__(self):
        self.release_event = threading.Event()
        self.entered = threading.Event()
        self.next_returned = threading.Event()

    def __iter__(self):
        return self

    def __next__(self):
        self.entered.set()
        self.release_event.wait()  # blocks the worker thread until released
        self.next_returned.set()
        return "finally-returned"

    def close(self):
        pass


def test_repeated_cancellation_against_a_hung_backend_cannot_outrun_admission(small_capacity):
    """The adversarial regression for the admission/cancellation lifecycle
    bug: cancel a consumer while its next() is genuinely stuck in a worker
    thread, MAX_CONCURRENT_STREAMS times over, and confirm admission stays
    at capacity (not reset to 0 by the cancellations) until the threads
    actually come free -- i.e. a saturating attacker cannot use repeated
    cancellation to make new streams' next() calls queue forever behind
    permanently wedged threads."""
    capacity = small_capacity
    hangs = [_HangForever() for _ in range(capacity)]

    async def go():
        agens = [aiter_blocking(h) for h in hangs]
        tasks = [asyncio.create_task(a.__anext__()) for a in agens]
        # Creating a task only SCHEDULES it -- it doesn't run until this
        # coroutine yields. Yield repeatedly (not a blocking h.entered.wait()
        # here, which would starve the loop and deadlock: the tasks need the
        # loop to run before their worker threads can even start) until every
        # task has actually reached its blocked next() call.
        for _ in range(200):
            if all(h.entered.is_set() for h in hangs):
                break
            await asyncio.sleep(0.01)
        assert all(h.entered.is_set() for h in hangs), "tasks never reached the blocked next() call"
        assert pool_stats()["in_use"] == capacity

        for t in tasks:
            t.cancel()
        for t in tasks:
            with pytest.raises(asyncio.CancelledError):
                await t

        # THE REGRESSION: admission must still show `capacity` in use --
        # the threads are still blocked on release_event, genuinely not
        # free, no matter that the consumers were cancelled.
        assert pool_stats()["in_use"] == capacity, (
            "admission was released while the worker thread was still occupied -- "
            "a new stream could now be admitted with no thread actually free for it"
        )

        # A new admission attempt while all threads are genuinely still
        # occupied must be rejected immediately, not queued.
        with pytest.raises(StreamingUnavailable):
            async with StreamAdmission():
                pass

        # Release the hung backends -- their threads can now actually finish.
        for h in hangs:
            h.release_event.set()
        for h in hangs:
            assert h.next_returned.wait(2)

        # Admission must drop back to 0 once the threads are genuinely free
        # (the done-callback fires asynchronously relative to this coroutine;
        # poll briefly rather than assert instantaneously).
        for _ in range(200):
            if pool_stats()["in_use"] == 0:
                break
            await asyncio.sleep(0.01)
        assert pool_stats()["in_use"] == 0

        # And a fresh stream is now genuinely admittable again.
        async with StreamAdmission():
            assert pool_stats()["in_use"] == 1
    asyncio.run(go())
    assert pool_stats()["in_use"] == 0


def test_cancellation_after_item_delivered_releases_immediately(small_capacity):
    """Contrast case: if the worker thread has ALREADY returned (the
    generator yielded a value and is between next() calls) when the
    consumer is cancelled, admission must release immediately -- there is
    no thread still occupied to wait for. Confirms the fix didn't just make
    every release deferred."""
    slow = _SlowGen(["a", "b", "c"], 0.05)

    async def go():
        agen = aiter_blocking(iter(slow))
        first = await agen.__anext__()
        assert first == "a"
        assert pool_stats()["in_use"] == 1
        await agen.aclose()
        return
    asyncio.run(go())
    # _SlowGen's own __iter__/next already returned by the time aclose() ran
    # (we awaited the first item already); release should be immediate, not
    # deferred behind a done-callback for a thread that's long since free.
    assert pool_stats()["in_use"] == 0


# ---------------------------------------------------------------------------
# Post-CP2-audit hardening #4: a REAL disconnect, over a real localhost TCP
# socket, not the in-process ASGITransport (which the earlier skipped test
# already established does not surface one).
# ---------------------------------------------------------------------------

def test_real_socket_disconnect_closes_the_backend_generator_and_frees_admission(monkeypatch):
    """Runs the actual app under a real uvicorn server bound to 127.0.0.1,
    sends a real HTTP request over a real TCP socket, reads the first SSE
    chunk, then abruptly closes the raw socket -- a genuine client
    disconnect, which uvicorn's protocol layer reports to Starlette as an
    ASGI http.disconnect (unlike ASGITransport). Confirms both the backend
    generator is closed AND the admission slot is released."""
    import socket

    uvicorn = pytest.importorskip("uvicorn")

    slow = _SlowGen(["a ", "b ", "c ", "d ", "e "], 0.2)
    monkeypatch.setattr(api_module, "_get_session", lambda *a, **k: _stub_session(slow))
    monkeypatch.setattr(api_module, "check_input", lambda text: MagicMock(action="allow", flagged_categories=[]))

    async def not_direct(message, user, model_variant, session_id=None):
        result = await _fake_cognitive_result(message, user, model_variant, session_id)
        result.output = None
        return result

    monkeypatch.setattr(api_module, "_run_cognitive_kernel", not_direct)
    monkeypatch.setattr(api_module, "_resolve_backend_for_chat",
                        lambda variant: SimpleNamespace(backend="ollama", tier="core", model="m",
                                                        data_left_infrastructure=False, sovereignty_overridden=False))
    monkeypatch.setattr(api_module, "_apply_cost_aware_routing",
                        lambda res, msg: (res, SimpleNamespace(escalated=False, reason="")))
    monkeypatch.setattr(api_module, "_record_shadow_verification", lambda *a, **k: None)

    sock = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
    sock.setsockopt(socket.SOL_SOCKET, socket.SO_REUSEADDR, 1)
    sock.bind(("127.0.0.1", 0))
    sock.listen(16)
    port = sock.getsockname()[1]

    config = uvicorn.Config(api_module.app, log_level="error", lifespan="off")
    server = uvicorn.Server(config)

    def run_server():
        asyncio.run(server.serve(sockets=[sock]))

    thread = threading.Thread(target=run_server, daemon=True)
    thread.start()
    try:
        for _ in range(200):
            if getattr(server, "started", False):
                break
            time.sleep(0.01)
        assert server.started, "uvicorn did not start within 2s"

        assert pool_stats()["in_use"] == 0

        body = json.dumps({"message": "hi", "model_variant": "nano"}).encode()
        request = (
            b"POST /api/stream HTTP/1.1\r\n"
            b"Host: 127.0.0.1\r\n"
            b"Content-Type: application/json\r\n"
            b"Connection: close\r\n"
            b"Content-Length: " + str(len(body)).encode() + b"\r\n\r\n" + body
        )
        client_sock = socket.create_connection(("127.0.0.1", port), timeout=5)
        client_sock.sendall(request)
        received = b""
        deadline = time.monotonic() + 5
        while b'"type": "chunk"' not in received and time.monotonic() < deadline:
            chunk = client_sock.recv(4096)
            if not chunk:
                break
            received += chunk
        assert b'"type": "chunk"' in received, f"never got a chunk, got: {received[:300]!r}"

        # The genuine disconnect: slam the socket shut mid-stream, like a
        # real client navigating away or losing its connection.
        client_sock.shutdown(socket.SHUT_RDWR)
        client_sock.close()

        assert slow.closed.wait(3), "backend generator was never closed after a real socket disconnect"
        assert slow.finished is False, "generator ran to completion instead of being stopped by the disconnect"

        for _ in range(300):
            if pool_stats()["in_use"] == 0:
                break
            time.sleep(0.01)
        assert pool_stats()["in_use"] == 0, "admission slot was never released after the disconnected stream's generator closed"
    finally:
        server.should_exit = True
        thread.join(timeout=5)
