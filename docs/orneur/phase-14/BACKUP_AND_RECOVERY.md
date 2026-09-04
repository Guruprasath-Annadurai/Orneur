# Phase 14 §57-68 — Backup and Recovery

## Real finding this phase made (critical, per the governing spec's own framing)

**Restoring a Godmode `leases.db` backup taken before a revocation
occurred silently un-revokes that lease.** Reproduced directly against
a real local SQLite file, not hypothesized:

1. Issue a 5-use lease.
2. Take a real online backup (`sqlite3.Connection.backup()`).
3. Revoke the lease — confirmed `REVOKED`.
4. Restore the pre-revocation backup over the live file.
5. A **fresh process** reads the restored row: `revocation_state ==
   ACTIVE`. `consume_use()` returns `True` — the privilege is
   resurrected.

This exactly matches the governing spec's own §67 warning: "Restoring
an old authority snapshot must not silently resurrect expired/revoked
privilege. This is critical." It was not merely disclosed — it was
fixed, and the fix is tested (`tests/test_authority_backup_restore.py`,
3 tests, all passing, including one that still deliberately reproduces
the raw bug with reconciliation skipped, so a future regression cannot
silently disappear).

## The fix: an append-only revocation ledger

`orca/godmode/revocation_ledger.py` — every successful `revoke()` now
also appends `{lease_id, revoked_at}` to a JSONL file kept deliberately
**separate** from the `leases` table/database, so copying an old
`leases.db` over the live one does not touch it. A new
`reconcile_after_restore()` function re-applies `revoke()` for every
lease_id the ledger has ever recorded, regardless of what the restored
row currently says — "the ledger says revoked" always wins over "the
restored row says active."

### Mandatory restore procedure (operational requirement)

Any restore of the Godmode authority store — SQLite file copy or
Postgres `pg_restore` — **must** be followed by calling
`orca.godmode.revocation_ledger.reconcile_after_restore()` before
resuming elevated traffic. This is not automatic (a restore is itself
an out-of-band operational action, matching this codebase's existing
`orca/ops/backup.py` convention of "these are ops tools, not something
the running server invokes on its own").

### A second real bug this same mechanism caused, found and fixed before delivery

The first implementation of `revocation_ledger.py` computed its file
path as a **module-level constant** (`LEDGER_PATH = ORCA_HOME / ...`),
evaluated once at first import. This is the exact staleness bug class
this codebase has hit before (`kill_switch.py`'s `_KILL_SWITCH_FILE`,
and the reason `lease_store.py`'s own `_db_path()` is a function, not a
constant, per its own docstring). The consequence: whichever test in a
pytest session first imported this module — regardless of which tmp
`ORCA_HOME` that specific test was using for its own lease store — bound
`LEDGER_PATH` to the REAL `~/.orca/godmode/revocation_ledger.jsonl`, and
every later test's `revoke()` call kept writing there.

**Caught by this phase's own routine leakage check** (`ls
~/.orca/godmode` — an established habit from Phase 13, run before
declaring this phase's work final): it found a real
`revocation_ledger.jsonl` file with 2 leaked entries. Root-caused,
fixed (converted to a function, `_ledger_path()`, recomputed on every
call — identical pattern to `_db_path()`), the leaked file removed, the
full authority-test regression (39 tests) and the full security suite
(826 tests) re-run and confirmed clean, and the leakage check re-run
and confirmed empty. This is reported here rather than silently
corrected, because it demonstrates exactly the kind of mistake this
phase's own new code can introduce even while explicitly designed to
fix a different bug — and because the discipline that caught it (a
routine, unglamorous "did anything leak into the real home directory"
check) is worth keeping visible.

### Disclosed limit of this fix

If the ledger file itself is restored from the SAME stale snapshot as
the leases table (e.g. an operator does a whole-`ORCA_HOME` restore
rather than restoring the leases table specifically), the ledger is
stale too and this mitigation does nothing — no application code can
recover data that was never captured. **This is an operational
requirement, not something code alone can enforce**: the revocation
ledger must be backed up on a cadence at least as frequent as, and
ideally independent of (e.g. shipped continuously to a separate,
append-only sink), the leases table itself. Stated explicitly here so
it is not silently assumed solved.

### Same class of risk, not yet fixed: the kill switch

`orca/godmode/kill_switch.py` is a single file flag under the same
`ORCA_HOME`. A whole-`ORCA_HOME` restore from before a kill-switch
activation would silently revert it, with no ledger-based mitigation
built this phase. Recommended follow-up: an append-only kill-switch
activation ledger using the identical pattern as
`revocation_ledger.py`. **Not built this phase** — disclosed as a real,
specific gap rather than silently left unaddressed.

## Backup/restore for the other durable stores

- `orca/auth/db.py`'s SQLite/Postgres backend already had real
  backup/restore tooling before this phase (`orca/ops/backup.py`,
  `backup_sqlite()`/`backup_postgres()`/`restore_sqlite()`) — unchanged
  this phase, not re-tested (it was not touched).
- Model/checkpoint/dataset/training registries, memory stores, the
  Gateway worker registry: all plain JSON files under `ORCA_HOME`, with
  no dedicated backup tooling (a filesystem-level backup of `ORCA_HOME`
  covers them, but no restore-and-verify test was built for these this
  phase — see `STATE_OWNERSHIP.md`'s "backup requirement" column for
  the full list).

## Disaster recovery: RPO/RTO (spec §60, §66)

**Not measured this phase against real infrastructure** — no cloud
environment exists to run a real timed restore against (see
`PHASE_14_CLOSURE.md`'s OWNER ACTION REQUIRED checkpoints). A local,
timed restore of the Godmode SQLite store was performed as part of the
finding above (backup → mutate → restore → reconcile), completing in
well under one second on this machine — this is evidence that the
*mechanism* is fast, not a measured production RPO/RTO, which depends
on real network/storage characteristics this environment does not
have. Per spec §66's own instruction ("do not invent enterprise-grade
numbers without evidence"), no RPO/RTO figure is stated here.
