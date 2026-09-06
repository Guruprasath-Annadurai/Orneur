# GPU / Model Worker Abstraction (`orca/gateway/worker.py`)

## Scope, honestly

This machine represents exactly one worker today — there is no multi-host hardware, no distributed scheduler, and this phase deliberately did not build one (per explicit instruction not to over-engineer distributed consensus, and not to require physical multi-host hardware to implement the abstraction). What exists is the `Worker` entity and health model a future multi-worker system would build on, proven correct in isolation.

## `Worker` fields

`worker_id`, `runtime`, `hardware` (descriptive string, e.g. `"local-cpu-16gb"` — not enforced/validated against real hardware), `available_models` (deployment_ids this worker can serve), `status` (`WorkerHealth`), `capacity`/`active_requests`/`queue_depth` (integers, not yet wired to the gateway's own per-deployment concurrency counters — see "Integration status" below), `last_heartbeat`.

## Health states

`STARTING` / `READY` / `DEGRADED` / `DRAINING` / `UNHEALTHY` / `OFFLINE` — mirrors `DeploymentHealth`'s states intentionally (a worker and the deployments running on it can be unhealthy independently, but the vocabulary is shared for consistency). `is_available_for_routing()` requires `READY`/`DEGRADED`, a fresh heartbeat (≤30s old, deliberately simple staleness check — no gossip protocol, no distributed consensus), and spare capacity.

## Heartbeat / liveness

`Worker.heartbeat()` updates `last_heartbeat` and persists. `is_stale()` is the only "is this worker still alive" mechanism — a single timestamp comparison, exactly the scope instructed ("track enough information to determine: worker reachable, runtime reachable, model available, capacity available, last successful probe" — not a consensus protocol).

## Integration status — honest, not overstated

The `Worker` entity exists, is persisted, and is independently tested (round-trip, staleness detection, capacity checks) — but `ModelGateway` does not yet consult `Worker` state when routing (it currently reasons about `ModelDeployment` health/lifecycle only, not which worker hosts that deployment or that worker's own health/capacity). This is a deliberate scope boundary for this phase: `ModelDeployment` and `Worker` are both real, both correct, and ready to be linked (a `ModelDeployment.worker_id` field, and a gateway check against `Worker.is_available_for_routing()` before routing) as a small, well-scoped follow-up — not attempted in this same pass to avoid growing the gateway's routing logic and its test surface simultaneously with the worker abstraction's own first real usage.
