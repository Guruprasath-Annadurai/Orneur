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

Completion protocol (LANDMARK-01 B-01 final integration)
--------------------------------------------------------
The first revision of this module signalled the end of a stream with a
sentinel *queued* behind the data and, when the queue was full, from a
fire-and-forget ``create_task``. That left two defects: a consumer that
waited for the terminal signal before the producer was allowed to send it
could wait forever, and the terminal-enqueue task was untracked and could
outlive the request. This revision removes both.

* A channel has exactly one terminal state, set once by the *producer side*
  (``close`` = success, ``fail`` = error) or by the *consumer side*
  (``abort`` = the consumer is gone). The terminal state is a plain
  attribute, never a queued item, so it needs no free slot and no task.
* The consumer drains every buffered delta, then observes the terminal state
  exactly once (``StopAsyncIteration`` for success, the original exception
  for failure, ``ChannelClosed`` for abort).
* ``push`` blocks while the buffer is full and never discards. It is woken by
  a consumer read, by ``abort`` (raising ``ChannelClosed``) and by task
  cancellation (the waiter is always unregistered).
* ``KernelRun`` supervises the producer task. The producer reports its own
  end onto the channel, so *every* way the Kernel can end - success, any
  exception, cancellation - releases the consumer, and ``aclose`` always
  awaits the producer to completion.
"""
from __future__ import annotations

import asyncio
from collections import deque
from collections.abc import AsyncIterator, Awaitable, Callable
from typing import Generic, Protocol, TypeVar, runtime_checkable

# Default bound: enough for token pacing without unbounded RAM growth.
DEFAULT_RAW_DELTA_QUEUE_SIZE = 64

RawDeltaHook = Callable[[str], Awaitable[None]]

T = TypeVar("T")

_OPEN, _ENDED, _FAILED, _ABORTED = "open", "ended", "failed", "aborted"
TIMEOUT = object()  # returned by RawDeltaChannel.receive(timeout=...) when nothing arrived in time


@runtime_checkable
class RawDeltaSink(Protocol):
    """Async sink for unredacted InferenceChunk.delta values."""

    async def on_raw_delta(self, delta: str) -> None: ...


class ChannelClosed(RuntimeError):
    """The channel can no longer carry deltas (closed, failed or aborted)."""


class ConsumerGone(Exception):
    """Raised by ``KernelRun.deltas`` when the consumer's ``is_gone`` probe reports the client left."""


class RawDeltaChannel:
    """Bounded async buffer bridging Kernel production → API consumption.

    - ``push`` never discards; it awaits while the buffer is full.
    - ``close`` / ``fail`` / ``abort`` set a single terminal state without
      needing a free slot and without creating any task.
    - Everything runs on one event loop and no method awaits between reading
      and mutating the buffer, so the state machine needs no lock.
    """

    def __init__(self, *, maxsize: int = DEFAULT_RAW_DELTA_QUEUE_SIZE):
        if maxsize < 1:
            raise ValueError("RawDeltaChannel maxsize must be >= 1")
        self._buf: deque[str] = deque()
        self._maxsize = maxsize
        self._state = _OPEN
        self._error: BaseException | None = None
        self._waiters: list[asyncio.Future] = []
        self._terminal_observed = 0
        self._pushed = 0
        self._delivered = 0

    # ---- introspection -------------------------------------------------
    @property
    def maxsize(self) -> int:
        return self._maxsize

    @property
    def closed(self) -> bool:
        """True once any terminal state has been set (no further pushes are accepted)."""
        return self._state != _OPEN

    @property
    def state(self) -> str:
        return self._state

    @property
    def pending(self) -> int:
        return len(self._buf)

    @property
    def waiting(self) -> int:
        """Coroutines currently parked on the channel (0 after a clean finalization)."""
        return sum(1 for f in self._waiters if not f.done())

    @property
    def terminal_observed(self) -> int:
        """1 once a consumer has observed the terminal state, else 0. The producer's error is raised to the consumer exactly once."""
        return self._terminal_observed

    @property
    def pushed(self) -> int:
        return self._pushed

    @property
    def delivered(self) -> int:
        return self._delivered

    # ---- internals -----------------------------------------------------
    def _notify(self) -> None:
        waiters, self._waiters = self._waiters, []
        for fut in waiters:
            if not fut.done():
                fut.set_result(None)

    async def _park(self, timeout: float | None = None) -> bool:
        """Wait for any channel state change; False on timeout. The waiter is always unregistered, including on cancellation."""
        fut = asyncio.get_running_loop().create_future()
        self._waiters.append(fut)
        try:
            if timeout is None:
                await fut
                return True
            done, _ = await asyncio.wait({fut}, timeout=timeout)
            return bool(done)
        finally:
            if fut in self._waiters:
                self._waiters.remove(fut)
            if not fut.done():
                fut.cancel()

    # ---- producer side -------------------------------------------------
    async def push(self, delta: str) -> None:
        """Enqueue one raw delta. Blocks if full — never drops. Raises ``ChannelClosed`` if a terminal state is set (before or while waiting)."""
        while True:
            if self._state != _OPEN:
                raise ChannelClosed("RawDeltaChannel is closed; refusing further raw deltas")
            if not delta:
                return
            if len(self._buf) < self._maxsize:
                self._buf.append(delta)
                self._pushed += 1
                self._notify()
                return
            await self._park()

    async def on_raw_delta(self, delta: str) -> None:
        """Protocol-compatible alias for ``push`` (use as CognitiveRequest hook)."""
        await self.push(delta)

    def as_hook(self) -> RawDeltaHook:
        return self.on_raw_delta

    def close(self) -> None:
        """Success: the consumer drains what is buffered, then sees a clean end. Idempotent; the first terminal state wins."""
        if self._state == _OPEN:
            self._state = _ENDED
            self._notify()

    def fail(self, exc: BaseException) -> None:
        """Failure: the consumer drains what is buffered, then sees ``exc`` (once). Idempotent; the first terminal state wins."""
        if self._state == _OPEN:
            self._state = _FAILED
            self._error = exc
            self._notify()

    def abort(self) -> None:
        """The consumer is gone: discard what is buffered and wake any blocked producer (it gets ``ChannelClosed``). Idempotent."""
        if self._state == _OPEN:
            self._state = _ABORTED
            self._buf.clear()
            self._notify()

    # ---- consumer side -------------------------------------------------
    async def receive(self, timeout: float | None = None):
        """Next delta, or ``TIMEOUT`` if ``timeout`` elapsed with nothing to read.

        Raises ``StopAsyncIteration`` after a clean end, the producer's own exception after a failure, ``ChannelClosed`` after an abort."""
        while True:
            if self._buf:
                item = self._buf.popleft()
                self._delivered += 1
                self._notify()                      # a producer may be waiting for this slot
                return item
            if self._state == _ENDED:
                self._terminal_observed = 1
                raise StopAsyncIteration
            if self._state == _FAILED:
                self._terminal_observed = 1
                err, self._error = self._error, None
                self._state = _ENDED                # the error is delivered exactly once; a further read just ends
                raise err if err is not None else ChannelClosed("RawDeltaChannel failed")
            if self._state == _ABORTED:
                self._terminal_observed = 1
                raise ChannelClosed("RawDeltaChannel was aborted")
            if not await self._park(timeout):
                return TIMEOUT

    def __aiter__(self) -> "RawDeltaChannel":
        return self

    async def __anext__(self) -> str:
        return await self.receive()


class KernelRun(Generic[T]):
    """Supervises one producer coroutine feeding a ``RawDeltaChannel``.

    ``start`` creates the producer task; the producer reports its own end onto the channel, so the consumer can never hang. ``deltas`` is
    the consumer loop; ``result`` returns the producer's value (or re-raises its exception); ``aclose`` cancels and *awaits* the producer so
    nothing outlives the request.
    """

    def __init__(self, producer: Callable[[RawDeltaHook], Awaitable[T]], *, maxsize: int = DEFAULT_RAW_DELTA_QUEUE_SIZE):
        self._producer = producer
        self.channel = RawDeltaChannel(maxsize=maxsize)
        self._task: asyncio.Task[T] | None = None

    @property
    def task(self) -> "asyncio.Task[T] | None":
        return self._task

    @property
    def done(self) -> bool:
        return self._task is not None and self._task.done()

    def start(self) -> "KernelRun[T]":
        if self._task is not None:
            raise RuntimeError("KernelRun already started")
        self._task = asyncio.get_running_loop().create_task(self._run(), name="kernel-run")
        return self

    async def _run(self) -> T:
        try:
            result = await self._producer(self.channel.as_hook())
        except asyncio.CancelledError:
            self.channel.abort()
            raise
        except BaseException as exc:
            self.channel.fail(exc)
            raise
        self.channel.close()
        return result

    async def deltas(self, *, is_gone: Callable[[], Awaitable[bool]] | None = None, poll_s: float = 0.5) -> AsyncIterator[str]:
        """Yield raw deltas until the producer ends; re-raises the producer's exception.

        If ``is_gone`` is given it is probed whenever ``poll_s`` passes without a delta; a True answer raises ``ConsumerGone`` (the caller then
        ``aclose``s)."""
        while True:
            try:
                item = await self.channel.receive(timeout=poll_s if is_gone is not None else None)
            except StopAsyncIteration:
                return
            if item is TIMEOUT:
                if is_gone is not None and await is_gone():
                    raise ConsumerGone()
                continue
            yield item  # type: ignore[misc]

    async def result(self) -> T:
        if self._task is None:
            raise RuntimeError("KernelRun was never started")
        return await self._task

    async def aclose(self) -> None:
        """Stop the producer (if still running) and wait for it to finish. Safe to call repeatedly and from a cancelled context."""
        self.channel.abort()
        task = self._task
        if task is None:
            return
        cancelled_while_waiting = False
        if not task.done():
            task.cancel()
        while not task.done():
            try:
                await asyncio.wait({task})
            except asyncio.CancelledError:
                cancelled_while_waiting = True      # we are being cancelled too: keep waiting for the producer, then re-raise
        if not task.cancelled():
            task.exception()                         # mark retrieved so asyncio never logs "exception was never retrieved"
        if cancelled_while_waiting:
            raise asyncio.CancelledError()
