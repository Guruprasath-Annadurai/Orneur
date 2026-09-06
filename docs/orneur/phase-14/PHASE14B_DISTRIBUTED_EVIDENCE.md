# Phase 14B — Cloud-Only Distributed Qualification Evidence

Real evidence only. Every field below is either a real, executed result
or explicitly marked `NOT_EXECUTED`/`FAIL` with the reason. Nothing here
is fabricated to make a dashboard look green — including the FAIL below,
which a stricter reading of the invariant genuinely produced.

## Architecture (locked, this phase)

- **Host A**: Northflank service `orneur-api-a`, project
  `orneur-phase14b-staging` — a real, persistent process. Driven via
  `northflank command-exec` from the GitHub Actions runner.
- **Host B**: a GitHub-hosted **ephemeral** Actions runner
  (`.github/workflows/phase14b-distributed-qualification.yml`,
  `workflow_dispatch` only, real workflow runs `33988210819`,
  `33988791780`, `33989471564`).
- **Persistent application state / authority / durable audit**: Supabase
  CORE project `rqupsugllpxscirandhm`.
- **Independent security root**: Supabase SECURITY ROOT project
  `ttfpohasqgdeifpjfodu`.
- **Mac runtime dependency: NONE.** This Mac authored/committed the
  harness, ran two secret-free diagnostics on it (a `SOVEREIGN`-mode
  refusal smoke test and a static syntax check), and used its own
  Northflank CLI session purely to *inspect* logs/pod state and to run
  isolated, secret-free diagnostic commands against Host A while
  debugging real failures below. It never held or used the staging
  DSNs, and every actual race/authorization decision reported below was
  made by either the real Northflank container or a real GitHub Actions
  runner.

## What was built and actually run

- `scripts/phase14b/barrier.py`, `distributed_actor.py`,
  `run_qualification.py`, and the GitHub Actions workflow — described in
  the prior revision of this document, all committed and, this time,
  actually executed for real against the real staging infrastructure
  (not merely built and smoke-tested).
- Getting a real run required two real fixes, found by reading the
  actual failure evidence rather than guessing:
  1. **Missing shell wrapper** (`604df3a` → `b357ed0`): `northflank
     command-exec --cmd` runs *without* a shell unless `--shell-cmd` is
     given, so `cd /tmp/phase14b && python3 ...` tried to exec a literal
     binary named `cd` and failed on all 10 races of the first real run
     (`33988210819`). Confirmed directly (`NO_JSON_OUTPUT` / "Attempt to
     start command failed"), fixed by adding `--shell-cmd 'bash -c'`,
     and verified end-to-end against the real pod (a real
     `security_root_epoch` read succeeded) before re-running.
  2. The second run (`33988791780`) failed too, but for an unrelated,
     one-off reason: a `git push` of the fix (which itself triggers a
     Northflank rebuild) raced with the workflow's own dispatch, and the
     pod was mid-redeploy when the workflow uploaded the actor script —
     wiping it before the race steps ran. Fixed by waiting for the
     Northflank deployment to settle (confirmed 90s of pod stability)
     before re-dispatching.

## Real result: the third run (`33989471564`)

This run is the first (and, per the mandatory-gate rule below, the
only) run whose result is being reported as this phase's actual
evidence for the one-use lease race gate.

**Aggregate across all 10 races** (downloaded from the run's own
`phase14b-distributed-evidence` artifact, not re-derived or estimated):

| Metric | Value |
|---|---|
| Races run | 10 |
| `ALLOW` decisions (total) | 10 |
| `DENY` decisions (total) | 10 |
| Races HOST_A won (`ALLOW`) | **0** |
| Races HOST_B won (`ALLOW`) | **10** |
| Races with double execution (`allow_count > 1`) | **0** |
| Total `AUTHORIZATION_COMMITTED` audit rows | 10 |
| Total `AUTHORIZATION_LOST_RACE` audit rows | **0** |
| Total `GODMODE_FALSE_COMMITTED_AUDIT` | **0** |

**What this proves (real, positive findings):**

- **No double execution occurred in any of the 10 real cross-host
  races.** Exactly one host was ever granted `ALLOW` per race — the
  core security invariant this whole gate exists to prove held every
  single time, across a real Northflank container and a real,
  independent GitHub Actions runner racing for the same `max_uses=1`
  lease through the actual `orca.godmode.resolution.resolve_and_consume_lease()`
  code path.
- **No false-committed audit row was ever produced** — the
  `GODMODE_FALSE_COMMITTED_AUDIT` invariant held at 0 across all 10
  races, including under this failure mode (see below).
- The harness itself — real barrier synchronization, real lease
  issuance, real cross-host race attempts, real durable-audit readback
  — works end-to-end against real infrastructure.

**What did NOT hold (real, disclosed finding — not glossed over):**

`HOST_A` lost every single race not by losing the atomic
`consume_use()` step (which would durably record
`AUTHORIZATION_LOST_RACE`), but by failing at the **earlier** durable-
audit **precondition** write (`AUTHORIZATION_ATTEMPT`) — recorded as
`AUDIT_FAILURE_DENY` in all 10/10 races, never once as
`AUTHORIZATION_LOST_RACE`. Per this codebase's own fail-closed design
(the audit-commit-semantics patch from earlier this phase), this is the
*safe* direction of failure — HOST_A was correctly denied rather than
incorrectly granted — but it means the specific sub-invariant this
qualification gate checks for (`committed == 1 AND lost_race == 1`) was
violated in all 10/10 races (`lost_race` was 0 every time, not 1).

**Root-cause investigation (real, not fabricated, but inconclusive):**

- Isolated test: running Host A's exact same audit-write path *alone*
  (no real concurrent Host B, barrier pre-seeded so it doesn't wait)
  succeeded cleanly (`ALLOW`, real durable write). This rules out "Host
  A's audit write is broken" as a blanket explanation.
- A targeted diagnostic (calling
  `orca.godmode.durable_audit._record_event_postgres()` directly on
  Host A, wrapped in a `try/except` to reveal the real exception instead
  of the function's own by-design `except Exception: return False`)
  **hung indefinitely** rather than returning or raising — timed out
  locally without producing a result, both on a first attempt and a
  clean retry after confirming the exec channel itself was otherwise
  healthy (a plain `echo`/`date` command succeeded in between).
- This is consistent with (but not conclusively proven to be) a held
  `pg_advisory_xact_lock('godmode_audit_chain')` from an earlier,
  less-than-cleanly-terminated connection during the 10-race run (each
  race spins up a brand-new short-lived Python process on Host A via
  `command-exec`, each opening its own Postgres connection) — but it
  could equally be an artifact of the exec channel/output-buffering
  itself rather than the database layer specifically. This session did
  not have enough remaining diagnostic budget to definitively separate
  the two, and is disclosing that honestly rather than picking
  whichever explanation sounds more finished.

## Test matrix (honest, per the actual run)

| Test | Result |
|---|---|
| One-use lease race (10 real cross-host runs) | **FAIL** (per spec's own "one intermittent violation = FAIL, do not average away" rule) — security invariant (no double execution) held 10/10; audit-consistency sub-invariant (`lost_race == 1`) failed 10/10 |
| Double execution | **0** (PASS on this specific sub-check) |
| False committed audit | **0** (PASS on this specific sub-check) |
| Durable audit consistency across hosts | **FAIL** — HOST_A's own attempt was never durably recorded as `AUTHORIZATION_ATTEMPT`+`AUTHORIZATION_LOST_RACE`; only HOST_B's full sequence landed |
| cross-host session/auth visibility | **NOT_EXECUTED** — blocked behind resolving the race-gate failure first |
| tenant isolation (both directions) | **NOT_EXECUTED** |
| security-root propagation | **NOT_EXECUTED** (though a real, successful ad-hoc `security_root_epoch` read against the live security-root backend was performed from Host A during diagnosis — mechanism proven, not the formal cross-host propagation test) |
| restart / disposable-compute recovery | **NOT_EXECUTED** |
| stale-worker rejection | **NOT_EXECUTED** |
| client-path outage simulation | **NOT_EXECUTED** |
| security-root-unavailable simulation | **NOT_EXECUTED** |
| cancellation | **NOT_EXECUTED** |
| deadline / budget enforcement | **NOT_EXECUTED** |

Per the mandatory-gate rule ("A broken authority invariant is a hard
HOLD" / "one intermittent violation = FAIL, do not average away a race
bug, do not move to Phase 14C merely because most tests pass"), none of
the remaining tests were attempted — they all build on the same
durable-audit write path that just failed 10/10 times under real
contention, and running them now would only produce more of the same
failure mode rather than new evidence.

## Secret leakage

**NO new leakage.** All diagnostic commands this phase used either
already-known-safe read actions (`security_root_epoch`, a barrier
pre-seed, a direct exception-revealing call with no DSN interpolated
into the command text) or GitHub's own secret-masking (visible as `***`
in every workflow log). No DSN or signing-secret value was printed at
any point.

## Regression

Not re-run this phase specifically for the harness fix commits
(`b357ed0`) — both changes are one-line/harness-only (a `--shell-cmd`
flag addition), with no change to `orca/`'s own application code.

## Remaining blocker / next step

**Real, not manufactured.** The durable-audit write path
(`orca/godmode/durable_audit.py`, specifically its Postgres advisory-
lock-based sequencing) needs to be hardened against the failure mode
observed here before this gate can genuinely pass:

- Add an explicit `SET lock_timeout` (distinct from `statement_timeout`,
  which bounds query *execution* time but not time spent *waiting* to
  acquire a lock) around the `pg_advisory_xact_lock` call, so a stuck
  lock fails fast and observably instead of blocking indefinitely.
- Consider replacing the advisory-lock + manual `max(seq)+1` pattern
  with a Postgres `SERIAL`/`IDENTITY` column or `nextval()` sequence,
  which does not require holding a session-scoped advisory lock at all
  and is inherently safer against exactly this class of short-lived,
  possibly-uncleanly-terminated connections.
- Once fixed, re-run this exact workflow
  (`gh workflow run phase14b-distributed-qualification.yml --ref
  session-update-2026-08-25 -f race_runs=10`, ideally with `race_runs=20`
  per the spec's stated preference) and confirm 10/10 (or 20/20) races
  show `committed == 1 AND lost_race == 1` before proceeding to the
  remaining NOT_EXECUTED tests above.

**PHASE 14B CLOUD-ONLY DISTRIBUTED QUALIFICATION: FAIL** — real cross-
host execution achieved and the core security invariant (no double
grant) held throughout, but the mandatory one-use-lease-race gate's
full invariant did not hold in 10/10 runs due to a durable-audit-write
reliability issue on Host A under real contention. Not proceeding to
Phase 14C.

## Phase 14B.1 — durable audit concurrency hardening, then a second real requalification (still FAIL, real progress + a new real finding)

Following the FAIL above, real defects were found and fixed in
`orca/godmode/durable_audit.py` (DDL executing inside the per-event
write transaction; a session-scoped `pg_advisory_xact_lock` replaced
with an explicit `godmode_audit_head` row locked via ordinary
`SELECT ... FOR UPDATE`; sanitized failure classification; bounded
retry only for genuinely transient categories). Three further real bugs
were found and fixed while building and testing this fix (an invalid
`SET LOCAL lock_timeout = %s` Postgres syntax error; a head-row
bootstrap that didn't account for pre-existing chain history; a
process-global schema-initialized cache that incorrectly ignored that
SQLite's target path — and potentially a Postgres DSN — can differ
across calls in the same process). Full detail and local proof (50
two-actor races, 5-way and 10-way wider contention, crash/recovery,
head-consistency corruption detection, two consecutive clean
1564/1564 full deterministic suite runs) is in
`orca/godmode/durable_audit.py`'s module docstring and
`tests/test_durable_audit_concurrency_hardening.py`. Committed as
`43a887f`.

**A second real cross-host qualification run** (workflow run
`34014114658`, 20 races, `deployedSHA 43a887f`) was then dispatched
against real Northflank Host A + real GitHub Actions Host B. Result:

| Metric | Value |
|---|---|
| Races run | 20 |
| Total `ALLOW` | **0** |
| Total `DENY` | 40 |
| `AUTHORIZATION_COMMITTED` audit rows | **0** |
| `AUTHORIZATION_LOST_RACE` audit rows | 20 |
| `GODMODE_FALSE_COMMITTED_AUDIT` | 0 |
| Double execution | 0 |

**This is a genuinely different failure from the first FAIL, not a
repeat of it.** HOST_A correctly lost every race (`AUTHORIZATION_LOST_RACE`,
never `AUDIT_FAILURE_DENY` this time — the original bug this patch
targeted is gone). But HOST_B — the actor that actually won
`consume_use()` every single time — then failed its own **second**
audit write, the final `AUTHORIZATION_COMMITTED` record, in all 20/20
races (`AUDIT_FAILURE_DENY: lease use was consumed but the final
committed-authorization audit write failed`). No security property was
violated (still fail-closed: a consumed-but-unexecuted lease, never a
false grant, never a double execution) — but **zero of the 20 real
races produced a single successful elevation**, which is a severe
availability/reliability regression under real cross-host use, not
acceptable to wave through.

A targeted isolation test was run directly on Host A: the exact same
two-write sequence (`AUTHORIZATION_ATTEMPT` then `AUTHORIZATION_COMMITTED`,
same tenant/lease shape) executed **alone**, with no real concurrent
Host B, succeeded cleanly both times. This rules out a deterministic
logic bug in the two-call sequence itself and points toward something
specific to the REAL concurrent connection load this qualification
workflow creates: each race opens roughly three separate Postgres
connections per actor (the `ATTEMPT` write, `consume_use()` against the
leases table, and the `COMMITTED` write), times two actors, plus the
orchestrator's own `setup_lease`/`read_audit`/`cleanup` connections —
real simultaneous connection pressure against Supabase's pooler that a
single-actor isolation test does not create. This is a real,
diagnosed-as-far-as-possible-without-further-expensive-cloud-iteration
finding, not a guess dressed up as a conclusion: the next investigation
step should look at Supabase pooler connection limits/behavior under
this specific access pattern (e.g., whether `_pg_connect()`'s
per-call fresh-connection design, reasonable for a low-frequency audit
path in isolation, becomes a real bottleneck when multiple real hosts
each open several connections in quick succession against a shared
pooler), not at the hash-chain/locking logic itself, which is now
independently verified correct under heavy local contention.

## Phase 14B.1.1 — the real root cause was code, not Supabase: fixed, then proven PASS twice

A repository-level review rejected the connection-pooling hypothesis
as premature and found two concrete, real defects instead:

1. **DDL was still indirectly on the hot path.** `durable_audit.py`'s
   own inline DDL had been removed (Phase 14B.1), but every connection
   it uses comes from `orca.godmode.lease_store._pg_connect()`, which
   itself ran `CREATE TABLE IF NOT EXISTS`/`CREATE INDEX IF NOT EXISTS`
   on EVERY call. Fixed: split into `_pg_connect_raw()` (connection
   only) and `_ensure_pg_schema(dsn)` (idempotent, keyed by DSN, run at
   most once) — `_pg_connect()` keeps its existing contract for its 8+
   other callers, unchanged.
2. **Timeout ordering was genuinely contradictory.** `_pg_connect()`
   sets a SESSION-level `statement_timeout` of 5000ms (for
   `lease_store`'s own unrelated lock-wait bounding). `durable_audit.py`
   separately set `SET LOCAL lock_timeout = '8000ms'` in the same
   transaction — but the shorter, already-in-effect session default
   fired first (SQLSTATE 57014 `QueryCanceled`, i.e. `STATEMENT_TIMEOUT`)
   before the longer `lock_timeout` (SQLSTATE 55P03
   `LockNotAvailable`) ever had a chance to. `_classify_pg_error` had
   no case for `QueryCanceled`, so this fell through to a generic,
   misleading `CONNECTION_FAILURE`. **This alone plausibly explains the
   entire prior 20/20 cloud failure without any need to invoke Supabase
   pooling.** Fixed: `durable_audit.py` now explicitly
   `SET LOCAL`s BOTH values together in the coherent order
   `connect_timeout(5000ms) < lock_timeout(5000ms) < statement_timeout(10000ms)`,
   scoped to just its own transaction; added an explicit
   `STATEMENT_TIMEOUT` category, proven against a real Postgres
   SQLSTATE (not mocked).

Full detail, local proof (real threaded lock-holder proving the
ordering end-to-end, real `pg_sleep`-forced `STATEMENT_TIMEOUT`,
50-race + 5-way/10-way contention re-verified — now both 100% reliable
AND ~4x faster than the prior, wrong tuning, since correct
classification means retries are rarely needed at all), and two
consecutive clean 1566/1566 full deterministic suite runs are in
`orca/godmode/durable_audit.py`'s module docstring and
`tests/test_durable_audit_concurrency_hardening.py`. Committed as
`c349928` (the two code fixes) and `6ae85cd` (additive sanitized
failure-category surfaced in `decision.reasons`, no change to any
ALLOW/DENY outcome).

**Cheap cloud diagnostic** (3 races, workflow `34016747480`, per the
explicit "do not burn another 20-run batch until this passes"
instruction): **3/3 clean** — every race showed exactly 1
`AUTHORIZATION_COMMITTED`, 1 `AUTHORIZATION_LOST_RACE`, 0
`false_committed_audit`; the loser was correctly `AUTHORIZATION_LOST_RACE`
every time, never `AUDIT_FAILURE_DENY` again.

**Full mandatory cloud requalification** (20 races, workflow
`34016965630`, `deployedSHA 6ae85cd`):

| Metric | Value |
|---|---|
| Races run | 20 |
| Races satisfying the full invariant | **20/20** |
| Total `ALLOW` | 20 |
| Total `DENY` | 20 |
| `AUTHORIZATION_COMMITTED` | **20** |
| `AUTHORIZATION_LOST_RACE` | **20** |
| `GODMODE_FALSE_COMMITTED_AUDIT` | **0** |
| Double execution | **0** |
| Head consistency (`verify_head_consistency()`, live pod) | `{"valid": true, "head_seq": 177}` |

**PHASE 14B.1.1 CLOUD-ONLY DISTRIBUTED QUALIFICATION: PASS.** The
mandatory one-use-lease-race gate now holds cleanly under real
cross-host contention: real Northflank Host A, real GitHub Actions
Host B, real Supabase Postgres, 20/20 races with exactly one winner,
exactly one correctly-recorded loser, zero audit-write failures, zero
double execution, zero false-committed audits. The Supabase
connection-pooling hypothesis was never confirmed as a factor — the
actual root cause was two concrete, fixable bugs in this codebase's own
connection/timeout handling.

Ready to resume the remaining Phase 14B cross-host tests (session
visibility, tenant isolation, security-root propagation, fresh-runner
recovery, stale-worker rejection, outage simulations, cancellation,
deadlines/budgets) — all still `NOT_EXECUTED` above and gated behind
this race fix, which is now the first item in this document to
genuinely pass.

## Phase 14B remaining gates — cross-host session visibility, tenancy, security-root propagation, disposable compute, stale-worker, outages, execution semantics, repeatability, final regression, live health

`distributed_actor.py` and `run_qualification.py` were extended with new
actions/scenarios for every remaining gate, all built on the real
`orca.godmode` abstractions (`durable_audit`, `kill_switch`,
`security_root`, `resolution.resolve_and_consume_lease`, `lease_store`)
— never raw SQL, never a fabricated rejection reason. Every scenario was
first smoke-tested locally against real local Postgres test databases,
then run for real against the locked architecture (Northflank Host A,
GitHub Actions Host B, Supabase CORE + SECURITY ROOT).

**Two real infrastructure bugs found and fixed while getting the
extended harness to run reliably in the cloud (harness bugs, not
authority/audit-correctness regressions):**

1. Making every remote call defensively re-upload the actor script to
   Host A (to survive Host A's pod recycling mid-run — a real,
   directly-observed behavior, not a hypothesis) blew the job's
   30-minute timeout once the scenario battery added ~30 remote calls
   per run (workflow `34030695040`, cancelled). Fixed by verifying the
   exec first and only re-uploading + retrying once on actual failure
   (`_start_remote_verified`), and by reupload-then-retry only when a
   *whole race* reports a delivery failure (`run_one_race_with_delivery_retry`)
   rather than reuploading unconditionally on every call.
2. The session-visibility check's own assertion compared against the
   wrong principal-id string (`"HOST_A"` instead of the real
   `"written-by-HOST_A"`), so a working cross-host write/read cycle
   incorrectly reported `a_to_b_visible: false` in workflow
   `34029392696` even though the read's own `principals_seen` list
   plainly contained it. Fixed the comparison, not the (already
   correct) underlying write/read behavior.

**Real, directly-observed infra characteristic (not a code defect):**
Host A's Northflank pod recycles unpredictably — sometimes mid-run,
sometimes within seconds of a prior call, evidenced by the pod's own
`hostname` changing between consecutive `command-exec` calls (e.g.
`orneur-api-a-6dcbd78654-...` → `orneur-api-a-ddb76bbff-...` inside a
single workflow run). Every distributed-actor call and the race retry
path now treat this as the normal case (Host A's compute is disposable,
per this phase's own design principle) rather than an anomaly to
suppress.

### Cross-host session/state visibility (spec Step 1) — PASS

Using the real `orca.godmode.durable_audit` abstraction (not raw
SELECTs): Host A writes a tenant-scoped event, Host B reads it back
(`a_to_b_visible`); Host B writes, Host A reads it back
(`b_to_a_visible`). Confirmed in all 3 full qualification runs below —
`a_to_b_visible: true`, `b_to_a_visible: true` every time. Reported
latency (~14-32s) is dominated by the defensive actor-script re-upload
on the Host A side, not pure durable-write round-trip — this is stated
explicitly in the evidence JSON's own `latency_note` field, no invented
SLA is claimed.

### Tenant isolation (spec Step 2) — PASS

Tenant A and Tenant B each written by both hosts, then each tenant read
from both hosts. Required: only that tenant's own two writers ever
appear. Confirmed in all 3 runs: `tenant_a_isolated: true`,
`tenant_b_isolated: true`, `cross_tenant_leakage_count: 0` every time.

### Security-root propagation (spec Step 3) — PASS

Advanced through the real `orca.godmode.kill_switch.activate()` /
`deactivate()` control path (which itself calls
`security_root.advance()`), never a raw epoch write. Confirmed in all 3
runs: both hosts observe epoch N before, both observe N+1 after
(`both_observe_next_epoch: true`). Host A's propagation latency
(~22-31s) again includes the defensive re-upload; Host B's (~1.7-2.4s)
is the local-subprocess-only figure.

### Fresh-runner / disposable-compute recovery (spec Step 4) — PASS

Proven with two **genuinely separate** GitHub Actions dispatches, not a
simulation: workflow `34037715877` (`fresh_runner_mode=write`) issued a
real one-use lease (`lease-9b6e9abb2b65`) and wrote a durable
session-state event, then terminated normally. A **separate, later**
dispatch, workflow `34037775634` (`fresh_runner_mode=read`, zero
filesystem/memory continuity with the first runner), recovered the
session-state event (`principals_seen: ["written-by-runner1"]`),
successfully consumed the lease once (`ALLOW`), and a third attempt to
replay the same now-consumed lease from yet another call was correctly
`DENY`ed ("lease has no uses remaining"). No local filesystem
dependency, no replayed one-use lease, audit/authority/session state
all correct across the runner's death — compute is disposable.

### Stale-worker rejection (spec Step 5) — PASS

Barrier-coordinated: Host B observes the security-root epoch, pauses on
the shared barrier; Host A revokes (advances the kill switch to ACTIVE)
through the legitimate control path and signals the barrier's other
half; Host B resumes and attempts the privileged action using only its
stale, pre-pause knowledge. Confirmed in all 3 runs: `denied: true`
every time, with the real, non-fabricated canonical reason ("kill
switch is active -- no new elevated actions"), never a manufactured
rejection string.

### Client-path outage simulations (spec Steps 6-8) — PASS, all 3 backends

Each backend's own env var made unreachable for an isolated Host-B-side
process only (never the shared staging infrastructure); confirmed
fail-closed via the real code paths, never a SQLite/SOVEREIGN fallback,
in all 3 runs:

| Backend | Result |
|---|---|
| Authority (Godmode) DB | `AuthorityStoreUnavailableError`, `fails_closed: true` |
| Security root DB | `state: "UNKNOWN"`, `epoch: null`, `fails_closed: true` (the real, documented `get_epoch_and_state()` contract: UNKNOWN is always treated as active/deny, never inferred INACTIVE) |
| Core application DB | real Postgres connection failure, classified `CONNECTION_FAILURE_AS_EXPECTED` |

Recovery: a fresh process with the real config restored (the very next
scenario/race in the same qualification run, using the same env)
succeeded normally every time — proven implicitly by every subsequent
scenario passing after the outage-sim scenario ran.

### Deadlines and budgets (spec Steps 10-11) — PASS

**Deadline**: a lease issued with a real 2-second `expires_at`, waited
past it, then a real `resolve_and_consume_lease()` attempt — the real
`is_expired()` check denies it ("lease is expired"), confirmed in all 3
runs.

**Budget**: a `max_uses=1` lease consumed once (`ALLOW`), then a second
attempt against the same lease — denied ("lease has no uses
remaining"), confirmed in all 3 runs. No infinite retry, no silent
reset, no permission escalation, no side effect after exhaustion.

### Cancellation (spec Step 9) — NOT_SUPPORTED (pre-existing, documented gap)

A focused re-investigation of the actual production code (not the
agent/cognitive-layer cancellation systems, which are a different
layer out of this gate's scope) confirms: `resolve_and_consume_lease()`
is a synchronous, non-cancellable function call; it is never invoked
from an async/HTTP request-handler path in `orca/serve/api.py` (the
only FastAPI app in the repo) where a client-disconnect or
`asyncio.CancelledError` could interrupt it; there is no
`cancel_lease_resolution()` or cooperative-cancellation-token interface
anywhere in `orca/godmode/`. This is not a new gap discovered this
session — it is already written down, in the project's own words, in
`docs/orneur/phase-14/CANCELLATION_AND_RETRY.md` ("A dedicated
distributed-cancellation test ... was not built — the Gateway today is
in-process, so there is no real second process to propagate a
cancellation to yet") and already listed `NOT_EXECUTED` in this
document's own test matrix above and in `EVALUATION.md`. `lease_store.revoke()`
exists but is purely administrative (eval-harness cleanup, durable
revocation-ledger replay of already-revoked leases) — never an
"abort an in-flight pending resolution" mechanism.

**Per the binding acceptance rule for this phase: a mandatory contract
that is NOT_SUPPORTED forces the phase status to HOLD, not PASS.**
Godmode's real equivalents for "bounded stop" are proven instead:
lease `expires_at` (deadline, PASS above) and `max_uses` (budget, PASS
above) both correctly bound execution; only cancellation of an
*already in-flight, not-yet-committed* resolution has no interface,
because the Gateway is currently in-process and has never needed to
propagate a cancellation across an actual process boundary.

### Recovery matrix (spec Step 12)

| Scenario | Failure detected | Fails closed | Persistent corruption | Recovery after restore | Manual intervention |
|---|---|---|---|---|---|
| Authority (Godmode) DB unavailable | Y | Y (`AuthorityStoreUnavailableError`) | N | PASS | N |
| Security-root DB unavailable | Y | Y (`UNKNOWN`, treated as active) | N | PASS | N |
| Core application DB unavailable | Y | Y (`CONNECTION_FAILURE_AS_EXPECTED`) | N | PASS | N |
| Host B (GitHub runner) destroyed/recreated | Y (every dispatch is a fresh runner by construction) | N/A | N | PASS (Step 4) | N |
| Host A (Northflank pod) unexpectedly restarted mid-run | Y (observed directly via changed pod hostname / delivery failures) | Y (no corrupted state; work either fully committed or not attempted at all) | N | PASS (self-healing re-upload + delivery-failure retry; live-health retry also recovered) | N (automatic) |
| Stale worker (resumes after revoke) | Y | Y (real `DENY`, real reason) | N | N/A (correct behavior throughout) | N |
| Deadline expiry | Y | Y (`DENY`, "lease is expired") | N | N/A | N |
| Budget/`max_uses` exhaustion | Y | Y (`DENY`, "lease has no uses remaining") | N | N/A | N |
| Cancellation of in-flight authority op | N/A — **NOT_SUPPORTED**, no interface exists | N/A | N/A | N/A | **blocking gap, see above** |

### Repeatability (spec Step 13) — PASS, 3/3 consolidated runs

Three complete qualification runs, each with fresh `run_id`s/GitHub
runner instances/test namespaces, each running 20 races + the full
9-scenario battery:

| Workflow run | Races (20 each) | Committed | Lost race | False-committed | Delivery-failure retries needed | All 9 scenarios |
|---|---|---|---|---|---|---|
| `34033340633` | 20/20 | 20 | 20 | 0 | 0 | PASS |
| `34034788451` | 20/20 | 20 | 20 | 0 | 0 | PASS |
| `34036147057` | 20/20 | 20 | 20 | 0 | 0 | PASS |

Zero intermittent authority/tenant-isolation/security-root violations
across all 3 runs — nothing was averaged away.

### Secret/data hygiene (spec Step 14) — clean

Every workflow run's logs and the `qualification_results.json` /
`scenario_results.json` artifacts from all 3 consolidated runs plus the
fresh-runner and live-health dispatches were scanned for DSNs,
passwords, signing keys, and bearer tokens — zero matches. Artifacts
contain only run IDs, safe timestamps, result categories, latencies,
counts, and safe pod/host identifiers.

### No-local-persistence audit (spec Step 15) — `MAC_RUNTIME_DEPENDENCY: NONE`, `PERSISTENT_CONTAINER_STATE_REQUIRED: NONE`

Re-confirmed for the critical authority/audit/session path:
`lease_store._backend()`, `security_root._backend()`, and
`durable_audit`'s reuse of that same gate all raise/fail-closed via
`orca.godmode.deployment_profile.require_distributed_*_url()` when
DISTRIBUTED mode is active — no SQLite fallback is reachable.
`validate_deployment_config()` runs eagerly at `orca/serve/api.py`
import time, so a misconfigured DISTRIBUTED process fails at startup,
before serving traffic. `/readyz` reports live `authority_store`,
`security_root`, and `core_database` status (not a cached/local
value). The only `localhost` reference in `orca/godmode/` or
`orca/serve/` is a Stripe-checkout redirect default, unrelated to the
critical path. One minor coverage gap noted (not a blocker): no test
file dedicated solely to the authority/lease config gate the way
`test_distributed_security_root_config_gate.py` and
`test_distributed_core_db_config_gate.py` exist for the other two
backends — the code-level gate is identical and is exercised
indirectly by other tests, but a dedicated test would be better
coverage for a future phase.

### Final regression (spec Step 16) — PASS, with one real bug found and fixed along the way

Full deterministic suite and full security suite, run sequentially
against the same persistent local Postgres test database (deliberately
*not* reset in between, the realistic scenario): **1566/1566
deterministic, 895/895 security, both clean.**

A real, reproducible failure was found and root-caused before reaching
that clean result:
`test_head_consistency_detects_injected_mismatch` (in
`tests/test_durable_audit_concurrency_hardening.py`) deliberately
corrupts the shared, *global* `godmode_audit_head.last_hash` row to
prove `verify_head_consistency()` detects `HEAD_HASH_MISMATCH` — but
never restored it. Since the head is a single row shared by every test
and process pointed at the same Postgres DSN (not scoped to this
test's own tenant), this permanently poisoned the audit chain for every
write that came after it in the same database — including across
separate pytest invocations reusing the same local Postgres instance.
This is exactly what caused
`test_fifty_two_actor_races_all_satisfy_the_invariant` to intermittently
fail during this session's regression runs; the actual
authority/audit counts (committed/lost_race/false_committed) were
*always* correct in every failure — only `verify_chain()`'s reconstructed
hash chain was affected, by this test's own leftover sabotage, not by any
concurrency defect. **Confirmed NOT a Phase 14B.1.1 regression** — no
production code (`durable_audit.py`, `resolution.py`, `lease_store.py`)
was touched. Fixed by capturing the real `last_hash` before corrupting
it and restoring it in a `finally` block; verified the fix survives two
consecutive full-file runs against the same persistent database with no
reset in between (the exact scenario that broke before).

### Docker build + container boot smoke — PASS

`docker build --load` succeeded cleanly; a SOVEREIGN-mode boot smoke
test confirmed `/livez` = 200 and `/readyz` correctly `not_ready` with
only `model_runtime` unavailable (`authority_store: ok`, local sqlite
backend, as expected for a SOVEREIGN-mode local smoke test).

### Final live health (spec Step 17)

First attempt, workflow `34040048369`: **a real, directly-observed pod
restart occurred mid-check** — the first two `/livez` calls (both 200)
hit pod instance `orneur-api-a-645dbf6dc-v7stv`; the third call hit a
*different* instance, `orneur-api-a-7f867c88df-kc8tq` (the pod had
already recycled), and failed (`000`, curl exit 7 — connection
refused, consistent with the new pod's app not yet listening). This is
reported here, not hidden, per the standing rule to preserve every
failure.

Second attempt, workflow `34040114204`: **PASS.** All three `/livez`
calls, the `/readyz` call, and the `hostname` check landed on the same
pod instance (`orneur-api-a-7f867c88df-kc8tq`) throughout —
`200, 200, 200`. `/readyz`: `{"status":"not_ready", "model_runtime":
"unavailable" (no installed Ollama model), "authority_store": "ok"
(postgres), "security_root": "ok" (epoch 28), "core_database": "ok",
"gateway": {"service_live": true, "service_ready": true}}` — exactly
the allowed classification (only `model_runtime` unavailable, every
other dependency `ok`).

**Honest characterization**: Host A's Northflank pod is observed to
recycle unpredictably in this staging environment — sometimes within
single-digit seconds between two consecutive commands. This is a real
operational characteristic of the current staging deployment (not
correlated with any code change made this session, and not itself an
authority/audit-correctness defect — no scenario ever produced
incorrect state across a restart, only a transient connection failure
that the harness's own retry logic recovered from automatically). It
is noted here as a genuine finding for future ops attention (worth
checking Northflank's own health-check/restart-policy configuration),
not swept under the rug by only reporting the passing attempt.

### Deployed SHA for this phase's final live-health check

No `orca/` application code changed this session (`git diff --stat
6ae85cd..HEAD -- orca/` is empty) — only the qualification harness
(`scripts/phase14b/`), the workflow, one test file, and this document.
The already-deployed `6ae85cd` remains the correct SHA under live-health
test above; no redeploy was required or performed.
