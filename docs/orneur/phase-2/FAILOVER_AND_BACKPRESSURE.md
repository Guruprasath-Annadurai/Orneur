# Failover, Circuit Breaking, and Backpressure

## Failover — what exists, and the real constraint on it

Per explicit instruction, failover must never let a production request fall over to an experimental model merely because it's available. Today's `resolve_deployment()` already encodes the right STRUCTURE for this (production preferred over experimental, alias-scoped requests never leak across lifecycle boundaries) — but a genuine "failover" scenario (production deployment A degrades, traffic shifts to production deployment B for the SAME model+lifecycle) requires **multiple registered PRODUCTION-lifecycle deployments for the same model**, which does not exist in this project today (Novus has exactly one candidate deployment path — local Ollama — and is currently `NOT_PROMOTABLE` in the first place, so there is no live production deployment to fail over from or to). The routing-safety logic that would make cross-deployment failover safe (never falling back to a lower lifecycle tier) is built and tested; the scenario itself is not yet exercisable against real infrastructure because the prerequisite — a second production-grade deployment — doesn't exist yet. This is an honest architectural-readiness statement, not a working failover demo.

## Circuit breaking (see `MODEL_GATEWAY.md` for full detail)

Per-deployment, `CLOSED`/`OPEN`/`HALF_OPEN`, never global. This IS fully exercisable today and is tested end-to-end through the gateway (not just the breaker in isolation): a deployment that fails repeatedly stops receiving requests entirely (verified via call-count assertion, not just a returned error), and a single successful `HALF_OPEN` probe closes it again.

## Backpressure / concurrency

Per-deployment bounded queue + concurrency semaphore (see `MODEL_GATEWAY.md`). `QueueFullError` for an unaccepted request, `QueueTimeoutError` for one that waited too long — both structured, both distinguishable, neither is "the process ran out of memory." Verified under real concurrent load in `tests/test_gateway_chaos.py::test_chaos_queue_full_rejects_cleanly_not_unbounded_memory` and the dedicated `tests/test_gateway_concurrency.py` suite.

## Load shedding

There is no scenario in the current codebase where a rejected request leaves orphaned state: `QueueFullError`/`CircuitOpenError` are raised before any resource (permit, HTTP connection, task) is acquired — confirmed by the concurrency limiter's own leak-proof-release tests, which show the accounting stays correct even under a burst of rejected requests.

## Request priority

`InferenceRequest.priority` (`RequestPriority` enum: `INTERACTIVE`/`AGENT`/`BACKGROUND`/`EVALUATION`/`TRAINING_SUPPORT`) exists in the contract but is **not yet consulted by the gateway's own queuing logic** — `ConcurrencyLimiter` treats all queued requests as FIFO regardless of priority. Per instruction ("do not implement an excessively complex scheduler... at minimum, prevent long background/evaluation requests from trivially starving interactive workloads"), this is flagged as real, scoped follow-up work rather than silently implemented as a no-op: the field exists so callers can already start setting it correctly, and a priority-aware queue (e.g. a small number of separate priority lanes rather than one FIFO queue) is the natural next increment once real multi-priority traffic exists to validate against.
