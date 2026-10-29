"""LANDMARK-01 B-01 final integration (Wave B): the producer/consumer completion protocol of the Kernel -> SSE bridge.

Evidence class: DETERMINISTIC (in-process asyncio; a controlled provider stands in for the gateway). Every test is time-bounded and asserts CLEANUP -
no surviving task, no parked waiter, the provider's stream really closed - not only the delivered content.

What the defect was: the handoff sample waited for the channel's terminal signal *before* the producer was allowed to send it (an infinite wait after the
last token), and ``close()``/``fail()`` enqueued their sentinel from a fire-and-forget ``create_task`` when the queue was full (an untracked task that
could outlive the request, and a terminal marker that needed a free slot).
"""
from __future__ import annotations

import asyncio

import pytest

from orca.cognitive.contracts import CognitiveRequest, CognitiveState
from orca.cognitive.errors import CognitiveExecutionFailedError
from orca.cognitive.streaming import TIMEOUT, ChannelClosed, ConsumerGone, KernelRun, RawDeltaChannel
from tests.test_kernel_streaming import _DelayedRuntime, kernel_stack  # noqa: F401  (fixture re-export)

T = 5.0  # no test may wait longer than this for anything


def _tasks() -> set:
    return {t for t in asyncio.all_tasks() if t is not asyncio.current_task()}


async def _settle() -> None:
    for _ in range(3):
        await asyncio.sleep(0)


async def _drain(run: KernelRun, **kw) -> list[str]:
    return [d async for d in run.deltas(**kw)]


# ---- pure producer/consumer protocol ------------------------------------------------------------------------------------------------------------

@pytest.mark.asyncio
async def test_successful_stream_terminates_the_consumer_without_help():
    before = _tasks()

    async def producer(hook):
        for piece in ("a", "b", "c"):
            await hook(piece)
        return "RESULT"

    run = KernelRun(producer).start()
    got = await asyncio.wait_for(_drain(run), T)
    assert got == ["a", "b", "c"]
    assert await asyncio.wait_for(run.result(), T) == "RESULT"
    assert run.channel.state == "ended" and run.channel.terminal_observed == 1
    await run.aclose()
    await _settle()
    assert run.channel.waiting == 0 and _tasks() == before


@pytest.mark.asyncio
async def test_provider_that_yields_zero_chunks_terminates_safely():
    before = _tasks()

    async def producer(hook):
        return ""

    run = KernelRun(producer).start()
    assert await asyncio.wait_for(_drain(run), T) == []
    assert await run.result() == ""
    await run.aclose()
    await _settle()
    assert run.channel.pushed == 0 and run.channel.waiting == 0 and _tasks() == before


@pytest.mark.asyncio
async def test_provider_failing_before_the_first_chunk_reaches_the_consumer_once():
    before = _tasks()

    async def producer(hook):
        raise RuntimeError("boom-before-output")

    run = KernelRun(producer).start()
    with pytest.raises(RuntimeError, match="boom-before-output"):
        await asyncio.wait_for(_drain(run), T)
    assert run.channel.terminal_observed == 1
    with pytest.raises(RuntimeError, match="boom-before-output"):
        await run.result()                                  # the authoritative exception is still available from the task
    assert [d async for d in run.deltas()] == []            # the error was delivered exactly once; a second read just ends
    await run.aclose()
    await _settle()
    assert run.channel.waiting == 0 and _tasks() == before


@pytest.mark.asyncio
async def test_provider_failing_after_several_chunks_delivers_them_then_the_failure():
    async def producer(hook):
        for piece in ("one", "two", "three"):
            await hook(piece)
        raise RuntimeError("boom-mid-stream")

    run = KernelRun(producer).start()
    seen: list[str] = []
    with pytest.raises(RuntimeError, match="boom-mid-stream"):
        async for d in run.deltas():
            seen.append(d)
    assert seen == ["one", "two", "three"], "output produced before the failure must not be lost"
    await run.aclose()
    assert run.done


@pytest.mark.asyncio
async def test_queue_at_capacity_blocks_the_producer_and_never_drops():
    before = _tasks()
    delivered: list[str] = []

    async def producer(hook):
        for i in range(12):
            await hook(f"d{i}")
        return "ok"

    run = KernelRun(producer, maxsize=2).start()
    await asyncio.sleep(0.05)                                # the consumer is slow to start: the producer must be parked, not dropping
    assert run.channel.pending == 2 and run.channel.waiting == 1 and not run.done
    async for d in run.deltas():
        delivered.append(d)
        await asyncio.sleep(0.005)
    assert delivered == [f"d{i}" for i in range(12)]
    assert run.channel.pushed == run.channel.delivered == 12
    await run.aclose()
    await _settle()
    assert _tasks() == before


@pytest.mark.asyncio
async def test_closing_a_full_channel_needs_no_free_slot_and_creates_no_task():
    """The defect: a full queue could not take its end marker, so close() spawned a task to wait for a slot. Now the terminal state is an attribute."""
    ch = RawDeltaChannel(maxsize=2)
    await ch.push("x")
    await ch.push("y")
    before = _tasks()
    ch.close()
    assert _tasks() == before, "close() must not create a background task"
    assert [d async for d in ch] == ["x", "y"], "buffered output is delivered in full before the end"
    assert ch.terminal_observed == 1 and ch.waiting == 0

    ch2 = RawDeltaChannel(maxsize=1)
    await ch2.push("only")
    before = _tasks()
    ch2.fail(RuntimeError("late failure"))
    assert _tasks() == before, "fail() must not create a background task"
    assert await ch2.receive() == "only"
    with pytest.raises(RuntimeError, match="late failure"):
        await ch2.receive()
    assert await _expect_stop(ch2)


async def _expect_stop(ch) -> bool:
    try:
        await asyncio.wait_for(ch.receive(), T)
    except StopAsyncIteration:
        return True
    return False


@pytest.mark.asyncio
async def test_consumer_disconnect_while_the_queue_is_full_releases_the_blocked_producer():
    closed = asyncio.Event()

    async def producer(hook):
        try:
            for i in range(100):
                await hook(f"d{i}")
        finally:
            closed.set()                                     # stands in for the gateway stream being closed by the Kernel's aclosing()

    before = _tasks()
    run = KernelRun(producer, maxsize=1).start()
    await asyncio.sleep(0.05)
    assert run.channel.pending == 1 and run.channel.waiting == 1 and not run.done     # producer parked on push()
    await asyncio.wait_for(run.aclose(), T)                  # the consumer vanished
    assert closed.is_set(), "the producer's cleanup (gateway close) must have run"
    assert run.done and run.channel.waiting == 0
    await _settle()
    assert _tasks() == before
    with pytest.raises(ChannelClosed):
        await run.channel.push("late")                       # a straggler can never enqueue after the abort


@pytest.mark.asyncio
async def test_producer_cancelled_while_blocked_on_push_releases_the_consumer():
    async def producer(hook):
        for i in range(100):
            await hook(f"d{i}")

    run = KernelRun(producer, maxsize=1).start()
    await asyncio.sleep(0.05)
    assert run.channel.waiting == 1                          # parked inside push()
    run.task.cancel()                                        # somebody else cancels the producer
    with pytest.raises(ChannelClosed):
        await asyncio.wait_for(_drain(run), T)               # the consumer is released, not left hanging
    assert run.channel.terminal_observed == 1 and run.channel.waiting == 0
    await run.aclose()


@pytest.mark.asyncio
async def test_a_cancelled_consumer_still_finishes_the_producer():
    """``aclose`` is called from a finally inside a request that is itself being cancelled (Stop / disconnect): it must keep waiting for the producer."""
    producer_cleaned = asyncio.Event()

    async def producer(hook):
        try:
            for i in range(1000):
                await hook(f"d{i}")
                await asyncio.sleep(0.01)
        finally:
            await asyncio.sleep(0.05)                        # slow cleanup, longer than the second cancellation below
            producer_cleaned.set()

    run = KernelRun(producer, maxsize=4).start()

    async def request():
        try:
            async for _ in run.deltas():
                pass
        finally:
            await run.aclose()

    req = asyncio.create_task(request())
    await asyncio.sleep(0.05)
    req.cancel()                                             # client disconnect
    await asyncio.sleep(0.01)
    req.cancel()                                             # ...and a second cancellation lands while aclose() is waiting
    with pytest.raises(asyncio.CancelledError):
        await asyncio.wait_for(req, T)
    assert producer_cleaned.is_set() and run.done


@pytest.mark.asyncio
async def test_consumer_gone_probe_raises_without_a_delta():
    started = asyncio.Event()

    async def producer(hook):
        started.set()
        await asyncio.sleep(30)                              # a provider that never produces a token

    async def gone():
        return True

    run = KernelRun(producer).start()
    await started.wait()
    with pytest.raises(ConsumerGone):
        await asyncio.wait_for(_drain(run, is_gone=gone, poll_s=0.02), T)
    await asyncio.wait_for(run.aclose(), T)
    assert run.done and run.task.cancelled()


@pytest.mark.asyncio
async def test_receive_timeout_does_not_lose_or_duplicate_items():
    ch = RawDeltaChannel(maxsize=4)
    assert await ch.receive(timeout=0.01) is TIMEOUT
    await ch.push("a")
    assert await ch.receive(timeout=0.5) == "a"
    assert await ch.receive(timeout=0.01) is TIMEOUT
    ch.close()
    with pytest.raises(StopAsyncIteration):
        await ch.receive(timeout=0.5)
    assert ch.waiting == 0


@pytest.mark.asyncio
async def test_first_terminal_state_wins_and_is_idempotent():
    ch = RawDeltaChannel(maxsize=2)
    await ch.push("a")
    ch.close()
    ch.fail(RuntimeError("ignored"))
    ch.abort()
    ch.close()
    assert [d async for d in ch] == ["a"]
    assert ch.state == "ended" and ch.terminal_observed == 1


# ---- against the REAL Cognitive Kernel and gateway (controlled provider) ----------------------------------------------------------------------------

def _kernel_run(kernel, objective="say something", maxsize=64):
    async def producer(hook):
        return await kernel.execute(CognitiveRequest(objective=objective, on_raw_delta=hook))
    return KernelRun(producer, maxsize=maxsize)


@pytest.mark.asyncio
async def test_real_kernel_success_closes_the_stream_and_leaves_nothing_behind(kernel_stack):
    kernel, runtime, _gw = kernel_stack
    before = _tasks()
    run = _kernel_run(kernel).start()
    got = await asyncio.wait_for(_drain(run), T)
    result = await run.result()
    assert "".join(got) == result.output == "Hello world" and result.status == CognitiveState.COMPLETED
    assert runtime.stream_calls == 1 and runtime.generate_calls == 0
    await run.aclose()
    await _settle()
    assert runtime._active_streams == 0 and runtime.stream_aclose_count == 1, "the gateway connection must be closed exactly once"
    assert _tasks() == before and run.channel.waiting == 0


@pytest.mark.asyncio
async def test_real_kernel_provider_with_zero_chunks(kernel_stack):
    kernel, runtime, _gw = kernel_stack
    runtime.chunks = []
    run = _kernel_run(kernel).start()
    assert await asyncio.wait_for(_drain(run), T) == []
    result = await run.result()
    assert result.output == "" and runtime._active_streams == 0
    await run.aclose()


@pytest.mark.asyncio
async def test_real_kernel_provider_failure_after_chunks(kernel_stack):
    kernel, runtime, _gw = kernel_stack
    runtime.chunks, runtime.fail_after = ["one", "two", "three"], 2
    run = _kernel_run(kernel).start()
    seen: list[str] = []
    with pytest.raises(CognitiveExecutionFailedError):
        async for d in run.deltas():
            seen.append(d)
    assert seen == ["one", "two"]
    await run.aclose()
    assert runtime._active_streams == 0 and runtime.stream_aclose_count == 1


@pytest.mark.asyncio
async def test_real_kernel_provider_failure_before_the_first_chunk(kernel_stack):
    kernel, runtime, _gw = kernel_stack
    runtime.chunks, runtime.fail_after = ["one"], 0
    run = _kernel_run(kernel).start()
    with pytest.raises(CognitiveExecutionFailedError):
        await asyncio.wait_for(_drain(run), T)
    await run.aclose()
    assert runtime._active_streams == 0


@pytest.mark.asyncio
async def test_real_kernel_disconnect_with_a_full_queue_closes_the_gateway_stream(kernel_stack):
    kernel, runtime, _gw = kernel_stack
    runtime.chunks, runtime.delay_s = [f"t{i}" for i in range(50)], 0.001
    before = _tasks()
    run = _kernel_run(kernel, maxsize=1).start()
    await asyncio.sleep(0.2)                                 # the consumer never reads: the Kernel is parked inside the raw-delta hook
    assert run.channel.pending == 1 and run.channel.waiting == 1 and runtime._active_streams == 1
    await asyncio.wait_for(run.aclose(), T)
    await _settle()
    assert runtime._active_streams == 0 and runtime.stream_aclose_count == 1, "the upstream (gateway) stream must have been closed"
    assert run.done and _tasks() == before


@pytest.mark.asyncio
async def test_real_kernel_stop_mid_stream_stops_the_provider_early(kernel_stack):
    kernel, runtime, _gw = kernel_stack
    runtime.chunks, runtime.delay_s = [f"t{i}" for i in range(40)], 0.02
    run = _kernel_run(kernel, maxsize=8).start()
    got = []
    async for d in run.deltas():
        got.append(d)
        if len(got) == 3:
            break
    await asyncio.wait_for(run.aclose(), T)
    assert runtime._active_streams == 0 and runtime.stream_aclose_count == 1
    emitted = len(got)
    await asyncio.sleep(0.2)
    assert run.channel.delivered == emitted and run.done, "nothing more may be produced after Stop"


# ---- the Truth-Fabric draft is never streamed, redaction precedes memory ingestion ---------------------------------------------------------------------

@pytest.mark.asyncio
async def test_truth_fabric_draft_tokens_never_reach_the_raw_delta_hook(kernel_stack, monkeypatch):
    """A Truth-Fabric answer is only a DRAFT until verify_answer() accepts it (it may still abstain). Streaming its tokens would show unverified text, so the
    Kernel withholds the hooks for that call: the answer is delivered whole, after verification (and the API labels it a replay, truthfully)."""
    from types import SimpleNamespace

    from orca.cognitive import kernel as kernel_mod
    from orca.truth.contracts import EvidenceState

    kernel, runtime, _gw = kernel_stack
    seen = []
    real = kernel_mod.CognitiveKernel._answer_directly

    async def spy(self, objective, tier, trace_id, request=None, route_info=None):
        seen.append(request)
        return await real(self, objective, tier, trace_id, request=request, route_info=route_info)

    class FakeFabric:
        async def assess_evidence(self, *a, **k):
            return SimpleNamespace(evidence_state=EvidenceState.SUFFICIENT, context_block="", evidence=[], sources=[])

        async def verify_answer(self, text, assessed, **k):
            return SimpleNamespace(evidence_state=EvidenceState.SUFFICIENT, citation_coverage={}, counter_evidence=None, sources=[], evidence=[], claims=[])

    monkeypatch.setattr(kernel_mod.CognitiveKernel, "_answer_directly", spy)
    monkeypatch.setattr("orca.truth.truth_fabric.TruthFabric", FakeFabric)
    delivered: list[str] = []

    async def hook(delta):
        delivered.append(delta)

    result = await kernel.execute(CognitiveRequest(objective="Who won the 2022 world cup? cite your sources", on_raw_delta=hook))
    assert result.status == CognitiveState.COMPLETED and result.evidence_state is not None, "this prompt must take the Truth Fabric branch"
    assert result.output == "Hello world"
    assert delivered == [], "draft tokens were handed to the raw-delta hook before verification"
    assert len(seen) == 1 and seen[0].on_raw_delta is None and seen[0].on_served is None
    assert runtime.stream_calls == 0 and runtime.generate_calls == 1, "the draft is generated whole (non-streaming)"


@pytest.mark.asyncio
async def test_on_served_is_announced_once_with_the_resolved_deployment_before_the_first_delta(kernel_stack):
    kernel, runtime, _gw = kernel_stack
    order: list[tuple[str, object]] = []

    async def served(info):
        order.append(("served", dict(info)))

    async def delta(d):
        order.append(("delta", d))

    result = await kernel.execute(CognitiveRequest(objective="Say hello.", on_raw_delta=delta, on_served=served))
    assert [k for k, _ in order].count("served") == 1 and order[0][0] == "served", order
    info = order[0][1]
    assert info["model"] == "fixture-llama3.2:1b" == result.resolved_model and info["tier"] == result.resolved_tier
    assert info["deployment_id"] == "dep-b01-fixture" and info["runtime"] == "fake" and info["degraded"] is False


@pytest.mark.asyncio
async def test_working_memory_ingestion_receives_the_redacted_answer_not_the_raw_one(kernel_stack, monkeypatch):
    kernel, runtime, _gw = kernel_stack
    secret = "sk-" + "a1B2c3D4e5F6g7H8i9J0k1L2"
    runtime.chunks = [f"your key is {secret} ok"]
    ingested = []

    def spy_ingest(session_id, objective, output_text):
        ingested.append(output_text)
        return None

    monkeypatch.setattr("orca.memory.turn_ingest.maybe_ingest_turn", spy_ingest)
    for hook in (None, (lambda d: _noop(d))):
        ingested.clear()
        result = await kernel.execute(CognitiveRequest(objective="what is my key", session_id="wm-redaction", on_raw_delta=hook))
        assert secret in result.output, "the Kernel's own result is raw by contract; callers must redact"
        assert ingested and secret not in ingested[0] and "REDACTED" in ingested[0]


async def _noop(delta):
    return None
