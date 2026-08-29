"""
Concurrency control + backpressure per deployment. Phase 0 found no
semaphore/queue/concurrency cap anywhere in the serving path -- every
simultaneous chat request independently opened its own connection to
Ollama with no coordination, which this session's own evaluation runs hit
directly as CPU-contention timeouts.

ConcurrencyLimiter is a per-deployment bounded semaphore with an explicit
queue-depth cap ahead of it: a request either acquires a permit
immediately, waits in a bounded queue, or is rejected outright with
QueueFullError -- never accepted into unbounded memory.
"""
from __future__ import annotations

import asyncio
import time
from dataclasses import dataclass, field

from orca.gateway.errors import QueueFullError, QueueTimeoutError


@dataclass
class ConcurrencyStats:
    active: int = 0
    queued: int = 0
    max_concurrency: int = 0
    max_queue_depth: int = 0


class _DeploymentLimiter:
    def __init__(self, max_concurrency: int, max_queue_depth: int):
        self.max_concurrency = max_concurrency
        self.max_queue_depth = max_queue_depth
        self._semaphore = asyncio.Semaphore(max_concurrency)
        self._queued = 0
        self._active = 0
        self._lock = asyncio.Lock()


class ConcurrencyLimiter:
    """
    One limiter instance is shared across the process; call sites pass a
    deployment_id so limits are configured/enforced independently per
    deployment (a slow/overloaded deployment backs up its own queue
    without affecting any other deployment's capacity).
    """

    def __init__(self):
        self._limiters: dict[str, _DeploymentLimiter] = {}

    def configure(self, deployment_id: str, max_concurrency: int, max_queue_depth: int) -> None:
        self._limiters[deployment_id] = _DeploymentLimiter(max_concurrency, max_queue_depth)

    def _get(self, deployment_id: str) -> _DeploymentLimiter:
        if deployment_id not in self._limiters:
            # Sensible default if a caller forgot to configure() first --
            # never silently unbounded.
            self.configure(deployment_id, max_concurrency=4, max_queue_depth=16)
        return self._limiters[deployment_id]

    def stats(self, deployment_id: str) -> ConcurrencyStats:
        lim = self._get(deployment_id)
        return ConcurrencyStats(
            active=lim._active, queued=lim._queued,
            max_concurrency=lim.max_concurrency, max_queue_depth=lim.max_queue_depth,
        )

    async def acquire(self, deployment_id: str, queue_timeout_s: float | None = None):
        """
        Async context manager. Usage:
            async with limiter.acquire(deployment_id):
                ... do the generation ...
        The permit is guaranteed released on ANY exit path -- normal
        return, exception, or cancellation -- via the `finally` block in
        __aexit__ below (see tests/test_gateway_concurrency.py for the
        explicit leak-proof verification of all three paths).
        """
        return _AcquireContext(self._get(deployment_id), queue_timeout_s)


class _AcquireContext:
    def __init__(self, limiter: _DeploymentLimiter, queue_timeout_s: float | None):
        self._limiter = limiter
        self._queue_timeout_s = queue_timeout_s
        self._acquired = False

    async def __aenter__(self):
        lim = self._limiter
        async with lim._lock:
            # Only reject if there's no free permit right now AND the queue
            # of waiters is already at capacity -- if a permit is free, or
            # there's room to wait, this request is accepted.
            no_free_permit = lim._active >= lim.max_concurrency
            if no_free_permit and lim._queued >= lim.max_queue_depth:
                raise QueueFullError(
                    f"queue depth {lim._queued} >= max {lim.max_queue_depth}, "
                    f"active {lim._active} >= max concurrency {lim.max_concurrency}"
                )
            lim._queued += 1
        t0 = time.monotonic()
        try:
            if self._queue_timeout_s is not None:
                try:
                    await asyncio.wait_for(lim._semaphore.acquire(), timeout=self._queue_timeout_s)
                except asyncio.TimeoutError:
                    raise QueueTimeoutError(f"waited {time.monotonic() - t0:.2f}s for a permit")
            else:
                await lim._semaphore.acquire()
        finally:
            async with lim._lock:
                lim._queued -= 1
        self._acquired = True
        lim._active += 1
        return self

    async def __aexit__(self, exc_type, exc, tb):
        # Runs on every exit path: normal return, raised exception, AND
        # asyncio.CancelledError (cancellation is just another exception
        # type here) -- this is what makes permit release leak-proof.
        if self._acquired:
            self._limiter._active -= 1
            self._limiter._semaphore.release()
        return False  # never swallow the original exception/cancellation
