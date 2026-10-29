"""LANDMARK-01 B-01 Wave B: RawDeltaChannel + KernelStreamBridge lifecycle."""
from __future__ import annotations

import asyncio

import pytest

from orca.cognitive.streaming import KernelStreamBridge, RawDeltaChannel


@pytest.mark.asyncio
async def test_successful_stream_closes_automatically():
    channel = RawDeltaChannel(maxsize=4)
    bridge = KernelStreamBridge(channel)

    async def producer():
        await channel.push("a")
        await channel.push("b")
        return "ok"

    bridge.start(producer())
    got = [d async for d in channel]
    assert got == ["a", "b"]
    assert await bridge.wait_result() == "ok"
    assert bridge.done() and channel.closed


@pytest.mark.asyncio
async def test_zero_chunks_terminates():
    channel = RawDeltaChannel(maxsize=2)
    bridge = KernelStreamBridge(channel)

    async def producer():
        return "empty"

    bridge.start(producer())
    got = [d async for d in channel]
    assert got == []
    assert await bridge.wait_result() == "empty"


@pytest.mark.asyncio
async def test_failure_before_first_chunk():
    channel = RawDeltaChannel(maxsize=2)
    bridge = KernelStreamBridge(channel)

    async def producer():
        raise RuntimeError("boom-early")

    bridge.start(producer())
    with pytest.raises(RuntimeError, match="boom-early"):
        async for _ in channel:
            pass
    with pytest.raises(RuntimeError, match="boom-early"):
        await bridge.wait_result()


@pytest.mark.asyncio
async def test_failure_after_several_chunks():
    channel = RawDeltaChannel(maxsize=8)
    bridge = KernelStreamBridge(channel)

    async def producer():
        await channel.push("1")
        await channel.push("2")
        raise RuntimeError("boom-mid")

    bridge.start(producer())
    seen = []
    with pytest.raises(RuntimeError, match="boom-mid"):
        async for d in channel:
            seen.append(d)
    assert seen == ["1", "2"]


@pytest.mark.asyncio
async def test_full_queue_blocks_then_drains_without_drop():
    channel = RawDeltaChannel(maxsize=1)
    received = []

    async def producer():
        for piece in ("A", "B", "C"):
            await channel.push(piece)
        channel.close()

    async def consumer():
        await asyncio.sleep(0.02)
        async for d in channel:
            received.append(d)
            await asyncio.sleep(0.02)

    await asyncio.gather(producer(), consumer())
    assert received == ["A", "B", "C"]


@pytest.mark.asyncio
async def test_cancel_while_blocked_on_push():
    channel = RawDeltaChannel(maxsize=1)
    bridge = KernelStreamBridge(channel)
    await channel.push("fill")

    async def producer():
        await channel.push("blocked")  # waits for room
        return "never"

    task = bridge.start(producer())
    await asyncio.sleep(0.05)
    assert not task.done()
    await bridge.cancel()
    assert bridge.done()
    # Consumer must unblock
    items = []
    async for d in channel:
        items.append(d)
    assert "fill" in items


@pytest.mark.asyncio
async def test_terminal_success_observed_exactly_once():
    channel = RawDeltaChannel(maxsize=4)
    channel.close()
    channel.close()
    channel.close()
    assert channel.closed
    assert [d async for d in channel] == []


@pytest.mark.asyncio
async def test_no_orphan_producer_after_cancel():
    channel = RawDeltaChannel(maxsize=2)
    bridge = KernelStreamBridge(channel)

    async def producer():
        while True:
            await channel.push("x")
            await asyncio.sleep(0.01)

    bridge.start(producer())
    await asyncio.sleep(0.05)
    await bridge.cancel()
    await asyncio.sleep(0.05)
    assert bridge.done()
    # No pending tasks named kernel-stream-producer
    pending = [t for t in asyncio.all_tasks() if t.get_name() == "kernel-stream-producer" and not t.done()]
    assert pending == []
