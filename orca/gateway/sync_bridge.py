"""
Bridges the (async) ModelGateway to the synchronous interface every
existing caller (AgentLoop, ContextManager, api.py) already uses via
orca.brain.providers.OrcaBrain. Must be safe to call from a thread that is
ALREADY running an asyncio event loop (FastAPI/uvicorn's main thread,
since orca/serve/api.py's `for chunk in gen:` iterates a sync generator
directly on the event-loop thread, not inside asyncio.to_thread) -- so
this always drives the async work on a dedicated background thread with
its own event loop, communicating back via thread-safe primitives
(queue.Queue / a plain result box), never nested asyncio.run()/
run_until_complete() calls on the calling thread itself.
"""
from __future__ import annotations

import asyncio
import queue
import threading
from typing import AsyncIterator, Callable, Iterator, TypeVar

T = TypeVar("T")

_DONE = object()


def run_async_in_thread(coro_factory: Callable[[], "asyncio.Future"]):
    """Runs one coroutine to completion on a dedicated background thread's
    own event loop and returns its result (or re-raises its exception) on
    the calling thread. Safe regardless of whether the calling thread
    already has a running event loop."""
    result_box: dict = {}

    def _runner():
        loop = asyncio.new_event_loop()
        asyncio.set_event_loop(loop)
        try:
            result_box["result"] = loop.run_until_complete(coro_factory())
        except BaseException as e:  # noqa: BLE001 -- must propagate, including asyncio.CancelledError
            result_box["error"] = e
        finally:
            loop.close()

    thread = threading.Thread(target=_runner, daemon=True)
    thread.start()
    thread.join()
    if "error" in result_box:
        raise result_box["error"]
    return result_box["result"]


def run_async_gen_in_thread(agen_factory: Callable[[], AsyncIterator[T]]) -> Iterator[T]:
    """Same safety property as run_async_in_thread, for an async generator
    -- yields items to the caller synchronously as they arrive, via a
    thread-safe queue.Queue (a plain OS-level blocking primitive, not
    asyncio-based, so `.get()` never conflicts with any event loop running
    on the calling thread)."""
    q: "queue.Queue" = queue.Queue()

    def _runner():
        loop = asyncio.new_event_loop()
        asyncio.set_event_loop(loop)

        async def _drain():
            try:
                async for item in agen_factory():
                    q.put(("item", item))
            except BaseException as e:  # noqa: BLE001
                q.put(("error", e))
                return
            q.put(("done", None))

        try:
            loop.run_until_complete(_drain())
        finally:
            loop.close()

    thread = threading.Thread(target=_runner, daemon=True)
    thread.start()
    try:
        while True:
            kind, payload = q.get()
            if kind == "item":
                yield payload
            elif kind == "error":
                raise payload
            else:
                break
    finally:
        thread.join()
