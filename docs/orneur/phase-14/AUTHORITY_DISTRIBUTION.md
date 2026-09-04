# Phase 14 — Authority Distribution Decision

## The problem (spec §4-6, §34-36)

Phase 13.2/13.3 proved Godmode's SQLite-backed authority store is
genuinely atomic across **multiple processes sharing one host**
(`BEGIN IMMEDIATE` transactions, real multiprocess races, real SIGKILL
crash injection — see `docs/orneur/phase-13/GODMODE_DISTRIBUTED_ATOMICITY.md`
and `CRASH_CONSISTENCY.md`). SQLite's locking is implemented via the
OS's own file-locking primitives on a single local file — it has no
meaning across two different hosts' filesystems. If ORNEUR DISTRIBUTED
ever runs the API/Agent Runtime on more than one host, each host
independently opening its own `leases.db` would silently reintroduce
exactly the authority-multiplication bug Phase 13 fixed, just one layer
up: two hosts, each honestly enforcing "one process may consume this
lease," could each let their own local process consume it once —
two consumptions of a `max_uses=1` lease, a real security regression.

## Options considered (per spec §4, §35)

- **A. Single authority-owner service** — a dedicated microservice all
  hosts call over the network, owning the only mutable copy of lease
  state. Correct, but introduces a new service, a new deployment unit,
  a new failure mode (network calls where there were none), and new
  operational surface (its own health checks, its own scaling) for a
  need that a database already solves.
- **B. Transactional shared database** — every host's `lease_store`
  functions point at the same transactional database instead of a local
  file. No new service; the existing `resolve_lease()` /
  `resolve_and_consume_lease()` / `delegate_lease()` call sites and
  their function signatures are completely unaffected.
- **C. Constrain all elevated actions to one authority host** — cheapest
  to build, but creates an operational bottleneck (every elevated action
  across the whole fleet serializes through one host) and a single point
  of failure that isn't actually simpler to operate than B once you
  already have a production database tier (which ORNEUR does — see
  below).

## Decision: Option B — PostgreSQL, reusing the existing `orca.auth.db` pattern

**Chosen because it is the simplest option that is actually correct**,
per the spec's own preference (§4: "prefer the simplest production-
correct architecture... do not implement distributed consensus
unnecessarily"). Two facts make this the obvious choice rather than a
new design:

1. `orca/auth/db.py` **already implements exactly this pattern** for
   ORNEUR's user/session/audit state: SQLite by default, PostgreSQL when
   `ORNEUR_DATABASE_URL`/`ORCA_DATABASE_URL` is set, via a `_PGConnAdapter`
   that makes a psycopg connection behave like a `sqlite3.Connection` so
   callers don't change. Its own docstring states the exact rationale
   Phase 14 needs: "Needed once you're running multiple API instances
   behind a load balancer — SQLite's file lock doesn't work across
   processes/machines."
2. Godmode's authority store gets its own dedicated connection string
   (`ORNEUR_GODMODE_DATABASE_URL`), deliberately **not** reusing
   `ORNEUR_DATABASE_URL` — the authority store and the user/auth store
   are different security domains with different blast radii (spec
   §35's "do not make every application worker a database superuser"
   principle extends naturally to "the authority DB and the auth DB
   need not be the same database, connection, or credential").

## Implementation

`orca/godmode/lease_store.py` now dispatches on `_backend()`
(`"postgres"` if `ORNEUR_GODMODE_DATABASE_URL` is set, else `"sqlite"`,
recomputed per call — never cached at import time, matching the
existing `_db_path()` convention that lets tests redirect storage by
mutating env vars and reloading the module). The **SQLite implementation
is byte-for-byte unchanged** (renamed to `_save_sqlite`/`_get_sqlite`/etc.
internally, called by the public functions when no Postgres URL is set)
— this preserves every one of Phase 13.2/13.3's proofs for the ORNEUR
SOVEREIGN profile without re-testing them from scratch.

The new PostgreSQL implementation uses `SELECT ... FOR UPDATE` inside an
explicit transaction as its atomicity primitive, taken on the specific
lease row before any read used to decide a mutation. This is actually
**finer-grained** than SQLite's `BEGIN IMMEDIATE` (which locks the whole
database file): a `FOR UPDATE` on lease A never blocks a concurrent
transaction on lease B. For the property this codebase actually needs —
"two callers racing the SAME lease can never both consume/reserve/revoke
it" — both backends give an identical, engine-enforced guarantee. A
bounded `statement_timeout` (same `_LOCK_TIMEOUT_S = 5.0` value as
SQLite's `timeout` parameter) ensures a caller that cannot acquire the
row lock in time fails closed with the same return semantics as the
existing `sqlite3.OperationalError` handling, rather than hanging.

All six public functions (`save`, `get`, `revoke`, `consume_use`,
`reserve_uses`, `list_active_for_tenant`) keep their exact existing
signatures — **zero changes** were needed to `resolution.py`,
`issuance.py`, `delegation.py`, `connector_elevation.py`, or any
existing caller. This is the same design discipline Phase 13.2 already
established when it swapped the JSON-file backend for SQLite.

## Real test evidence (not cloud, not fabricated — a local Postgres server)

This machine already runs a real local PostgreSQL 17 server (Homebrew
service `postgresql@17`, independent of and predating this session). A
dedicated local database (`orneur_phase14_test`) was created for this
work. `tests/test_godmode_authority_postgres.py` (4 tests) exercises the
exact same real-multiprocess-race properties Phase 13.2 proved for
SQLite, now against this real Postgres backend:

| Test | Result |
|---|---|
| Two processes race a `max_uses=1` lease | **exactly 1 success**, `uses_remaining == 0` |
| Eight processes race a `max_uses=3` lease | **exactly 3 successes**, `uses_remaining == 0` |
| Concurrent consume vs. revoke | valid linearized `ACTIVE`-or-`REVOKED` outcome; once `REVOKED`, further consumption denies |
| Two processes each delegate 3 uses from a shared 5-use parent | **exactly 1 succeeds**, parent ends at `uses_remaining == 2` (never 5, never negative) |

All 4 passed on real execution against the real local server (`4
passed... in 1.89s`). This test file skips cleanly (not a fabricated
pass) if no local Postgres is reachable, so it degrades gracefully in
an environment without this happen-to-be-running local service — it
does **not** stand in for a real cloud-hosted Postgres instance (Cloud
SQL, RDS, Azure Database for PostgreSQL), which Phase 14B/C/D's cloud
qualification work will need to test separately once real cloud
infrastructure exists (see the OWNER ACTION REQUIRED checkpoints in
`PHASE_14_CLOSURE.md`).

Full regression after this change: the entire pre-existing godmode/
connector/simulation/red-team test inventory (274 tests across 23
files) plus the full deterministic application suite were re-run and
confirmed green — see `PHASE_14_CLOSURE.md` for the exact counts.

## What this decision does NOT do

- It does not implement distributed consensus (Raft, etc.) — a single
  Postgres instance (or a Postgres primary with standard replication)
  is the authority of record, matching spec §36's explicit instruction:
  "Phase 14 does NOT need active-active authority databases... ONE
  authoritative production/staging authority location."
- It does not remove the SQLite path — ORNEUR SOVEREIGN (self-hosted,
  single host) keeps SQLite as a fully supported, zero-setup backend.
- It does not stand up any cloud database. `ORNEUR_GODMODE_DATABASE_URL`
  is a connection string the deployment profile sets; provisioning an
  actual managed Postgres instance in GCP/Azure/AWS is Phase 14B/C/D
  work gated on real owner-approved cloud access.
