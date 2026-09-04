# Phase 14 §18-22 — Health Model

## The gap this closes

`CURRENT_DEPLOYMENT_ARCHITECTURE.md`'s audit found `/healthz` used for
**both** `livenessProbe` and `readinessProbe` in the pre-existing
`k8s/deployment.yaml` — liveness and readiness were conflated. A slow
dependency (e.g. Ollama) could get an otherwise-healthy pod killed and
restarted by Kubernetes, which fixes nothing about a dependency problem
and adds restart churn on top of it.

## The fix

Two new real endpoints in `orca/serve/api.py`, both tested
(`tests/test_livez_readyz_endpoints.py`, 5 tests passing):

- **`GET /livez`** — LIVENESS only. Answers "is this process alive?"
  with zero I/O and zero dependency calls (`{"status": "alive", "pid":
  ...}`). Verified by a test that makes the model-resolution dependency
  raise and confirms `/livez` still returns 200 — liveness genuinely
  never touches it.
- **`GET /readyz`** — READINESS. Answers "can this worker safely serve
  the claimed model/capabilities right now?" Checks dependencies
  **separately** (spec §21) rather than collapsing them into one
  boolean:
  - `model_runtime` — **REQUIRED**. Failure flips `ready` to `false`
    and returns HTTP 503 (fail-closed).
  - `authority_store` — reported (which backend, sqlite/postgres, and
    whether it's reachable) but does **not** by itself flip readiness,
    since ordinary non-elevated requests never touch it; elevated call
    sites already fail closed on their own via
    `AuthorityStoreUnavailableError`.
  - `gateway` — reported via the existing `report_health()` method,
    same non-gating treatment.
- **`GET /healthz`** — preserved byte-for-byte as it existed before
  this phase (same `status`/`nano_model`/`gateway` response shape).
  This was a deliberate correction mid-implementation: an initial draft
  made `/healthz` an alias for `/readyz`'s new response shape, which
  broke the 5 pre-existing tests asserting the old contract
  (`tests/test_healthz_endpoint.py`, `tests/test_healthz_gateway_readiness.py`)
  — reverted immediately, confirmed all 6 pre-existing tests pass
  unmodified. New deployments should point `livenessProbe`/
  `readinessProbe` at the new split endpoints (done in the updated
  `k8s/deployment.yaml`); `/healthz` remains available, unmodified, for
  any caller not yet migrated.

## Degraded-mode / fail-closed-vs-fail-soft matrix (spec §22-23)

| Dependency | On failure | Rationale |
|---|---|---|
| Godmode authority store | **Fail closed** — all elevated operations DENY | Already true before this phase (`AuthorityStoreUnavailableError` caught at every public `lease_store` boundary, converted to `False`/`None`, never ambiguous) |
| Model runtime (for `/readyz`) | **Fail closed** — worker marked not-ready, removed from routing | A worker that cannot resolve a model must not receive traffic it cannot serve |
| Truth Fabric, for a strict/audit-graded task | **Fail closed / abstain** — must not fabricate an answer | Existing behavior (`orca/truth/*`), unchanged by this phase; confirmed by reading `orca/truth/graph.py`'s docstring, no code change needed |
| Memory | **Fail soft where policy permits** — a request may continue without memory context | Existing behavior; memory unavailability is not itself a security boundary |
| Connector provider | **Fail closed on write** — "no fake success" | Existing `fake_provider`/real-connector pattern (Phase 9); a write must never be reported as successful when the provider call itself failed |
| Analytics/observability pipeline | **Fail soft** — never block a request because a metric couldn't be emitted | Standard practice; no observability call site in this codebase is on the request's critical path today (confirmed by the audit — no metrics backend was even wired in before this phase, see `OBSERVABILITY.md`) |

This matrix was assembled by reading the actual code, not invented —
every "existing behavior" row reflects what the audited code already
did before Phase 14; the two new rows (model runtime for `/readyz`)
reflect this phase's actual change.
