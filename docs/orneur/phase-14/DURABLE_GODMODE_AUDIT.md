# Phase 14B §15-18 — Durable Godmode Elevation Audit

## The finding (worse than previously disclosed)

Phase 14A.4's own audit stated: "Godmode's OWN elevation audit
(`orca.godmode.audit`) is a plain in-memory list, entirely separate
from `ORNEUR_DATABASE_URL`'s hash-chained `audit_log`." True, but this
phase's mandatory pre-multi-host audit (spec §15) went one step
further and grepped **every real caller** of
`orca.godmode.audit.record_elevation_event()`:

```
orca/godmode/latency_bench.py:64:  record_elevation_event(...)
```

Exactly one call site — a benchmark script. The actual authorization
choke point, `orca.godmode.resolution.resolve_and_consume_lease()`
(the single function every real caller — AgentRuntime-compatible file
elevation, connector elevation, simulation revalidation — goes
through), **never called any audit function at all**, in-memory or
otherwise. The honest finding is not "the elevation audit trail isn't
durable" — it is "there was no elevation audit trail for real elevated
actions before this phase."

## Fix

`orca/godmode/durable_audit.py` (new) — a hash-chained, dual-backend
store reusing `orca.godmode.lease_store`'s existing connection
primitives (`_backend()`, `_connect()`, `_pg_connect()`), so this audit
trail lives in the same authority database as leases: SQLite for
SOVEREIGN, the shared `ORNEUR_GODMODE_DATABASE_URL` Postgres database
for DISTRIBUTED (proven cross-worker in Phase 14A already).

- **Schema**: `event_id`, `seq`, `event_type`, `principal_id`,
  `tenant_id`, `lease_id`, `capability`, `resource_scope`,
  `operation_scope`, `issuer`, `timestamp`, `trace_id`, `result`,
  `prev_hash`, `entry_hash`, `signature` — every field spec §15
  requires (tenant/principal/action identifiers, lease ID, outcome,
  timestamp, trace correlation), no more.
- **Tamper-evident**: each entry embeds the SHA-256 hash of the
  previous entry (single-writer chain, same design as `orca.audit`'s
  existing user/session audit log) plus an HMAC signature reusing
  `orca.audit._audit_key()` — the same key-management convention this
  project already established (`ORNEUR_AUDIT_KEY`, falls back to a
  loud dev-only key). `verify_chain()` recomputes every hash and
  compares against both the stored hash and the next entry's recorded
  `prev_hash` — a modified, deleted, or reordered row breaks the chain
  from that point forward, detected without any external trust anchor.
- **No secrets**: `capability`/`resource_scope` pass through
  `redact_secrets()` before persisting, matching
  `orca.godmode.audit`'s existing discipline exactly.
- **No raw chain-of-thought**: the schema has no field capable of
  holding model output/reasoning text.

`orca/godmode/resolution.py::resolve_and_consume_lease()` now calls
`durable_audit.record_event_durable()` directly for every decision it
reaches (both ALLOW and DENY are audited).

## Failure semantics (spec §16)

**Fail-closed, before the side effect**: for an ALLOW decision, the
durable audit write happens **before** `consume_use()`. If the audit
write fails, the function returns `DENY` (with a reason naming the
audit failure) and the lease use is **never consumed** — the elevated
action is denied rather than granted without a durable record. Tested
directly (`test_allow_decision_denied_when_durable_audit_write_fails`):
simulating an audit-write failure confirms both the DENY outcome and
that `uses_remaining` is unchanged.

A DENY decision is still audited (best-effort, no ordering constraint)
since nothing was granted either way — an audit-write failure for an
already-DENY decision does not need to change the decision.

**A disclosed accuracy nuance, not a security gap**: because the audit
write and `consume_use()` are two separate transactions (not one
atomically-coupled transaction), a narrow race is possible — the audit
write for an ALLOW decision could commit, and then `consume_use()`
could still lose a concurrent race and return DENY. In that case, the
audit trail would show a "USE"/"ALLOW" event for an action that
ultimately did not execute. This is the safe direction of error (an
audit record overclaiming, never underclaiming, what happened) and
does not permit any privilege escalation — the function's actual
returned decision is still correctly DENY. A fully atomic coupling
(one transaction spanning both the audit table and the leases table)
was not implemented this phase; disclosed as a known limitation rather
than silently accepted as perfect.

## Audit-commit-semantics patch (closes the accuracy nuance above)

The "disclosed accuracy nuance" above was not a privilege escalation,
but it WAS a real audit-truth defect: a durable row could say
`event_type="USE", result="ALLOW"` for an action that a concurrent
competitor's `consume_use()` call ultimately won instead. An owner
patch requested this be closed before any real multi-host
elevated-action test runs. Fixed in
`orca/godmode/resolution.py::resolve_and_consume_lease()` by replacing
the single pre-consume audit write with an explicit four-gate sequence
that never records a pre-consume event as a final grant:

1. `resolve_lease()` DENY → durably recorded as `AUTHORIZATION_DENIED`
   (result="DENY"), returned immediately.
2. Durable audit **precondition**: `AUTHORIZATION_ATTEMPT`
   (result="PENDING_CONSUME" — explicitly never "ALLOW") is written
   BEFORE `consume_use()` is even called. Write failure → DENY, lease
   untouched (unchanged from the original spec §16 ordering).
3. `consume_use()` is attempted. Lost race → durably recorded as
   `AUTHORIZATION_LOST_RACE` (result="LOST_RACE", never "ALLOW"), DENY
   returned. **This is the fix**: the earlier ATTEMPT row already made
   clear that row was never a grant, so no row anywhere claims ALLOW
   for an action that did not execute.
4. Only after `consume_use()` actually returns success is the FINAL
   `AUTHORIZATION_COMMITTED` event (result="ALLOW") durably written —
   the one and only event type/result pair that means the privileged
   side effect may execute. If this write fails, the consumed lease
   use is deliberately **not** restored or re-credited (per the
   patch's explicit instruction — "consuming a lease without executing
   is acceptable safe failure"); the caller still receives DENY, and a
   best-effort `AUDIT_FAILURE_DENY` marker is attempted (its own
   success is not required, since the write path that just failed is
   unlikely to succeed on immediate retry).

**New audit counter**: `GODMODE_FALSE_COMMITTED_AUDIT` — counts any
persisted row with `result="ALLOW"` whose `event_type` is not
`AUTHORIZATION_COMMITTED`. By this construction it is structurally 0;
`orca/godmode/durable_audit.py::count_false_committed_audit()` computes
it directly from a real event list rather than asserting it by
narrative, and the new concurrency test below checks it against real
concurrent contention, not just the single-worker happy path.

**Real concurrency test**
(`test_concurrent_workers_max_uses_one_exactly_one_committed_one_lost_race`):
a single `max_uses=1` lease, two real separate OS processes (real
`multiprocessing.get_context("spawn")`, real shared local Postgres)
race for it. Result: exactly one worker's decision is ALLOW, durably
recorded as the one `AUTHORIZATION_COMMITTED` row; the other is DENY,
durably recorded as `AUTHORIZATION_LOST_RACE`; the lease's
`uses_remaining` reaches exactly 0 (consumed once, not twice); and a
simulated privileged side effect (a shared counter incremented only
when `decision.state == "ALLOW"`) executes exactly once — zero double
execution. Confirmed stable across 5 consecutive real runs.

Cost of the fix: a successful elevation now writes 2 durable rows
(ATTEMPT + COMMITTED) instead of 1 — a deliberate, disclosed trade of
one extra write per decision for audit-truth correctness under real
concurrent contention. `LEASE_CONSUMED` (also in the requested
vocabulary) is not persisted as its own third row — the existence of
the `AUTHORIZATION_COMMITTED` row already proves consumption succeeded
(it is only ever written after `consume_use()` returns `True`), and
`AUTHORIZATION_LOST_RACE` already proves it did not; a redundant third
row per decision was judged not worth the extra write.

## Real test evidence

`tests/test_durable_godmode_audit.py` — **11 tests, all passing**:

| Test | What it proves |
|---|---|
| ALLOW durably audited (2 rows: ATTEMPT + COMMITTED), readable after a fresh reload | The core fix, updated for the commit-semantics patch |
| DENY also audited (as `AUTHORIZATION_DENIED`) | Complete decision coverage |
| Audit-write failure denies the action, use not consumed | Spec §16's fail-closed ordering (gate 2, unchanged) |
| Redaction preserved (both rows) | No secret leakage into the durable record |
| Cross-process visibility + "restart" persistence | Real multiprocess test against a real local Postgres database — see scope note below |
| `verify_chain()` on a clean chain (4 entries: 2 elevations × 2 rows) | No false positives |
| `verify_chain()` detects a tampered row | Spec §18 |
| `verify_chain()` detects a deleted row | Spec §18 |
| SQLite Sovereign path (2 rows) | Explicit backend coverage |
| Store unavailable denies | Fail-closed on connectivity loss |
| **Two-worker, max_uses=1 real race → exactly one COMMITTED, one LOST_RACE, one consumption, zero double execution, `GODMODE_FALSE_COMMITTED_AUDIT == 0`** | **The audit-commit-semantics patch** |

## Honest scope note (spec §17 vs. this session's actual capability)

The "cross-process visibility + restart persistence" test proves the
**mechanism** — a real, separate OS process, writing to and reading
from a real local PostgreSQL 17 database, sees the same audit trail,
and a full module reload (standing in for a process restart) still
sees it. This is **not** a claim of literal cross-**host** qualification
(spec §17's actual scenario: "Host A authorizes... Host B queries...
Restart Host A... event remains visible" across two genuinely separate
machines) — this session has no real second host, VPS, or Cloudflare
account available (confirmed: no SSH config, no `cloudflared`, no
prior infrastructure setup exists — see `REAL_STAGING_TOPOLOGY.md`).
The mechanism this phase built and proved is exactly what a real
cross-host deployment would need — the same `ORNEUR_GODMODE_DATABASE_URL`
Postgres instance, reachable from two hosts instead of two local
processes — but that final step requires real infrastructure this
session does not have, per the OWNER ACTION REQUIRED checkpoint in
`PHASE_14_CLOSURE.md`.

## Regression

Full godmode/connector/simulation/red-team regression (327 tests
across 27 files) reconfirmed green after wiring this into the live
authorization path — the highest-risk change this phase made, since it
touches the actual elevation choke point every real caller depends on.
No `~/.orca/godmode`/`~/.orneur-security-root` leakage; the real,
pre-existing `~/.orca/auth.db` confirmed byte-for-byte unchanged
throughout.

**After the audit-commit-semantics patch**: targeted
godmode/connector/simulation/redteam/security-root/core-db regression
re-run — **428 passed, 0 failed**. Full deterministic-only suite
(`pytest -m "not live_ollama_smoke"`) — **1551 passed, 0 failed, 43
deselected** (up 1 from the pre-patch 1550, the new concurrency test).
Security suite — **886 passed, 0 failed, 4 deselected** (up 1). Leak
check re-run clean: no `~/.orca/godmode`, no `~/.orneur-security-root`,
`~/.orca/auth.db` still byte-for-byte unchanged
(md5 `79bdd5281e3fd3122985fff307269d12`).
