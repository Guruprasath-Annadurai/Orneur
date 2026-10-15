"""Streaming contract of ModelGateway.stream(): honest upstream streaming, bounded waiting, and release on stop.

All runtimes here are deterministic in-process DOUBLES (no network, no model). They prove the gateway's
contract, not any model's behaviour.
"""
from __future__ import annotations

import asyncio
import time

import pytest

from orca.gateway import metrics
from orca.gateway.circuit_breaker import CircuitState
from orca.gateway.contracts import InferenceChunk
from orca.gateway.errors import GenerationTimeoutError
from tests.test_gateway_model_gateway import _FakeRuntime, _deployment, _gateway, _req


class _StallRuntime(_FakeRuntime):
    """Yields ``before`` chunks, then stalls forever (a hung upstream)."""

    def __init__(self, before: int = 0):
        super().__init__()
        self.before = before
        self.closed = False

    async def stream(self, request):
        try:
            for i in range(self.before):
                yield InferenceChunk(request_id=request.request_id, sequence=i, delta=f"c{i}")
            await asyncio.sleep(3600)
        finally:
            self.closed = True


class _EndlessRuntime(_FakeRuntime):
    """Keeps producing chunks at a steady rate (a runaway generation)."""

    def __init__(self, gap_s: float = 0.05):
        super().__init__()
        self.gap_s = gap_s
        self.closed = False
        self.produced = 0

    async def stream(self, request):
        try:
            i = 0
            while True:
                await asyncio.sleep(self.gap_s)
                self.produced += 1
                yield InferenceChunk(request_id=request.request_id, sequence=i, delta="x")
                i += 1
        finally:
            self.closed = True


def _state(gw, dep="dep-fake-1"):
    return gw.circuit_breaker._get(dep).state


@pytest.mark.asyncio
async def test_upstream_that_never_sends_a_first_chunk_times_out_and_releases_everything():
    rt = _StallRuntime(before=0)
    gw = _gateway(rt, _deployment(), first_token_timeout_s=0.2)
    t0 = time.monotonic()
    with pytest.raises(GenerationTimeoutError):
        async with asyncio.timeout(3):  # the bug being fixed: this used to hang until the 3600 s sleep
            async for _ in gw.stream(_req()):
                pass
    assert time.monotonic() - t0 < 2.0
    assert rt.closed, "the stalled upstream generator must be closed"
    assert "req-1" in rt.cancelled_ids, "cancellation must be propagated to the runtime"
    assert gw.concurrency.stats("dep-fake-1").active == 0, "the concurrency slot must be released"


@pytest.mark.asyncio
async def test_a_stall_after_some_chunks_times_out_but_the_partial_output_was_delivered():
    rt = _StallRuntime(before=2)
    gw = _gateway(rt, _deployment(), first_token_timeout_s=5, stream_idle_timeout_s=0.2)
    got = []
    with pytest.raises(GenerationTimeoutError):
        async with asyncio.timeout(3):
            async for c in gw.stream(_req()):
                got.append(c.delta)
    assert got == ["c0", "c1"]
    assert rt.closed and gw.concurrency.stats("dep-fake-1").active == 0


@pytest.mark.asyncio
async def test_total_request_deadline_applies_to_streams_that_keep_producing():
    rt = _EndlessRuntime(gap_s=0.05)
    gw = _gateway(rt, _deployment(), first_token_timeout_s=5, stream_idle_timeout_s=5, total_request_timeout_s=0.4)
    got = 0
    t0 = time.monotonic()
    with pytest.raises(GenerationTimeoutError):
        async with asyncio.timeout(4):
            async for _ in gw.stream(_req()):
                got += 1
    assert 1 <= got < 20 and time.monotonic() - t0 < 2.0
    assert rt.closed and gw.concurrency.stats("dep-fake-1").active == 0


@pytest.mark.asyncio
async def test_client_stop_cancels_upstream_releases_the_slot_and_is_not_a_failure():
    rt = _EndlessRuntime(gap_s=0.02)
    gw = _gateway(rt, _deployment())
    agen = gw.stream(_req(request_id="req-stop"))
    first = await agen.__anext__()
    assert first.delta == "x"
    before = dict(metrics._cancellation_count)
    await agen.aclose()  # the client pressed Stop / disconnected
    assert rt.closed, "upstream generation must be closed immediately"
    assert "req-stop" in rt.cancelled_ids, "cancel must be propagated to the runtime"
    assert gw.concurrency.stats("dep-fake-1").active == 0
    assert _state(gw) == CircuitState.CLOSED.value, "a user stop must not trip the circuit breaker"
    assert metrics._cancellation_count.get("dep-fake-1", 0) == before.get("dep-fake-1", 0) + 1


@pytest.mark.asyncio
async def test_task_cancellation_is_propagated_like_a_stop():
    rt = _EndlessRuntime(gap_s=0.02)
    gw = _gateway(rt, _deployment())

    async def consume():
        async for _ in gw.stream(_req(request_id="req-task")):
            pass

    task = asyncio.create_task(consume())
    await asyncio.sleep(0.15)
    task.cancel()
    with pytest.raises(asyncio.CancelledError):
        await task
    assert rt.closed and "req-task" in rt.cancelled_ids
    assert gw.concurrency.stats("dep-fake-1").active == 0


@pytest.mark.asyncio
async def test_chunks_carry_the_actual_serving_identity_not_the_requested_alias():
    rt = _FakeRuntime(chunks=["a", "b"])
    gw = _gateway(rt, _deployment(model_version="served-v7"))
    chunks = [c async for c in gw.stream(_req())]
    assert chunks and all(c.deployment_id == "dep-fake-1" and c.resolved_version == "served-v7" and c.runtime == "fake" for c in chunks)


@pytest.mark.asyncio
async def test_streaming_is_pull_based_so_a_slow_consumer_never_makes_the_gateway_buffer():
    """Backpressure: the runtime may run at most one chunk ahead of what the consumer has taken."""
    rt = _EndlessRuntime(gap_s=0)
    gw = _gateway(rt, _deployment())
    agen = gw.stream(_req(request_id="req-slow"))
    for _ in range(5):
        await agen.__anext__()
        await asyncio.sleep(0.02)  # slow consumer
    assert rt.produced <= 6
    await agen.aclose()


@pytest.mark.asyncio
async def test_the_happy_path_is_unchanged_and_strictly_ordered():
    rt = _FakeRuntime(chunks=["hello", " ", "world"])
    gw = _gateway(rt, _deployment())
    chunks = [c async for c in gw.stream(_req())]
    assert [c.delta for c in chunks if c.delta] == ["hello", " ", "world"]
    assert chunks[-1].finish_reason == "stop"
    assert [c.sequence for c in chunks] == sorted(c.sequence for c in chunks)
    assert gw.concurrency.stats("dep-fake-1").active == 0 and _state(gw) == CircuitState.CLOSED.value
