"""
Capability lease persistence (Phase 10 spec §57-58; Phase 13.2 spec
§1-9). SQLite-backed under `ORCA_HOME/godmode/leases.db` (stdlib
`sqlite3`, no new dependency) -- the same real persistence convention as
`orca.gateway.deployment`'s `ModelDeployment` records, extended to be
genuinely safe across MULTIPLE OS PROCESSES sharing the same file, not
just multiple threads within one process.

Phase 13.2 finding (docs/orneur/phase-13/GODMODE_DISTRIBUTED_ATOMICITY.md):
the previous one-JSON-file-per-lease + `threading.Lock` design was atomic
only within a single Python process -- a real `multiprocessing.Process`-
based test proved two independent OS processes could both read
`uses_remaining == 1` and both write back `0`, since nothing serialized
the read-modify-write across process boundaries. Fixed here: `consume_use()`
and `revoke()` now run as a single SQLite transaction using `BEGIN
IMMEDIATE`, which acquires a RESERVED lock on the database file that is
enforced by the OS (via SQLite's own file-locking, `flock`-equivalent on
POSIX) -- genuinely visible across processes, not just threads. Only one
transaction can hold that lock at a time; a second, concurrent
`BEGIN IMMEDIATE` from ANY process (or thread) blocks until the first
commits or rolls back, then re-reads the now-current row. This is
`orca.godmode.lease_store`'s ENTIRE cross-process safety mechanism -- no
`threading.Lock` is needed anymore (SQLite's own locking already
subsumes it, including for same-process concurrent callers), so the
former `_lock_for()`/`_lease_locks` machinery has been removed rather
than kept as redundant dead code.
"""
from __future__ import annotations

import json
import sqlite3
from contextlib import contextmanager
from dataclasses import asdict
from pathlib import Path

from orca.config import ORCA_HOME
from orca.godmode.contracts import (
    ArgumentBindingMode,
    CapabilityDomain,
    CapabilityLease,
    LeaseIssuerClass,
    LeaseRevocationState,
    now_iso,
    parse_iso,
)
from orca.godmode.integrity import verify_lease_integrity

LEASE_DIR = ORCA_HOME / "godmode" / "leases"

# Bounded lock-wait (spec §26: "avoid unbounded process blocking... on
# timeout: deny"). sqlite3's own `timeout` parameter controls how long a
# connection will retry acquiring a lock before raising
# `sqlite3.OperationalError` -- this deliberately fails CLOSED (spec
# §25: "if lock/transaction infrastructure fails: DENY. Do not fail open
# because authority store is busy/unavailable.") rather than blocking
# forever or silently proceeding without the lock.
_LOCK_TIMEOUT_S = 5.0


class AuthorityStoreUnavailableError(Exception):
    """Raised internally, always caught at the public function boundary
    and converted to a fail-closed return value (None/False) -- spec
    §25's `AUTHORITY_STORE_UNAVAILABLE` represented as this exception
    class, never allowed to propagate as an ambiguous crash a caller
    might mishandle as "maybe it succeeded." """


def _db_path() -> Path:
    """Recomputed on every call (never cached at import time) so tests
    that monkeypatch the module-level `LEASE_DIR` attribute -- the
    existing, established pattern across this codebase's test suite --
    continue to redirect storage correctly, exactly as they did when
    `LEASE_DIR` pointed at a directory of one-file-per-lease JSON."""
    return LEASE_DIR / "leases.db"


def _init_schema(conn: sqlite3.Connection) -> None:
    conn.execute(
        """
        CREATE TABLE IF NOT EXISTS leases (
            lease_id TEXT PRIMARY KEY,
            tenant_id TEXT NOT NULL,
            uses_remaining INTEGER,
            revocation_state TEXT NOT NULL,
            expires_at TEXT NOT NULL,
            data TEXT NOT NULL
        )
        """
    )


@contextmanager
def _connect():
    """One fresh connection per call -- sqlite3 connections are not
    meant to be shared across threads/processes, and opening a new one
    per operation sidesteps that entirely (this is a low-frequency,
    authority-boundary operation, not a hot request path -- see spec
    §27-28's explicit performance framing: correctness over micro-
    latency here, while normal non-elevated request handling never
    touches this module at all)."""
    LEASE_DIR.mkdir(parents=True, exist_ok=True)
    conn = sqlite3.connect(str(_db_path()), timeout=_LOCK_TIMEOUT_S, isolation_level=None)
    try:
        conn.row_factory = sqlite3.Row
        _init_schema(conn)
        yield conn
    finally:
        conn.close()


def _to_dict(lease: CapabilityLease) -> dict:
    d = asdict(lease)
    d["capability_domain"] = lease.capability_domain.value
    d["issuer"] = lease.issuer.value
    d["revocation_state"] = lease.revocation_state.value
    d["binding_mode"] = lease.binding_mode.value
    return d


def _from_dict(d: dict) -> CapabilityLease:
    return CapabilityLease(
        lease_id=d["lease_id"], principal_id=d["principal_id"], tenant_id=d["tenant_id"],
        capability_domain=CapabilityDomain(d["capability_domain"]), capability=d["capability"],
        resource_scope=d["resource_scope"], operation_scope=d["operation_scope"],
        issued_at=d["issued_at"], expires_at=d["expires_at"],
        issuer=LeaseIssuerClass(d["issuer"]), issuer_id=d["issuer_id"], reason=d["reason"],
        approval_id=d.get("approval_id"), max_uses=d.get("max_uses"), uses_remaining=d.get("uses_remaining"),
        delegable=d.get("delegable", False), nonce=d["nonce"],
        revocation_state=LeaseRevocationState(d["revocation_state"]), signature=d.get("signature", ""),
        arguments_hash=d.get("arguments_hash"),
        binding_mode=ArgumentBindingMode(d.get("binding_mode", ArgumentBindingMode.EXACT_ARGUMENTS.value)),
    )


def _row_to_lease(row: sqlite3.Row) -> CapabilityLease | None:
    """Fail closed on a corrupted/malformed `data` blob -- spec §20:
    'malformed/truncated lease record must fail closed. Do not reset
    usage count because state cannot be parsed.' Returning None here
    means the lease is treated as not-found/unusable, never as a fresh
    lease with restored uses."""
    try:
        return _from_dict(json.loads(row["data"]))
    except Exception:
        return None


def save(lease: CapabilityLease) -> None:
    """Upsert -- used for both first issuance and any full-record
    rewrite. Runs in its own short IMMEDIATE transaction so a save can
    never interleave with a concurrent consume_use()/revoke() on the
    same lease_id from another process."""
    payload = json.dumps(_to_dict(lease))
    try:
        with _connect() as conn:
            conn.execute("BEGIN IMMEDIATE")
            try:
                conn.execute(
                    """
                    INSERT INTO leases (lease_id, tenant_id, uses_remaining, revocation_state, expires_at, data)
                    VALUES (?, ?, ?, ?, ?, ?)
                    ON CONFLICT(lease_id) DO UPDATE SET
                        tenant_id=excluded.tenant_id, uses_remaining=excluded.uses_remaining,
                        revocation_state=excluded.revocation_state, expires_at=excluded.expires_at, data=excluded.data
                    """,
                    (lease.lease_id, lease.tenant_id, lease.uses_remaining, lease.revocation_state.value, lease.expires_at, payload),
                )
                conn.execute("COMMIT")
            except Exception:
                conn.execute("ROLLBACK")
                raise
    except sqlite3.OperationalError:
        raise AuthorityStoreUnavailableError("could not acquire the authority store lock to save this lease")


def get(lease_id: str) -> CapabilityLease | None:
    try:
        with _connect() as conn:
            row = conn.execute("SELECT data FROM leases WHERE lease_id = ?", (lease_id,)).fetchone()
    except sqlite3.OperationalError:
        return None  # fail closed -- an unreadable store must never be treated as "lease not found -> maybe fine"
    if row is None:
        return None
    return _row_to_lease(row)


def revoke(lease_id: str) -> bool:
    """Immediate revocation (spec §14) -- the lease becomes unusable for
    new actions the instant this returns, regardless of remaining TTL or
    uses_remaining. Atomic across processes: uses the same BEGIN
    IMMEDIATE transaction discipline as consume_use()."""
    try:
        with _connect() as conn:
            conn.execute("BEGIN IMMEDIATE")
            try:
                row = conn.execute("SELECT data FROM leases WHERE lease_id = ?", (lease_id,)).fetchone()
                if row is None:
                    conn.execute("ROLLBACK")
                    return False
                lease = _row_to_lease(row)
                if lease is None:
                    conn.execute("ROLLBACK")
                    return False
                lease.revocation_state = LeaseRevocationState.REVOKED
                conn.execute(
                    "UPDATE leases SET revocation_state = ?, data = ? WHERE lease_id = ?",
                    (LeaseRevocationState.REVOKED.value, json.dumps(_to_dict(lease)), lease_id),
                )
                conn.execute("COMMIT")
                return True
            except Exception:
                conn.execute("ROLLBACK")
                raise
    except sqlite3.OperationalError:
        return False  # fail closed -- see AuthorityStoreUnavailableError's docstring


def is_revoked(lease_id: str) -> bool:
    lease = get(lease_id)
    return lease is None or lease.revocation_state == LeaseRevocationState.REVOKED


def is_expired(lease: CapabilityLease, *, at: str | None = None) -> bool:
    reference = parse_iso(at) if at else parse_iso(now_iso())
    try:
        return reference >= parse_iso(lease.expires_at)
    except Exception:
        return True  # fail closed on an unparseable expiry


def consume_use(lease_id: str) -> bool:
    """
    Atomic single-use (or N-use) consumption (spec §35-36; Phase 13.2
    spec §4-9, §10-13). Returns True if a use was successfully consumed,
    False if the lease has no uses remaining, is revoked, is expired,
    fails integrity verification, does not exist, or the authority store
    itself could not be locked in time -- ALL fail-closed, never an
    exception the caller must remember to catch.

    THE Phase 13.2 fix: this entire read-validate-decrement-persist
    sequence runs inside ONE `BEGIN IMMEDIATE` SQLite transaction.
    `BEGIN IMMEDIATE` acquires a RESERVED lock on the database file
    immediately (before any read in this transaction), enforced by
    SQLite's own file-level locking -- which is visible across process
    boundaries on the same machine, unlike a `threading.Lock`. A second,
    concurrent call to this function -- from another THREAD or another
    PROCESS entirely -- blocks (up to `_LOCK_TIMEOUT_S`) until this
    transaction commits or rolls back, then re-reads the row fresh. This
    is what makes "only one of two processes racing a one-use lease can
    ever observe uses_remaining==1 and decrement it" a real, OS-enforced
    guarantee instead of an in-process-only promise.
    """
    try:
        with _connect() as conn:
            conn.execute("BEGIN IMMEDIATE")
            try:
                row = conn.execute("SELECT data FROM leases WHERE lease_id = ?", (lease_id,)).fetchone()
                if row is None:
                    conn.execute("ROLLBACK")
                    return False
                lease = _row_to_lease(row)
                if lease is None:
                    conn.execute("ROLLBACK")
                    return False
                if lease.revocation_state == LeaseRevocationState.REVOKED:
                    conn.execute("ROLLBACK")
                    return False
                if is_expired(lease):
                    conn.execute("ROLLBACK")
                    return False
                if not verify_lease_integrity(lease):
                    conn.execute("ROLLBACK")
                    return False
                if lease.max_uses is None:
                    conn.execute("COMMIT")
                    return True  # explicitly unmetered lease -- reviewed at issuance, nothing to decrement
                if lease.uses_remaining is None or lease.uses_remaining <= 0:
                    conn.execute("ROLLBACK")
                    return False
                lease.uses_remaining -= 1
                conn.execute(
                    "UPDATE leases SET uses_remaining = ?, data = ? WHERE lease_id = ?",
                    (lease.uses_remaining, json.dumps(_to_dict(lease)), lease_id),
                )
                conn.execute("COMMIT")
                return True
            except Exception:
                conn.execute("ROLLBACK")
                raise
    except sqlite3.OperationalError:
        # Spec §25: lock/transaction infrastructure failure (e.g. the
        # bounded timeout above was exceeded under extreme contention) ->
        # DENY, never fail open.
        return False


def list_active_for_tenant(tenant_id: str) -> list[CapabilityLease]:
    try:
        with _connect() as conn:
            rows = conn.execute(
                "SELECT data FROM leases WHERE tenant_id = ? AND revocation_state != ?",
                (tenant_id, LeaseRevocationState.REVOKED.value),
            ).fetchall()
    except sqlite3.OperationalError:
        return []
    leases = []
    for row in rows:
        lease = _row_to_lease(row)
        if lease is None:
            continue
        if is_expired(lease):
            continue
        leases.append(lease)
    return leases
