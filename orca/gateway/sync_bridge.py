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
    on the calling thread).

    Cancellation: if the returned sync generator is closed early (client
    disconnect on /api/stream triggers exactly this via Starlette's
    StreamingResponse cleanup), the abandoned drain must not be left to run
    to completion -- that would block whatever thread calls .close() for
    however long the underlying generation still had left, and would hold
    the Gateway's concurrency permit for a request nobody is reading
    anymore. The background work runs as a cancellable asyncio.Task; the
    generator's `finally` cancels it via `loop.call_soon_threadsafe` (safe
    to call from a different thread than the one running that loop) before
    joining, so `close()`/GeneratorExit propagates real
    asyncio.CancelledError into agen_factory() -- reaching the same
    permit-release-on-cancellation path already proven leak-proof in
    tests/test_gateway_concurrency.py -- instead of just waiting it out.
    """
    q: "queue.Queue" = queue.Queue()
    state: dict = {}
    ready = threading.Event()

    def _runner():
        loop = asyncio.new_event_loop()
        asyncio.set_event_loop(loop)
        state["loop"] = loop

        async def _drain():
            try:
                async for item in agen_factory():
                    q.put(("item", item))
            except asyncio.CancelledError:
                q.put(("cancelled", None))
                return
            except BaseException as e:  # noqa: BLE001
                q.put(("error", e))
                return
            q.put(("done", None))

        task = loop.create_task(_drain())
        state["task"] = task
        ready.set()
        try:
            loop.run_until_complete(task)
        except asyncio.CancelledError:
            pass
        finally:
            loop.close()

    thread = threading.Thread(target=_runner, daemon=True)
    thread.start()
    ready.wait()
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
        loop = state.get("loop")
        task = state.get("task")
        if loop is not None and task is not None and not task.done():
            loop.call_soon_threadsafe(task.cancel)
        thread.join()
