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

Claude's ``/api/stream`` integration MUST pass every delta through
``orca.serve.stream_dlp.StreamRedactor`` (or an equivalent whole-stream
redactor) before external delivery or persistence. The Kernel only
accumulates the complete raw string for its own ``CognitiveResult.output``;
callers that persist must redacted-scan that final string as today.

The channel is intentionally bounded and never silently drops deltas:
a full queue blocks the producer (gateway consumption) until the consumer
drains it, fails closed, or cancels.
"""
from __future__ import annotations

import asyncio
from collections.abc import AsyncIterator, Awaitable, Callable
from dataclasses import dataclass
from typing import Protocol, runtime_checkable

# Default bound: enough for token pacing without unbounded RAM growth.
DEFAULT_RAW_DELTA_QUEUE_SIZE = 64

RawDeltaHook = Callable[[str], Awaitable[None]]


@runtime_checkable
class RawDeltaSink(Protocol):
    """Async sink for unredacted InferenceChunk.delta values."""

    async def on_raw_delta(self, delta: str) -> None: ...


@dataclass
class _Sentinel:
    kind: str  # "end" | "error"
    error: BaseException | None = None


class RawDeltaChannel:
    """Bounded async queue bridging Kernel production → API consumption.

    - ``push`` never discards; it awaits when the queue is full.
    - ``close`` / ``fail`` are idempotent end markers for the consumer.
    - Cancellation of the consumer should cancel the Kernel task so the
      gateway stream is aclosed (see Kernel ``_answer_directly``).
    """

    def __init__(self, *, maxsize: int = DEFAULT_RAW_DELTA_QUEUE_SIZE):
        if maxsize < 1:
            raise ValueError("RawDeltaChannel maxsize must be >= 1")
        self._q: asyncio.Queue[str | _Sentinel] = asyncio.Queue(maxsize=maxsize)
        self._closed = False
        self._maxsize = maxsize

    @property
    def maxsize(self) -> int:
        return self._maxsize

    @property
    def closed(self) -> bool:
        return self._closed

    async def push(self, delta: str) -> None:
        """Enqueue one raw delta. Blocks if full — never drops."""
        if self._closed:
            raise RuntimeError("RawDeltaChannel is closed; refusing further raw deltas")
        if not delta:
            return
        await self._q.put(delta)

    async def on_raw_delta(self, delta: str) -> None:
        """Protocol-compatible alias for ``push`` (use as CognitiveRequest hook)."""
        await self.push(delta)

    def close(self) -> None:
        if self._closed:
            return
        self._closed = True
        try:
            self._q.put_nowait(_Sentinel("end"))
        except asyncio.QueueFull:
            # Consumer is behind; schedule the end marker once a slot frees.
            asyncio.get_running_loop().create_task(self._q.put(_Sentinel("end")))

    def fail(self, exc: BaseException) -> None:
        if self._closed:
            return
        self._closed = True
        try:
            self._q.put_nowait(_Sentinel("error", error=exc))
        except asyncio.QueueFull:
            asyncio.get_running_loop().create_task(self._q.put(_Sentinel("error", error=exc)))

    def as_hook(self) -> RawDeltaHook:
        return self.on_raw_delta

    async def __aiter__(self) -> AsyncIterator[str]:
        while True:
            item = await self._q.get()
            if isinstance(item, _Sentinel):
                if item.kind == "error" and item.error is not None:
                    raise item.error
                return
            yield item
