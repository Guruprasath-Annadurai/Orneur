"""
Capability lease persistence (Phase 10 spec §57-58; Phase 13.2 spec
§1-9; Phase 14 spec §34-36). Dual-backend by the same design already
established in `orca.auth.db`:

  - Default (no `ORNEUR_GODMODE_DATABASE_URL` set): SQLite under
    `ORCA_HOME/godmode/leases.db` (stdlib `sqlite3`, no new dependency).
    This is the ORNEUR SOVEREIGN profile -- a single host, `BEGIN
    IMMEDIATE` transactions, proven cross-process-safe on one host by
    Phase 13.2/13.3 (real multiprocess races, real SIGKILL crash
    injection). Nothing about this path changes in Phase 14.
  - Production/distributed mode (`ORNEUR_GODMODE_DATABASE_URL` set, e.g.
    `postgresql://...`): PostgreSQL. This is the ORNEUR DISTRIBUTED
    profile's answer to Phase 14 spec §4-6/§34: "do NOT let each host
    maintain an independent authority database" -- SQLite's file lock
    is inherently single-host, so once ORNEUR runs on more than one
    host, every host must point at the SAME transactional database
    rather than each keeping its own `leases.db`. See
    docs/orneur/phase-14/AUTHORITY_DISTRIBUTION.md for the full
    decision record and real (non-cloud, local Postgres) test evidence.

Both backends preserve identical atomicity semantics for the exact same
reason: SQLite's `BEGIN IMMEDIATE` acquires a RESERVED lock on the whole
database file before any read in the transaction; Postgres's
`SELECT ... FOR UPDATE` acquires a row-level lock on the specific lease
row before any read used for a mutation decision. Either way, a second
concurrent transaction attempting to read-modify-write the SAME lease
blocks until the first commits or rolls back, then re-reads the
now-current row -- this is what makes "only one of N callers racing a
one-use lease can ever decrement it" a real, engine-enforced guarantee
under both backends, not an in-process-only promise.

Phase 13.2 finding (docs/orneur/phase-13/GODMODE_DISTRIBUTED_ATOMICITY.md):
the previous one-JSON-file-per-lease + `threading.Lock` design was atomic
only within a single Python process -- a real `multiprocessing.Process`-
based test proved two independent OS processes could both read
`uses_remaining == 1` and both write back `0`, since nothing serialized
the read-modify-write across process boundaries. Fixed with SQLite's
`BEGIN IMMEDIATE` for the single-host case; Phase 14 extends the same
guarantee across hosts via the Postgres backend below.
"""
from __future__ import annotations

import json
import os
import sqlite3
import time
from contextlib import contextmanager
from dataclasses import asdict
from pathlib import Path

from orca.config import ORCA_HOME, orneur_env
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

# Backend selection recomputed as a function (not a module-level constant)
# so tests -- and a running process reacting to a config reload the same
# way `orca.auth.db` already assumes -- can flip backends by setting/
# clearing the env var and re-importing, matching this module's existing
# test convention of `importlib.reload(orca.godmode.lease_store)`.
def _backend() -> str:
    return "postgres" if orneur_env("GODMODE_DATABASE_URL") else "sqlite"

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


# --------------------------------------------------------------- Phase 13.3 §3: test-only crash-injection hook
#
# Inert in ordinary production operation: `_test_checkpoint()` is a single
# `os.environ.get()` read that returns immediately unless
# `GODMODE_TEST_CRASH_CHECKPOINT` is set to the EXACT checkpoint name
# passed in -- an environment variable no production deployment ever
# sets. This is what makes "kill a real OS process while it is provably
# inside this exact point of an authority-store transaction" a real,
# verifiable test (tests/test_godmode_crash_consistency.py) rather than a
# guess about timing: the child process signals readiness by creating a
# file, then blocks, giving the parent test process a wide, reliable
# window to SIGKILL it before it can proceed past this exact checkpoint.
_CRASH_CHECKPOINT_ENV = "GODMODE_TEST_CRASH_CHECKPOINT"
_CRASH_SIGNAL_FILE_ENV = "GODMODE_TEST_CRASH_SIGNAL_FILE"


def _test_checkpoint(name: str) -> None:
    target = os.environ.get(_CRASH_CHECKPOINT_ENV)
    if target != name:
        return
    signal_file = os.environ.get(_CRASH_SIGNAL_FILE_ENV)
    if signal_file:
        with open(signal_file, "w") as f:
            f.write("ready")
    time.sleep(30)  # far longer than any real test needs to observe the signal file and SIGKILL this process


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


def _save_sqlite(lease: CapabilityLease) -> None:
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


def _get_sqlite(lease_id: str) -> CapabilityLease | None:
    try:
        with _connect() as conn:
            row = conn.execute("SELECT data FROM leases WHERE lease_id = ?", (lease_id,)).fetchone()
    except sqlite3.OperationalError:
        return None  # fail closed -- an unreadable store must never be treated as "lease not found -> maybe fine"
    if row is None:
        return None
    return _row_to_lease(row)


def _revoke_sqlite(lease_id: str) -> bool:
    """Immediate revocation (spec §14) -- the lease becomes unusable for
    new actions the instant this returns, regardless of remaining TTL or
    uses_remaining. Atomic across processes: uses the same BEGIN
    IMMEDIATE transaction discipline as consume_use()."""
    try:
        with _connect() as conn:
            conn.execute("BEGIN IMMEDIATE")
            _test_checkpoint("AFTER_BEGIN_IMMEDIATE")
            try:
                row = conn.execute("SELECT data FROM leases WHERE lease_id = ?", (lease_id,)).fetchone()
                _test_checkpoint("AFTER_RECORD_READ")
                if row is None:
                    conn.execute("ROLLBACK")
                    return False
                lease = _row_to_lease(row)
                if lease is None:
                    conn.execute("ROLLBACK")
                    return False
                _test_checkpoint("AFTER_MUTABLE_VALIDATION")
                lease.revocation_state = LeaseRevocationState.REVOKED
                conn.execute(
                    "UPDATE leases SET revocation_state = ?, data = ? WHERE lease_id = ?",
                    (LeaseRevocationState.REVOKED.value, json.dumps(_to_dict(lease)), lease_id),
                )
                _test_checkpoint("AFTER_UPDATE_BEFORE_COMMIT")
                conn.execute("COMMIT")
                _test_checkpoint("AFTER_COMMIT")
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


def _consume_use_sqlite(lease_id: str) -> bool:
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
            _test_checkpoint("AFTER_BEGIN_IMMEDIATE")
            try:
                row = conn.execute("SELECT data FROM leases WHERE lease_id = ?", (lease_id,)).fetchone()
                _test_checkpoint("AFTER_RECORD_READ")
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
                _test_checkpoint("AFTER_MUTABLE_VALIDATION")
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
                _test_checkpoint("AFTER_UPDATE_BEFORE_COMMIT")
                conn.execute("COMMIT")
                _test_checkpoint("AFTER_COMMIT")
                return True
            except Exception:
                conn.execute("ROLLBACK")
                raise
    except sqlite3.OperationalError:
        # Spec §25: lock/transaction infrastructure failure (e.g. the
        # bounded timeout above was exceeded under extreme contention) ->
        # DENY, never fail open.
        return False


def _reserve_uses_sqlite(lease_id: str, n: int) -> bool:
    """
    Phase 13.2 spec §17 finding: `orca.godmode.delegation.delegate_lease()`
    read `parent.uses_remaining` to VALIDATE that `child_max_uses` did not
    exceed it, but never actually reserved/decremented anything from the
    parent -- a delegable parent with `uses_remaining=5` could delegate a
    child ALSO carrying its own independent `uses_remaining=5`, doubling
    total available authority to 10. This is a real authority-
    multiplication bug, distinct from (but sibling to) the cross-process
    `consume_use()` race this phase's main fix addresses -- same missing
    atomicity discipline, different call site.

    `reserve_uses()` atomically checks-and-decrements `uses_remaining` by
    `n` in ONE `BEGIN IMMEDIATE` transaction (same locking discipline as
    `consume_use()`), so two concurrent delegations from the same parent
    can never each believe they reserved the same uses out of a shared
    pool. Returns True (and commits the decrement) only if the lease is
    valid (exists, not revoked, not expired, passes integrity) AND has at
    least `n` uses remaining; False otherwise (nothing is decremented on
    a False return -- the transaction rolls back).

    A lease with `max_uses=None` (explicitly unmetered) has nothing to
    reserve from -- always returns True without touching any counter,
    matching `consume_use()`'s own treatment of unmetered leases.
    """
    if n <= 0:
        return False
    try:
        with _connect() as conn:
            conn.execute("BEGIN IMMEDIATE")
            _test_checkpoint("AFTER_BEGIN_IMMEDIATE")
            try:
                row = conn.execute("SELECT data FROM leases WHERE lease_id = ?", (lease_id,)).fetchone()
                _test_checkpoint("AFTER_RECORD_READ")
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
                _test_checkpoint("AFTER_MUTABLE_VALIDATION")
                if lease.max_uses is None:
                    conn.execute("COMMIT")
                    return True  # unmetered -- nothing to reserve
                if lease.uses_remaining is None or lease.uses_remaining < n:
                    conn.execute("ROLLBACK")
                    return False
                lease.uses_remaining -= n
                conn.execute(
                    "UPDATE leases SET uses_remaining = ?, data = ? WHERE lease_id = ?",
                    (lease.uses_remaining, json.dumps(_to_dict(lease)), lease_id),
                )
                _test_checkpoint("AFTER_UPDATE_BEFORE_COMMIT")
                conn.execute("COMMIT")
                _test_checkpoint("AFTER_COMMIT")
                return True
            except Exception:
                conn.execute("ROLLBACK")
                raise
    except sqlite3.OperationalError:
        return False


def _list_active_for_tenant_sqlite(tenant_id: str) -> list[CapabilityLease]:
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


# ─────────────────────────────────────────────────────────────────────────────
# Phase 14 §34-36: PostgreSQL backend for the ORNEUR DISTRIBUTED profile.
#
# The atomicity primitive here is `SELECT ... FOR UPDATE` inside an explicit
# transaction, taken on the lease's own row before any read used to decide a
# mutation. This is actually FINER-GRAINED than SQLite's `BEGIN IMMEDIATE`
# (which locks the whole database file): a `FOR UPDATE` on lease A does not
# block a concurrent transaction on lease B. For the property this codebase
# actually needs -- "two callers racing the SAME lease can never both
# consume/reserve/revoke it" -- both give an identical, engine-enforced
# guarantee. A bounded `statement_timeout` (mirroring `_LOCK_TIMEOUT_S`)
# is set per-transaction so a caller that cannot acquire the row lock in
# time gets `psycopg.errors.QueryCanceled`, caught at the same public
# function boundary as SQLite's `OperationalError` and converted to the
# same fail-closed return value -- never a fresh ambiguous exception type
# a caller has to learn to catch separately.
# ─────────────────────────────────────────────────────────────────────────────

_PG_LOCK_TIMEOUT_MS = int(_LOCK_TIMEOUT_S * 1000)

_PG_SCHEMA = """
CREATE TABLE IF NOT EXISTS godmode_leases (
    lease_id TEXT PRIMARY KEY,
    tenant_id TEXT NOT NULL,
    uses_remaining INTEGER,
    revocation_state TEXT NOT NULL,
    expires_at TEXT NOT NULL,
    data TEXT NOT NULL
);
CREATE INDEX IF NOT EXISTS ix_godmode_leases_tenant ON godmode_leases(tenant_id);
"""


def _pg_connect():
    """One fresh connection per call, same rationale as `_connect()` above
    -- this is a low-frequency authority-boundary operation, not a hot
    request path. `autocommit=False` so every caller controls its own
    transaction boundary explicitly (never an implicit one left open)."""
    import psycopg

    dsn = orneur_env("GODMODE_DATABASE_URL")
    conn = psycopg.connect(dsn, autocommit=False, connect_timeout=_LOCK_TIMEOUT_S)
    with conn.cursor() as cur:
        cur.execute(f"SET statement_timeout = {_PG_LOCK_TIMEOUT_MS}")
        cur.execute(_PG_SCHEMA)
    conn.commit()
    return conn


def _pg_row_to_lease(data: str) -> CapabilityLease | None:
    try:
        return _from_dict(json.loads(data))
    except Exception:
        return None


def _save_postgres(lease: CapabilityLease) -> None:
    import psycopg

    payload = json.dumps(_to_dict(lease))
    try:
        conn = _pg_connect()
        try:
            with conn.cursor() as cur:
                cur.execute(
                    """
                    INSERT INTO godmode_leases (lease_id, tenant_id, uses_remaining, revocation_state, expires_at, data)
                    VALUES (%s, %s, %s, %s, %s, %s)
                    ON CONFLICT (lease_id) DO UPDATE SET
                        tenant_id=excluded.tenant_id, uses_remaining=excluded.uses_remaining,
                        revocation_state=excluded.revocation_state, expires_at=excluded.expires_at, data=excluded.data
                    """,
                    (lease.lease_id, lease.tenant_id, lease.uses_remaining, lease.revocation_state.value, lease.expires_at, payload),
                )
            conn.commit()
        finally:
            conn.close()
    except psycopg.Error:
        raise AuthorityStoreUnavailableError("could not reach the authority store (postgres) to save this lease")


def _get_postgres(lease_id: str) -> CapabilityLease | None:
    import psycopg

    try:
        conn = _pg_connect()
        try:
            with conn.cursor() as cur:
                cur.execute("SELECT data FROM godmode_leases WHERE lease_id = %s", (lease_id,))
                row = cur.fetchone()
            conn.commit()
        finally:
            conn.close()
    except psycopg.Error:
        return None  # fail closed -- see AuthorityStoreUnavailableError's docstring
    if row is None:
        return None
    return _pg_row_to_lease(row[0])


def _revoke_postgres(lease_id: str) -> bool:
    import psycopg

    try:
        conn = _pg_connect()
        try:
            with conn.cursor() as cur:
                cur.execute("SELECT data FROM godmode_leases WHERE lease_id = %s FOR UPDATE", (lease_id,))
                _test_checkpoint("AFTER_RECORD_READ")
                row = cur.fetchone()
                if row is None:
                    conn.rollback()
                    return False
                lease = _pg_row_to_lease(row[0])
                if lease is None:
                    conn.rollback()
                    return False
                _test_checkpoint("AFTER_MUTABLE_VALIDATION")
                lease.revocation_state = LeaseRevocationState.REVOKED
                cur.execute(
                    "UPDATE godmode_leases SET revocation_state = %s, data = %s WHERE lease_id = %s",
                    (LeaseRevocationState.REVOKED.value, json.dumps(_to_dict(lease)), lease_id),
                )
                _test_checkpoint("AFTER_UPDATE_BEFORE_COMMIT")
            conn.commit()
            _test_checkpoint("AFTER_COMMIT")
            return True
        except Exception:
            conn.rollback()
            raise
        finally:
            conn.close()
    except psycopg.Error:
        return False


def _consume_use_postgres(lease_id: str) -> bool:
    import psycopg

    try:
        conn = _pg_connect()
        try:
            with conn.cursor() as cur:
                cur.execute("SELECT data FROM godmode_leases WHERE lease_id = %s FOR UPDATE", (lease_id,))
                _test_checkpoint("AFTER_RECORD_READ")
                row = cur.fetchone()
                if row is None:
                    conn.rollback()
                    return False
                lease = _pg_row_to_lease(row[0])
                if lease is None:
                    conn.rollback()
                    return False
                if lease.revocation_state == LeaseRevocationState.REVOKED:
                    conn.rollback()
                    return False
                if is_expired(lease):
                    conn.rollback()
                    return False
                if not verify_lease_integrity(lease):
                    conn.rollback()
                    return False
                _test_checkpoint("AFTER_MUTABLE_VALIDATION")
                if lease.max_uses is None:
                    conn.commit()
                    return True  # explicitly unmetered lease -- nothing to decrement
                if lease.uses_remaining is None or lease.uses_remaining <= 0:
                    conn.rollback()
                    return False
                lease.uses_remaining -= 1
                cur.execute(
                    "UPDATE godmode_leases SET uses_remaining = %s, data = %s WHERE lease_id = %s",
                    (lease.uses_remaining, json.dumps(_to_dict(lease)), lease_id),
                )
                _test_checkpoint("AFTER_UPDATE_BEFORE_COMMIT")
            conn.commit()
            _test_checkpoint("AFTER_COMMIT")
            return True
        except Exception:
            conn.rollback()
            raise
        finally:
            conn.close()
    except psycopg.Error:
        return False


def _reserve_uses_postgres(lease_id: str, n: int) -> bool:
    import psycopg

    if n <= 0:
        return False
    try:
        conn = _pg_connect()
        try:
            with conn.cursor() as cur:
                cur.execute("SELECT data FROM godmode_leases WHERE lease_id = %s FOR UPDATE", (lease_id,))
                _test_checkpoint("AFTER_RECORD_READ")
                row = cur.fetchone()
                if row is None:
                    conn.rollback()
                    return False
                lease = _pg_row_to_lease(row[0])
                if lease is None:
                    conn.rollback()
                    return False
                if lease.revocation_state == LeaseRevocationState.REVOKED:
                    conn.rollback()
                    return False
                if is_expired(lease):
                    conn.rollback()
                    return False
                if not verify_lease_integrity(lease):
                    conn.rollback()
                    return False
                _test_checkpoint("AFTER_MUTABLE_VALIDATION")
                if lease.max_uses is None:
                    conn.commit()
                    return True  # unmetered -- nothing to reserve
                if lease.uses_remaining is None or lease.uses_remaining < n:
                    conn.rollback()
                    return False
                lease.uses_remaining -= n
                cur.execute(
                    "UPDATE godmode_leases SET uses_remaining = %s, data = %s WHERE lease_id = %s",
                    (lease.uses_remaining, json.dumps(_to_dict(lease)), lease_id),
                )
                _test_checkpoint("AFTER_UPDATE_BEFORE_COMMIT")
            conn.commit()
            _test_checkpoint("AFTER_COMMIT")
            return True
        except Exception:
            conn.rollback()
            raise
        finally:
            conn.close()
    except psycopg.Error:
        return False


def _list_active_for_tenant_postgres(tenant_id: str) -> list[CapabilityLease]:
    import psycopg

    try:
        conn = _pg_connect()
        try:
            with conn.cursor() as cur:
                cur.execute(
                    "SELECT data FROM godmode_leases WHERE tenant_id = %s AND revocation_state != %s",
                    (tenant_id, LeaseRevocationState.REVOKED.value),
                )
                rows = cur.fetchall()
            conn.commit()
        finally:
            conn.close()
    except psycopg.Error:
        return []
    leases = []
    for row in rows:
        lease = _pg_row_to_lease(row[0])
        if lease is None:
            continue
        if is_expired(lease):
            continue
        leases.append(lease)
    return leases


# ─────────────────────────────────────────────────────────────────────────────
# Public API -- dispatches to the SQLite or Postgres implementation above
# based on `_backend()`. Every caller in the codebase (resolution.py,
# issuance.py, delegation.py, connector_elevation.py, and every existing
# test) continues to call these exact same six function names with the
# exact same signatures -- this is precisely why Phase 13.2 kept the
# original SQLite migration's function surface frozen, and it pays off
# again here: adding a second backend required zero changes outside this
# one file.
# ─────────────────────────────────────────────────────────────────────────────


def save(lease: CapabilityLease) -> None:
    if _backend() == "postgres":
        return _save_postgres(lease)
    return _save_sqlite(lease)


def get(lease_id: str) -> CapabilityLease | None:
    if _backend() == "postgres":
        return _get_postgres(lease_id)
    return _get_sqlite(lease_id)


def revoke(lease_id: str) -> bool:
    """Dispatches to the backend-specific revoke, then records the
    revocation in the append-only ledger (Phase 14 §67-68 --
    orca.godmode.revocation_ledger) so a later restore of a stale
    pre-revocation backup can be reconciled back to REVOKED rather than
    silently resurrecting the privilege. Recorded only on an actual
    successful revocation (not on a no-op/already-revoked/not-found
    call) -- the ledger records events, not attempts."""
    if _backend() == "postgres":
        result = _revoke_postgres(lease_id)
    else:
        result = _revoke_sqlite(lease_id)
    if result:
        from orca.godmode.revocation_ledger import record_revocation
        record_revocation(lease_id)
    return result


def consume_use(lease_id: str) -> bool:
    if _backend() == "postgres":
        return _consume_use_postgres(lease_id)
    return _consume_use_sqlite(lease_id)


def reserve_uses(lease_id: str, n: int) -> bool:
    if _backend() == "postgres":
        return _reserve_uses_postgres(lease_id, n)
    return _reserve_uses_sqlite(lease_id, n)


def list_active_for_tenant(tenant_id: str) -> list[CapabilityLease]:
    if _backend() == "postgres":
        return _list_active_for_tenant_postgres(tenant_id)
    return _list_active_for_tenant_sqlite(tenant_id)
