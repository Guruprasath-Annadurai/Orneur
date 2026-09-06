# Phase 14 §7, §37, §88 — Multi-Worker Evidence

## What was proven for real (local, no cloud)

`tests/test_multiworker_session_and_fault_injection.py` (2 tests, both
passing) against a genuinely-running local Redis (Homebrew service,
predates this session):

1. **Cross-worker session continuity**: a session created by one real
   OS process (simulating API worker A) is fully visible to, and safely
   extendable by, a completely different real OS process (worker B) —
   proving `orca.serve.session_store`'s Redis backend genuinely removes
   the process-local assumption the audit found in the in-memory
   `_sessions` dict fallback.
2. **Fault injection**: worker A is real-SIGKILLed (via the same
   signal-file-handshake pattern Phase 13.3 established for crash
   injection — readiness confirmed via a signal file, then `kill()`)
   immediately after saving state. Worker B, a separate still-alive
   process, reads that state correctly — a crashed worker does not
   corrupt or roll back state a survivor depends on.

`tests/test_livez_readyz_endpoints.py` (5 tests, passing) proves the
liveness/readiness split itself (see `HEALTH_AND_READINESS.md`).

`tests/test_godmode_authority_postgres.py` (4 tests, passing, from
`AUTHORITY_DISTRIBUTION.md`) proves the authority store specifically
survives real multiprocess races when backed by Postgres — the
distributed-authority half of "multi-worker."

## What was NOT executed this phase (disclosed, not fabricated)

- **A full authenticated HTTP end-to-end across two real uvicorn
  processes** (spin up `orca.serve.api:app` twice on different ports,
  drive `/api/chat` through real JWT auth and a real model round-trip
  on both, confirm identical behavior). This requires provisioning a
  real user account and exercising the full auth/chat pipeline over
  HTTP — real, buildable work, but substantially heavier than the
  property actually being tested needed. What was tested instead
  (above) isolates and directly proves the exact mechanism that HTTP
  E2E test would ultimately be exercising (`session_store`'s real
  cross-process behavior), without the additional auth/model-serving
  plumbing. Recommended as the next concrete addition if a future pass
  continues Phase 14 work.
- **Two real `uvicorn --workers 2` processes under an actual load
  balancer** (nginx, Envoy, a cloud LB) — no load balancer was stood up
  locally. The multiprocessing-based tests above prove the underlying
  state-sharing correctness that a load balancer's request distribution
  would rely on, but do not exercise an actual LB's routing behavior.
- **Multiple real inference (Gateway) worker identities** (spec §38) —
  the existing `orca/gateway/circuit_breaker.py` and
  `orca/gateway/concurrency.py` were read and confirmed process-local
  (see `CURRENT_DEPLOYMENT_ARCHITECTURE.md`) but no new multi-worker
  Gateway test was built this pass; Gateway worker registration already
  binds deployment ID/model family/checkpoint/capability per
  `orca/gateway/worker.py`, unchanged this phase.

## Tenant isolation (spec §49, §70)

`tests/test_godmode_authority_postgres.py::test_postgres_backend_tenant_isolation_no_cross_tenant_leak`
races two tenants' `max_uses=1` leases concurrently (2 processes per
tenant, 4 total, single shared start barrier) against the real Postgres
authority backend: each tenant's lease is independently enforced
(exactly 1 success per tenant, `uses_remaining == 0` for both), proving
no shared lock or row confusion between tenants under real concurrent
load. This covers the Godmode authority layer specifically. A broader
concurrent-Tenant-A/Tenant-B test across the full request path (chat
sessions, memory, connectors together) was not built this pass — listed
as a real gap, not claimed as covered.
