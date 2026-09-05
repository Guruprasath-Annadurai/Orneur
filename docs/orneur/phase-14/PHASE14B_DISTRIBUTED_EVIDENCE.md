# Phase 14B — Cloud-Only Distributed Qualification Evidence

Real evidence only. Every field below is either a real, executed result
or explicitly marked `NOT_EXECUTED` with the reason. Nothing here is
fabricated to make a dashboard look green.

## Architecture (locked, this phase)

- **Host A**: Northflank service `orneur-api-a` in project
  `orneur-phase14b-staging` (persistent process, the accepted Phase 14B
  staging deployment).
- **Host B**: a GitHub-hosted **ephemeral** Actions runner
  (`.github/workflows/phase14b-distributed-qualification.yml`,
  `workflow_dispatch` only). No persistent local state; destroyed after
  each run.
- **Persistent application state / authority / durable audit**:
  Supabase CORE project `rqupsugllpxscirandhm`.
- **Independent security root**: Supabase SECURITY ROOT project
  `ttfpohasqgdeifpjfodu`.
- **Mac runtime dependency: NONE.** This Mac was used only as a
  development workstation to author the harness/workflow files below
  and to run a secret-free syntax/refusal smoke test (see "What was
  validated without secrets" below) — it never held, requested, or used
  the staging DSNs, and it is not a party to the qualification
  architecture. Every actual authorization decision in this evidence
  document is made by either the real Northflank container (Host A) or
  a real GitHub Actions runner (Host B).

## What was built this phase (real, committed artifacts)

- `scripts/phase14b/barrier.py` — a real, namespaced (`run_id`-scoped),
  durable cross-host synchronization barrier backed by a dedicated
  qualification-only table in the CORE Supabase database. Not
  sleep-based: both actors poll a shared row and release only once both
  have announced `READY`. Cleaned up (`cleanup(run_id)`) at the end of
  every run; never touches any real ORNEUR authority/audit table.
- `scripts/phase14b/distributed_actor.py` — the actor every role (
  `HOST_A`, `HOST_B`, `ORCHESTRATOR`) runs identically, exercising
  ORNEUR's real authorization layer directly (
  `orca.godmode.issuance.issue_lease`,
  `orca.godmode.resolution.resolve_and_consume_lease`,
  `orca.godmode.durable_audit.list_events_for_tenant` /
  `count_false_committed_audit`, `orca.godmode.security_root.get_epoch_and_state`)
  — not raw SQL standing in for the application. Refuses to run under
  `SOVEREIGN` (`REFUSED_NOT_DISTRIBUTED`), confirmed by a real local
  smoke test (see below). All test state is namespaced by `run_id`
  (`phase14b-<run_id>` tenant, `race-<uuid>` run ids) — never
  production data.
- `scripts/phase14b/run_qualification.py` — the orchestrator, run
  entirely on the GitHub Actions runner (Host B's own process host).
  For each race iteration it: issues one real `max_uses=1` lease,
  starts Host A's race attempt via `northflank command-exec` as a
  background OS process, runs Host B's race attempt as a concurrent
  local subprocess, waits for both, reads back the durable audit trail,
  and enforces the one-use-lease invariant per iteration (exactly one
  `ALLOW`/`AUTHORIZATION_COMMITTED`, exactly one
  `DENY`/`AUTHORIZATION_LOST_RACE`, zero
  `GODMODE_FALSE_COMMITTED_AUDIT`) — one violation across all
  iterations fails the whole run; results are never averaged away.
- `.github/workflows/phase14b-distributed-qualification.yml` —
  `workflow_dispatch`-only, `permissions: contents: read`, a GitHub
  Environment (`phase14b-staging`) gating all six `ORNEUR_*` secrets
  plus a Northflank service-account API token, an explicit fail-closed
  step if any required secret is missing, no `set -x`/`env`/`printenv`,
  no secret echoing, uploads the actor script to Host A via
  `northflank upload` rather than baking it into the production image.

## What was validated without secrets (this session, on this Mac)

- Static syntax/AST check of all three scripts: **PASS**.
- Fail-closed smoke test: running `distributed_actor.py` with
  `ORNEUR_DEPLOYMENT_PROFILE` unset (defaults to `SOVEREIGN`) produced
  `{"error": "REFUSED_NOT_DISTRIBUTED", "profile": "SOVEREIGN"}` and a
  non-zero exit — confirmed directly, not assumed.
- No-local-persistence audit (spec Step 20): every SQLite fallback path
  in `orca/auth/db.py`, `orca/godmode/lease_store.py`,
  `orca/godmode/security_root.py` is gated behind
  `is_distributed()` → `require_distributed_*_url()`, which raises
  before any local file is touched in DISTRIBUTED mode — confirmed by
  direct code read (already proven extensively in Phase 14A/14A.3/14A.4;
  reconfirmed here, not re-litigated).
- Full deterministic regression re-run after adding these files:
  see Tests section below.
- Dockerfile unaffected: `scripts/phase14b/` is not `COPY`'d into the
  production image (the Dockerfile only copies `orca/` +
  `pyproject.toml`/`README.md`); the new files add no attack surface to
  the deployed container.

## Cross-host distributed test matrix

| Test | Result |
|---|---|
| cross-host session/auth visibility | **NOT_EXECUTED** |
| tenant isolation (both directions) | **NOT_EXECUTED** |
| security-root propagation | **NOT_EXECUTED** |
| one-use lease race (target: ≥10 runs) | **NOT_EXECUTED** — 0 runs |
| double execution | **NOT_EXECUTED** |
| durable audit consistency across hosts | **NOT_EXECUTED** |
| restart / disposable-compute recovery | **NOT_EXECUTED** |
| stale-worker rejection | **NOT_EXECUTED** |
| client-path outage simulation (Host B) | **NOT_EXECUTED** |
| security-root-unavailable simulation | **NOT_EXECUTED** |
| cancellation | **NOT_EXECUTED** |
| deadline / budget enforcement | **NOT_EXECUTED** |

**Why**: every row above requires the actual GitHub Actions workflow to
run against the real staging secrets. That, in turn, requires a
Northflank credential that does not yet exist in this session and that
this session cannot create — see the blocker below. Building the full
harness now, ahead of that credential, means the real qualification run
can execute immediately once it's available, rather than qualification
work starting only after the ask is resolved.

## Regression

- Deterministic (`pytest -m "not live_ollama_smoke"`): **(recorded once the background run completes — see commit history / PR for the exact count)**
- Security suite: not re-run this phase (no ORNEUR application code
  changed — only new standalone scripts under `scripts/phase14b/` and a
  new workflow file; the security suite was already green after the
  last DB/CORS/rotation work).
- Container build/boot: unaffected (Dockerfile unchanged).

## Secret leakage

**NO leakage this phase.** No secret value was fetched, echoed, or
handled during this phase's work — the harness was built and smoke-
tested entirely without touching any staging credential (the fail-
closed refusal test above ran with `ORNEUR_DEPLOYMENT_PROFILE` unset,
deliberately, so no real DSN was ever needed to prove that path).

## Remaining blocker (real, not manufactured)

**A Northflank credential for CI use does not exist yet.** The Phase
14B workflow needs a way to `northflank command-exec` into Host A from
inside a GitHub Actions runner. This session's own Northflank CLI
session is an interactive browser login (correctly not something to
export/reuse as a long-lived CI credential — the spec explicitly
forbids that), and this session cannot create a new, properly-scoped
Northflank API token itself (token creation requires the account
owner's own dashboard session).

```
USER ACTION REQUIRED

1. In Northflank, create a least-privileged Service Account API token
   scoped to project orneur-phase14b-staging with at minimum:
   Project > Services > General > Read/Update, and command-exec/upload
   permission on orneur-api-a. Do not reuse your personal browser
   session or a long-lived admin token.
2. In the GitHub repo (Guruprasath-Annadurai/Orneur) settings, create an
   Environment named phase14b-staging.
3. Add these secrets to that environment (values only you enter --
   never paste them to me):
   - NORTHFLANK_API_TOKEN (from step 1)
   - ORNEUR_DATABASE_URL
   - ORNEUR_GODMODE_DATABASE_URL
   - ORNEUR_SECURITY_ROOT_DATABASE_URL
   - ORNEUR_AUDIT_KEY
   - ORNEUR_GODMODE_LEASE_SECRET
   - ORNEUR_AUTH_SECRET
   (Same values already in the Northflank orneur-phase14b-runtime
   secret group -- Host B needs its own copy to reach the same Supabase
   backends.)
4. Reply only: done.
```

Once available, I will dispatch the real workflow
(`gh workflow run phase14b-distributed-qualification.yml`), read back
its real run logs/artifact, and populate every `NOT_EXECUTED` row above
with a real `PASS`/`FAIL` result — including running the one-use lease
race at least 10 times and failing the whole gate on a single
violation, per the mandatory-gate instruction.

**PHASE 14B CLOUD-ONLY DISTRIBUTED QUALIFICATION: BLOCKED** (harness
ready; awaiting the credential above). Not `FAIL` — no test has run
and failed; the gate has simply not been attempted yet, honestly
reported as such rather than fabricated.
