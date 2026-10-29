"""
Internal raw-delta streaming bridge for CognitiveKernel (LANDMARK-01 B-01).

SECURITY BOUNDARY — RAW MODEL OUTPUT
------------------------------------
Deltas forwarded through ``on_raw_delta`` / ``RawDeltaChannel`` are the
**unredacted** model stream. They must NEVER be:

- yielded to a browser / SSE client,
- written to SQLite / JSONL / Redis transcript stores,
- appended to long-term memory or working-memory episodes,
- logged as message content.

``/api/stream`` MUST pass every delta through
``orca.serve.stream_dlp.StreamRedactor`` before external delivery or
persistence.

Lifecycle (Wave B correction)
-----------------------------
Terminal signaling uses an ``asyncio.Event``, not a fire-and-forget
``create_task`` to enqueue a sentinel into a full bounded queue. That
avoids orphan tasks and the producer/consumer deadlock where the
consumer waits for an end marker the producer only emits after the
consumer finishes.

``KernelStreamBridge`` owns the producer task: on success it ``close()``s
the channel; on failure it ``fail()``s; on cancel it closes and awaits
cleanup. Callers must ``await bridge.wait_result()`` or ``cancel()``.
"""
from __future__ import annotations

import asyncio
from collections.abc import AsyncIterator, Awaitable, Callable
from typing import Any, Protocol, runtime_checkable

DEFAULT_RAW_DELTA_QUEUE_SIZE = 64

RawDeltaHook = Callable[[str], Awaitable[None]]


@runtime_checkable
class RawDeltaSink(Protocol):
    """Async sink for unredacted InferenceChunk.delta values."""

    async def on_raw_delta(self, delta: str) -> None: ...


class RawDeltaChannel:
    """Bounded async queue bridging Kernel production → API consumption.

    - ``push`` never discards; it awaits when the queue is full.
    - ``close`` / ``fail`` are idempotent; they wake the consumer via Event
      (no background enqueue task).
    - Consumer drains remaining deltas after close before exiting.
    """

    def __init__(self, *, maxsize: int = DEFAULT_RAW_DELTA_QUEUE_SIZE):
        if maxsize < 1:
            raise ValueError("RawDeltaChannel maxsize must be >= 1")
        self._q: asyncio.Queue[str] = asyncio.Queue(maxsize=maxsize)
        self._wake = asyncio.Event()
        self._closed = False
        self._error: BaseException | None = None
        self._maxsize = maxsize
        self._terminal_once = False

    @property
    def maxsize(self) -> int:
        return self._maxsize

    @property
    def closed(self) -> bool:
        return self._closed

    @property
    def error(self) -> BaseException | None:
        return self._error

    def qsize(self) -> int:
        return self._q.qsize()

    async def push(self, delta: str) -> None:
        """Enqueue one raw delta. Blocks if full — never drops."""
        if self._closed:
            raise RuntimeError("RawDeltaChannel is closed; refusing further raw deltas")
        if not delta:
            return
        await self._q.put(delta)
        self._wake.set()

    async def on_raw_delta(self, delta: str) -> None:
        await self.push(delta)

    def close(self) -> None:
        """Signal successful end. Idempotent; wakes waiters exactly once."""
        if self._closed:
            return
        self._closed = True
        self._terminal_once = True
        self._wake.set()

    def fail(self, exc: BaseException) -> None:
        """Signal failed end. Idempotent."""
        if self._closed:
            return
        self._error = exc
        self._closed = True
        self._terminal_once = True
        self._wake.set()

    def as_hook(self) -> RawDeltaHook:
        return self.on_raw_delta

    async def __aiter__(self) -> AsyncIterator[str]:
        while True:
            try:
                item = self._q.get_nowait()
            except asyncio.QueueEmpty:
                if self._closed:
                    if self._error is not None:
                        raise self._error
                    return
                self._wake.clear()
                # Re-check after clear to avoid a lost wakeup between empty and wait.
                if not self._q.empty() or self._closed:
                    continue
                await self._wake.wait()
                continue
            yield item


class KernelStreamBridge:
    """Supervises ``kernel.execute`` (or equivalent) as the channel producer.

    Guarantees the channel receives exactly one terminal signal (close or
    fail) when the producer finishes, and that ``cancel()`` awaits the
    producer task so no orphan generation remains.
    """

    def __init__(self, channel: RawDeltaChannel):
        self.channel = channel
        self._task: asyncio.Task[Any] | None = None

    @property
    def task(self) -> asyncio.Task[Any] | None:
        return self._task

    def start(self, awaitable: Awaitable[Any]) -> asyncio.Task[Any]:
        if self._task is not None:
            raise RuntimeError("KernelStreamBridge already started")
        self._task = asyncio.create_task(self._run(awaitable), name="kernel-stream-producer")
        return self._task

    async def _run(self, awaitable: Awaitable[Any]) -> Any:
        try:
            result = await awaitable
        except asyncio.CancelledError:
            if not self.channel.closed:
                self.channel.close()
            raise
        except Exception as exc:
            if not self.channel.closed:
                self.channel.fail(exc)
            raise
        else:
            if not self.channel.closed:
                self.channel.close()
            return result

    async def wait_result(self) -> Any:
        if self._task is None:
            raise RuntimeError("KernelStreamBridge was never started")
        return await self._task

    async def cancel(self) -> None:
        """Cancel the producer and wait for it to finish; unblock the consumer."""
        if self._task is None:
            if not self.channel.closed:
                self.channel.close()
            return
        if not self._task.done():
            self._task.cancel()
            try:
                await self._task
            except asyncio.CancelledError:
                pass
            except Exception:
                pass
        if not self.channel.closed:
            self.channel.close()

    def done(self) -> bool:
        return self._task is None or self._task.done()
