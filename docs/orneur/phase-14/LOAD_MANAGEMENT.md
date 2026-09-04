# Phase 14 §24-28 — Load Management

## What already existed (confirmed by reading the code, not built this phase)

`orca/gateway/concurrency.py`'s `ConcurrencyLimiter`/`_DeploymentLimiter`
already implements everything spec §24-27 asks for, per-deployment:

- **Bounded concurrency** (`max_concurrency`) and a **bounded queue**
  (`max_queue_depth`) — a request beyond both is rejected, not queued
  unboundedly (spec §27: "bounded queue, then explicit overload
  response, not infinite waiting").
- **Priority with aging** (`_Waiter.effective_rank()`): waiters are
  ranked by priority, but the longer a lower-priority request waits,
  the more its effective rank improves (`aging_interval_s`), which is
  the standard fix for priority-queue starvation (spec §26: "no
  permanent starvation").
- **Bounded queue timeout** (`queue_timeout_s` on `acquire()`).

`orca/gateway/circuit_breaker.py`'s per-deployment `CircuitBreaker`
already exists for the "quarantine a repeatedly-failing deployment"
requirement (spec §41).

**Phase 14 did not need to build any of this — it already existed.**
The one confirmed gap (from `CURRENT_DEPLOYMENT_ARCHITECTURE.md`'s
audit) is that both mechanisms are **per-process** (`_breakers`,
`_waiters` are plain in-memory structures with no cross-process
accounting).

## The distributed backpressure gap (spec §25) — disclosed, not fixed this phase

"Do not let multiple API workers independently overload one inference
worker" requires capacity accounting **shared across** the processes
making requests to that inference worker, not per-process limiters that
each independently think they have the full `max_concurrency` budget.
Today, if N API workers each run their own `ConcurrencyLimiter` pointed
at the same downstream deployment, the deployment can receive up to
N × `max_concurrency` concurrent requests — a real oversubscription
risk once ORNEUR runs more than one API worker.

**Not fixed this phase.** The correct fix (a shared, Redis- or
Postgres-backed concurrency counter, following the exact same pattern
already proven for Godmode leases and chat sessions) is a natural next
step, explicitly out of scope for this pass given the priority given to
the authority-distribution work. Recorded here as a real, specific,
actionable gap rather than left implicit.

## Cognitive budgets (spec §28) — see `CANCELLATION_AND_RETRY.md`

Budget propagation across workers is covered there since it shares the
same underlying mechanism (a single `CognitiveBudget` object threaded
through, not recreated).
