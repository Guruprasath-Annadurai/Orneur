# Phase 14 §49, §75-77 — Fault Injection

## Real fault injection executed this phase

All via genuine `multiprocessing.Process.kill()` (real SIGKILL, not a
simulated exception), following the exact signal-file-handshake pattern
Phase 13.3 established for crash injection:

| Scenario | Test | Result |
|---|---|---|
| Kill a process mid-Godmode-transaction (SQLite) | `tests/test_godmode_crash_consistency.py` (Phase 13.3, reconfirmed green this phase) | No extra/negative authority, `PRAGMA integrity_check == ok` |
| Kill an API-worker-equivalent process after it wrote shared session state | `tests/test_multiworker_session_and_fault_injection.py::test_worker_a_crash_does_not_corrupt_or_lose_worker_b_visible_state` | Surviving process reads the pre-crash state correctly; no corruption |
| Restore a stale authority backup (a form of fault: "recovery from an old snapshot") | `tests/test_authority_backup_restore.py` | Real bug found and fixed (see `BACKUP_AND_RECOVERY.md`) |

## Fault injection NOT executed this phase (disclosed, not fabricated)

- **Kill a Gateway/inference-worker process specifically** — the
  Gateway's worker calls are in-process today (no real second process
  to kill mid-inference-call yet); this becomes meaningful once a real
  network/process boundary exists between Gateway and inference
  workers.
- **Authority store unavailable (connection refused / Postgres down)**
  — the fail-closed behavior (`AuthorityStoreUnavailableError` →
  deny) is exercised by existing unit-level tests
  (`sqlite3.OperationalError`/`psycopg.Error` paths in
  `lease_store.py`), but no test actually stopped a real Postgres
  process mid-test to observe end-to-end behavior. The Postgres-backed
  tests in this phase always ran against a live, reachable server.
- **Truth Fabric / Memory / connector-provider unavailable, injected as
  a real fault** — Phase 13.2's own disclosed live-flakiness finding
  (transient `TruthTimeoutError`) is the closest real evidence this
  codebase has of Truth Fabric under real degraded conditions, and it
  was investigated (not just observed) this phase — see
  `PHASE_14_CLOSURE.md`'s "Live flakiness" section for the actual root-
  cause work done.
- **Node-level failure** (spec §50) — no real Kubernetes cluster exists
  in this environment; a real multi-node cluster test could not be
  executed. Per spec §50's own instruction ("do not claim multi-node
  failure if cluster has only one node"), this is reported as
  NOT_EXECUTED, not simulated and reported as if real.
- **Network-level fault simulation** (timeout, connection refused,
  connection reset, slow response — spec §76) — no dedicated test
  harness for this was built this phase. The Postgres `statement_timeout`
  bound added to the authority store's Postgres path (see
  `AUTHORITY_DISTRIBUTION.md`) is the one piece of code this phase
  added specifically to bound an otherwise-unbounded wait, but it was
  not separately fault-tested against a genuinely stalled connection.
