# Phase 14 §95-97 — Evaluation Harness Results

## Required scenarios (spec §95), honest status

| Scenario | Status |
|---|---|
| Two API workers | **Partial** — cross-worker session continuity + fault injection proven via real multiprocess test (not full HTTP E2E) |
| Multiple inference workers | NOT_EXECUTED — Gateway calls remain in-process |
| Stale worker removed | NOT_EXECUTED (this phase) — Gateway staleness logic pre-existing, unchanged, not re-tested |
| Worker crash mid-request | **Proven** — real SIGKILL fault injection, `test_worker_a_crash_does_not_corrupt_or_lose_worker_b_visible_state` |
| Worker drain | NOT_EXECUTED |
| Bad candidate canary | NOT_EXECUTED — no real canary infrastructure |
| Stable deployment survives bad canary | NOT_EXECUTED |
| Deadline propagation | Structural argument only, no executable test (`CANCELLATION_AND_RETRY.md`) |
| Distributed cancellation | NOT_EXECUTED |
| Budget not duplicated | Structural argument only, no executable test |
| Tenant isolation across workers | **Proven** — `test_postgres_backend_tenant_isolation_no_cross_tenant_leak` |
| Godmode centralized | **Proven** — `AUTHORITY_DISTRIBUTION.md`, 5 real Postgres multiprocess tests |
| Kill switch visible to all workers | NOT_EXECUTED — kill switch remains single-host this phase |
| Authority store unavailable fails closed | **Proven** (pre-existing, reconfirmed) — `AuthorityStoreUnavailableError` handling for both SQLite and the new Postgres path |
| Registry unavailable | NOT_EXECUTED |
| Truth unavailable | Investigated as part of live-flakiness root-causing (see `PHASE_14_CLOSURE.md`), not a dedicated fault-injection test |
| Memory unavailable | NOT_EXECUTED |
| Connector unavailable | NOT_EXECUTED (this phase; Phase 9/13 already cover related ground) |
| Rolling upgrade | NOT_EXECUTED — no real multi-replica deployment |
| Backup | **Proven** — real SQLite online backup, `test_authority_backup_restore.py` |
| Restore | **Proven** — same test file, including the critical stale-restore finding |
| Stale authority backup | **Proven — real finding, real fix** — the centerpiece of this phase's security work |
| Config failure | NOT_EXECUTED — no config-validation-at-startup test built this phase |
| Worker registration forgery | NOT_EXECUTED (this phase) |
| Checkpoint mismatch | NOT_EXECUTED (this phase) |
| Load shedding | Confirmed structurally (pre-existing `ConcurrencyLimiter`), not newly tested |
| Queue bound | Confirmed structurally (pre-existing), not newly tested |
| Trace propagation | NOT_EXECUTED as an asserted property |

## Test counts added this phase

- `tests/test_godmode_authority_postgres.py` — 5 tests (one-use race,
  high-contention, revocation race, delegation race, tenant isolation),
  all passing against a real local Postgres 17 server.
- `tests/test_authority_backup_restore.py` — 3 tests (the raw
  stale-restore bug reproduction, the fix via reconciliation, a
  no-op-when-nothing-stale safety check), all passing.
- `tests/test_livez_readyz_endpoints.py` — 5 tests, all passing.
- `tests/test_multiworker_session_and_fault_injection.py` — 2 tests
  (cross-worker session continuity, real-SIGKILL fault injection),
  both passing against a real local Redis server.

**Total new tests this phase: 15, all passing on real infrastructure**
(local Postgres, local Redis, real SIGKILL) — none mocked, none
fabricated.

## Performance (spec §96)

See `LOAD_AND_SOAK.md` for the full real, bounded, local measurement
(336 req/s, p50 31ms / p95 178ms / p99 352ms on `/livez`, one uvicorn
process, 20-way concurrency, 30s). No production/cloud-scale numbers
exist (no cloud environment). Model inference time was not separately
measured this phase (out of scope — `/livez` was chosen specifically to
isolate framework overhead from it, per spec §73/§96's instruction to
keep the two separate).

## Reliability test duration (spec §97)

- Load test: 30.00s, 10,090 requests, 0 faults.
- Soak test: ~110s, continuous single-client requests, 0 leaks
  observed (RSS and FD count both stable).
- Fault count: 1 real SIGKILL injected and recovered from cleanly
  (multiworker session test) — plus every Phase 13.3 crash-injection
  scenario reconfirmed green this phase (11 SIGKILL scenarios in
  `test_godmode_crash_consistency.py`, unchanged, still passing).
