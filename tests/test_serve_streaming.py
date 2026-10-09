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
