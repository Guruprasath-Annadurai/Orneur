"""
Phase 14B §15-16 -- durable, dual-backend, tamper-evident Godmode
elevation audit.

Real finding, MORE serious than what Phase 14A.4 disclosed: Phase
14A.4's own audit said "Godmode's OWN elevation audit
(orca.godmode.audit) is a plain in-memory list" -- true, but a deeper
grep for this phase found something worse: `record_elevation_event()`
was not called by ANY real authorization path at all.
`orca.godmode.resolution.resolve_and_consume_lease()` (the single
choke point every real caller -- AgentRuntime-compatible file
elevation, connector elevation, simulation revalidation -- goes
through) never called it. The ONLY real caller in the entire codebase
was `orca/godmode/latency_bench.py`, a benchmark script. There was, in
effect, NO elevation audit trail at all for real elevated actions
before this phase -- not "in-memory only," but "not wired in."

This module provides the durable backend; `resolve_and_consume_lease()`
(orca/godmode/resolution.py) was updated to actually call it for every
decision. Design:

- Dual-backend, reusing `orca.godmode.lease_store`'s existing
  connection primitives (`_backend()`, `_connect()`, `_pg_connect()`)
  rather than duplicating them -- this audit trail lives in the SAME
  authority database as leases (SQLite for SOVEREIGN, the shared
  `ORNEUR_GODMODE_DATABASE_URL` Postgres database for DISTRIBUTED),
  since it is authority-domain data, not core application data.
- Hash-chained (SHA-256 of the previous entry's hash, single-writer
  chain, same design as `orca.audit`'s existing user/session audit
  log) plus an HMAC signature reusing `orca.audit._audit_key()` --
  the same key management convention this project already established
  (`ORNEUR_AUDIT_KEY`/`ORCA_AUDIT_KEY` env var, falls back to a loud
  dev-only key). Tampering with any historical row breaks the chain
  from that point forward, detectable via `verify_chain()`.
- No secrets: `capability`/`resource_scope` are passed through
  `redact_secrets()` before being persisted, matching
  `orca.godmode.audit`'s existing discipline exactly.
- No raw chain-of-thought: this table has no field capable of holding
  model output/reasoning text -- only the same structured fields
  `ElevationAuditEvent` already defined (principal/tenant/lease/
  capability/scope/outcome/timestamp/trace).

Audit-commit-semantics patch (still Phase 14B, applied before any real
multi-host elevated-action test per the governing spec): the original
design above had an audit-TRUTH defect, not a privilege escalation --
the durable audit write and `consume_use()` were separate
transactions, so a row could say result="ALLOW" moments before a
concurrent competitor's `consume_use()` call actually won the race.
Fixed in `orca/godmode/resolution.py::resolve_and_consume_lease()`: a
successful elevation now writes TWO rows -- AUTHORIZATION_ATTEMPT
(result="PENDING_CONSUME", written before `consume_use()`, never a
final grant) and, only after `consume_use()` actually succeeds,
AUTHORIZATION_COMMITTED (result="ALLOW", the one and only event
type/result pair that means the privileged side effect may execute).
A race loss is recorded as AUTHORIZATION_LOST_RACE (result=
"LOST_RACE"), never "ALLOW". See `resolve_and_consume_lease()`'s
docstring for the full four-gate sequence and
`count_false_committed_audit()` below for the resulting
`GODMODE_FALSE_COMMITTED_AUDIT` counter.

Phase 14B.1 -- durable audit concurrency hardening (a real distributed
qualification found a real reliability bug, not a security one): a
real cross-host run (10 real races between a genuine Northflank
container and a genuine GitHub Actions runner, both writing to the
same Supabase Postgres) showed the LOSING actor's durable audit write
failing in 10/10 races -- never the correct AUTHORIZATION_LOST_RACE
outcome, always AUDIT_FAILURE_DENY instead. Two real, independent
defects in the Postgres write path were found and fixed here:

1. **DDL on the hot path**: `_record_event_postgres()` used to execute
   `CREATE TABLE IF NOT EXISTS` / `CREATE INDEX IF NOT EXISTS`
   (`_PG_SCHEMA`) on EVERY write, INSIDE the transaction already
   holding the lock -- lengthening how long that lock was held on every
   call and adding real catalog-lock contention risk under genuine
   concurrent, cross-process, cross-network access. Schema
   initialization is now a separate, explicit, idempotent
   `_ensure_pg_schema()`, called once per process (cached), never
   inside the per-event write transaction.
2. **Advisory lock, not durable state**: `pg_advisory_xact_lock` is
   session-scoped, invisible to normal Postgres diagnostics, and not
   tied to any actual row -- if a connection terminates uncleanly, its
   release depends on Postgres's own connection-death detection, which
   is not always prompt. Replaced with an explicit `godmode_audit_head`
   row (`id=1, last_seq, last_hash`), locked via ordinary
   `SELECT ... FOR UPDATE` inside the same short transaction that
   inserts the event and advances the head -- ordinary transactional
   row-lock semantics, visible in `pg_locks`/`pg_stat_activity`,
   automatically released at transaction end (commit OR abort).

A local, real-Postgres, barrier-synchronized reproduction (10-way true-
simultaneous contention, 100 real concurrent writes total) did NOT
reproduce a failure even before this fix -- the serialization logic was
never wrong under pure contention; the real failure required genuine
network latency (a real Supabase pooler round-trip, real cross-host
timing) a local test cannot recreate. This fix is therefore validated
locally for correctness (real concurrency tests below) and by an actual
re-run of the real cross-host qualification -- both are honestly
distinguished in `docs/orneur/phase-14/PHASE14B_DISTRIBUTED_EVIDENCE.md`,
never conflated as if the local pass alone proved the cloud fix.

Bounded retry (`_MAX_RETRY_ATTEMPTS`, short jittered backoff) is added
ONLY for `LOCK_TIMEOUT`/`DEADLOCK`/`SERIALIZATION_FAILURE` -- a safety
guardrail against real transient contention, never the primary
correctness mechanism, and never applied to authentication/permission/
schema/data-integrity failures (those fail closed immediately, no
retry). `SET lock_timeout` bounds time spent WAITING for the head-row
lock specifically (distinct from `statement_timeout`, which bounds
total query execution time and was already set by
`lease_store._pg_connect()`).
"""
from __future__ import annotations

import hashlib
import hmac
import json

from orca.connectors.security import redact_secrets
from orca.godmode.contracts import ElevationAuditEvent, ElevationAuditEventType

_GENESIS_HASH = "0" * 64


def _audit_key() -> bytes:
    from orca.audit import _audit_key as _shared_audit_key
    return _shared_audit_key()


def _canonical_payload(seq: int, event: ElevationAuditEvent) -> str:
    return json.dumps(
        {
            "seq": seq, "event_id": event.event_id, "event_type": event.event_type.value,
            "principal_id": event.principal_id, "tenant_id": event.tenant_id, "lease_id": event.lease_id,
            "capability": event.capability, "resource_scope": event.resource_scope,
            "operation_scope": event.operation_scope, "issuer": event.issuer,
            "timestamp": event.timestamp, "trace_id": event.trace_id, "result": event.result,
        },
        sort_keys=True,
    )


def _compute_hash(payload: str) -> str:
    return hashlib.sha256(payload.encode()).hexdigest()


def _compute_signature(entry_hash: str) -> str:
    return hmac.new(_audit_key(), entry_hash.encode(), hashlib.sha256).hexdigest()


def _redact(event: ElevationAuditEvent) -> ElevationAuditEvent:
    """Same redaction discipline as `orca.godmode.audit.record_elevation_event()`
    -- never persist an unredacted capability/resource_scope."""
    event.capability = redact_secrets(event.capability)
    event.resource_scope = redact_secrets(event.resource_scope)
    return event


_SQLITE_SCHEMA = """
CREATE TABLE IF NOT EXISTS godmode_audit (
    event_id TEXT PRIMARY KEY,
    seq INTEGER,
    event_type TEXT NOT NULL,
    principal_id TEXT NOT NULL,
    tenant_id TEXT NOT NULL,
    lease_id TEXT,
    capability TEXT,
    resource_scope TEXT,
    operation_scope TEXT,
    issuer TEXT,
    timestamp TEXT NOT NULL,
    trace_id TEXT,
    result TEXT,
    prev_hash TEXT NOT NULL,
    entry_hash TEXT NOT NULL,
    signature TEXT NOT NULL
)
"""

_PG_TABLE_SCHEMA = """
CREATE TABLE IF NOT EXISTS godmode_audit (
    event_id TEXT PRIMARY KEY,
    seq BIGINT,
    event_type TEXT NOT NULL,
    principal_id TEXT NOT NULL,
    tenant_id TEXT NOT NULL,
    lease_id TEXT,
    capability TEXT,
    resource_scope TEXT,
    operation_scope TEXT,
    issuer TEXT,
    timestamp TEXT NOT NULL,
    trace_id TEXT,
    result TEXT,
    prev_hash TEXT NOT NULL,
    entry_hash TEXT NOT NULL,
    signature TEXT NOT NULL
);
CREATE INDEX IF NOT EXISTS ix_godmode_audit_tenant ON godmode_audit(tenant_id);
CREATE INDEX IF NOT EXISTS ix_godmode_audit_seq ON godmode_audit(seq);
"""

# Phase 14B.1: the durable chain-head. A single authoritative row
# (id=1) whose `last_seq`/`last_hash` are protected by an ordinary
# `SELECT ... FOR UPDATE` row lock -- not a session-scoped advisory
# lock -- inside the same short transaction that inserts the event and
# advances the head. See module docstring for why this replaced
# `pg_advisory_xact_lock`.
_PG_HEAD_SCHEMA = """
CREATE TABLE IF NOT EXISTS godmode_audit_head (
    id INTEGER PRIMARY KEY,
    last_seq BIGINT NOT NULL,
    last_hash TEXT NOT NULL
);
"""

# Kept for backward compatibility with any external reference to the
# old combined-schema name (verify_chain()/list callers only need the
# table schema, not the head table).
_PG_SCHEMA = _PG_TABLE_SCHEMA

# Phase 14B.1.1: the earlier tuning history below (2000ms -> 5000ms ->
# 8000ms, 4 -> 5 -> 7 attempts) was chasing the WRONG variable. The real
# cloud failure (20/20 races, winner's final audit write failing) was
# root-caused to a genuine bug, not insufficient wait time:
# `lease_store._pg_connect()` sets a SESSION-level `statement_timeout`
# (5000ms) on every connection durable_audit.py obtains through it. This
# module's own `SET LOCAL lock_timeout` was being silently capped by
# that shorter, unrelated, already-in-effect session default -- a
# statement running past 5s was cancelled by `statement_timeout`
# (SQLSTATE 57014, `QueryCanceled`) BEFORE `lock_timeout` (SQLSTATE
# 55P03, `LockNotAvailable`) ever had a chance to fire, and this module
# had no explicit case for `QueryCanceled`, so it fell through to a
# generic, misleading "CONNECTION_FAILURE" classification. Raising the
# lock_timeout constant repeatedly could never fix this: any value
# still tried to exceed the connection's own shorter statement_timeout.
#
# Fixed at the source (`lease_store._pg_connect()` no longer runs DDL on
# every call -- see that function's own docstring) AND here: this
# module now explicitly `SET LOCAL`s BOTH values together, in the
# coherent relationship spec Phase 14B.1.1 requires --
# connect_timeout < lock_timeout < statement_timeout -- scoped to just
# this transaction, so it never affects lease_store's own unrelated use
# of the same connection helper.
_MAX_RETRY_ATTEMPTS = 4
_PG_LOCK_WAIT_TIMEOUT_MS = 5000
_PG_STATEMENT_TIMEOUT_MS = 10000  # must stay > _PG_LOCK_WAIT_TIMEOUT_MS

# Keyed by the actual target (resolved SQLite file path / Postgres DSN),
# NOT a bare process-global bool -- SQLite's target changes per test
# (each uses its own ORCA_HOME/tmp_path), and even Postgres's DSN can
# change across a reloaded module within one process (e.g. different
# tests pointing at different local databases). A bare global flag
# caused a real regression: test A's schema-initialized flag incorrectly
# skipped schema creation for test B's different, empty database,
# producing "no such table"/DENY failures with no relation to
# concurrency at all.
_pg_schema_initialized_dsns: set[str] = set()
_sqlite_schema_initialized_paths: set[str] = set()


def _classify_pg_error(exc: BaseException) -> str:
    """Maps a real psycopg exception to a coarse, secret-safe category.
    Never includes the DSN, username, password, SQL parameter values,
    or the raw exception body -- only the category name. Used for
    tests/structured telemetry (spec Phase 14B.1 §1); production
    authorization only ever sees the plain bool from
    `record_event_durable()`."""
    import psycopg

    if isinstance(exc, psycopg.errors.LockNotAvailable):
        return "LOCK_TIMEOUT"
    if isinstance(exc, psycopg.errors.QueryCanceled):
        # SQLSTATE 57014 -- statement_timeout expired, DISTINCT from
        # LockNotAvailable's 55P03 (lock_timeout expired). Must be
        # checked as its own category, never allowed to fall through to
        # the generic OperationalError branch below -- that exact
        # fallthrough was the real Phase 14B.1 cloud-failure
        # misclassification (see this module's _MAX_RETRY_ATTEMPTS
        # comment for the full story).
        return "STATEMENT_TIMEOUT"
    if isinstance(exc, psycopg.errors.DeadlockDetected):
        return "DEADLOCK"
    if isinstance(exc, psycopg.errors.SerializationFailure):
        return "SERIALIZATION_FAILURE"
    if isinstance(exc, psycopg.errors.UniqueViolation):
        return "UNIQUE_VIOLATION"
    if isinstance(exc, psycopg.errors.InFailedSqlTransaction):
        return "TRANSACTION_ABORTED"
    if isinstance(exc, (psycopg.errors.DuplicateTable, psycopg.errors.DuplicateObject, psycopg.errors.UndefinedTable, psycopg.errors.UndefinedColumn)):
        return "SCHEMA_FAILURE"
    if isinstance(exc, (psycopg.errors.InvalidPassword, psycopg.errors.InsufficientPrivilege)):
        return "PERMISSION_FAILURE"
    if isinstance(exc, psycopg.OperationalError):
        return "CONNECTION_FAILURE"
    if isinstance(exc, psycopg.Error):
        return "UNKNOWN_DATABASE_FAILURE"
    return "UNKNOWN_DATABASE_FAILURE"


def _retry_backoff_seconds(attempt: int) -> float:
    import random
    return min(0.05 * (2 ** attempt), 0.5) + random.uniform(0, 0.05)


def _ensure_sqlite_schema() -> None:
    """One-time PER DATABASE FILE (not per process -- see the cache set's
    docstring above), idempotent. NOT run inside the per-event write
    transaction -- moved off the hot path per spec Phase 14B.1 §2, for
    consistency with the Postgres path even though SQLite's
    `BEGIN IMMEDIATE` (whole-file exclusive lock) does not have the same
    catalog-lock contention risk DDL-in-hot-path created for Postgres."""
    from orca.godmode.lease_store import _connect, _db_path

    path = str(_db_path())
    if path in _sqlite_schema_initialized_paths:
        return
    with _connect() as conn:
        conn.execute(_SQLITE_SCHEMA)
    _sqlite_schema_initialized_paths.add(path)


def _ensure_pg_schema() -> None:
    """One-time PER DSN (not per process -- see the cache set's
    docstring above), idempotent, and run on its OWN short
    connection/transaction -- never inside the per-event write
    transaction that holds the head-row lock (spec Phase 14B.1 §2:
    'Event append should NOT execute CREATE TABLE / CREATE INDEX on
    every authorization audit write')."""
    from orca.config import orneur_env
    from orca.godmode.lease_store import _pg_connect

    dsn = orneur_env("GODMODE_DATABASE_URL")
    if dsn in _pg_schema_initialized_dsns:
        return

    conn = _pg_connect()
    try:
        with conn.cursor() as cur:
            cur.execute(_PG_TABLE_SCHEMA)
            cur.execute(_PG_HEAD_SCHEMA)
            # Bootstrap the head from whatever chain state already
            # exists (a real production database may already have rows
            # from before this table was introduced) -- never assume an
            # empty chain. An empty chain correctly bootstraps to
            # (-1, GENESIS_HASH), matching what the write path expects
            # as "no prior entry."
            cur.execute(
                """
                INSERT INTO godmode_audit_head (id, last_seq, last_hash)
                SELECT 1, COALESCE(MAX(seq), -1),
                       COALESCE((SELECT entry_hash FROM godmode_audit ORDER BY seq DESC LIMIT 1), %s)
                FROM godmode_audit
                ON CONFLICT (id) DO NOTHING
                """,
                (_GENESIS_HASH,),
            )
        conn.commit()
        _pg_schema_initialized_dsns.add(dsn)
    finally:
        conn.close()


def _record_event_sqlite(event: ElevationAuditEvent) -> bool:
    ok, _category = _record_event_sqlite_with_diagnostics(event)
    return ok


def _record_event_sqlite_with_diagnostics(event: ElevationAuditEvent) -> tuple[bool, str]:
    import sqlite3
    from orca.godmode.lease_store import _connect

    _ensure_sqlite_schema()
    try:
        with _connect() as conn:
            conn.execute("BEGIN IMMEDIATE")
            try:
                last = conn.execute("SELECT entry_hash, seq FROM godmode_audit ORDER BY seq DESC LIMIT 1").fetchone()
                prev_hash = last["entry_hash"] if last else _GENESIS_HASH
                seq = (last["seq"] + 1) if last else 0
                payload = _canonical_payload(seq, event)
                entry_hash = _compute_hash(payload)
                signature = _compute_signature(entry_hash)
                conn.execute(
                    """
                    INSERT INTO godmode_audit
                        (event_id, seq, event_type, principal_id, tenant_id, lease_id, capability,
                         resource_scope, operation_scope, issuer, timestamp, trace_id, result,
                         prev_hash, entry_hash, signature)
                    VALUES (?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?)
                    """,
                    (
                        event.event_id, seq, event.event_type.value, event.principal_id, event.tenant_id,
                        event.lease_id, event.capability, event.resource_scope, event.operation_scope,
                        event.issuer, event.timestamp, event.trace_id, event.result,
                        prev_hash, entry_hash, signature,
                    ),
                )
                conn.execute("COMMIT")
                return True, "SUCCESS"
            except Exception:
                conn.execute("ROLLBACK")
                raise
    except sqlite3.OperationalError:
        return False, "LOCK_TIMEOUT"
    except Exception:
        return False, "UNKNOWN_DATABASE_FAILURE"


def _record_event_postgres(event: ElevationAuditEvent) -> bool:
    ok, _category = _record_event_postgres_with_diagnostics(event)
    return ok


def _record_event_postgres_with_diagnostics(event: ElevationAuditEvent) -> tuple[bool, str]:
    """Real hot path: a short transaction that locks the single
    `godmode_audit_head` row (`SELECT ... FOR UPDATE`, an ordinary
    transactional row lock -- not a session-scoped advisory lock),
    inserts the event, advances the head, and commits -- all in one
    transaction, so a failure at any point rolls back BOTH the insert
    and the head advance (no orphan chain entry, no partially-advanced
    head). Schema initialization happens once, outside this path (see
    `_ensure_pg_schema()`). Bounded retry only for genuinely transient
    categories (`LOCK_TIMEOUT`/`DEADLOCK`/`SERIALIZATION_FAILURE`);
    every other failure fails closed immediately."""
    import psycopg
    from orca.godmode.lease_store import _pg_connect

    try:
        _ensure_pg_schema()
    except psycopg.Error as e:
        return False, _classify_pg_error(e)

    last_category = "UNKNOWN_DATABASE_FAILURE"
    for attempt in range(_MAX_RETRY_ATTEMPTS):
        try:
            conn = _pg_connect()
        except psycopg.Error as e:
            return False, _classify_pg_error(e)

        try:
            with conn.cursor() as cur:
                # SET does not accept bind parameters in Postgres; both
                # values are internal integer constants, never
                # user/caller-supplied, so literals are safe here.
                # statement_timeout is set FIRST and LARGER so it can
                # never silently cap lock_timeout's shorter wait --
                # `lease_store._pg_connect()` already set a 5000ms
                # statement_timeout at the SESSION level for its OWN
                # unrelated purpose; SET LOCAL overrides that for just
                # this transaction (spec Phase 14B.1.1: connect_timeout
                # < lock_timeout < statement_timeout, coherent and
                # explicit, never inherited from an unrelated caller).
                cur.execute(f"SET LOCAL statement_timeout = '{_PG_STATEMENT_TIMEOUT_MS}ms'")
                cur.execute(f"SET LOCAL lock_timeout = '{_PG_LOCK_WAIT_TIMEOUT_MS}ms'")
                cur.execute("SELECT last_seq, last_hash FROM godmode_audit_head WHERE id = 1 FOR UPDATE")
                head = cur.fetchone()
                if head is None:
                    # Schema init raced with a concurrent process's own
                    # init; retry -- the row will exist on the next attempt.
                    raise psycopg.errors.UndefinedTable("godmode_audit_head row missing")
                last_seq, last_hash = head
                seq = last_seq + 1
                prev_hash = last_hash
                payload = _canonical_payload(seq, event)
                entry_hash = _compute_hash(payload)
                signature = _compute_signature(entry_hash)
                cur.execute(
                    """
                    INSERT INTO godmode_audit
                        (event_id, seq, event_type, principal_id, tenant_id, lease_id, capability,
                         resource_scope, operation_scope, issuer, timestamp, trace_id, result,
                         prev_hash, entry_hash, signature)
                    VALUES (%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s)
                    """,
                    (
                        event.event_id, seq, event.event_type.value, event.principal_id, event.tenant_id,
                        event.lease_id, event.capability, event.resource_scope, event.operation_scope,
                        event.issuer, event.timestamp, event.trace_id, event.result,
                        prev_hash, entry_hash, signature,
                    ),
                )
                cur.execute(
                    "UPDATE godmode_audit_head SET last_seq = %s, last_hash = %s WHERE id = 1",
                    (seq, entry_hash),
                )
            conn.commit()
            return True, "SUCCESS"
        except Exception as e:
            conn.rollback()
            category = _classify_pg_error(e) if isinstance(e, psycopg.Error) else "UNKNOWN_DATABASE_FAILURE"
            last_category = category
            if category in ("LOCK_TIMEOUT", "STATEMENT_TIMEOUT", "DEADLOCK", "SERIALIZATION_FAILURE") and attempt < _MAX_RETRY_ATTEMPTS - 1:
                import time
                time.sleep(_retry_backoff_seconds(attempt))
                continue
            return False, category
        finally:
            conn.close()

    return False, last_category


def record_event_durable(event: ElevationAuditEvent) -> bool:
    """Persists `event` durably, hash-chained. Returns True on success,
    False on ANY failure (fail closed -- the caller, per spec §16,
    decides whether a failed audit write should deny the elevated
    action it was meant to record). Never raises. Production
    authorization only ever sees this plain bool -- use
    `record_event_durable_with_diagnostics()` for the sanitized failure
    category (tests/telemetry only)."""
    ok, _category = record_event_durable_with_diagnostics(event)
    return ok


def record_event_durable_with_diagnostics(event: ElevationAuditEvent) -> tuple[bool, str]:
    """Same as `record_event_durable()`, but also returns a sanitized
    failure category (`SUCCESS` on success; one of `_classify_pg_error()`'s
    categories, or `UNKNOWN_DATABASE_FAILURE`/a backend-selection
    failure otherwise). Never includes a DSN, credential, SQL parameter
    value, or the raw exception body -- category name only. Intended
    for tests and structured telemetry; production authorization code
    should keep using the plain-bool `record_event_durable()`."""
    from orca.godmode.lease_store import _backend

    event = _redact(event)
    try:
        backend = _backend()
    except Exception:
        return False, "CONNECTION_FAILURE"
    if backend == "postgres":
        return _record_event_postgres_with_diagnostics(event)
    return _record_event_sqlite_with_diagnostics(event)


def list_events_for_tenant(tenant_id: str) -> list[dict]:
    from orca.godmode.lease_store import _backend

    try:
        backend = _backend()
    except Exception:
        return []
    if backend == "postgres":
        return _list_events_postgres(tenant_id)
    return _list_events_sqlite(tenant_id)


def _list_events_sqlite(tenant_id: str) -> list[dict]:
    from orca.godmode.lease_store import _connect

    try:
        with _connect() as conn:
            conn.execute(_SQLITE_SCHEMA)
            rows = conn.execute(
                "SELECT * FROM godmode_audit WHERE tenant_id = ? ORDER BY seq ASC", (tenant_id,)
            ).fetchall()
    except Exception:
        return []
    return [dict(r) for r in rows]


def _list_events_postgres(tenant_id: str) -> list[dict]:
    import psycopg
    from orca.godmode.lease_store import _pg_connect

    try:
        conn = _pg_connect()
        try:
            with conn.cursor() as cur:
                cur.execute(_PG_SCHEMA)
                cur.execute("SELECT * FROM godmode_audit WHERE tenant_id = %s ORDER BY seq ASC", (tenant_id,))
                cols = [d[0] for d in cur.description]
                rows = [dict(zip(cols, r)) for r in cur.fetchall()]
            conn.commit()
            return rows
        finally:
            conn.close()
    except psycopg.Error:
        return []


def count_false_committed_audit(events: list[dict]) -> int:
    """`GODMODE_FALSE_COMMITTED_AUDIT` counter (audit-commit-semantics
    patch). Counts any persisted event whose `result` says "ALLOW" but
    whose `event_type` is NOT `AUTHORIZATION_COMMITTED` -- the one and
    only event type `resolve_and_consume_lease()` writes with
    result="ALLOW", and only after `consume_use()` has already
    returned True. Must always be 0; a nonzero count means some other
    event type persisted a final grant it never durably earned (the
    exact audit-truth defect this patch closes). Callers pass in the
    event list they already have (e.g. from `list_events_for_tenant()`
    or a full-chain fetch) rather than this function re-querying, so it
    composes with both per-tenant and whole-chain callers without a
    third storage-dispatch path to maintain."""
    return sum(
        1 for e in events
        if e.get("result") == "ALLOW" and e.get("event_type") != ElevationAuditEventType.AUTHORIZATION_COMMITTED.value
    )


def verify_chain(tenant_id: str | None = None) -> dict:
    """Recomputes each entry's hash from its own recorded fields and
    compares against both the stored `entry_hash` and the NEXT entry's
    recorded `prev_hash` -- detects any row that was modified, deleted
    (a gap in `seq`), or reordered after being written. `tenant_id=None`
    verifies the WHOLE chain (all tenants), since seq is a single,
    global, strictly-ordered sequence, not per-tenant."""
    from orca.godmode.lease_store import _backend

    try:
        backend = _backend()
    except Exception:
        return {"valid": False, "reason": "authority store unavailable"}

    if backend == "postgres":
        rows = _all_events_postgres()
    else:
        rows = _all_events_sqlite()

    if tenant_id is not None:
        rows = [r for r in rows if r["tenant_id"] == tenant_id]

    expected_prev = _GENESIS_HASH
    for row in sorted(rows, key=lambda r: r["seq"]):
        event = ElevationAuditEvent(
            event_id=row["event_id"], event_type=ElevationAuditEventType(row["event_type"]),
            principal_id=row["principal_id"], tenant_id=row["tenant_id"], lease_id=row["lease_id"],
            capability=row["capability"] or "", resource_scope=row["resource_scope"] or "",
            operation_scope=row["operation_scope"] or "", issuer=row["issuer"], timestamp=row["timestamp"],
            trace_id=row["trace_id"], result=row["result"] or "",
        )
        payload = _canonical_payload(row["seq"], event)
        recomputed_hash = _compute_hash(payload)
        if recomputed_hash != row["entry_hash"]:
            return {"valid": False, "reason": f"entry_hash mismatch at seq={row['seq']} (row content modified)"}
        if row["prev_hash"] != expected_prev:
            return {"valid": False, "reason": f"prev_hash mismatch at seq={row['seq']} (chain broken -- a row was deleted, reordered, or inserted)"}
        expected_signature = _compute_signature(recomputed_hash)
        if not hmac.compare_digest(expected_signature, row["signature"]):
            return {"valid": False, "reason": f"signature mismatch at seq={row['seq']} (forged without the audit key)"}
        expected_prev = row["entry_hash"]

    return {"valid": True, "entries_verified": len(rows)}


def _all_events_sqlite() -> list[dict]:
    from orca.godmode.lease_store import _connect

    try:
        with _connect() as conn:
            conn.execute(_SQLITE_SCHEMA)
            rows = conn.execute("SELECT * FROM godmode_audit ORDER BY seq ASC").fetchall()
    except Exception:
        return []
    return [dict(r) for r in rows]


def _all_events_postgres() -> list[dict]:
    import psycopg
    from orca.godmode.lease_store import _pg_connect

    try:
        conn = _pg_connect()
        try:
            with conn.cursor() as cur:
                cur.execute(_PG_SCHEMA)
                cur.execute("SELECT * FROM godmode_audit ORDER BY seq ASC")
                cols = [d[0] for d in cur.description]
                rows = [dict(zip(cols, r)) for r in cur.fetchall()]
            conn.commit()
            return rows
        finally:
            conn.close()
    except psycopg.Error:
        return []


def verify_head_consistency() -> dict:
    """Phase 14B.1 §6: cross-checks the durable `godmode_audit_head` row
    against the actual chain tail. SOVEREIGN/SQLite has no separate head
    row (the last row IS the head, protected by `BEGIN IMMEDIATE`'s
    whole-file exclusive lock) so this is a Postgres-only check;
    SQLite reports `{"valid": True, "reason": "no separate head row in
    SQLite backend"}` unconditionally. Never auto-repairs a detected
    inconsistency -- fails closed and surfaces the fault for an
    operator to investigate, per spec's explicit "do not silently
    repair corruption automatically in production"."""
    from orca.godmode.lease_store import _backend

    try:
        backend = _backend()
    except Exception:
        return {"valid": False, "reason": "authority store unavailable"}

    if backend != "postgres":
        return {"valid": True, "reason": "no separate head row in SQLite backend"}

    import psycopg
    from orca.godmode.lease_store import _pg_connect

    try:
        _ensure_pg_schema()
    except psycopg.Error:
        return {"valid": False, "reason": "authority store unavailable"}

    try:
        conn = _pg_connect()
        try:
            with conn.cursor() as cur:
                cur.execute("SELECT last_seq, last_hash FROM godmode_audit_head WHERE id = 1")
                head = cur.fetchone()
                cur.execute("SELECT seq, entry_hash FROM godmode_audit ORDER BY seq DESC LIMIT 1")
                tail = cur.fetchone()
            conn.commit()
        finally:
            conn.close()
    except psycopg.Error:
        return {"valid": False, "reason": "authority store unavailable"}

    if head is None:
        return {"valid": False, "reason": "HEAD_MISSING"}

    head_seq, head_hash = head
    if tail is None:
        if head_seq != -1 or head_hash != _GENESIS_HASH:
            return {"valid": False, "reason": "HEAD_AHEAD_OF_CHAIN", "head_seq": head_seq}
        return {"valid": True, "head_seq": head_seq}

    tail_seq, tail_hash = tail
    if head_seq < tail_seq:
        return {"valid": False, "reason": "HEAD_BEHIND_CHAIN", "head_seq": head_seq, "tail_seq": tail_seq}
    if head_seq > tail_seq:
        return {"valid": False, "reason": "HEAD_AHEAD_OF_CHAIN", "head_seq": head_seq, "tail_seq": tail_seq}
    if head_hash != tail_hash:
        return {"valid": False, "reason": "HEAD_HASH_MISMATCH", "head_seq": head_seq}

    return {"valid": True, "head_seq": head_seq}
