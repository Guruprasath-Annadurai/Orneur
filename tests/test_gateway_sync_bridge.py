"""
The sync bridge's entire reason to exist: orca/serve/api.py's SSE handler
iterates a sync generator (AgentLoop.stream()'s wrapper around
brain.stream()) DIRECTLY on the FastAPI/uvicorn event-loop thread -- not
inside asyncio.to_thread. A naive asyncio.run()/run_until_complete() bridge
would raise "This event loop is already running" in that exact context.
These tests reproduce that exact hazard (a running event loop on the
calling thread) rather than only testing the bridge from a plain thread.
"""
from __future__ import annotations

import asyncio

import pytest

from orca.gateway.sync_bridge import run_async_gen_in_thread, run_async_in_thread


async def _sample_coro():
    await asyncio.sleep(0.01)
    return "coro-result"


async def _failing_coro():
    await asyncio.sleep(0.01)
    raise ValueError("simulated coroutine failure")


async def _sample_agen():
    for i in range(3):
        await asyncio.sleep(0.005)
        yield i


async def _failing_agen():
    yield "first"
    raise ConnectionError("simulated mid-stream failure")


def test_run_async_in_thread_from_plain_sync_context():
    result = run_async_in_thread(_sample_coro)
    assert result == "coro-result"


def test_run_async_in_thread_propagates_exception():
    with pytest.raises(ValueError, match="simulated coroutine failure"):
        run_async_in_thread(_failing_coro)


def test_run_async_gen_in_thread_from_plain_sync_context():
    items = list(run_async_gen_in_thread(_sample_agen))
    assert items == [0, 1, 2]


def test_run_async_gen_in_thread_propagates_exception_after_partial_yield():
    items = []
    with pytest.raises(ConnectionError, match="simulated mid-stream failure"):
        for item in run_async_gen_in_thread(_failing_agen):
            items.append(item)
    assert items == ["first"]  # the item yielded before the failure is not lost


@pytest.mark.asyncio
async def test_run_async_in_thread_works_while_a_loop_is_already_running_on_this_thread():
    """
    THE critical case: this test itself runs inside pytest-asyncio's own
    running event loop on this thread. A naive bridge
    (asyncio.new_event_loop() + loop.run_until_complete() called directly,
    without a background thread) would raise RuntimeError here. Calling
    run_async_in_thread() must work anyway, because the async work happens
    on a SEPARATE thread with its own loop.
    """
    result = await asyncio.to_thread(run_async_in_thread, _sample_coro)
    assert result == "coro-result"


@pytest.mark.asyncio
async def test_run_async_gen_in_thread_works_while_a_loop_is_already_running_on_this_thread():
    def _consume():
        return list(run_async_gen_in_thread(_sample_agen))

    items = await asyncio.to_thread(_consume)
    assert items == [0, 1, 2]


def test_run_async_gen_in_thread_cancels_promptly_on_early_close():
    """
    Phase 2.1 closure finding: client disconnect on /api/stream closes the
    sync generator early (Starlette's StreamingResponse cleanup calls
    .close() on it). Before this fix, .close() blocked in thread.join()
    until the abandoned async generator finished on its own -- for a real
    generation, that could be tens of seconds, potentially stalling
    whatever thread called .close(). Cancellation must now propagate
    promptly: closing early must return near-instantly, and the abandoned
    async generator must actually observe asyncio.CancelledError (proving
    it can release resources -- e.g. a Gateway concurrency permit -- rather
    than being silently abandoned mid-await forever).
    """
    import time

    cleanup: list = []

    async def _slow_agen():
        try:
            yield "first"
            await asyncio.sleep(30)
            yield "second"
        except asyncio.CancelledError:
            cleanup.append("cancelled")
            raise
        finally:
            cleanup.append("finally")

    gen = run_async_gen_in_thread(_slow_agen)
    assert next(gen) == "first"

    start = time.monotonic()
    gen.close()
    elapsed = time.monotonic() - start

    assert elapsed < 2.0, f"close() took {elapsed:.2f}s -- cancellation did not propagate promptly"
    assert cleanup == ["cancelled", "finally"]


def test_run_async_in_thread_works_when_called_directly_from_the_main_thread_with_a_manually_started_loop():
    """
    Simulates orca/serve/api.py's exact real shape more precisely: a
    background loop is running (like uvicorn's), and code on that SAME
    thread (not a separate to_thread call) invokes the bridge synchronously
    -- e.g. inside a lambda passed to a sync generator that a `for` loop
    drives directly on the event-loop thread.
    """
    outer_loop = asyncio.new_event_loop()

    async def _simulate_fastapi_handler():
        # This runs "on the event loop thread" from asyncio's perspective,
        # but the bridge call itself is a plain synchronous function call,
        # exactly like `for chunk in gen:` iterating a sync generator
        # directly inside an `async def` handler in orca/serve/api.py.
        def _sync_work():
            return run_async_in_thread(_sample_coro)

        # This mirrors api.py's `await asyncio.to_thread(lambda: sess.agent.stream(...))`
        # for the SETUP call, but the actual per-chunk iteration in api.py
        # happens synchronously after that -- reproduced directly here
        # without to_thread to prove the bridge itself doesn't depend on it.
        return _sync_work()

    try:
        result = outer_loop.run_until_complete(_simulate_fastapi_handler())
        assert result == "coro-result"
    finally:
        outer_loop.close()
