"""
Bridge a blocking (synchronous) token generator into an async stream.

Real gap this closes (Checkpoint 1): ``/api/stream`` iterated
``sess.agent.stream(...)`` with a plain ``for chunk in gen`` inside an
``async def`` handler. That generator does blocking network I/O (the model
backend), so every wait for the next token froze the whole event loop -- one
slow generation stalled health probes and every other user's request.

``aiter_blocking`` pulls each item in a worker thread, so the loop stays free.
When the consumer stops early (client disconnect, cancellation, an error in
the consumer) the underlying generator is closed -- which unwinds the backend
call and releases its connection. If a ``next()`` is still in flight in the
worker thread at that moment, the close is deferred until it returns: a
generator cannot be closed while another thread is executing it.

This is cancellation of the *iteration*. It cannot interrupt a backend call
that is blocked inside a read; the thread finishes that read, then closes.

DEF-CP1-01 (Checkpoint 2 finding): Checkpoint 1's pool had a fixed worker
count but an UNBOUNDED submission queue -- ``ThreadPoolExecutor.submit``
never blocks or refuses; past ``max_workers`` concurrent streams, requests
just piled up in the executor's internal queue, each one holding its
generator, request state and buffers alive indefinitely while it waited for
a thread. A slow/unresponsive backend (every worker stuck on a stalled read)
combined with continued incoming requests had no ceiling: unbounded queued
work, unbounded memory, and no signal to the caller that anything was wrong
until requests the caller had already given up on finally got a thread.

``StreamAdmission`` is the fix: a bounded semaphore sized to the worker
count, acquired by the ROUTE before it starts consuming the generator.
Admission is a fast, non-blocking try: at capacity, the caller is rejected
immediately with a classified, retryable error -- never queued. One admitted
stream occupies exactly one admission slot and, while waiting on a token,
exactly one worker thread; the two are kept in lockstep by using the same
capacity for both, so "admitted" and "has a thread available when it needs
one" are the same guarantee.

DEF-CP1-01 hardening (post-Checkpoint-2-audit finding): that lockstep claim
was wrong for the cancelled-mid-wait case. ``aiter_blocking`` previously
wrapped its whole body in ``async with StreamAdmission():`` -- which
releases on *Python-level scope exit*, i.e. the moment this async
generator unwinds (cancellation, the consumer calling ``aclose()``). But
when the consumer is cancelled while a ``next()`` call is genuinely stuck
in a worker thread (a hung backend), that thread is NOT free yet -- it's
still blocked inside ``next()`` and will stay that way until the backend
eventually returns or the process is killed. Releasing admission at scope
exit let a new stream be ADMITTED while the actual thread count available
to serve it hadn't changed: repeat "start a stream against a hung backend,
then cancel" ``MAX_CONCURRENT_STREAMS`` times, and every worker thread is
now permanently wedged in a ``next()`` that will never return, while
admission has long since reset to 0 and kept accepting -- new streams'
``_POOL.submit()`` calls then queue forever behind threads that are never
coming back. Exactly the unbounded-queuing failure mode this module exists
to prevent, just reached via repeated cancellation instead of concurrency.

The fix: admission is now acquired and released explicitly, not via
``async with``, and release is deferred to the point where the worker
thread is actually known to be free again -- the ``concurrent.futures``
completion callback on the in-flight ``next()`` call, not this async
generator's own cleanup. A cancelled/abandoned stream keeps its admission
slot occupied for exactly as long as its thread stays occupied, which is
the only thing admission is meant to track.
"""
from __future__ import annotations

import asyncio
import concurrent.futures
import logging
import os
import threading
from typing import AsyncIterator, Iterator, TypeVar

T = TypeVar("T")

_logger = logging.getLogger("orca.serve.streaming")
_END = object()

# Same capacity for the thread pool and the admission semaphore (see module
# docstring): an admitted stream is guaranteed a worker when it next needs
# one, and nothing queues past that. Configurable for operators who need a
# different ceiling for their hardware; the default is conservative for a
# single-process deployment.
MAX_CONCURRENT_STREAMS = int(os.environ.get("ORNEUR_MAX_CONCURRENT_STREAMS", "64"))

_POOL = concurrent.futures.ThreadPoolExecutor(
    max_workers=MAX_CONCURRENT_STREAMS, thread_name_prefix="orca-stream",
)

# A plain counter + lock, not asyncio.Semaphore: asyncio's Semaphore has no
# non-blocking try-acquire, and admission here must REJECT at capacity, never
# wait for a slot (that wait would just be the same unbounded queuing this
# fix exists to remove, moved one layer up).
_admission_lock = threading.Lock()
_in_use = 0
_shutdown_lock = threading.Lock()
_shut_down = False


class StreamingUnavailable(Exception):
    """Raised by ``StreamAdmission`` when the pool is at capacity or shutting down."""


class StreamAdmission:
    """One admission slot. ``acquire()``/``release()`` are plain, synchronous,
    non-blocking calls -- there is nothing to await; the whole point is that
    acquiring never waits for a slot to free up, it either gets one now or
    raises immediately.

    Also usable as ``async with StreamAdmission():`` for callers who DO want
    scope-tied acquire/release (tests, and anything that isn't deferring
    release past its own exit) -- ``aiter_blocking`` below deliberately does
    NOT use that form, for the reason in the module docstring.
    """

    def __init__(self) -> None:
        self._acquired = False

    def acquire(self) -> None:
        global _in_use
        if _shut_down:
            raise StreamingUnavailable("streaming is shutting down")
        with _admission_lock:
            if _in_use >= MAX_CONCURRENT_STREAMS:
                raise StreamingUnavailable(f"at capacity ({MAX_CONCURRENT_STREAMS} concurrent streams)")
            _in_use += 1
            self._acquired = True

    def release(self) -> None:
        global _in_use
        if self._acquired:
            with _admission_lock:
                _in_use -= 1
            self._acquired = False

    async def __aenter__(self) -> "StreamAdmission":
        self.acquire()
        return self

    async def __aexit__(self, *_exc) -> None:
        self.release()


def pool_stats() -> dict:
    """Point-in-time admission/pool occupancy, for /readyz and tests."""
    with _admission_lock:
        in_use = _in_use
    return {"capacity": MAX_CONCURRENT_STREAMS, "in_use": in_use, "shut_down": _shut_down}


def shutdown_streaming_pool(wait: bool = True) -> None:
    """Stop accepting new work and release pool threads. Call once, at app exit.

    Idempotent. In-flight generator closes already scheduled on the pool are
    allowed to finish (``cancel_futures=False``) so a client mid-disconnect
    still gets its backend connection released; new submissions after this
    call raise ``RuntimeError`` from the executor, which ``aiter_blocking``
    lets propagate as a normal stream error.
    """
    global _shut_down
    with _shutdown_lock:
        if _shut_down:
            return
        _shut_down = True
    _POOL.shutdown(wait=wait, cancel_futures=False)


def _close_quietly(gen: Iterator) -> None:
    close = getattr(gen, "close", None)
    if close is None:
        return
    try:
        close()
    except Exception:  # closing must never mask the original outcome
        _logger.warning("closing a stream generator failed", exc_info=True)


def _schedule_close(gen: Iterator) -> concurrent.futures.Future | None:
    """Submit the close to the pool; if the pool is already shut down
    (``shutdown_streaming_pool`` ran mid-stream), close synchronously in this
    thread instead of letting the executor's RuntimeError propagate and mask
    whatever exception/cancellation is already unwinding through the caller."""
    try:
        return _POOL.submit(_close_quietly, gen)
    except RuntimeError:
        _close_quietly(gen)
        return None


async def aiter_blocking(gen: Iterator[T]) -> AsyncIterator[T]:
    """Iterate a blocking generator without blocking the event loop.

    Does its own admission: raises :class:`StreamingUnavailable` immediately
    if the pool is saturated, instead of silently queuing behind it (the
    caller never even starts reading from the backend in that case).

    Admission release is NOT tied to this async generator's own exit (see
    the "DEF-CP1-01 hardening" module docstring section for why): it is
    deferred to whenever the worker thread that was actually occupied is
    confirmed free again, which may be well after this function has
    returned/been cancelled, if a ``next()`` call is genuinely stuck.
    """
    admission = StreamAdmission()
    admission.acquire()  # raises StreamingUnavailable immediately; nothing to release yet if so
    inflight: concurrent.futures.Future | None = None
    try:
        while True:
            inflight = _POOL.submit(next, gen, _END)
            item = await asyncio.wrap_future(inflight)
            inflight = None
            if item is _END:
                return
            yield item
    finally:
        if inflight is not None and not inflight.done():
            # The worker thread still owns this next() call and is NOT free
            # yet, regardless of what happens to this async generator from
            # here (cancelled, closed, or the consumer just stopped reading).
            # Release only once the callback actually fires -- i.e. only
            # once the thread is confirmed free -- so admission can never
            # outrun real thread availability, even under repeated
            # cancellation against a backend that never returns.
            def _on_worker_free(_fut: concurrent.futures.Future) -> None:
                try:
                    _close_quietly(gen)
                finally:
                    admission.release()

            inflight.add_done_callback(_on_worker_free)
        else:
            # The thread that ran the last (or only) next() call has
            # already returned -- it's free now, so release immediately
            # after scheduling/awaiting the close.
            try:
                close_future = _schedule_close(gen)
                if close_future is not None:
                    await asyncio.shield(asyncio.wrap_future(close_future))
            finally:
                admission.release()
