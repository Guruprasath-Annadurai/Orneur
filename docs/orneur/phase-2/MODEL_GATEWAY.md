# Model Gateway (`orca/gateway/gateway.py`)

## Routing safety (`resolve_deployment`)

1. Parses an optional `:production`/`:candidate`/`:experimental` alias suffix off `model_id`. An unrecognized suffix raises `ModelNotRoutableError` immediately.
2. Looks up registered deployments for the base model_id (optionally filtered to an exact `model_version` pin).
3. **Zero deployments registered** (Aeternum's real, current state) → `ModelNotRoutableError` — never substitutes a different family's model. Tested: `test_aeternum_shaped_model_with_no_deployment_is_not_routable`.
4. If an alias was named, only that exact lifecycle's routable deployments are considered — naming the alias IS the policy decision, independent of the `allow_experimental` flag.
5. Otherwise: a bare `model_id` requires a `PRODUCTION`-lifecycle, routable deployment unless `allow_experimental=True` is explicitly passed — a bare alias never silently falls through to a candidate/experimental deployment. Tested: `test_bare_alias_never_falls_back_to_candidate`.

`ModelDeployment.is_routable()` (the per-deployment eligibility check this all depends on) additionally refuses `REJECTED`/`RETIRED` lifecycle, any health state other than `READY`/`DEGRADED`, and any deployment that hasn't completed warmup — regardless of alias/policy. `REJECTED` is never reachable even with `allow_experimental=True`. Tested: `tests/test_gateway_deployment.py` (14 tests covering every refusal condition individually).

## Circuit breaking

Per-deployment (`orca/gateway/circuit_breaker.py`), never global — one unhealthy deployment cannot take down routing for any other model. `CLOSED → OPEN` after `failure_threshold` consecutive failures; `OPEN → HALF_OPEN` after `open_duration_s`; only one probe request admitted in `HALF_OPEN` at a time. Integrated into `generate()`/`stream()`: a request is rejected with `CircuitOpenError` **before** reaching the runtime at all once open — verified by asserting the fake runtime's call count doesn't increase (`test_repeated_failures_open_the_circuit`).

## Concurrency / backpressure

Per-deployment bounded semaphore + queue-depth cap (`orca/gateway/concurrency.py`). A request either gets a permit immediately, waits in a bounded queue (optionally with a `queue_timeout_s`), or is rejected outright with `QueueFullError` — never accepted into unbounded memory. Permit release is verified leak-proof on three separate exit paths: normal success, an exception raised inside the held permit, and `asyncio.CancelledError` (a task cancelled mid-generation) — each has its own dedicated test in `tests/test_gateway_concurrency.py`, not just inferred from a `try/finally` block's presence.

## Timeout categories (real, distinct, not one vague value)

| Category | Where enforced | Error raised |
|---|---|---|
| `queue_timeout_s` | `ConcurrencyLimiter.acquire()`'s optional wait | `QueueTimeoutError` |
| `first_token_timeout_s` | Checked between stream start and first non-empty chunk | `GenerationTimeoutError` (internal_detail distinguishes it from total-timeout) |
| `total_request_timeout_s` | `asyncio.wait_for()` around the whole `generate()` call | `GenerationTimeoutError` |

No blind automatic retry exists at the gateway layer for any of these — a caller that wants to retry does so explicitly; the gateway's job is to fail fast and clearly, not to silently re-attempt a request that may have already had side effects.

## Request/parameter validation (before any runtime call)

- **Context length**: a rough `chars/3.2` token estimate (no tokenizer dependency at this layer, deliberately conservative/over-estimating) checked against `ModelDeployment.context_limit`. Exceeding it raises `ContextTooLongError` — never silently truncated.
- **Parameters**: `temperature ∈ [0,2]`, `top_p ∈ [0,1]`, `max_tokens > 0` — anything outside raises `InvalidParametersError` before the runtime is ever called.

## Warmup

`ModelGateway.warmup(deployment)`: calls the runtime's `load_model()` (a no-op returning `False` for runtimes that don't support it, e.g. frontier passthrough) then a small deterministic `generate()` probe. Only on success does it set `health=READY` and `warmup_completed=True` — a failed warmup leaves the deployment exactly where it was, and `is_routable()` correctly refuses it regardless of what `lifecycle` says. Tested: `test_warmup_failure_leaves_deployment_not_ready`.

## Health reporting

`ModelGateway.report_health()` returns three genuinely distinct facts: `service_live` (this process is up), `service_ready` (at least one runtime is registered), and a per-model `model_readiness` map (`READY` / `CANDIDATE_ONLY` / `NOT_ROUTABLE`). The service can report ready with zero models registered — tested explicitly (`test_report_health_is_ready_with_zero_models`) so these three facts can never be accidentally conflated into one boolean.

## Observability

`orca/gateway/metrics.py` (same in-memory/never-raises/thread-locked pattern as the existing `orca/serve/metrics.py`, deliberately kept separate so the gateway has no import-time dependency on the HTTP-serving layer): request/success/failure/cancellation/timeout/retry counts, queue/total/TTFT latency samples, tokens generated — all keyed per-deployment. Structured logging (`_logger`, `orca.gateway` namespace) on every `generate()`/`stream()` outcome includes model_id, model_version, deployment_id, runtime, request_id, trace_id, status, latency, and error_class — **never** prompt content, system text, or secret values.
