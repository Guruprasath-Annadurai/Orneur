"""
Concurrency control + backpressure per deployment. Phase 0 found no
semaphore/queue/concurrency cap anywhere in the serving path -- every
simultaneous chat request independently opened its own connection to
Ollama with no coordination, which this session's own evaluation runs hit
directly as CPU-contention timeouts.

ConcurrencyLimiter is a per-deployment bounded permit pool with an
explicit queue-depth cap ahead of it: a request either acquires a permit
immediately, waits in a bounded priority-aware queue, or is rejected
outright with QueueFullError -- never accepted into unbounded memory.

Priority scheduling (Phase 2.1): RequestPriority (contracts.py) previously
existed on InferenceRequest but the queue was plain FIFO. Waiters are now
ranked by priority with AGING -- the longer a lower-priority request
waits, the better its effective rank gets, until it is eventually treated
as top priority. This guarantees no priority class starves indefinitely
(bounded fairness) while still generally preferring higher-priority
requests when wait times are short. Same-priority waiters are still
strictly FIFO (tie-broken by enqueue time), so this is fully backward
compatible with every caller that never sets a priority.
"""
from __future__ import annotations

import asyncio
import time
from dataclasses import dataclass, field

from orca.gateway.contracts import RequestPriority
from orca.gateway.errors import QueueFullError, QueueTimeoutError

_PRIORITY_RANK: dict[str, int] = {
    RequestPriority.INTERACTIVE.value: 0,
    RequestPriority.AGENT.value: 1,
    RequestPriority.BACKGROUND.value: 2,
    RequestPriority.EVALUATION.value: 3,
    RequestPriority.TRAINING_SUPPORT.value: 4,
}

# Every this-many seconds a waiter spends queued, its effective priority
# rank improves by 1 -- a BACKGROUND request (rank 2) waiting 2 intervals
# becomes indistinguishable from a fresh INTERACTIVE request (rank 0).
# Small default so tests can run fast; production callers can configure a
# larger interval via ConcurrencyLimiter(aging_interval_s=...).
_DEFAULT_AGING_INTERVAL_S = 5.0


@dataclass
class ConcurrencyStats:
    active: int = 0
    queued: int = 0
    max_concurrency: int = 0
    max_queue_depth: int = 0


class _Waiter:
    __slots__ = ("priority", "enqueued_at", "future")

    def __init__(self, priority: str, future: asyncio.Future):
        self.priority = priority
        self.enqueued_at = time.monotonic()
        self.future = future

    def effective_rank(self, now: float, aging_interval_s: float) -> float:
        base = _PRIORITY_RANK.get(self.priority, _PRIORITY_RANK[RequestPriority.BACKGROUND.value])
        if aging_interval_s <= 0:
            return float(base)
        aged = (now - self.enqueued_at) / aging_interval_s
        return max(0.0, base - aged)


class _DeploymentLimiter:
    def __init__(self, max_concurrency: int, max_queue_depth: int, aging_interval_s: float):
        self.max_concurrency = max_concurrency
        self.max_queue_depth = max_queue_depth
        self.aging_interval_s = aging_interval_s
        self._active = 0
        self._waiters: list[_Waiter] = []
        self._lock = asyncio.Lock()

    def _hand_off_permit_to_next_waiter(self) -> bool:
        """
        Picks the best-ranked waiter and grants it the permit directly
        (transfer, not release-then-reacquire -- avoids a race where a
        brand-new request could sneak in between). Skips any waiter whose
        future is already done/cancelled (e.g. it timed out concurrently
        with this call) and tries the next-best instead. Returns True if a
        waiter was actually granted the permit, False if none were (permit
        should be released back to the pool instead).
        """
        while self._waiters:
            now = time.monotonic()
            best = min(self._waiters, key=lambda w: (w.effective_rank(now, self.aging_interval_s), w.enqueued_at))
            self._waiters.remove(best)
            if not best.future.done():
                best.future.set_result(True)
                return True
        return False


class ConcurrencyLimiter:
    """
    One limiter instance is shared across the process; call sites pass a
    deployment_id so limits are configured/enforced independently per
    deployment (a slow/overloaded deployment backs up its own queue
    without affecting any other deployment's capacity).
    """

    def __init__(self, aging_interval_s: float = _DEFAULT_AGING_INTERVAL_S):
        self._limiters: dict[str, _DeploymentLimiter] = {}
        self._aging_interval_s = aging_interval_s

    def configure(self, deployment_id: str, max_concurrency: int, max_queue_depth: int) -> None:
        self._limiters[deployment_id] = _DeploymentLimiter(max_concurrency, max_queue_depth, self._aging_interval_s)

    def _get(self, deployment_id: str) -> _DeploymentLimiter:
        if deployment_id not in self._limiters:
            # Sensible default if a caller forgot to configure() first --
            # never silently unbounded.
            self.configure(deployment_id, max_concurrency=4, max_queue_depth=16)
        return self._limiters[deployment_id]

    def stats(self, deployment_id: str) -> ConcurrencyStats:
        lim = self._get(deployment_id)
        return ConcurrencyStats(
            active=lim._active, queued=len(lim._waiters),
            max_concurrency=lim.max_concurrency, max_queue_depth=lim.max_queue_depth,
        )

    async def acquire(self, deployment_id: str, queue_timeout_s: float | None = None, priority: str = RequestPriority.INTERACTIVE.value):
        """
        Async context manager. Usage:
            async with await limiter.acquire(deployment_id, priority=...):
                ... do the generation ...
        The permit is guaranteed released on ANY exit path -- normal
        return, exception, or cancellation -- via __aexit__ below (see
        tests/test_gateway_concurrency.py for the explicit leak-proof
        verification of all three paths).
        """
        return _AcquireContext(self._get(deployment_id), queue_timeout_s, priority)


class _AcquireContext:
    def __init__(self, limiter: _DeploymentLimiter, queue_timeout_s: float | None, priority: str):
        self._limiter = limiter
        self._queue_timeout_s = queue_timeout_s
        self._priority = priority
        self._acquired = False
        self._waiter: "_Waiter | None" = None

    async def __aenter__(self):
        lim = self._limiter
        async with lim._lock:
            if lim._active < lim.max_concurrency and not lim._waiters:
                lim._active += 1
                self._acquired = True
                return self
            if len(lim._waiters) >= lim.max_queue_depth:
                raise QueueFullError(
                    f"queue depth {len(lim._waiters)} >= max {lim.max_queue_depth}, "
                    f"active {lim._active} >= max concurrency {lim.max_concurrency}"
                )
            future: asyncio.Future = asyncio.get_event_loop().create_future()
            waiter = _Waiter(self._priority, future)
            self._waiter = waiter
            lim._waiters.append(waiter)

        t0 = time.monotonic()
        try:
            if self._queue_timeout_s is not None:
                try:
                    await asyncio.wait_for(future, timeout=self._queue_timeout_s)
                except asyncio.TimeoutError:
                    async with lim._lock:
                        if waiter in lim._waiters:
                            lim._waiters.remove(waiter)
                        elif future.done() and not future.cancelled():
                            # Rare race: the permit was handed to this
                            # waiter concurrently with the timeout firing.
                            # This context is about to raise and will never
                            # use it, so it must be passed on immediately --
                            # NOT released-then-reacquired (that would
                            # transiently under-count _active by one permit
                            # while this lock is held, wrongly letting a
                            # brand-new request slip in).
                            if not lim._hand_off_permit_to_next_waiter():
                                lim._active -= 1  # no other waiter -- the permit is genuinely free now
                    raise QueueTimeoutError(f"waited {time.monotonic() - t0:.2f}s for a permit")
            else:
                await future
        except asyncio.CancelledError:
            async with lim._lock:
                if waiter in lim._waiters:
                    lim._waiters.remove(waiter)
                elif future.done() and not future.cancelled():
                    if not lim._hand_off_permit_to_next_waiter():
                        lim._active -= 1
            raise

        self._acquired = True
        return self

    async def __aexit__(self, exc_type, exc, tb):
        # Runs on every exit path: normal return, raised exception, AND
        # asyncio.CancelledError (cancellation is just another exception
        # type here) -- this is what makes permit release leak-proof.
        if self._acquired:
            lim = self._limiter
            async with lim._lock:
                if not lim._hand_off_permit_to_next_waiter():
                    lim._active -= 1
                # else: active count stays the same -- the permit transfers
                # directly to the picked waiter rather than being released
                # and immediately re-acquired, avoiding a race where a
                # brand-new request could sneak in between release and the
                # next waiter's wakeup.
        return False  # never swallow the original exception/cancellation
