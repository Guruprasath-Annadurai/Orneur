"""
Priority-aware, aging-based fairness in the concurrency limiter.
RequestPriority previously existed on InferenceRequest but the queue was
plain FIFO -- these tests verify: (1) higher priority is generally served
first, (2) aging guarantees a lower-priority request is NOT starved
indefinitely once it has waited long enough, (3) same-priority waiters
remain strictly FIFO (backward compatible), (4) priority never defeats the
bounded queue depth.
"""
from __future__ import annotations

import asyncio

import pytest

from orca.gateway.concurrency import ConcurrencyLimiter
from orca.gateway.contracts import RequestPriority
from orca.gateway.errors import QueueFullError


@pytest.mark.asyncio
async def test_higher_priority_served_before_lower_priority_queued_at_same_time():
    limiter = ConcurrencyLimiter(aging_interval_s=100.0)  # aging effectively off for this test
    limiter.configure("dep-1", max_concurrency=1, max_queue_depth=5)

    order: list[str] = []
    holder_entered = asyncio.Event()
    release_holder = asyncio.Event()

    async def _holder():
        async with await limiter.acquire("dep-1"):
            holder_entered.set()
            await release_holder.wait()

    async def _waiter(name: str, priority: str):
        async with await limiter.acquire("dep-1", priority=priority):
            order.append(name)

    holder_task = asyncio.create_task(_holder())
    await holder_entered.wait()

    # Enqueue BACKGROUND first, then INTERACTIVE shortly after -- despite
    # arriving second, INTERACTIVE must be served first (higher priority,
    # negligible wait-time difference).
    background_task = asyncio.create_task(_waiter("background", RequestPriority.BACKGROUND.value))
    await asyncio.sleep(0.01)
    interactive_task = asyncio.create_task(_waiter("interactive", RequestPriority.INTERACTIVE.value))
    await asyncio.sleep(0.01)

    release_holder.set()
    await holder_task
    await background_task
    await interactive_task

    assert order == ["interactive", "background"]


@pytest.mark.asyncio
async def test_same_priority_waiters_remain_strictly_fifo():
    """Backward compatibility: callers that never set a priority (all
    INTERACTIVE, the default) must see unchanged FIFO ordering."""
    limiter = ConcurrencyLimiter(aging_interval_s=100.0)
    limiter.configure("dep-1", max_concurrency=1, max_queue_depth=5)

    order: list[str] = []
    holder_entered = asyncio.Event()
    release_holder = asyncio.Event()

    async def _holder():
        async with await limiter.acquire("dep-1"):
            holder_entered.set()
            await release_holder.wait()

    async def _waiter(name: str):
        async with await limiter.acquire("dep-1"):
            order.append(name)

    holder_task = asyncio.create_task(_holder())
    await holder_entered.wait()

    first = asyncio.create_task(_waiter("first"))
    await asyncio.sleep(0.01)
    second = asyncio.create_task(_waiter("second"))
    await asyncio.sleep(0.01)
    third = asyncio.create_task(_waiter("third"))
    await asyncio.sleep(0.01)

    release_holder.set()
    await asyncio.gather(holder_task, first, second, third)

    assert order == ["first", "second", "third"]


@pytest.mark.asyncio
async def test_aging_prevents_indefinite_starvation():
    """
    A BACKGROUND request that has waited long enough must eventually be
    served even though a stream of fresh INTERACTIVE requests keeps
    arriving -- this is the actual bounded-fairness guarantee, not just
    "priority mostly wins." Uses a small aging_interval_s so the test runs
    fast and deterministically.
    """
    aging_interval_s = 0.05
    limiter = ConcurrencyLimiter(aging_interval_s=aging_interval_s)
    limiter.configure("dep-1", max_concurrency=1, max_queue_depth=20)

    order: list[str] = []
    holder_entered = asyncio.Event()
    release_holder = asyncio.Event()

    async def _holder():
        async with await limiter.acquire("dep-1"):
            holder_entered.set()
            await release_holder.wait()

    async def _waiter(name: str, priority: str):
        async with await limiter.acquire("dep-1", priority=priority):
            order.append(name)

    holder_task = asyncio.create_task(_holder())
    await holder_entered.wait()

    # BACKGROUND (rank 2) enqueued first.
    background_task = asyncio.create_task(_waiter("background", RequestPriority.BACKGROUND.value))
    await asyncio.sleep(0.01)

    # Let it age past 2 full intervals (rank 2 -> effectively rank 0,
    # matching INTERACTIVE) before any INTERACTIVE requests arrive.
    await asyncio.sleep(aging_interval_s * 2.5)

    # Now a burst of fresh INTERACTIVE requests arrives -- without aging,
    # these would all jump the queue ahead of "background" forever.
    interactive_tasks = [
        asyncio.create_task(_waiter(f"interactive-{i}", RequestPriority.INTERACTIVE.value))
        for i in range(3)
    ]
    await asyncio.sleep(0.01)

    release_holder.set()
    await holder_task
    await asyncio.gather(background_task, *interactive_tasks)

    # "background" must not be last -- it aged into parity with (or above)
    # the freshly-arrived INTERACTIVE requests and was served promptly,
    # not starved behind all three of them.
    assert order[0] == "background", f"background was starved, full order: {order}"


@pytest.mark.asyncio
async def test_priority_does_not_bypass_bounded_queue_depth():
    limiter = ConcurrencyLimiter(aging_interval_s=100.0)
    limiter.configure("dep-1", max_concurrency=1, max_queue_depth=1)

    holder_entered = asyncio.Event()
    release_holder = asyncio.Event()

    async def _holder():
        async with await limiter.acquire("dep-1"):
            holder_entered.set()
            await release_holder.wait()

    async def _waiter(priority: str):
        async with await limiter.acquire("dep-1", priority=priority):
            pass

    holder_task = asyncio.create_task(_holder())
    await holder_entered.wait()

    waiter_task = asyncio.create_task(_waiter(RequestPriority.BACKGROUND.value))
    await asyncio.sleep(0.02)  # occupies the single queue slot

    # Even the HIGHEST priority must be rejected once the bounded queue is full.
    with pytest.raises(QueueFullError):
        async with await limiter.acquire("dep-1", priority=RequestPriority.INTERACTIVE.value):
            pass

    release_holder.set()
    await holder_task
    await waiter_task
