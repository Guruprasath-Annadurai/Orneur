# Phase 13.2 — Godmode Distributed Atomicity

## Authority store audit

| State | File | Read-modify-write operation | Pre-fix classification | Post-fix classification |
|---|---|---|---|---|
| `CapabilityLease.uses_remaining` | `orca/godmode/lease_store.py` | `consume_use()`: read, validate, decrement, persist | **NON_ATOMIC** (in-process `threading.Lock` only) | **ATOMIC_CROSS_PROCESS** (SQLite `BEGIN IMMEDIATE`) |
| `CapabilityLease.revocation_state` | same | `revoke()`: read, set REVOKED, persist | NON_ATOMIC | ATOMIC_CROSS_PROCESS |
| `CapabilityLease` full record (issuance) | same | `save()`: upsert | NON_ATOMIC (plain file overwrite) | ATOMIC_CROSS_PROCESS (SQLite upsert in its own transaction) |
| Kill switch flag | `orca/godmode/kill_switch.py` | `activate()`/`deactivate()`: existence-based flag, no counter | ATOMIC_CROSS_PROCESS (file existence is inherently atomic at the OS level; no read-modify-write counter exists here to race) | unchanged — already correct, not touched |
| `GodmodeSession` | `orca/godmode/session.py` | none — purely in-memory, caller-held, never persisted to disk | READ_ONLY / not applicable (no file-backed state) | unchanged |
| Elevation audit events | `orca/godmode/audit.py` | `record_elevation_event()`: in-memory append (`_AUDIT_LOG` list) | not applicable — in-memory only, not shared across processes today | unchanged |
| Approval linkage (`GodmodeApproval`) | N/A | `GodmodeApproval` objects are never persisted independently — they exist only as the input to `issue_lease()`, which folds their fields into the resulting `CapabilityLease` record | READ_ONLY (ephemeral, caller-constructed) | unchanged |

**The only real cross-process race existed in `CapabilityLease.uses_remaining`
and `.revocation_state`** — the two mutable fields with a genuine
read-modify-write pattern. Everything else was either already safe
(kill switch, a pure existence flag) or not file-backed at all (session,
audit log, approval).

## The fix

`orca/godmode/lease_store.py` was rewritten from one-JSON-file-per-lease
(`threading.Lock`-guarded) to a single SQLite database
(`ORCA_HOME/godmode/leases.db`, stdlib `sqlite3`, no new dependency).

`consume_use()` and `revoke()` each run their entire read-validate-
mutate-persist sequence inside ONE `BEGIN IMMEDIATE` transaction.
`BEGIN IMMEDIATE` acquires a RESERVED lock on the database file
immediately — enforced by SQLite's own file-locking (`fcntl`-based
advisory locking on POSIX under the hood), which is visible across
process boundaries, unlike an in-process `threading.Lock` object (which
only exists in one process's memory and means nothing to a second OS
process). A concurrent `BEGIN IMMEDIATE` from ANY other thread or
process blocks (up to a bounded `_LOCK_TIMEOUT_S = 5.0` seconds) until
the first transaction commits or rolls back, then re-reads the row
fresh — this is what makes "only one of N processes racing a one-use
lease can ever decrement it" a real, OS-enforced guarantee.

The former `_lock_for()`/`_lease_locks` `threading.Lock` machinery was
removed entirely rather than kept alongside — SQLite's own transaction
locking already subsumes same-process thread safety too, so keeping both
would have been redundant, dead-weight complexity.

### Why SQLite (spec §5-6) rather than raw file locking (§7)

- **Simplicity**: `BEGIN IMMEDIATE` + a conditional `UPDATE` is a well-
  understood, battle-tested primitive; hand-rolled `fcntl.flock`
  file-locking around a JSON read-modify-write would need to get the
  entire lock-acquire → read → validate → write → fsync → lock-release
  sequence exactly right, including all the platform-specific edge cases
  (`fcntl` semantics differ subtly across POSIX systems; Windows has no
  direct equivalent at all).
- **No new dependency**: `sqlite3` is in the Python standard library.
- **Existing precedent**: this project already reaches for SQLite as its
  default backend elsewhere (`orca.auth.db`) when a real transactional
  store is needed, rather than inventing a bespoke locking scheme per
  module.
- **Correctness over cleverness**: spec §5 explicitly lists this as
  option A and the preferred simplest-consistent-with-reliability choice.

### Failure mode (spec §25-26)

If the SQLite lock cannot be acquired within `_LOCK_TIMEOUT_S`,
`sqlite3.OperationalError` is raised internally and caught at every
public function boundary, converted to a fail-closed return value
(`False`/`None`) — never allowed to propagate as an ambiguous crash, and
never treated as "the store is busy, so allow the action anyway."

### Validation vs. mutation split (spec §9)

`resolve_lease()` (immutable checks: signature, tenant, principal,
capability, resource, operation, arguments hash, binding mode) remains a
pure, read-only, non-transactional function — it was already correct and
untouched. Only `resolve_and_consume_lease()`'s FINAL step — the actual
`consume_use()` call — needed the atomic fix, exactly matching this
project's existing architecture where the mutable checks (revocation,
expiry, usage count) are re-validated INSIDE the same atomic transaction
as the decrement itself, never trusted from an earlier, now-possibly-stale
read.

## Phase 14 compatibility (spec §39-40)

This fix guarantees correctness for **multiple local processes sharing
the same file-backed authority store on one host** — the actual Phase
13.2 scope. It does **not** implement, and Phase 13.2 deliberately does
NOT build, any of: a Kubernetes multi-node authority service, a Redis
cluster, distributed consensus, or global replication across hosts —
those remain explicitly Phase 14's responsibility if a truly distributed
(multi-host) deployment is ever required. SQLite's file-level locking is
inherently single-host (it locks a local file); a future multi-host
Phase 14 architecture would need a real distributed transactional store
(e.g. a proper database server) behind the same `lease_store` API
surface — the function signatures (`save`, `get`, `revoke`, `consume_use`,
`list_active_for_tenant`) were deliberately kept unchanged through this
fix specifically so that swap could happen later without touching
`resolution.py`, `issuance.py`, `session.py`, or any caller.
