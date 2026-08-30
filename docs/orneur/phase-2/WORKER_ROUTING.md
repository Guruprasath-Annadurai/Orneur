# Worker-Aware Routing

Phase 2 defined the `Worker` entity (`orca/gateway/worker.py`) — health status, capacity, heartbeat — but nothing in `ModelGateway.resolve_deployment()` ever consulted it. Every deployment routed purely on lifecycle/health/artifact-availability, blind to which physical worker (if any) hosted it. This phase wires worker state into the actual routing decision.

## What changed

`ModelDeployment` (`orca/gateway/deployment.py`) gained one new field:

```python
worker_id: str | None = None
```

Optional, defaulting to `None` — every deployment registered before this phase, and every deployment that has no meaningful worker concept (e.g. a frontier API passthrough), is completely unaffected. This is purely additive.

`ModelGateway` gained:

- `register_worker(worker: Worker)` — registers a `Worker` instance the gateway can consult by `worker_id`.
- `_worker_permits_routing(deployment) -> bool` — the filter. A deployment with `worker_id is None` always passes (unconstrained, backward compatible). A deployment WITH a `worker_id` is refused if that worker was never registered, or if `Worker.is_available_for_routing()` returns `False`. That method already existed in Phase 2 and already covers `UNHEALTHY`, `OFFLINE`, `DRAINING` status, stale heartbeat (>30s, `_HEARTBEAT_STALE_SECONDS`), and no spare capacity (`active_requests >= capacity`) — Phase 2.1 didn't need to reinvent any of that, just call it.
- `_rank_key(deployment) -> tuple` — deterministic ranking among multiple eligible deployments for the same request: `(worker_rank, load, deployment_id)`. `worker_rank` is `0` for a `READY` worker (or no worker constraint), `1` for `DEGRADED`. `load` is the worker's current `active_requests` (lower wins). Ties break on `deployment_id` for reproducibility. This replaces plain `candidates[0]` indexing in `resolve_deployment()` with `sorted(candidates, key=self._rank_key)[0]`, in both the aliased-lookup branch and the default-lifecycle branch.

## Routing decision, updated

`resolve_deployment()`'s eligibility filters now read:

```python
d.is_routable(...) and self._artifact_is_available(d) and self._worker_permits_routing(d)
```

A worker-constrained deployment whose worker has gone `UNHEALTHY`/`OFFLINE`/`DRAINING`, or whose heartbeat is stale, is excluded from `candidates` before ranking even runs — it behaves exactly like an unroutable lifecycle state: `ModelNotRoutableError` if it was the only candidate, otherwise the gateway falls through to the next eligible deployment.

## Why this is safe

- **Additive field, additive filter.** No existing deployment (all of which predate `worker_id`) can regress: `worker_id is None` short-circuits `_worker_permits_routing` to `True` unconditionally.
- **Reuses proven Phase 2 logic.** `is_available_for_routing()`, heartbeat staleness, and capacity accounting were all built and tested in Phase 2; this phase only adds the call site.
- **Deterministic, not probabilistic.** No load balancer randomness — the same worker/deployment state always produces the same ranking, which makes the routing behavior testable and debuggable.

## Tests

`tests/test_gateway_worker_routing.py` (11 tests) covers: unconstrained (no `worker_id`) deployments still route exactly as before; an `UNHEALTHY`/`OFFLINE`/`DRAINING` worker excludes its deployment; a stale heartbeat excludes its deployment; a worker at full capacity excludes its deployment; ranking prefers `READY` over `DEGRADED`; ranking prefers lower `active_requests`; tie-breaking by `deployment_id` is deterministic across repeated calls; an unregistered `worker_id` (referenced but never `register_worker()`-ed) excludes the deployment rather than crashing.
