"""
Concurrency permit release must never leak, on any exit path: normal
success, an exception raised inside the `async with` block, or the task
being cancelled mid-generation. Each is tested explicitly rather than
assumed from the `finally` block's presence.
"""
from __future__ import annotations

import asyncio

import pytest

from orca.gateway.concurrency import ConcurrencyLimiter
from orca.gateway.errors import QueueFullError, QueueTimeoutError


@pytest.mark.asyncio
async def test_permit_released_on_success():
    limiter = ConcurrencyLimiter()
    limiter.configure("dep-1", max_concurrency=2, max_queue_depth=5)

    async with await limiter.acquire("dep-1"):
        assert limiter.stats("dep-1").active == 1

    assert limiter.stats("dep-1").active == 0


@pytest.mark.asyncio
async def test_permit_released_on_exception():
    limiter = ConcurrencyLimiter()
    limiter.configure("dep-1", max_concurrency=2, max_queue_depth=5)

    with pytest.raises(ValueError):
        async with await limiter.acquire("dep-1"):
            assert limiter.stats("dep-1").active == 1
            raise ValueError("simulated generation failure")

    assert limiter.stats("dep-1").active == 0


@pytest.mark.asyncio
async def test_permit_released_on_cancellation():
    limiter = ConcurrencyLimiter()
    limiter.configure("dep-1", max_concurrency=2, max_queue_depth=5)

    started = asyncio.Event()

    async def _long_running():
        async with await limiter.acquire("dep-1"):
            started.set()
            await asyncio.sleep(10)  # would hang forever if not cancelled

    task = asyncio.create_task(_long_running())
    await started.wait()
    assert limiter.stats("dep-1").active == 1

    task.cancel()
    with pytest.raises(asyncio.CancelledError):
        await task

    assert limiter.stats("dep-1").active == 0


@pytest.mark.asyncio
async def test_concurrency_cap_enforced():
    limiter = ConcurrencyLimiter()
    limiter.configure("dep-1", max_concurrency=1, max_queue_depth=5)

    entered_first = asyncio.Event()
    release_first = asyncio.Event()

    async def _holder():
        async with await limiter.acquire("dep-1"):
            entered_first.set()
            await release_first.wait()

    task = asyncio.create_task(_holder())
    await entered_first.wait()
    assert limiter.stats("dep-1").active == 1

    # A second acquire should queue (not error) since queue_depth allows it,
    # and should only proceed once the first is released.
    second_entered = asyncio.Event()

    async def _second():
        async with await limiter.acquire("dep-1"):
            second_entered.set()

    second_task = asyncio.create_task(_second())
    await asyncio.sleep(0.05)
    assert not second_entered.is_set()  # still waiting, correctly blocked

    release_first.set()
    await task
    await second_task
    assert second_entered.is_set()


@pytest.mark.asyncio
async def test_queue_full_rejects_cleanly():
    limiter = ConcurrencyLimiter()
    limiter.configure("dep-1", max_concurrency=1, max_queue_depth=1)

    holder_entered = asyncio.Event()
    release_holder = asyncio.Event()

    async def _holder():
        async with await limiter.acquire("dep-1"):
            holder_entered.set()
            await release_holder.wait()

    async def _waiter():
        async with await limiter.acquire("dep-1"):
            pass

    holder_task = asyncio.create_task(_holder())
    await holder_entered.wait()

    waiter_task = asyncio.create_task(_waiter())
    await asyncio.sleep(0.05)  # let it enter the queue

    # Queue depth is now 1 (at capacity) and no permit is free -- a third
    # request must be rejected outright, not silently queued unbounded.
    with pytest.raises(QueueFullError):
        async with await limiter.acquire("dep-1"):
            pass

    release_holder.set()
    await holder_task
    await waiter_task


@pytest.mark.asyncio
async def test_queue_timeout_raises_structured_error():
    limiter = ConcurrencyLimiter()
    limiter.configure("dep-1", max_concurrency=1, max_queue_depth=5)

    release_holder = asyncio.Event()

    async def _holder():
        async with await limiter.acquire("dep-1"):
            await release_holder.wait()

    holder_task = asyncio.create_task(_holder())
    await asyncio.sleep(0.02)

    with pytest.raises(QueueTimeoutError):
        async with await limiter.acquire("dep-1", queue_timeout_s=0.05):
            pass

    release_holder.set()
    await holder_task


@pytest.mark.asyncio
async def test_deployments_are_isolated():
    """A full queue on one deployment must not affect another's capacity."""
    limiter = ConcurrencyLimiter()
    limiter.configure("dep-busy", max_concurrency=1, max_queue_depth=0)
    limiter.configure("dep-free", max_concurrency=1, max_queue_depth=0)

    release = asyncio.Event()

    async def _hold_busy():
        async with await limiter.acquire("dep-busy"):
            await release.wait()

    busy_task = asyncio.create_task(_hold_busy())
    await asyncio.sleep(0.02)

    # dep-busy has no room (0 queue depth, permit taken) -- must reject.
    with pytest.raises(QueueFullError):
        async with await limiter.acquire("dep-busy"):
            pass

    # dep-free is untouched and must work normally.
    async with await limiter.acquire("dep-free"):
        assert limiter.stats("dep-free").active == 1

    release.set()
    await busy_task
