# Priority Scheduling with Bounded Fairness

`RequestPriority` (`orca/gateway/contracts.py`) existed on `InferenceRequest` since Phase 2, but `ConcurrencyLimiter`'s queue was plain FIFO — priority was carried on every request and used by nothing. This phase activates it, without letting priority defeat the bounded backpressure Phase 2 built.

## Priority ranks

```python
_PRIORITY_RANK = {
    INTERACTIVE:      0,   # lower rank = served first
    AGENT:            1,
    BACKGROUND:       2,
    EVALUATION:       3,
    TRAINING_SUPPORT: 4,
}
```

## Aging — the starvation guard

A pure priority queue lets a steady stream of high-priority traffic starve everything below it forever. `_Waiter.effective_rank(now, aging_interval_s)` prevents that:

```python
effective_rank = max(0, base_rank - (time_waited / aging_interval_s))
```

Every `aging_interval_s` seconds a request has spent queued, its effective rank improves by 1, floored at 0. A `BACKGROUND` request (rank 2) that has waited two full intervals becomes indistinguishable from a fresh `INTERACTIVE` request (rank 0) — it will win ties against new arrivals rather than being pushed behind them forever. Default `aging_interval_s` is 5.0s (`ConcurrencyLimiter(aging_interval_s=...)` is configurable per instance; tests use much smaller values to run fast and deterministically).

Same-priority waiters remain strictly FIFO: `effective_rank` ties break on `enqueued_at`, so callers that never set a priority (defaulting to `INTERACTIVE`) see byte-for-byte the same ordering as before this phase — required for backward compatibility.

## Mechanism: hand-off, not release-then-reacquire

`_DeploymentLimiter` was rewritten from an `asyncio.Semaphore` to a manual waiter list, because a semaphore's `release()` wakes waiters in acquisition order — no way to re-rank them by priority/age. `_hand_off_permit_to_next_waiter()` instead:

1. Scans all pending waiters, picks the one with the lowest `(effective_rank, enqueued_at)`.
2. Hands the permit **directly** to that waiter's future (`future.set_result(True)`) rather than releasing the permit back to a pool and letting whoever acquires next win it. Direct hand-off closes a race where a brand-new request could acquire the freed permit before an already-waiting, higher-priority request gets a chance.
3. If the chosen waiter's future is already done (e.g. it timed out concurrently with the hand-off), it's skipped and the next-best is tried — the loop only stops once a live waiter is granted the permit, or no waiters remain (permit goes back to the free pool).

`acquire(deployment_id, queue_timeout_s=None, priority=RequestPriority.INTERACTIVE.value)` is the public API — `priority` is optional and defaults to `INTERACTIVE`, so every pre-Phase-2.1 caller keeps its exact existing behavior with zero code changes. `ModelGateway.generate()`/`.stream()` now pass `priority=request.priority.value` into `concurrency.acquire()`.

## Priority never bypasses bounded backpressure

`max_queue_depth` is enforced identically regardless of priority — a `QueueFullError` is raised for **any** priority, including the highest, once the bounded queue is full. Priority only re-orders who is served next among requests that were already admitted to the queue; it cannot admit more requests than the queue depth allows. This was an explicit constraint: priority scheduling must never let a flood of "urgent" requests defeat the backpressure guarantees Phase 2 built.

## A related concurrency-safety bug found while testing the integrated path

Writing the timeout-through-the-integrated-path closure test (`tests/test_api_gateway_integration.py::test_queue_timeout_surfaces_through_the_real_api_without_reaching_ollama`) surfaced a real bug: `ConcurrencyLimiter.configure()` unconditionally replaced the `_DeploymentLimiter` object for a `deployment_id`. `ModelGateway.register_deployment()` calls `configure()` on **every** request (idempotent registration is deliberate — see `orca/gateway/wiring.py`'s "safe to call every request"), so under real concurrent traffic, one request's registration could silently discard another concurrently-in-flight request's `_active` permit count and orphan its `_waiters` futures — a genuine risk of over-admission past `max_concurrency`, or a legitimately-queued waiter left stuck forever pointing at a `_DeploymentLimiter` object no longer referenced by `self._limiters[deployment_id]`.

Fixed by making `configure()` idempotent with respect to in-flight state: if a limiter already exists for the `deployment_id`, its `max_concurrency`/`max_queue_depth` are updated **in place** rather than the object being replaced, preserving `_active`/`_waiters`/`_lock` exactly. `tests/test_gateway_concurrency.py::test_reconfigure_while_a_permit_is_held_does_not_lose_it` proves a permit held across a reconfigure is not lost, and that a subsequent acquire attempt correctly queues/times out rather than being wrongly admitted.

## Tests

`tests/test_gateway_priority_scheduling.py` (4 tests):

1. Higher priority served before lower priority queued at nearly the same time (interactive jumps ahead of background).
2. Same-priority waiters remain strictly FIFO (backward compatibility for every caller that never sets a priority).
3. **Starvation-prevention proof**: a `BACKGROUND` request that has aged past two intervals is served promptly even against a fresh burst of `INTERACTIVE` arrivals — the core bounded-fairness guarantee, not just "priority mostly wins."
4. Priority does not bypass `max_queue_depth` — even `INTERACTIVE` is rejected with `QueueFullError` once the bounded queue is full.

All 7 pre-existing tests in `tests/test_gateway_concurrency.py` pass unchanged against the rewritten limiter, confirming the rewrite preserved Phase 2's semaphore-based behavior exactly for every caller that doesn't use priority.
