"""
Phase 14A.2 -- independent security-root store, closing the REAL,
CONFIRMED vulnerability Phase 14A.1's own closure disclosed as a known
limitation: restoring the kill-switch ledger TOGETHER WITH the stale
authority database restores both to the same old state, defeating
stale-restore protection entirely. Reproduced directly before writing
any of this file: kill switch OFF -> snapshot the ENTIRE godmode
directory (state table AND ledger together) -> activate -> confirmed
DENY -> restore the entire snapshot -> restart -> reconciliation finds
nothing to reconcile (the ledger's own activation record was rolled
back too) -> elevated authorization ALLOWS again. Classified
WHOLE_SNAPSHOT_SECURITY_ROLLBACK, a real security vulnerability, not an
operational documentation footnote.

Core principle (spec §3): "back up the ledger more often" is not a fix
-- it is the same class of promise the ledger itself already made and
broke. Security monotonicity needs an authority domain that is
STRUCTURALLY separate from anything an ordinary "restore my backup"
operation could ever touch, not merely a separate FILE inside the same
backup unit.

Design (spec §4-5, Option A: "separately located security-root store
outside normal backup domain" -- chosen as the simplest production-
correct design actually available in this repository and environment,
per spec's own instruction not to pretend commodity filesystems provide
hardware monotonic counters):

  SOVEREIGN (no ORNEUR_SECURITY_ROOT_DATABASE_URL set): a SQLite file
  at `Path.home() / ".orneur-security-root" / "security_root.db"` by
  default -- a directory that is a SIBLING of `~/.orca`, not nested
  inside it, and whose default location does NOT derive from ORCA_HOME
  at all (even if an operator sets a completely different ORCA_HOME,
  the security root's default path is unaffected -- this is the whole
  point: a "restore my ORCA_HOME backup" operation, by construction,
  has no reason to ever touch a directory outside ORCA_HOME). The
  ONLY honest guarantee this provides: an operator's ordinary backup/
  restore tooling that scopes itself to ORCA_HOME (as this project's
  own `orca/ops/backup.py` does) will not touch this directory. It is
  NOT a hardware-backed monotonic counter, NOT tamper-proof against an
  operator with full filesystem access, and NOT protected by any OS
  keychain/secure-enclave mechanism -- this repository and this
  environment have no such primitive available, and claiming one would
  be dishonest. Real protection here comes from PROCESS, not hardware:
  documented as a directory operators must exclude from routine
  ORCA_HOME backup/restore procedures and must back up/restore
  separately, under its own explicit disaster-recovery procedure (spec
  §7's "SECURITY ROOT BACKUP" class).

  DISTRIBUTED (ORNEUR_SECURITY_ROOT_DATABASE_URL set, e.g.
  postgresql://...): a SEPARATE Postgres DATABASE from the one
  `ORNEUR_GODMODE_DATABASE_URL` points at (a different database name,
  ideally on a different instance/cluster entirely for real production
  use) -- so restoring a pg_dump of the operational authority database
  does not touch this one. Tested locally against two genuinely
  separate databases on the same local PostgreSQL 17 server
  (`orneur_phase14_test` for authority, `orneur_phase14_security_root_test`
  for the security root) -- this proves the CODE PATH's separation
  logic, not a claim that two databases on the same physical server
  survive every disaster scenario a truly separate cluster would.

Epoch semantics (spec §6, §14-15): `epoch` is a plain monotonically-
increasing integer, advanced by exactly 1 on every `advance()` call,
inside the same atomic transaction that also writes the new state --
no caller can ever specify or decrement it directly. This is what makes
"reset produces a NEW epoch, never deletes/reverts history" (spec §15)
true by construction rather than by convention: there is no code path
that writes an epoch value a caller supplies.

Cache policy (spec §19): NONE. `is_active()`/`get_epoch_and_state()`
always read fresh from the security root on every call -- a single-row
local read (SQLite) or a small indexed query (Postgres), cheap enough
that caching would trade a real security property (spec §18's "no
stale-permissive cache") for a performance gain this operation does not
need (Godmode elevation is already a low-frequency, non-hot-path
operation by this codebase's own established design, per
`lease_store.py`'s own docstring making the identical performance
argument for the exact same reason).
"""
from __future__ import annotations

import sqlite3
from contextlib import contextmanager
from pathlib import Path

from orca.config import orneur_env
from orca.godmode.contracts import now_iso

_LOCK_TIMEOUT_S = 5.0


def _backend() -> str:
    return "postgres" if orneur_env("SECURITY_ROOT_DATABASE_URL") else "sqlite"


def _root_home() -> Path:
    """Recomputed on every call, never a module-level constant (the
    exact bug class this codebase has hit twice before this phase --
    kill_switch's old `_KILL_SWITCH_FILE`, and the first version of
    `revocation_ledger.py`). Deliberately does NOT derive from
    `orca.config.ORCA_HOME` -- reading ORCA_HOME here would silently
    defeat the entire point of this module (a security root whose
    default location moves whenever ORCA_HOME does is not independent
    of ORCA_HOME). `ORNEUR_SECURITY_ROOT_HOME` is the one and only
    override, used by tests to isolate the security root the same way
    `ORCA_HOME` isolates everything else -- production deployments
    should not normally need to set this, since the whole point is a
    fixed, well-known, separately-backed-up location."""
    return Path(orneur_env("SECURITY_ROOT_HOME", str(Path.home() / ".orneur-security-root")))


def _db_path() -> Path:
    return _root_home() / "security_root.db"


def _init_schema(conn: sqlite3.Connection) -> None:
    conn.execute(
        """
        CREATE TABLE IF NOT EXISTS security_root (
            id INTEGER PRIMARY KEY CHECK (id = 1),
            epoch INTEGER NOT NULL,
            state TEXT NOT NULL,
            updated_at TEXT NOT NULL,
            reason TEXT
        )
        """
    )


@contextmanager
def _connect():
    root_home = _root_home()
    root_home.mkdir(parents=True, exist_ok=True)
    conn = sqlite3.connect(str(_db_path()), timeout=_LOCK_TIMEOUT_S, isolation_level=None)
    try:
        conn.row_factory = sqlite3.Row
        _init_schema(conn)
        yield conn
    finally:
        conn.close()


def _get_sqlite() -> tuple[int | None, str]:
    try:
        with _connect() as conn:
            row = conn.execute("SELECT epoch, state FROM security_root WHERE id = 1").fetchone()
    except sqlite3.OperationalError:
        return (None, "UNKNOWN")  # fail closed -- spec §9
    if row is None:
        return (0, "INACTIVE")  # a security root that has never recorded an event -- honest starting point, not a fabricated ACTIVE
    return (row["epoch"], row["state"])


def _advance_sqlite(new_state: str, reason: str) -> int | None:
    from orca.godmode.lease_store import _test_checkpoint  # reused Phase 13.3 crash-injection hook, inert unless GODMODE_TEST_CRASH_CHECKPOINT is set

    try:
        with _connect() as conn:
            conn.execute("BEGIN IMMEDIATE")
            _test_checkpoint("SECURITY_ROOT_AFTER_BEGIN_IMMEDIATE")
            try:
                row = conn.execute("SELECT epoch FROM security_root WHERE id = 1").fetchone()
                current_epoch = row["epoch"] if row is not None else 0
                new_epoch = current_epoch + 1
                conn.execute(
                    """
                    INSERT INTO security_root (id, epoch, state, updated_at, reason) VALUES (1, ?, ?, ?, ?)
                    ON CONFLICT(id) DO UPDATE SET epoch=excluded.epoch, state=excluded.state, updated_at=excluded.updated_at, reason=excluded.reason
                    """,
                    (new_epoch, new_state, now_iso(), reason),
                )
                _test_checkpoint("SECURITY_ROOT_AFTER_UPDATE_BEFORE_COMMIT")
                conn.execute("COMMIT")
                _test_checkpoint("SECURITY_ROOT_AFTER_COMMIT")
                return new_epoch
            except Exception:
                conn.execute("ROLLBACK")
                raise
    except sqlite3.OperationalError:
        return None


def _pg_connect():
    import psycopg

    dsn = orneur_env("SECURITY_ROOT_DATABASE_URL")
    conn = psycopg.connect(dsn, autocommit=False, connect_timeout=_LOCK_TIMEOUT_S)
    with conn.cursor() as cur:
        cur.execute(f"SET statement_timeout = {int(_LOCK_TIMEOUT_S * 1000)}")
        cur.execute(
            """
            CREATE TABLE IF NOT EXISTS security_root (
                id INTEGER PRIMARY KEY CHECK (id = 1),
                epoch INTEGER NOT NULL,
                state TEXT NOT NULL,
                updated_at TEXT NOT NULL,
                reason TEXT
            )
            """
        )
    conn.commit()
    return conn


def _get_postgres() -> tuple[int | None, str]:
    import psycopg

    try:
        conn = _pg_connect()
        try:
            with conn.cursor() as cur:
                cur.execute("SELECT epoch, state FROM security_root WHERE id = 1")
                row = cur.fetchone()
            conn.commit()
        finally:
            conn.close()
    except psycopg.Error:
        return (None, "UNKNOWN")
    if row is None:
        return (0, "INACTIVE")
    return (row[0], row[1])


def _advance_postgres(new_state: str, reason: str) -> int | None:
    import psycopg

    try:
        conn = _pg_connect()
        try:
            with conn.cursor() as cur:
                cur.execute("SELECT epoch FROM security_root WHERE id = 1 FOR UPDATE")
                row = cur.fetchone()
                current_epoch = row[0] if row is not None else 0
                new_epoch = current_epoch + 1
                cur.execute(
                    """
                    INSERT INTO security_root (id, epoch, state, updated_at, reason) VALUES (1, %s, %s, %s, %s)
                    ON CONFLICT (id) DO UPDATE SET epoch=excluded.epoch, state=excluded.state, updated_at=excluded.updated_at, reason=excluded.reason
                    """,
                    (new_epoch, new_state, now_iso(), reason),
                )
            conn.commit()
            return new_epoch
        except Exception:
            conn.rollback()
            raise
        finally:
            conn.close()
    except psycopg.Error:
        return None


def get_epoch_and_state() -> tuple[int | None, str]:
    """Returns (epoch, state). `state` is "ACTIVE", "INACTIVE", or
    "UNKNOWN" (root unreachable -- callers MUST treat UNKNOWN as active,
    spec §9: never infer INACTIVE, epoch 0, or a permissive default).
    `epoch` is None only when state is UNKNOWN."""
    if _backend() == "postgres":
        return _get_postgres()
    return _get_sqlite()


def advance(new_state: str, *, reason: str = "") -> int | None:
    """Atomically increments the epoch by 1 and records `new_state`.
    Returns the new epoch, or None if the root could not be written
    (fail closed -- caller must not assume the advance took effect)."""
    if _backend() == "postgres":
        return _advance_postgres(new_state, reason)
    return _advance_sqlite(new_state, reason)


def is_active() -> bool:
    """The ONE function every elevated-authorization gate should
    consult -- ground truth, always read fresh, never cached (spec
    §18-19). Fail-closed: UNKNOWN state (root unreachable) is treated
    as active."""
    _, state = get_epoch_and_state()
    return state != "INACTIVE"
