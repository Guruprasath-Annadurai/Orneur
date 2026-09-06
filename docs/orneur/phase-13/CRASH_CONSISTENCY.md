# Phase 13.3 — Crash Consistency (Real SIGKILL Injection)

## What this closes

Phase 13.2's own disclosed residual risk #5: "crash consistency" had been
reasoned about only via SQLite's rollback-journal semantics and a
module-reload-based restart check — no real OS process had actually been
killed mid-transaction. This document reports the result of doing that
for real.

## Mechanism (spec §2-4)

A test-only checkpoint hook, `orca.godmode.lease_store._test_checkpoint(name)`,
is inserted at five points inside every transactional function
(`consume_use()`, `revoke()`, `reserve_uses()`):

- `AFTER_BEGIN_IMMEDIATE` — immediately after the transaction acquires
  its RESERVED lock.
- `AFTER_RECORD_READ` — immediately after the lease row is fetched.
- `AFTER_MUTABLE_VALIDATION` — after revocation/expiry/integrity checks
  pass, before the in-memory mutation.
- `AFTER_UPDATE_BEFORE_COMMIT` — after the `UPDATE` statement executes,
  before `COMMIT`.
- `AFTER_COMMIT` — after `COMMIT`, before the function returns.

The hook is a no-op unless the environment variable
`GODMODE_TEST_CRASH_CHECKPOINT` exactly matches the checkpoint name — an
env var no production deployment sets. When active, it writes to a
signal file (path from `GODMODE_TEST_CRASH_SIGNAL_FILE`) and sleeps 30
seconds — far longer than any test needs to observe the signal and act.

The test harness (`tests/test_godmode_crash_consistency.py`) spawns a
real child process (via `multiprocessing.get_context("spawn")`, so the
child re-execs a fresh interpreter and correctly picks up the parent's
env-var mutations), polls for the signal file's existence, then calls
`Process.kill()` — a real `SIGKILL`, which cannot be caught, blocked, or
ignored by the target — and confirms the process is actually dead before
proceeding. No test simulates a crash by raising a Python exception.

## SQLite journal mode (disclosed, spec §8)

`orca.godmode.lease_store` opens its connections with no explicit
`PRAGMA journal_mode` statement anywhere in the module (`grep -n
journal_mode orca/godmode/lease_store.py` returns nothing). SQLite's
default is the rollback journal (`delete` mode) — **not WAL**. This was
directly confirmed against a fresh, tempdir-isolated database:
`PRAGMA journal_mode` returns `delete`. All durability claims below are
scoped to this journal mode.

A SIGKILL'd process releases its file descriptors and OS-level locks
immediately (kernel-enforced, not application-dependent). On the next
connection to the database, SQLite detects a hot/incomplete rollback
journal from the interrupted transaction and automatically replays it,
restoring the database to its pre-transaction state — this is what makes
every "crash before commit never leaves partial state" result below a
property of SQLite itself, not of any code this project wrote.

## Results by scenario

### Pre-commit crash (spec §9) — never creates extra or negative authority

Parametrized across `AFTER_BEGIN_IMMEDIATE`, `AFTER_RECORD_READ`,
`AFTER_MUTABLE_VALIDATION`, `AFTER_UPDATE_BEFORE_COMMIT` — a `max_uses=1`
lease, `consume_use()` SIGKILL'd at each checkpoint:

- `PRAGMA integrity_check` (from a **freshly opened connection in a
  separate process**, not the one that crashed) returns `ok` after every
  checkpoint.
- Recovered `uses_remaining` is always `1` (the killed transaction never
  committed at any of these four checkpoints, so the rollback journal
  restores the pre-transaction value).
- A follow-up `consume_use()` call succeeds exactly once, after which
  `uses_remaining == 0`. Total successful consumptions across the crash
  + recovery sequence is exactly 1 — never 0, never 2 — matching
  `max_uses=1` exactly.

### Post-commit crash (spec §10) — no resurrection, no blind retry

`AFTER_COMMIT`: the transaction has already committed before the kill,
so `uses_remaining == 0` is durably recorded and confirmed after
recovery — no resurrection of the consumed use. A further `consume_use()`
call correctly returns `False` (denied) rather than silently succeeding
again — this reuses the store's existing fail-closed "no uses remaining"
semantics rather than inventing a new "outcome unknown" abstraction,
since from the caller's perspective a post-commit crash and a normal
"lease already exhausted" state are indistinguishable and require no new
handling: the privileged action already executed exactly once (the
commit is the linearization point), and the store correctly refuses to
authorize a second one.

### Revocation crash (spec §11) — valid linearized state only

Parametrized across `AFTER_BEGIN_IMMEDIATE`, `AFTER_UPDATE_BEFORE_COMMIT`,
`AFTER_COMMIT` — `revoke()` SIGKILL'd at each checkpoint. Recovered
`revocation_state` is always exactly `ACTIVE` (pre-commit checkpoints) or
`REVOKED` (post-commit checkpoint) — never any other value, never a
torn/partial state. When recovered as `REVOKED`, a further `consume_use()`
correctly denies.

### Delegation-reservation crash (spec §12) — never duplicates authority

Parametrized across the same three checkpoints — a 5-use parent
delegating 3 uses to a child, with `reserve_uses()` SIGKILL'd on the
parent's reservation. Recovered parent `uses_remaining` is always
exactly one of two valid values: `5` (reservation never committed) or
`2` (reservation committed: `5 - 3`) — never any other value, and in
particular never `5` **and** a child lease also existing with its own
independent `5` (the Phase 13.2 authority-multiplication bug this
mechanism specifically guards against).

## Durability scope (spec §13, conservative claim)

This work proves **process-crash consistency**, not physical-disk or
power-loss durability. `SIGKILL` terminates the Python process but does
not interrupt the OS's page cache or the physical disk — a real power
loss mid-`fsync` is a different failure mode this test suite does not
and cannot exercise (SQLite's rollback-journal durability guarantee
under real power loss depends on the underlying filesystem's own fsync
semantics, which were not tested here). The claim made is narrower and
fully supported by the evidence above: *if this process is killed at any
point during a Godmode authority transaction, no other process will ever
observe extra, negative, or duplicated authority, and the database
remains structurally valid.*

## Test results

`tests/test_godmode_crash_consistency.py` — **11 passed, 0 failed**
(all real multiprocess SIGKILL tests; each confirmed via `PRAGMA
integrity_check == ok` from a fresh process after the kill).

## Audit counters (spec's new Phase 13.3 counters)

- `AUTHORITY_CRASH_EXTRA_USE`: **0** — no scenario ever produced more
  than `max_uses` total successful consumptions.
- `AUTHORITY_CRASH_CORRUPTION`: **0** — every `PRAGMA integrity_check`
  returned `ok`.
- `AUTHORITY_COMMIT_RESPONSE_LOSS_RETRY`: **0** — the post-commit crash
  test's follow-up `consume_use()` correctly denied rather than being
  blindly retried into a second success.
