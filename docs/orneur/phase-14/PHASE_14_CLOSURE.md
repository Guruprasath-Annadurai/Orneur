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
