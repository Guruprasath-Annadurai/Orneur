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

_PG_SCHEMA = """
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


def _record_event_sqlite(event: ElevationAuditEvent) -> bool:
    import sqlite3
    from orca.godmode.lease_store import _connect

    try:
        with _connect() as conn:
            conn.execute(_SQLITE_SCHEMA)
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
                return True
            except Exception:
                conn.execute("ROLLBACK")
                raise
    except sqlite3.OperationalError:
        return False


def _record_event_postgres(event: ElevationAuditEvent) -> bool:
    import psycopg
    from orca.godmode.lease_store import _pg_connect

    try:
        conn = _pg_connect()
        try:
            with conn.cursor() as cur:
                cur.execute("SELECT pg_advisory_xact_lock(hashtext('godmode_audit_chain'))")
                cur.execute(_PG_SCHEMA)
                cur.execute("SELECT entry_hash, seq FROM godmode_audit ORDER BY seq DESC LIMIT 1")
                last = cur.fetchone()
                prev_hash = last[0] if last else _GENESIS_HASH
                seq = (last[1] + 1) if last else 0
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
            conn.commit()
            return True
        except Exception:
            conn.rollback()
            return False
        finally:
            conn.close()
    except psycopg.Error:
        return False


def record_event_durable(event: ElevationAuditEvent) -> bool:
    """Persists `event` durably, hash-chained. Returns True on success,
    False on ANY failure (fail closed -- the caller, per spec §16,
    decides whether a failed audit write should deny the elevated
    action it was meant to record). Never raises."""
    from orca.godmode.lease_store import _backend

    event = _redact(event)
    try:
        backend = _backend()
    except Exception:
        return False
    if backend == "postgres":
        return _record_event_postgres(event)
    return _record_event_sqlite(event)


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
