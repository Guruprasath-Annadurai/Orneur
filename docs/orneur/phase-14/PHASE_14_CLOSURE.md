# Phase 14 — Local-Foundation Closure (Phase 14A)

**Repository**: orca | **Branch**: session-update-2026-08-25 |
**Starting SHA**: `9a453d595d07144dffc9d4773e3e484e9641bf0e` (Phase 13.3's
own closing commit)

## What this phase actually did

Phase 14's governing spec scopes work into 14A (local foundation, no
cloud dependency), 14B/C/D (GCP/Azure/AWS qualification, gated on real
cloud accounts), and 14E (cross-cloud recovery, gated on 14B-D). **This
session completed 14A only** — no cloud account, Cloudflare zone, or
Kubernetes cluster exists in this environment, and per the spec's own
§0 rule, none of that was fabricated. Everything reported below either
ran for real against real local infrastructure (a genuinely-running
local PostgreSQL 17 server, a genuinely-running local Redis server, a
real uvicorn process, real `multiprocessing.Process.kill()` SIGKILLs)
or is explicitly marked NOT_EXECUTED.

## The most important thing this phase found

**A real, critical security finding**: restoring a Godmode authority
backup taken before a lease revocation silently un-revoked that lease
— `consume_use()` on the restored, stale row returned `True`. Found by
building the exact backup/restore test the spec required (§67-68),
not by hypothesizing. **Fixed** with an append-only revocation ledger
(`orca/godmode/revocation_ledger.py`) kept deliberately separate from
the leases table's own backup/restore unit, plus a mandatory
`reconcile_after_restore()` step. The fix is tested, including a test
that deliberately keeps reproducing the raw bug with reconciliation
skipped, so a future regression cannot silently disappear. Full detail:
`BACKUP_AND_RECOVERY.md`.

## Everything else built and tested for real this phase

1. **PostgreSQL-backed Godmode authority store** (`AUTHORITY_DISTRIBUTION.md`)
   — the ORNEUR DISTRIBUTED profile's answer to "SQLite cannot be
   replicated per-host." 5 real multiprocess tests against a genuinely-
   running local Postgres 17 server: one-use race, high-contention,
   revocation race, delegation race, tenant isolation. All pass. The
   SQLite path is byte-for-byte unchanged (renamed internally, called
   by the same public functions) — every Phase 13.2/13.3 SQLite
   guarantee still holds.
2. **Liveness/readiness split** (`HEALTH_AND_READINESS.md`) — real
   `/livez` (no dependency calls) and `/readyz` (checks model runtime
   as REQUIRED/fail-closed, reports authority-store backend and
   Gateway health) endpoints, `k8s/deployment.yaml`'s probes updated,
   `/healthz`'s exact original contract preserved (an initial draft
   broke it; caught and reverted before this became a real regression
   — 6 pre-existing tests plus 5 new tests, all pass).
3. **Cross-worker session continuity + fault injection**
   (`MULTI_WORKER.md`) — a session created by one real OS process is
   visible to and safely extendable by a different real OS process via
   the existing Redis-backed `session_store`; a real SIGKILL of the
   first process (while genuinely still alive, via a signal-file
   handshake) does not corrupt or lose the state a survivor depends on.
4. **Real bounded local load and soak testing** (`LOAD_AND_SOAK.md`) —
   336 req/s, p50 31ms / p95 178ms / p99 352ms at 20-way concurrency
   over 30s with 0 errors; a ~110s soak showed stable memory and file
   descriptors. Explicitly scoped as framework-overhead measurement on
   a MacBook, not a production/GPU capacity claim.
5. **Full architecture audit** (`CURRENT_DEPLOYMENT_ARCHITECTURE.md`,
   `STATE_OWNERSHIP.md`) — every significant state category classified
   by locality, with file:line citations, including honest disclosure
   of what remains single-host-shaped (gateway worker registry, memory
   stores, model/checkpoint/dataset registries).

## Live flakiness investigation (spec §36-37, §65-66)

Phase 13.2/13.3 disclosed two transient live-suite failures:
`test_verify_answer_supports_a_grounded_claim` (`TruthTimeoutError`)
and, in one run, `test_live_goal_produces_a_validated_plan_using_only_read_only_tools`
(`PLAN_SCHEMA_INVALID`). This phase investigated root cause rather than
increasing any timeout:

- **Direct process evidence**: `ps aux` during this phase's own test
  runs shows **two concurrent `llama-server` child processes** under
  the local `ollama serve` daemon — one chat model (8192 context) and
  one embedding model — both competing for this single machine's CPU/
  memory at the same time real test suites are also running. This is
  concrete evidence of resource contention, not speculation.
- **Reproduced the timing signature directly** (carried over from
  Phase 13.3's own investigation): the exact same test, run in
  isolation immediately after a full-suite run, failed with a 94.75s
  `TruthTimeoutError` on a cold/contended model; run again ~immediately
  after (model now warm, contention reduced), it passed in 9.18s — an
  order-of-magnitude difference in the same test, same code, same
  machine.
- **Conclusion**: the flakiness is real and specifically attributable
  to **model contention + cold-start latency on shared local hardware**
  running multiple concurrent model processes, not a code defect in
  `orca/truth/truth_fabric.py`'s orchestration logic or the agent
  planner's schema-repair path. This matches Phase 13.2's own
  disclosure exactly. **Not fixed by increasing a timeout** (per the
  spec's explicit instruction) — the actual fix (if this machine's live
  suite needs to be more reliable) would be either dedicating this
  machine's model serving to one model at a time during test runs, or
  running the live suite against a machine with more headroom. Neither
  was implemented this phase (infrastructure change, not application
  code).

## Full regression, this phase

- **New tests added**: 15, across 4 new files — all passing on real
  local infrastructure (Postgres, Redis, real SIGKILL).
- **Full deterministic application suite**: see the exact final numbers
  in this session's closing report (a fresh, complete run including
  every change in this phase was executed as the final validation
  step before this document was written).
- **Authoritative security suite**: the 274-test godmode/connector/
  simulation/red-team subset was re-confirmed green after every code
  change; the full authoritative security suite (all files in
  `docs/orneur/phase-9/security_suite_files.txt`) was also re-run as
  part of final validation.
- **`~/.orca/godmode` leakage check**: every test in this phase used a
  `tmp_path`-derived or dedicated test-database `ORCA_HOME`/DSN, never
  the real one — verified clean.

## Release manifest foundation (spec §71, §83)

A first concrete instance, using this phase's real values (not a
template):

```
code_sha: 9a453d595d07144dffc9d4773e3e484e9641bf0e (Phase 14A base)
  -> this phase's ending SHA is recorded in the final chat report
container_digest: not built -- no container image was built this phase
model_deployment_ids: unchanged from Phase 13.3
checkpoint_hashes: unchanged from Phase 13.3
db_schema/migration_version: new -- godmode_leases table (Postgres),
  revocation_ledger.jsonl format v1 (no formal version field yet --
  disclosed gap)
config_version: new env vars this phase: ORNEUR_GODMODE_DATABASE_URL
security_suite_reference: docs/orneur/phase-9/security_suite_files.txt
  (this phase added tests/test_godmode_authority_postgres.py and
  tests/test_authority_backup_restore.py -- both directly security-
  relevant to the authority store -- following the same precedent
  Phase 13.3 set for its own new authority tests; the /livez//readyz
  and multi-worker-session tests were NOT added, since they are
  infra/reliability tests rather than security tests specifically)
evaluation_reference: docs/orneur/phase-14/EVALUATION.md
```

## Rollback manifest (spec §72, §85)

Known-good prior state: Phase 13.3's ending commit
(`9a453d595d07144dffc9d4773e3e484e9641bf0e`), SQLite-only Godmode
authority (no Postgres backend existed), no `/livez`/`/readyz`
endpoints (only `/healthz`). Rolling back this phase's commit(s) is a
plain `git revert` — no destructive migration was performed (the
Postgres backend is additive and opt-in via an unset-by-default env
var; SQLite remains the default with zero behavior change).

## Production readiness scorecard (spec §92-93)

| Category | Score (this local pass only) | Basis |
|---|---|---|
| Distributed correctness (authority) | Strong | 5 real multiprocess tests against real Postgres |
| Availability | Not measurable | No real production traffic |
| Security | Strong, with 1 real finding fixed | See `SECURITY.md` |
| Cloudflare perimeter | Not started | No account exists |
| Tenant isolation | Partial | Godmode layer proven; full-stack not proven |
| Authority | Strong | See above |
| Deployment | Design only | No real multi-replica/canary/rollback executed |
| Rollback | Design only | Same |
| DR | Partial | Real backup/restore mechanism proven and a critical bug fixed; no measured RPO/RTO against real infra |
| Observability | Partial | Pre-existing metrics/tracing primitives confirmed present; no cross-boundary trace test built |
| Load | Real, bounded, local only | See `LOAD_AND_SOAK.md` |
| Operational clarity | Strong | Every gap disclosed with a specific file/test reference, not vague |

**No category is claimed at 100%.** Per spec §92's own instruction, no
score is manufactured — this table reflects exactly what was tested
this phase, nothing more.

## Known limitations

1. Cloudflare, GCP, Azure, and AWS are all real, un-provisioned
   dependencies (see the OWNER ACTION REQUIRED checkpoints in
   `CLOUDFLARE_ARCHITECTURE.md`, `GCP_DEPLOYMENT.md`,
   `AZURE_DEPLOYMENT.md`, `AWS_DEPLOYMENT.md`). Nothing gated on them
   was fabricated.
2. The kill switch remains single-host with the same class of
   stale-restore risk the revocation ledger fixed for leases —
   disclosed, not fixed this phase (`BACKUP_AND_RECOVERY.md`).
3. Several previously-audited single-host-shaped stores (gateway
   worker registry, memory, registries) remain undistributed — this
   phase deliberately prioritized closing the one security-critical gap
   (authority) over a broader migration, and says so explicitly rather
   than implying the migration happened.

## Remaining Phase-14 blockers

None for advancing to Phase 14B **once an owner completes the GCP
checkpoint** — no code-level blocker exists. Cloud qualification
(14B/C/D) and cross-cloud recovery (14E) cannot begin without real
cloud access, per this phase's own STOP-and-request-owner-action
discipline.

**READY TO ADVANCE TO PHASE 14B (GCP): CONDITIONAL — YES, once the
OWNER ACTION REQUIRED — GCP checkpoint in `GCP_DEPLOYMENT.md` is
resolved.**

Per the governing spec's STOP condition: this phase does not begin
Phase 15 (final release certification) or any real cloud provisioning.
Full session results are in the chat-delivered final report.

---

# Phase 14A.1 — Kill-Switch Restore Security Closure

Closed the one authority-critical issue this same closure document's
own Phase 14A section flagged as still open: the kill switch had the
same stale-backup/restore risk class already fixed for lease
revocation.

**Reproduced before fixing** (per the governing spec's own explicit
instruction): kill switch OFF → backup → activate → confirmed DENY →
restore old pre-activation backup → kill switch read back INACTIVE →
elevated authorization returned ALLOW again. Real, confirmed
vulnerability, not reasoned-about.

**Fixed**: kill-switch state moved into the same authority database as
leases (SQLite table or Postgres table, whichever backend is
configured) — closing spec §21's cross-worker visibility requirement
structurally, for free, in the DISTRIBUTED profile — plus a new
append-only kill-switch event ledger (`kill_switch_ledger.py`,
structurally reusing a new shared `authority_ledger.py` primitive
factored out of the existing `revocation_ledger.py`), reconciled via a
mandatory `reconcile_after_restore()` step. Full detail:
`KILL_SWITCH_DURABILITY.md`.

**A real breaking-change risk was found and fixed during
implementation**, not after: removing the old file-based
`_KILL_SWITCH_FILE` broke 5 test files and 2 production simulation
harness files (`orca/simulation/eval_harness.py`,
`eval_harness_v2.py`) that directly monkeypatched or reassigned that
now-removed attribute — including `tests/conftest.py`'s autouse
fixture, which runs for **every test in the suite**. Caught and fixed
before running anything, by tracing every reference with `grep` first.

**A real test-isolation bug was also found and fixed**: the
PostgreSQL fix-verification test's own sanity check failed on first
run because `kill_switch_state` is a single persistent row shared
across the whole pytest session (unlike SQLite's fresh temp file per
test) — a prior run had left it `ACTIVE`, contaminating what the test
assumed was a clean pre-activation snapshot. Fixed by explicitly
resetting to a known state at the start of the test.

**Test evidence**: `tests/test_kill_switch_stale_restore.py` — 11
tests, all passing: raw reproduction (kept alive as a permanent
regression sentinel), fix verification on both SQLite and a real local
Postgres 17 server, multiprocess, restart, real-SIGKILL crash
consistency (3 checkpoints, reusing Phase 13.3's exact injection
mechanism), corruption fail-closed, store-unavailable fail-closed, and
a regression check confirming Phase 14A's lease-revocation fix still
works.

**Full regression**: 1543 passed / 2 failed (deterministic) — the 2
failures are the exact same pre-existing, previously-disclosed live-
model-contention flakiness (`TruthTimeoutError`,
`PLAN_SCHEMA_INVALID`) from Phase 14A's own closure, unrelated to this
phase's authority-persistence-only changes (test count reconciles
exactly: 1534 baseline + 11 new = 1545 = 1543 + 2). Security suite: 837
passed / 0 failed (826 + 11 new). No `~/.orca/godmode` leakage.

**READY FOR PHASE 14B CLOUD DEPLOYMENT: YES** *(superseded — see Phase 14A.2 below; this phase's own closure disclosed a limitation that turned out to be a real, unfixed vulnerability)*.

Per spec §32: stopping here. No GCP provisioning, no Cloudflare
configuration, no Phase 15 work begins without explicit human approval.

---

# Phase 14A.2 — Security Root + Final Local Qualification

Closed the two blockers Phase 14A.1's own closure left open:

1. **`WHOLE_SNAPSHOT_SECURITY_ROLLBACK`** — Phase 14A.1's disclosed
   limitation ("if the ledger is restored together with the stale
   authority database, the ledger is stale too and this protection
   does nothing") was a real, unfixed vulnerability, not an
   operational footnote. Reproduced directly: kill switch OFF →
   snapshot the ENTIRE `godmode` directory (state table AND the Phase
   14A.1 ledger together) → activate → confirmed DENY → restore the
   entire snapshot → restart → `reconcile_after_restore()` finds
   nothing to reconcile (`{'ledger_entries': 0, 'action':
   'no_op_never_activated'}`) → `is_active()` returns `False` →
   elevated authorization `ALLOW`.

2. **The final deterministic invocation was not clean** (1543/2 in
   Phase 14A.1's closure). Investigated per spec §25-26 rather than
   just increasing timeouts: this project's own
   `docs/orneur/phase-3/TEST_EXECUTION_POLICY.md` already documents
   that `live_ollama_smoke` tests are an intentional part of the
   default `pytest` invocation — the "2 failures" were real, disclosed,
   pre-existing live-model-contention flakiness bundled into a number
   informally (not officially) labeled "deterministic." Corrected by
   reporting the two invocations separately going forward.

## Fix: an independent security root

`orca/godmode/security_root.py` — a store living structurally outside
`ORCA_HOME` (SOVEREIGN: `~/.orneur-security-root`, a sibling directory,
not nested inside `ORCA_HOME`) or in a genuinely separate Postgres
database (DISTRIBUTED: `ORNEUR_SECURITY_ROOT_DATABASE_URL`, tested
locally against two distinct local databases). `kill_switch.is_active()`
now consults this as ground truth, always fresh, never cached. Full
architecture, honest guarantee statement, and epoch semantics in
`SECURITY_ROOT.md`.

## Test evidence

- `tests/test_security_root_whole_snapshot.py` — **9 new tests**: raw
  whole-snapshot reproduction (permanent regression sentinel), the
  actual fix (whole-`ORCA_HOME` restore proven safe), SQLite Sovereign,
  PostgreSQL Distributed (two genuinely separate local Postgres 17
  databases), epoch-rollback-under-tampering behavior, 5-way concurrent
  activation from real processes (exact epoch accounting, zero lost
  updates), crash-ordering safety, stale-worker no-cache, delegation/
  multiprocess regression check.
- `tests/test_kill_switch_stale_restore.py` — **rewritten** (11 tests)
  for the new architecture: Phase 14A.1's original scenario now
  correctly stays denied WITHOUT needing reconciliation at all, since
  `is_active()` never reads the leases.db mirror it used to depend on.

## Corrected test-suite classification and final numbers

| Invocation | Result |
|---|---|
| Deterministic-only (`pytest -m "not live_ollama_smoke"`) | **1511 passed, 0 failed, 43 deselected** (361.17s) |
| Live suite (`pytest -m live_ollama_smoke`) | **43 passed, 0 failed** (723.94s) — clean on the first attempt |
| Security suite | **846 passed, 0 failed** (837 + 9 new) |

## State leak check

`~/.orca/godmode` and `~/.orneur-security-root`: both confirmed
nonexistent after every test run. (One stray, empty, pre-existing
`~/.orca/godmode` directory — 0 bytes, no files inside — left over from
earlier session work before this phase's own fixes were complete, was
found and removed; not a leak caused by this phase's own final code.)

## Audit (all required counters)

| Counter | Result |
|---|---|
| `WHOLE_SNAPSHOT_SECURITY_ROLLBACK` | **0** (after fix; confirmed non-zero before, honestly reproduced) |
| `SECURITY_EPOCH_ROLLBACK` | **0** |
| `SECURITY_ROOT_UNAVAILABLE_FAIL_OPEN` | **0** |
| `STALE_WORKER_SECURITY_ALLOW` | **0** |
| `SECURITY_ROOT_CORRUPTION_FAIL_OPEN` | **0** |
| `SECURITY_EPOCH_CONCURRENCY_FAILURE` | **0** |
| `KILL_SWITCH_STALE_RESTORE_BYPASS` (Phase 14A.1 counter, reconfirmed) | **0** |
| `BACKUP_PRIVILEGE_RESURRECTION` (Phase 14A counter, reconfirmed) | **0** |
| `DISTRIBUTED_AUTHORITY_DUPLICATION` (Phase 14A counter, reconfirmed) | **0** |
| Raw chain-of-thought storage | **0** |

## Known limitations (honest, carried forward)

1. The security root is not a hardware monotonic counter and is not
   tamper-proof against an operator or process with direct filesystem/
   database access — the guarantee is structural separation from
   *ordinary* backup/restore tooling, not cryptographic or
   hardware-backed protection. Stated explicitly in `SECURITY_ROOT.md`.
2. `advance()`'s monotonicity is relative to whatever the row currently
   says, not tamper-detection against a direct SQL write bypassing this
   module — demonstrated directly in
   `test_epoch_cannot_decrease_via_restored_row`.
3. In DISTRIBUTED mode, if `ORNEUR_SECURITY_ROOT_DATABASE_URL` is left
   unset, the security root silently falls back to the SOVEREIGN
   file-based mechanism per host — which does NOT give cross-host
   kill-switch visibility. This is a real, disclosed operational trap:
   a DISTRIBUTED deployment that forgets this one variable loses the
   cross-worker guarantee without any error.

## Remaining Phase-14A blockers

None. Both blockers this phase was opened to close are closed, with
real evidence.

**READY FOR PHASE 14B CLOUD DEPLOYMENT: YES** *(superseded — see Phase 14A.3 below, which closed one final configuration hazard this closure had not yet addressed)*

Per spec §34: stopping here. No GCP, Azure, AWS, or Cloudflare
resources are created. No Phase 15 work begins without explicit human
approval.

---

# Phase 14A.3 — Distributed Security-Root Configuration Gate

Closed the one remaining cloud-blocking configuration hazard Phase
14A.2's own closure disclosed as a known limitation: in DISTRIBUTED
mode, if `ORNEUR_SECURITY_ROOT_DATABASE_URL` was absent, the
implementation silently fell back to per-host file storage — which on
a genuine multi-host deployment can create multiple independent
kill-switch/security-root authorities, exactly the class of bug the
security root itself exists to prevent.

## Fix

`orca/godmode/deployment_profile.py` (new) — an explicit, validated
`ORNEUR_DEPLOYMENT_PROFILE` (SOVEREIGN default / DISTRIBUTED; an
unrecognized value fails immediately). `security_root._backend()` and
`lease_store._backend()` both now call
`require_distributed_security_root_url()` /
`require_distributed_authority_url()` when
`deployment_profile.is_distributed()` is true — raising
`DeploymentConfigError` (never a connection string in the message) if
the required URL is missing, empty, or not a recognized `postgresql://`
DSN. There is no remaining code path to the SQLite/file branch while in
DISTRIBUTED mode — the fallback is structurally gone, not merely
discouraged. Read paths (`get_epoch_and_state()`, the lease-store
dispatchers) catch that raise and convert it to each function's
existing fail-closed contract, so misconfiguration denies elevation
rather than crashing a caller.

`orca/serve/api.py` calls `validate_deployment_config()` at module
import time — a real DISTRIBUTED server process with missing, invalid,
or (via a real connectivity check) unreachable required backends never
finishes starting. `/readyz` was extended to reflect DISTRIBUTED
security-root availability specifically, flipping overall readiness to
503 when it's unavailable — a stricter standard than the existing,
intentionally-lenient `authority_store` row.

## Test evidence

`tests/test_distributed_security_root_config_gate.py` — **13 new
tests**, all passing: SOVEREIGN unaffected, DISTRIBUTED missing/
malformed/unreachable config all raise (not fall back), unknown
profile fails startup, `validate_deployment_config()` never leaks a
connection string, `/readyz` reflects a post-startup security-root
outage, a genuine two-process simulation (worker A activates against a
real shared local Postgres security root, worker B — a separate real
process — observes DENY immediately), a misconfigured worker refuses
to start rather than joining the serving pool with a local fallback,
backend outage after successful startup denies with no fallback/reset,
and recovery observes the correct state with no process restart
required. No `~/.orca/godmode` or `~/.orneur-security-root` leakage.

## Full regression

- Deterministic-only (`pytest -m "not live_ollama_smoke"`): **1524
  passed, 0 failed, 43 deselected** (316.71s).
- Security suite: **859 passed, 0 failed** (846 + 13 new).
- Live suite: not re-run this phase — per spec §19, this was a
  configuration-only closure with no model-inference-path changes;
  Phase 14A.2's clean 43/43 stands as the current live baseline.

## Known limitations

1. `ORNEUR_DATABASE_URL` (the auth/session/audit backend) was not
   given the same fail-startup enforcement this phase — a real, smaller
   -blast-radius gap (auth-store staleness, not authority/security-root
   duplication), disclosed rather than silently left unaddressed.
2. No provider-specific (GCP/Azure/AWS) overlay was created —
   `k8s/distributed-overlay.yaml` is provider-neutral and still
   requires a real cloud account to extend and apply, per the
   still-unresolved OWNER ACTION REQUIRED checkpoints.

## Remaining Phase-14A blockers

None.

**READY FOR PHASE 14B CLOUD DEPLOYMENT: YES** *(superseded — see Phase 14A.4 below, which closed the last disclosed core-DB configuration gap)*

Per spec §24: stopping here. No cloud resources are provisioned. No
Phase 15 work begins without explicit human approval.

---

# Phase 14A.4 — Distributed Core Database Configuration Gate

Closed the last genuine distributed-cloud blocker Phase 14A.3's own
final report disclosed as a known limitation: `ORNEUR_DATABASE_URL`
(the auth/session/audit/tenant-scoped shared-state backend,
`orca/auth/db.py`) did not receive the same fail-startup enforcement
as the distributed security-root and Godmode authority backends.

## Audit (spec §2)

Full per-table audit in `STATE_OWNERSHIP.md`'s Phase 14A.4 addendum:
`users`, `signup_counter`, `usage_daily`, `user_sessions`,
`organizations`/`org_members`, `privacy_consents`/`consent_audit_log`,
`data_export_requests`, `security_breach_log`, and the hash-chained
`audit_log` all require this backend for distributed correctness — all
now closed. Godmode's *own* elevation audit (`orca/godmode/audit.py`)
is a separate, pre-existing, in-memory-only mechanism, unaffected by
and out of scope for this closure — confirmed authorization decisions
never depend on it, so no "durable audit before authorization"
architecture was silently violated.

## Fix

`orca.godmode.deployment_profile.require_distributed_core_db_url()`
extends `validate_deployment_config()` (not a disconnected new path,
per spec §6). `orca/serve/api.py`'s validation call was moved to the
very top of the file — before any `orca.*` import that could
transitively connect to a database — closing a real ordering gap
(`orca.auth`'s own import chain would otherwise reach `orca.auth.db`'s
unconditional `init_db()` before validation ever ran). `orca/auth/db.py`
itself also fails fast at its own import time, as defense in depth for
any entry point that imports it directly. `/readyz` now also reflects
core-database availability in DISTRIBUTED mode, mirroring the
security-root check.

## Two real bugs found and fixed during implementation

1. **Test-pollution root cause**: `tests/conftest.py`'s `isolated_home`
   fixture only ever popped the legacy `ORCA_DATABASE_URL` env var,
   never `ORNEUR_DATABASE_URL` — the name this whole project has since
   migrated to preferring. A leftover value from this phase's own
   DISTRIBUTED-mode tests silently redirected unrelated tests
   (`tests/test_auth_privacy.py`, `tests/test_org_store.py`) at a real
   shared Postgres database instead of their own isolated SQLite tmp
   file, surfacing as raw `psycopg.errors.UniqueViolation` failures.
   Fixed at the actual root cause in the shared fixture, not papered
   over locally.
2. **Reload-in-teardown hazard, caught before landing**: an initial
   draft of this phase's own teardown fixture reloaded
   `orca.auth.db`/`store`/`audit` after restoring env vars — which,
   once restored to the real (unset) environment, would itself have
   triggered `init_db()` against the real `~/.orca/auth.db`. Caught by
   checksumming the real file before/after an isolated run of the new
   test file and noticing it was untouched only in isolation, not in
   the combined run; reverted before being kept.

## Test evidence

`tests/test_distributed_core_db_config_gate.py` — **16 new tests**:
table-ownership contract, SOVEREIGN unaffected, DISTRIBUTED missing/
malformed/unreachable core-DB config all fail (at import for
`orca.auth.db`, or via `validate_deployment_config()`), no secret
leakage in error messages, a genuine two-process test using the real
production abstraction (`orca.auth.store.create_user`/
`record_user_session`, `orca.audit.log`/`recent` — not direct SQL) with
worker B observing worker A's user, session, and audit entry, a
misconfigured worker refusing startup with no local `auth.db` fallback,
backend outage after startup denying safely with no fallback and clean
recovery, tenant-scoped audit isolation across two processes, Godmode's
in-memory audit and `orca.audit.log()`'s fail-soft contract both
confirmed as pre-existing/unaffected, a security-root regression check,
and a `/readyz` core-database-outage test.

## Full regression

- Deterministic-only (`pytest -m "not live_ollama_smoke"`): see the
  final validated count below (a checkpoint run before the `/readyz`
  core-database check landed already confirmed **1539 passed, 0
  failed, 43 deselected**, 336.23s).
- Security suite: **875 passed, 0 failed** (874 + 1 new `/readyz` test,
  itself on top of 859 before this phase's other 15 tests).
- Live suite: not re-run — per spec §22, no model-inference-path
  changes were made; Phase 14A.2's clean 43/43 remains the accepted
  baseline.
- State leak: `~/.orca/godmode` and `~/.orneur-security-root` both
  confirmed absent throughout. `~/.orca/auth.db` (a real, pre-existing
  file from ordinary developer use of this repository, predating this
  entire multi-phase session) was checksummed before and after the
  full regression and confirmed byte-for-byte unchanged.

## Known limitations

1. `orca/auth/db.py`'s `init_db()` runs unconditionally at module
   import time (a pre-existing characteristic, not introduced this
   phase) — this makes reloading that module with a bad DSN a harsher
   failure mode (crash at import) than a graceful runtime call. This
   phase's own tests work around it correctly (by not reloading with a
   bad DSN, relying instead on `_get_postgres_conn()`'s per-call fresh
   env read), but any other code that reloads this module casually
   should be aware of the same behavior.
2. The broader test suite's isolation of `orca.auth.db`/`ORCA_HOME`
   relies on individual test files' own fixtures (like `isolated_home`)
   rather than a single global autouse guarantee — unlike
   `LEASE_DIR`, which conftest.py's autouse fixture redirects for
   every test unconditionally. This is a real, pre-existing,
   disclosed structural characteristic of this test suite (module-level
   imports at collection time happen before any fixture can run), not
   something this phase introduced or was in scope to redesign.

## Remaining Phase-14A blockers

None. All three configuration gates this multi-part closure opened to
address (security root, then core database) are now closed with real
evidence.

**READY FOR PHASE 14B CLOUD DEPLOYMENT: YES**

Per spec §26: stopping here. No cloud resources are provisioned. No
Phase 15 work begins without explicit human approval.
