# Phase 14 §78-81, §93 — Security Summary

## Phase 13 invariants re-confirmed under Phase 14 changes

The full godmode/connector/simulation/red-team test inventory (274
tests across 23 files, per this phase's own regression run) was
re-confirmed green after every code change this phase made
(`lease_store.py`'s Postgres backend, the revocation ledger, the
`/livez`/`/readyz` endpoints). No Phase 13 security test was modified
to make it pass — every pre-existing assertion still holds.

## New real finding this phase: stale authority backup resurrection

The single most significant security finding of Phase 14 — see
`BACKUP_AND_RECOVERY.md` for full detail. Summary: restoring a
pre-revocation Godmode authority backup silently un-revoked a lease.
**Found, reproduced, and fixed** (append-only revocation ledger +
mandatory `reconcile_after_restore()` step), with a regression test
that deliberately keeps reproducing the raw bug (with reconciliation
skipped) so a future change cannot silently regress the fix unnoticed.

## Distributed red-team (spec §79) — partial

| Attack | Status |
|---|---|
| Duplicated lease across workers/hosts | **Tested, denied** — `tests/test_godmode_authority_postgres.py`'s one-use and high-contention races prove the Postgres backend closes this exactly as SQLite did for single-host |
| Cross-worker tenant cache leak | **Tested, denied** — `test_postgres_backend_tenant_isolation_no_cross_tenant_leak` |
| Stale revocation worker | **Tested, and a REAL instance found and fixed** — the backup/restore finding above IS a stale-revocation-class bug; the ledger closes it for the leases table specifically |
| Stale model lifecycle worker | NOT_EXECUTED this phase — no new test built against the registry/lifecycle path |
| Stale registry view | NOT_EXECUTED — registries remain single-host JSON files (disclosed in `STATE_OWNERSHIP.md`), no multi-worker registry-staleness test built |
| Trace spoofing | NOT_EXECUTED — no trace-identity validation exists to attack yet (tracing itself is only partially built, see `OBSERVABILITY.md`) |
| Worker identity forgery | Partially covered structurally (Gateway worker registration binds deployment ID/checksum, unchanged pre-existing code) but no NEW forged-worker-registration attack was executed this phase |

## Worker authentication (spec §80)

**Not applicable yet, structurally**: Gateway-to-inference-worker calls
are in-process today (confirmed in `CURRENT_DEPLOYMENT_ARCHITECTURE.md`'s
audit — no real network boundary exists between them), so there is no
worker-to-worker authentication surface to build or test yet. This
becomes a real requirement the moment that boundary becomes a real
network call (not built this phase). No fake mTLS was built to give
the appearance of solving a problem that does not exist yet on real
infrastructure — per spec §80's own explicit instruction to be honest
about this.

## Audit counters (spec §93) — this phase's actual results

| Counter | Result | Basis |
|---|---|---|
| `DISTRIBUTED_TENANT_LEAK` | **0** | Real multiprocess test, `test_postgres_backend_tenant_isolation_no_cross_tenant_leak` |
| `DISTRIBUTED_AUTHORITY_DUPLICATION` | **0** | Real multiprocess tests against Postgres (one-use, high-contention, delegation races) |
| `STALE_REVOCATION_BYPASS` | **0** (after fix) | Real finding, real fix, real regression test — see above |
| `KILL_SWITCH_PROPAGATION_BYPASS` | **0** (Phase 14A.1/14A.2) | Kill-switch ground truth (the security root) is consulted fresh on every call; multiprocess test in `SECURITY_ROOT.md` |
| `KILL_SWITCH_STALE_RESTORE_BYPASS` | **0** (Phase 14A.1 fix superseded by Phase 14A.2's stronger fix) | Phase 14A.1's ledger fix was itself found incomplete (restoring the ledger together with the database defeated it — `WHOLE_SNAPSHOT_SECURITY_ROLLBACK`); Phase 14A.2's independent security root closes it completely — `SECURITY_ROOT.md` |
| `WHOLE_SNAPSHOT_SECURITY_ROLLBACK` | **0** (after fix, Phase 14A.2) | Real finding, reproduced before fixing (kill switch OFF → snapshot everything including the ledger → activate → restore everything → ALLOW), real architectural fix (independent security root), permanent regression sentinel test |
| `SECURITY_EPOCH_ROLLBACK` | **0** | `advance()` never accepts a caller-supplied epoch; always computes current+1 atomically — tested under direct tampering and under 5-way concurrent activation |
| `SECURITY_ROOT_UNAVAILABLE_FAIL_OPEN` | **0** | Real test — unreachable security-root Postgres host treated as active |
| `STALE_WORKER_SECURITY_ALLOW` | **0** | Real test — no caching, every call re-consults the security root fresh |
| `SECURITY_ROOT_CORRUPTION_FAIL_OPEN` | **0** | Real test — garbage state value treated as active |
| `SECURITY_EPOCH_CONCURRENCY_FAILURE` | **0** | Real test — 5 concurrent real processes, exact epoch accounting (epoch_after == epoch_before + 5), no lost updates |
| `DISTRIBUTED_SECURITY_ROOT_FALLBACK` | **0** (Phase 14A.3) | `security_root._backend()` raises rather than falling back in DISTRIBUTED mode with missing/invalid config — no code path to "sqlite" remains reachable |
| `DISTRIBUTED_MISSING_SECURITY_ROOT_READY` | **0** | `/readyz` returns 503 when DISTRIBUTED and the security root is unavailable — real test |
| `DISTRIBUTED_LOCAL_SECURITY_ROOT_CREATION` | **0** | Real test confirms no `~/.orneur-security-root` is created when DISTRIBUTED config is missing |
| `SECURITY_ROOT_OUTAGE_FAIL_OPEN` | **0** | Real test — post-startup outage denies, no fallback, no epoch reset, recovery observes correct state |
| `CROSS_WORKER_KILL_SWITCH_DIVERGENCE` | **0** | Real two-process test against a shared local Postgres security root — worker B denies immediately |
| `KILL_SWITCH_RESTART_BYPASS` | **0** | Real test — activation survives module reload |
| `KILL_SWITCH_MULTIPROCESS_BYPASS` | **0** | Real multiprocess test |
| `KILL_SWITCH_CORRUPTION_FAIL_OPEN` | **0** | Real test — garbage state value treated as active |
| `KILL_SWITCH_STORE_FAILURE_FAIL_OPEN` | **0** | Real test — unreachable Postgres host treated as active |
| `KILL_SWITCH_UNAUTHORIZED_RESET` | NOT_EXECUTED | No production code path exposes activate/deactivate to any request-scoped caller — no authorization boundary exists to test; disclosed in `KILL_SWITCH_DURABILITY.md`'s "Production reset path" section rather than fabricated |
| `STALE_MODEL_LIFECYCLE_ROUTE` | NOT_EXECUTED | No new test built |
| `UNREGISTERED_WORKER_ROUTE` | NOT_EXECUTED (this phase) | Pre-existing Gateway registration logic unchanged; not re-attacked this phase |
| `BUDGET_RESET_ACROSS_WORKER` | NOT_EXECUTED as an asserted test | Structural argument made in `CANCELLATION_AND_RETRY.md`; no executable property test built |
| `ORPHAN_DISTRIBUTED_TASK` | NOT_EXECUTED | No distributed task-cancellation test built (Gateway calls remain in-process) |
| `UNBOUNDED_QUEUE` | **0** | `orca/gateway/concurrency.py`'s bounded queue confirmed by code reading (pre-existing, unchanged) |
| `CANARY_TRAFFIC_LEAK` | NOT_EXECUTED | No real canary deployment exists |
| `ROLLBACK_FAILURE` | NOT_EXECUTED | No real rollback scenario executed against real infrastructure |
| `BACKUP_PRIVILEGE_RESURRECTION` | **0** (after fix; confirmed non-zero before the fix, honestly disclosed) | The central finding of this phase |
| `CLOUD_METADATA_SSRF` | NOT_EXECUTED | No cloud environment exists |
| `CROSS_CLOUD_CREDENTIAL_ESCALATION` | NOT_EXECUTED | No multi-cloud credentials exist |
| `CHECKPOINT_INTEGRITY_BYPASS` | NOT_EXECUTED (this phase) | Pre-existing checksum verification unchanged, not re-attacked |
| `SECRET_IN_DEPLOYMENT_LOG` | **0** | No secrets were printed to any log by this phase's changes (manually reviewed all new code) |
| `RAW_CHAIN_OF_THOUGHT_STORAGE` | **0** | No chain-of-thought storage was added anywhere this phase |
| `DIRECT_ORIGIN_BYPASS` | NOT_EXECUTED | No Cloudflare/cloud origin exists |
| `TRUSTED_PROXY_HEADER_SPOOF` | NOT_EXECUTED | No Cloudflare deployment exists |
| `CLOUDFLARE_POLICY_BYPASS` | NOT_EXECUTED | No Cloudflare deployment exists |
| `DECEPTION_PRODUCTION_ACCESS` / `DECEPTION_SECRET_EXPOSURE` / `DECEPTION_RESOURCE_EXHAUSTION` | NOT_EXECUTED | No deception service was built |

Every `NOT_EXECUTED` above is reported as such rather than a fabricated
0, per spec §93's own explicit instruction.
