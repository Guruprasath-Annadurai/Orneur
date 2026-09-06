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

**PHASE 14B.1 CLOUD-ONLY DISTRIBUTED QUALIFICATION: FAIL** (unchanged
verdict, new and different root cause than the first FAIL; real
progress made and disclosed, not claimed as resolved). Not proceeding
to Phase 14C. Stopping further expensive real cross-host iteration at
this point given the cost/time already spent this session; the next
session should investigate Supabase connection-pooling behavior under
concurrent multi-connection-per-race load before attempting a third
real requalification run.
