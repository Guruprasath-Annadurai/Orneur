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

## Real test evidence

`tests/test_durable_godmode_audit.py` — **10 tests, all passing**:

| Test | What it proves |
|---|---|
| ALLOW durably audited, readable after a fresh reload | The core fix |
| DENY also audited | Complete decision coverage |
| Audit-write failure denies the action, use not consumed | Spec §16's fail-closed ordering |
| Redaction preserved | No secret leakage into the durable record |
| Cross-process visibility + "restart" persistence | Real multiprocess test against a real local Postgres database — see scope note below |
| `verify_chain()` on a clean chain | No false positives |
| `verify_chain()` detects a tampered row | Spec §18 |
| `verify_chain()` detects a deleted row | Spec §18 |
| SQLite Sovereign path | Explicit backend coverage |
| Store unavailable denies | Fail-closed on connectivity loss |

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
