# Phase 14A.1 — Kill-Switch Durability and Stale-Restore Closure

## The vulnerability, reproduced before any fix

Phase 14's own closure report explicitly flagged this as open: "the
Godmode kill switch has the same stale-backup/restore risk class that
was discovered and fixed for lease revocation." Reproduced directly,
exactly per the governing spec's required steps, before writing any
fix code:

1. Kill switch initially OFF — confirmed (`is_active() == False`).
2. Backed up the authority state (the whole `godmode` directory).
3. Activated the kill switch — confirmed (`is_active() == True`).
4. Verified an elevated authorization attempt DENIES.
5. Restored the pre-activation backup over the live state.
6. Attempted elevated authorization again.

**Pre-fix result**: the restored kill switch read back `INACTIVE`, and
the elevated authorization attempt returned `ALLOW` — the kill switch
was silently disabled by the stale restore. This is preserved as a
permanent regression sentinel in
`tests/test_kill_switch_stale_restore.py::test_raw_vulnerability_stale_restore_resurrects_disabled_kill_switch`,
which deliberately keeps reproducing the raw bug (by stripping the
fix's own ledger file out of the restored copy) so a future change
cannot silently regress this fix unnoticed.

## Design

Two changes, reusing the proven pattern from Phase 14A's lease-
revocation fix, per the governing spec's own instruction not to
blindly duplicate code where a shared abstraction is cleaner:

1. **Kill-switch state moved into the authority database itself**
   (`orca/godmode/lease_store.py`'s new `kill_switch_state` table — a
   single row, `id=1`, present in both the SQLite and PostgreSQL
   schemas) instead of a standalone flag file. This closes spec §21's
   cross-worker visibility requirement **structurally, for free**, in
   the DISTRIBUTED profile: every worker querying the same shared
   Postgres instance sees the same row, live — exactly the same
   guarantee leases already had. State changes go through the same
   `BEGIN IMMEDIATE` (SQLite) / `SELECT...FOR UPDATE`-equivalent
   (Postgres — a single-row upsert here, since there's nothing to
   read-validate-mutate atomically beyond the write itself) transaction
   discipline as leases.
2. **A new append-only kill-switch event ledger**
   (`orca/godmode/kill_switch_ledger.py`), structurally identical to
   `revocation_ledger.py`'s pattern but for a singleton "latest event
   wins" reconciliation semantic rather than per-lease-id tracking. A
   new shared primitive, `orca/godmode/authority_ledger.py`, factors
   out the actual file-append/file-read mechanics both ledgers now use
   — the two ledgers' *reconciliation* semantics stay separate (they
   genuinely differ), but the low-level I/O is shared, not duplicated.

`activate()`/`deactivate()` write to **both** the live state table (so
`is_active()` stays a fast, single-row read) and the ledger (so a later
stale restore can be caught and corrected) — the same two-layer pattern
already proven for lease revocation.

## Monotonicity (spec §3, §6)

No numeric epoch/generation counter is used. Reasoning, stated
explicitly rather than assumed: each `activate()`/`deactivate()` call
appends exactly one line to the ledger before returning, so file append
order already gives a total order without a separate counter to get
wrong — "the last line in the file" **is** the epoch. Effective state
after any restore is always re-derived as "whichever event the ledger
recorded last," never a value a restored `kill_switch_state` row can
override on its own. Reset (`deactivate()`) is only reachable by
direct, deliberate Python-level operator action today (see "No
production reset endpoint" below) — it is never triggered by database
restore, process restart, host migration, or a lagged replica, since
none of those paths call `activate()`/`deactivate()` at all; they only
ever read state.

## Mandatory restore reconciliation (spec §7, §13)

Exactly matching the lease-revocation precedent: any restore of the
Godmode authority store's `kill_switch_state` table (SQLite file copy
or Postgres restore) **must** be followed by
`orca.godmode.kill_switch_ledger.reconcile_after_restore()` before
resuming elevated traffic. This function raises (rather than returning
a misleadingly-successful summary) if it cannot write the reconciled
state back — fail-closed on reconciliation failure, per spec §7's
explicit requirement.

## Real test evidence

`tests/test_kill_switch_stale_restore.py` — **11 tests, all passing**:

| Test | What it proves |
|---|---|
| Raw vulnerability reproduction | The bug is real (kept alive as a permanent sentinel) |
| Fix verification, SQLite | Reconciliation closes it on the Sovereign backend |
| Fix verification, PostgreSQL | Same invariant against a real local Postgres 17 server — not a unit mock |
| Multiprocess | A separate real OS process, reloading post-reconciliation state, still denies |
| Restart | Activation survives a full module reload |
| Crash consistency (×3 checkpoints) | Real SIGKILL via Phase 13.3's exact injection mechanism; `PRAGMA integrity_check == ok`; state is always one valid linearized result |
| Corruption | A garbage `state` value is treated as active (fail-closed) |
| Store unavailable | An unreachable Postgres host makes `is_active()` return `True` (fail-closed) |
| Lease-revocation regression check | Phase 14A's original fix still works, unaffected by this change |

## A real isolation bug found and fixed while writing these tests

The PostgreSQL fix-verification test initially failed its own sanity
check: `kill_switch_state` is a single persistent row (`id=1`) in the
shared `orneur_phase14_test` database, unlike SQLite's fresh temp file
per test — a prior run of the same test had left the row `ACTIVE`,
contaminating what the test assumed was a clean "pre-activation"
snapshot. Fixed by explicitly resetting to a known `INACTIVE` state at
the start of the test rather than trusting whatever a previous run left
behind. Documented here because it is exactly the kind of test-
isolation mistake this phase's own discipline (routine leak checks,
reproducing before fixing) exists to catch.

## Production reset path — a real, disclosed gap

`orca/godmode/kill_switch.activate()`/`deactivate()` are called from
exactly one place in production code: `orca/godmode/eval_harness.py`
(a simulation/evaluation tool, not a request-handling path). **No HTTP/
API endpoint in this codebase exposes activating or deactivating the
kill switch to any request-scoped caller.** This means spec §15's
"unauthorized user/process cannot reset kill switch" has no real
authorization boundary to test today — there is no exposed reset
surface for an unauthorized caller to reach. This is a favorable
security property (no API attack surface exists), but it also means no
executable "wrong principal denied" test could be written against a
real boundary — fabricating one against a nonexistent endpoint was
avoided rather than done for appearance. **If an admin API endpoint
exposing this is ever added**, it must apply the same
`require_permission`/RBAC pattern already used elsewhere in
`orca/serve/api.py`, and a corresponding authorization test must be
added at that time.

## Scoped kill-switch variants (spec §16)

Not applicable — this codebase has exactly one, global kill switch. No
per-tenant or per-scope variant exists to test cross-scope reset
against.

## Disclosed limit — CLOSED in Phase 14A.2

This section originally disclosed: "if `kill_switch_ledger.jsonl` is
restored from the SAME stale snapshot as `kill_switch_state`'s own
database (e.g. a whole-`ORCA_HOME` restore), the ledger is stale too
and this protection does nothing." **This is exactly the vulnerability
Phase 14A.2 closed** — reproduced directly, classified
`WHOLE_SNAPSHOT_SECURITY_ROLLBACK`, and fixed with an independent
security root (`orca/godmode/security_root.py`) that lives structurally
outside `ORCA_HOME` entirely, not merely in a separate file within it.
`is_active()` now consults that security root as ground truth, not the
`kill_switch_state` mirror this document originally described as the
sole source of truth. Full detail: `SECURITY_ROOT.md`.

The ledger and mirror described above still exist and still have real
value as defense-in-depth (see `SECURITY_ROOT.md`'s "Real test
evidence" section) — they are simply no longer the *only* layer
protecting this invariant.
