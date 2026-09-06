# Phase 14A.2 — Independent Security Root

## The vulnerability this closes

Phase 14A.1's own closure disclosed, as a known limitation, exactly the
gap the governing spec required closing before any cloud provisioning:
restoring the kill-switch ledger **together with** the stale authority
database restores both to the same old state, defeating stale-restore
protection entirely. Reproduced directly, before writing any of
`orca/godmode/security_root.py`:

1. Kill switch INACTIVE.
2. Snapshotted the complete `godmode` directory — the authority
   database (`leases.db`, containing the `kill_switch_state` mirror)
   **and** Phase 14A.1's append-only ledger, together.
3. Activated the kill switch — confirmed DENY.
4. Restored the entire snapshot, including the ledger.
5. Restarted (reloaded every module).
6. Ran `reconcile_after_restore()` anyway, as an operator normally
   would — result: `{'ledger_entries': 0, 'action':
   'no_op_never_activated'}`. The ledger's own activation record had
   been rolled back too, so reconciliation had nothing to work with.
7. `is_active()` returned `False`. Elevated authorization returned
   `ALLOW`.

Classified `WHOLE_SNAPSHOT_SECURITY_ROLLBACK` — a real security
vulnerability, not downgraded to an operational footnote, per the
governing spec's explicit instruction.

## Core principle

"Back up the ledger more often" is not a fix — it is the exact same
promise the ledger already made and broke. Security monotonicity needs
an authority domain **structurally separate** from anything an ordinary
"restore my backup" operation could ever reach — not a separate file
inside the same backup unit, a separate *directory tree* (or, for
Postgres, a separate *database*) that a scoped restore procedure has no
path to.

## Architecture (Option A: separately located security-root store)

`orca/godmode/security_root.py` is a new, small, dual-backend store:

- **SOVEREIGN**: a SQLite file at `~/.orneur-security-root/security_root.db`
  by default — a directory that is a **sibling** of `~/.orca`, not
  nested inside it, and whose default location does **not** derive
  from `ORCA_HOME` at all. Even if an operator points `ORCA_HOME`
  somewhere entirely different, the security root's default path is
  unaffected. Overridable via `ORNEUR_SECURITY_ROOT_HOME` (used by
  tests for isolation; production deployments should not normally need
  to set this, since the whole point is a fixed, well-known, separately
  backed-up location).
- **DISTRIBUTED**: `ORNEUR_SECURITY_ROOT_DATABASE_URL` points at a
  **separate Postgres database** from `ORNEUR_GODMODE_DATABASE_URL` —
  tested locally against two genuinely distinct databases on the same
  local Postgres 17 server (`orneur_phase14_test` for the operational
  authority DB, `orneur_phase14_security_root_test` for the security
  root). For real production use, these should be separate database
  *instances or clusters* entirely, not merely separate database names
  on the same server — this local test proves the code path's
  separation logic, not a claim that two databases on one physical
  server survive every disaster scenario a truly separate cluster
  would.

## Honest guarantee (spec §5's explicit instruction)

This is **not** a hardware monotonic counter, **not** tamper-proof
against an operator or process with direct filesystem/database access,
and **not** protected by any OS keychain or secure-enclave mechanism —
this environment has no such primitive, and claiming one would be
dishonest. The real, honest guarantee: an operator's *ordinary*
ORCA_HOME-scoped backup/restore tooling (including this project's own
`orca/ops/backup.py`) has no reason to ever reach a directory outside
`ORCA_HOME`, so a normal restore procedure cannot make the mistake that
defeated Phase 14A.1's fix. Direct, deliberate tampering with the
security-root file/database itself is a different threat model this
module does not defend against — see the epoch-rollback test's own
disclosed limitation below.

## Epoch semantics

`epoch` is a plain monotonically-increasing integer, advanced by
exactly 1 on every `advance()` call, inside the same atomic transaction
that writes the new state. No code path ever accepts a caller-supplied
epoch value — this is what makes "reset produces a NEW epoch, never
reverts history" true by construction, not convention.

**Disclosed limitation**: `advance()` guarantees monotonicity *relative
to whatever the row currently says* — it does not detect or reject a
row that was directly tampered with via raw SQL (bypassing this module
entirely). A test (`test_epoch_cannot_decrease_via_restored_row`) makes
this explicit: after tampering the epoch down to `2`, the next
`advance()` call computes `3`, not the pre-tamper value. Protection
against direct tampering is the security root's physical/access
separation (a different threat surface entirely), not an in-band check
this module could add without also being bypassable the same way.

## Crash-safety ordering

`kill_switch.activate()`/`deactivate()` write to the security root
**first** (the authoritative write, using the same `BEGIN IMMEDIATE`
transaction discipline and Phase 13.3 crash-injection checkpoints as
leases), then to the Phase 14A.1 leases.db mirror and ledger **second**.
A crash between the two leaves the security root already correct — the
mirror catching up late is a display/audit convenience gap, never a
security gap. Tested directly
(`test_crash_between_security_root_and_mirror_update_leaves_security_root_authoritative`).

## Cache policy

None. `is_active()` always reads the security root fresh on every
call — no caching, anywhere. This is a cheap, low-frequency operation
(Godmode elevation is not a hot request path, by this codebase's own
established design), so there is no performance reason to trade away
the "no stale-permissive cache" property for a speed gain the code
doesn't need.

## Real test evidence

`tests/test_security_root_whole_snapshot.py` — 9 tests, all passing:
raw whole-snapshot reproduction (permanent sentinel), the actual fix
(whole-`ORCA_HOME` restore proven safe), SQLite Sovereign, PostgreSQL
Distributed (two genuinely separate local databases), epoch-rollback
tampering behavior, concurrent activation from 5 real processes (exact
epoch accounting, no lost updates), crash-ordering safety, stale-worker
cache-freshness, and a delegation/multiprocess regression check.

`tests/test_kill_switch_stale_restore.py` was substantially rewritten
for the new architecture — 11 tests, all passing, now correctly
asserting that Phase 14A.1's original scenario (restoring the leases.db
mirror alone) is doubly closed: it no longer even needs
`reconcile_after_restore()` to stay denied, since `is_active()` never
consulted that mirror in the first place.

## Phase 14A.3 addendum — DISTRIBUTED mode can no longer silently fall back to a local file

This document originally disclosed, as a known limitation: "in
DISTRIBUTED mode, if `ORNEUR_SECURITY_ROOT_DATABASE_URL` is left unset,
the security root silently falls back to the SOVEREIGN file-based
mechanism per host." **This has since been closed.**

`orca/godmode/deployment_profile.py` introduces an explicit,
validated `ORNEUR_DEPLOYMENT_PROFILE` (SOVEREIGN default /
DISTRIBUTED). `security_root._backend()` now checks
`is_distributed()` first: if true, it calls
`require_distributed_security_root_url()`, which **raises**
`DeploymentConfigError` (never a connection string in the message) if
the URL is missing, empty, or not a recognized `postgresql://` DSN.
There is no code path left in `_backend()` that reaches the SQLite
branch while in DISTRIBUTED mode — the fallback is not merely
discouraged, it no longer exists.

`get_epoch_and_state()` and `advance()` catch that raise and convert it
to the same fail-closed `(None, "UNKNOWN")` / `None` result a real
connectivity failure already produced — a caller of `is_active()` sees
"deny," never a crash and never a silent file. The loud, process-
halting version of this check lives in
`orca.godmode.deployment_profile.validate_deployment_config()`, called
once at `orca/serve/api.py`'s module import time — a real DISTRIBUTED
server with missing or invalid configuration never finishes starting.

**Real test evidence**: `tests/test_distributed_security_root_config_gate.py`
— 13 tests, all passing, including a genuine two-process simulation
(worker A activates against a real shared local Postgres security
root, worker B — a separate real OS process — observes the DENY) and a
misconfigured-worker test (worker B, missing the URL, refuses to start
at all rather than joining the serving pool with a local fallback).

**Known, disclosed, narrower gap**: `ORNEUR_DATABASE_URL` (the
user/session/audit backend, `orca/auth/db.py`) was not given the same
fail-startup enforcement this phase — it remains dual-backend but
un-validated at startup. This is a real, smaller-blast-radius gap
(auth-store staleness, not authority/security-root duplication) not
closed this phase.
