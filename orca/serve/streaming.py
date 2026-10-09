"""
Bridge a blocking (synchronous) token generator into an async stream.

Real gap this closes: ``/api/stream`` iterated ``sess.agent.stream(...)`` with
a plain ``for chunk in gen`` inside an ``async def`` handler. That generator
does blocking network I/O (the model backend), so every wait for the next
token froze the whole event loop -- one slow generation stalled health
probes and every other user's request.

``aiter_blocking`` pulls each item in a worker thread, so the loop stays free.
When the consumer stops early (client disconnect, cancellation, an error in
the consumer) the underlying generator is closed -- which unwinds the backend
call and releases its connection. If a ``next()`` is still in flight in the
worker thread at that moment, the close is deferred until it returns: a
generator cannot be closed while another thread is executing it.

This is cancellation of the *iteration*. It cannot interrupt a backend call
that is blocked inside a read; the thread finishes that read, then closes.
"""
from __future__ import annotations

import asyncio
import concurrent.futures
import logging
from typing import AsyncIterator, Iterator, TypeVar

T = TypeVar("T")

_logger = logging.getLogger("orca.serve.streaming")
_END = object()
# Each in-flight next() occupies one worker for the duration of a token wait.
_POOL = concurrent.futures.ThreadPoolExecutor(max_workers=128, thread_name_prefix="orca-stream")


def _close_quietly(gen: Iterator) -> None:
    close = getattr(gen, "close", None)
    if close is None:
        return
    try:
        close()
    except Exception:  # closing must never mask the original outcome
        _logger.warning("closing a stream generator failed", exc_info=True)


async def aiter_blocking(gen: Iterator[T]) -> AsyncIterator[T]:
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
            # Cancelled mid-wait: the worker thread still owns the generator.
            inflight.add_done_callback(lambda _fut: _close_quietly(gen))
        else:
            await asyncio.shield(asyncio.wrap_future(_POOL.submit(_close_quietly, gen)))
