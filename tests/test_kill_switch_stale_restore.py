"""
Phase 14A.1 -- kill-switch stale-restore security closure (narrower
scenario: restoring the leases.db authority mirror alone).

Phase 14A.2 update: `orca.godmode.kill_switch.is_active()` now consults
`orca.godmode.security_root` as ground truth (see that module and
`tests/test_security_root_whole_snapshot.py` for the broader,
whole-snapshot closure). This file's tests were rewritten accordingly
-- several scenarios that used to require Phase 14A.1's
`kill_switch_ledger.reconcile_after_restore()` to pass now correctly
pass WITHOUT reconciliation, because the security root (which lives
structurally outside the leases.db authority database) was never
touched by restoring leases.db alone. This is Phase 14A.2's fix working
exactly as intended -- these tests were updated to assert the stronger,
correct behavior rather than the old, now-superseded assumption that
`is_active()` reads the leases.db mirror.

The one thing this file does NOT cover -- restoring the SECURITY ROOT
itself alongside everything else -- is exactly what
`test_security_root_whole_snapshot.py` exists for.
"""
from __future__ import annotations

import importlib
import multiprocessing
import os
import shutil
import time
import uuid

import pytest

_TEST_DSN = "postgresql://ag@localhost/orneur_phase14_test"


@pytest.fixture(autouse=True)
def _restore_env_after_test():
    prev = {k: os.environ.get(k) for k in (
        "ORCA_HOME", "ORNEUR_HOME", "ORNEUR_GODMODE_DATABASE_URL",
        "ORNEUR_SECURITY_ROOT_HOME", "ORNEUR_SECURITY_ROOT_DATABASE_URL",
        "GODMODE_TEST_CRASH_CHECKPOINT", "GODMODE_TEST_CRASH_SIGNAL_FILE",
    )}
    yield
    for k, v in prev.items():
        if v is not None:
            os.environ[k] = v
        else:
            os.environ.pop(k, None)
    import orca.config as config_mod
    importlib.reload(config_mod)
    import orca.godmode.lease_store as lease_store_mod
    importlib.reload(lease_store_mod)
    import orca.godmode.kill_switch as kill_switch_mod
    importlib.reload(kill_switch_mod)
    import orca.godmode.resolution as resolution_mod
    importlib.reload(resolution_mod)


def _setup_home(home: str, *, postgres: bool = False, security_root_home: str | None = None):
    """`security_root_home` defaults to a fixed sibling of `home` (NOT
    nested inside it -- this file's own tests care about isolating the
    lease-store domain from the security-root domain exactly as
    production does; conftest.py's autouse fixture already isolates
    the security root to a per-test tmp path by default, but tests
    below that explicitly manipulate `home`'s directory tree need a
    security-root path they can reason about independently)."""
    os.environ["ORCA_HOME"] = home
    os.environ["ORNEUR_HOME"] = home
    if security_root_home is not None:
        os.environ["ORNEUR_SECURITY_ROOT_HOME"] = security_root_home
    if postgres:
        os.environ["ORNEUR_GODMODE_DATABASE_URL"] = _TEST_DSN
    else:
        os.environ.pop("ORNEUR_GODMODE_DATABASE_URL", None)
    import orca.config as config_mod
    importlib.reload(config_mod)
    import orca.godmode.lease_store as lease_store_mod
    importlib.reload(lease_store_mod)
    import orca.godmode.kill_switch as kill_switch_mod
    importlib.reload(kill_switch_mod)
    import orca.godmode.resolution as resolution_mod
    importlib.reload(resolution_mod)
    return lease_store_mod, kill_switch_mod, resolution_mod


def _issue_lease(home: str, lease_id: str, *, postgres: bool = False):
    _setup_home(home, postgres=postgres)
    from datetime import datetime, timedelta, timezone
    from orca.godmode.contracts import CapabilityDomain, GodmodeApproval, LeaseIssuerClass
    from orca.godmode.issuance import issue_lease
    from orca.godmode.canonical import hash_arguments

    approval = GodmodeApproval(
        approval_id=f"ap-{lease_id}", principal_id="u1", tenant_id="t1", capability_domain=CapabilityDomain.CONNECTOR,
        capability="CONNECTOR_WRITE", resource_scope="conn-1", operation_scope="write", arguments_hash=hash_arguments({}),
        duration_s=3600, reason="kill switch stale restore test", approved_by="human:tester",
        expires_at=(datetime.now(timezone.utc) + timedelta(seconds=3600)).strftime("%Y-%m-%dT%H:%M:%SZ"),
    )
    return issue_lease(approval=approval, issuer=LeaseIssuerClass.HUMAN_APPROVAL, issuer_id="human:tester", max_uses=5)


def _try_elevated(resolution_mod, lease_id: str) -> str:
    from orca.godmode.contracts import CapabilityDomain
    decision = resolution_mod.resolve_and_consume_lease(
        lease_id=lease_id, tenant_id="t1", capability_domain=CapabilityDomain.CONNECTOR,
        capability="CONNECTOR_WRITE", resource_scope="conn-1", operation_scope="write", arguments={},
    )
    return decision.state.value


# --------------------------------------------------------------- Phase 14A.1 scenario, now doubly closed


def test_restoring_leases_db_mirror_alone_no_longer_defeats_kill_switch(tmp_path):
    """Phase 14A.1's original scenario (restore leases.db's
    kill_switch_state mirror, WITHOUT touching the security root):
    now correctly stays DENIED even with NO reconciliation step at
    all, because `is_active()` (Phase 14A.2) never reads that mirror
    in the first place -- it reads the security root directly, which
    this restore never touched. This is Phase 14A.2's fix working
    correctly, not a weaker test."""
    security_root_home = str(tmp_path / "security-root")
    home = str(tmp_path / "home-fixed")
    os.makedirs(home, exist_ok=True)
    ls, ks, resolution = _setup_home(home, security_root_home=security_root_home)
    lease = _issue_lease(home, "fixed-1")

    godmode_dir = ls.LEASE_DIR.parent
    backup_dir = tmp_path / "backup_pre_activation"
    shutil.copytree(godmode_dir, backup_dir)

    ks.activate(reason="fix verification test")
    assert ks.is_active() is True

    from orca.godmode.kill_switch_ledger import _ledger_path
    assert _ledger_path().exists(), "activate() must have recorded this event in the append-only ledger"

    # Restore the leases.db mirror alone (the ledger, a sibling file in
    # the same directory, and the security root, an entirely separate
    # directory tree, are both left untouched).
    leases_db = ls._db_path()
    backup_db = backup_dir / "leases" / "leases.db"
    shutil.copy2(backup_db, leases_db)
    _setup_home(home, security_root_home=security_root_home)
    import orca.godmode.kill_switch as ks2
    import orca.godmode.resolution as resolution2

    assert ks2.is_active() is True, "the security root was never touched by this restore -- state must remain ACTIVE with NO reconciliation needed"
    assert _try_elevated(resolution2, lease.lease_id) == "DENY"


# --------------------------------------------------------------- Phase 14A.1's reconcile mechanism, still exercised (defense in depth)


def test_reconcile_after_restore_repairs_the_leases_db_mirror_itself(tmp_path):
    """Phase 14A.1's `reconcile_after_restore()` is no longer THE
    security boundary (the security root is), but it still has real
    value: it repairs the leases.db MIRROR's own displayed state (used
    by `/readyz` and `kill_switch.status()`'s activated_at/reason
    fields) back to consistency after a stale restore, independent of
    the security root's own correctness."""
    home = str(tmp_path / "home-reconcile")
    os.makedirs(home, exist_ok=True)
    ls, ks, resolution = _setup_home(home)
    _issue_lease(home, "reconcile-1")

    godmode_dir = ls.LEASE_DIR.parent
    backup_dir = tmp_path / "backup_pre_activation"
    shutil.copytree(godmode_dir, backup_dir)

    ks.activate(reason="mirror reconciliation test")
    from orca.godmode.lease_store import ks_get_state
    assert ks_get_state()[0] == "ACTIVE"

    leases_db = ls._db_path()
    shutil.copy2(backup_dir / "leases" / "leases.db", leases_db)
    _setup_home(home)
    import orca.godmode.lease_store as ls2
    assert ls2.ks_get_state()[0] == "INACTIVE", "sanity: the MIRROR alone does read back stale"

    from orca.godmode.kill_switch_ledger import reconcile_after_restore
    summary = reconcile_after_restore()
    assert summary["action"] == "reconciled_to_ACTIVE"
    assert ls2.ks_get_state()[0] == "ACTIVE", "the mirror's own displayed state must be repaired too"


# --------------------------------------------------------------- Postgres


def _postgres_reachable() -> bool:
    try:
        import psycopg
        conn = psycopg.connect(_TEST_DSN, connect_timeout=2)
        conn.close()
        return True
    except Exception:
        return False


@pytest.mark.skipif(not _postgres_reachable(), reason="no local PostgreSQL reachable -- this test proves the fix against a real local server, not a fabricated one")
def test_postgres_mirror_restore_alone_no_longer_defeats_kill_switch(tmp_path):
    """Same invariant as the SQLite test above, real local Postgres
    authority backend -- restoring the kill_switch_state MIRROR row
    alone (the security root lives in a separate local directory, not
    in Postgres at all, unless ORNEUR_SECURITY_ROOT_DATABASE_URL is
    explicitly configured -- see test_security_root_whole_snapshot.py
    for the dedicated Postgres-security-root test)."""
    home = str(tmp_path / "home-pg")
    os.makedirs(home, exist_ok=True)
    ls, ks, resolution = _setup_home(home, postgres=True)
    lease_id = f"pg-ks-{uuid.uuid4().hex[:10]}"
    lease = _issue_lease(home, lease_id, postgres=True)

    # Reset to a known baseline first -- kill_switch_state is a single
    # persistent Postgres row shared across the whole test session
    # (unlike SQLite's fresh temp file per test).
    ks.deactivate()

    ks.activate(reason="postgres mirror restore test")
    assert ks.is_active() is True

    import psycopg
    conn = psycopg.connect(_TEST_DSN)
    cur = conn.cursor()
    cur.execute("UPDATE kill_switch_state SET state='INACTIVE', activated_at=NULL, reason=NULL WHERE id=1")
    conn.commit()
    conn.close()

    from orca.godmode.lease_store import ks_get_state
    assert ks_get_state()[0] == "INACTIVE", "sanity: the mirror alone reads back stale"
    assert ks.is_active() is True, "the security root (a separate local directory) was never touched -- state must remain ACTIVE"
    assert _try_elevated(resolution, lease.lease_id) == "DENY"


# --------------------------------------------------------------- multiprocess


def _worker_check_kill_switch(home: str, security_root_home: str, lease_id: str, result_queue, *, postgres: bool = False):
    _setup_home(home, postgres=postgres, security_root_home=security_root_home)
    from orca.godmode.contracts import CapabilityDomain
    import orca.godmode.resolution as resolution_mod
    decision = resolution_mod.resolve_and_consume_lease(
        lease_id=lease_id, tenant_id="t1", capability_domain=CapabilityDomain.CONNECTOR,
        capability="CONNECTOR_WRITE", resource_scope="conn-1", operation_scope="write", arguments={},
    )
    result_queue.put(decision.state.value)


def test_multiprocess_worker_sees_security_root_activation(tmp_path):
    """A separate real OS process, given the SAME security-root
    location, sees an activation made by the parent process
    immediately -- no propagation delay, no stale cache (spec §18-19:
    the security root is always read fresh)."""
    security_root_home = str(tmp_path / "security-root")
    home = str(tmp_path / "home-mp")
    os.makedirs(home, exist_ok=True)
    ls, ks, resolution = _setup_home(home, security_root_home=security_root_home)
    lease = _issue_lease(home, "mp-1")

    ks.activate(reason="multiprocess test")
    assert ks.is_active() is True

    ctx = multiprocessing.get_context("spawn")
    result_queue = ctx.Queue()
    worker = ctx.Process(target=_worker_check_kill_switch, args=(home, security_root_home, lease.lease_id, result_queue))
    worker.start()
    worker.join(timeout=15)
    assert worker.exitcode == 0
    assert result_queue.get(timeout=5) == "DENY", "a genuinely separate process, given the same security-root location, must see the activation"


# --------------------------------------------------------------- restart


def test_restart_activation_survives_module_reload(tmp_path):
    """Restart/reload after activation -- ACTIVE survives, no
    module-level stale-path bug in either kill_switch.py or
    security_root.py (neither holds a module-level ORCA_HOME- or
    SECURITY_ROOT_HOME-derived path constant)."""
    home = str(tmp_path / "home-restart")
    os.makedirs(home, exist_ok=True)
    _, ks, _ = _setup_home(home)
    ks.activate(reason="restart test")
    assert ks.is_active() is True

    _setup_home(home)
    import orca.godmode.kill_switch as ks2
    assert ks2.is_active() is True, "activation must survive a restart/reload"


# --------------------------------------------------------------- crash consistency (targets the security root's own transaction)


def _ks_activate_worker(home: str, security_root_home: str, checkpoint: str, signal_file: str):
    os.environ["GODMODE_TEST_CRASH_CHECKPOINT"] = checkpoint
    os.environ["GODMODE_TEST_CRASH_SIGNAL_FILE"] = signal_file
    _setup_home(home, security_root_home=security_root_home)
    import orca.godmode.kill_switch as ks
    try:
        ks.activate(reason="crash injection test")
    except Exception:
        pass


def _run_and_kill_at_checkpoint(target, args, checkpoint: str, tmp_path) -> None:
    signal_file = str(tmp_path / f"crash-signal-{checkpoint}-{time.time_ns()}")
    ctx = multiprocessing.get_context("spawn")
    p = ctx.Process(target=target, args=(*args, checkpoint, signal_file))
    p.start()
    deadline = time.time() + 15
    while time.time() < deadline and not os.path.exists(signal_file):
        time.sleep(0.02)
    assert os.path.exists(signal_file), f"child never reached checkpoint {checkpoint!r}"
    assert p.is_alive()
    p.kill()
    p.join(timeout=10)
    assert not p.is_alive()


@pytest.mark.parametrize("checkpoint", ["SECURITY_ROOT_AFTER_BEGIN_IMMEDIATE", "SECURITY_ROOT_AFTER_UPDATE_BEFORE_COMMIT", "SECURITY_ROOT_AFTER_COMMIT"])
def test_crash_during_security_root_advance_leaves_valid_linearized_state(tmp_path, checkpoint):
    """Real SIGKILL at each transaction checkpoint INSIDE
    `security_root.advance()` -- the actually security-relevant
    transaction as of Phase 14A.2 (the leases.db mirror update happens
    AFTER this, per kill_switch.py's crash-safety ordering, so a crash
    here is the meaningful case; a crash during the mirror update
    alone, with the security root already committed, is covered by
    `test_reconcile_after_restore_repairs_the_leases_db_mirror_itself`
    above -- the security root is already correct by then regardless).
    Required: after recovery, state is one valid linearized result, and
    PRAGMA integrity_check passes."""
    security_root_home = str(tmp_path / f"security-root-{checkpoint}")
    home = str(tmp_path / f"home-crash-{checkpoint}")
    os.makedirs(home, exist_ok=True)
    ls, ks, _ = _setup_home(home, security_root_home=security_root_home)
    assert ks.is_active() is False

    _run_and_kill_at_checkpoint(_ks_activate_worker, (home, security_root_home), checkpoint, tmp_path)

    _setup_home(home, security_root_home=security_root_home)
    import orca.godmode.kill_switch as ks2
    import orca.godmode.security_root as security_root
    import sqlite3
    conn = sqlite3.connect(str(security_root._db_path()))
    integrity = conn.execute("PRAGMA integrity_check").fetchone()[0]
    conn.close()
    assert integrity == "ok"

    state = ks2.is_active()
    if checkpoint == "SECURITY_ROOT_AFTER_COMMIT":
        assert state is True, "if the security-root transaction committed, ACTIVE must remain effective"
    else:
        assert state is False, "if the security-root transaction never committed, state must remain INACTIVE -- never a torn state"


# --------------------------------------------------------------- corruption (security root)


def test_corrupted_security_root_state_fails_closed(tmp_path):
    """Malformed security-root state must fail closed -- never
    inferred as INACTIVE. A garbage value in the `state` column
    (anything other than the exact string "INACTIVE") must be treated
    as active."""
    security_root_home = str(tmp_path / "security-root")
    home = str(tmp_path / "home-corrupt")
    os.makedirs(home, exist_ok=True)
    _, ks, _ = _setup_home(home, security_root_home=security_root_home)
    ks.activate(reason="setup")

    import orca.godmode.security_root as security_root
    import sqlite3
    conn = sqlite3.connect(str(security_root._db_path()))
    conn.execute("UPDATE security_root SET state = 'GARBAGE_NOT_A_REAL_STATE' WHERE id = 1")
    conn.commit()
    conn.close()

    _setup_home(home, security_root_home=security_root_home)
    import orca.godmode.kill_switch as ks2
    assert ks2.is_active() is True, "an unreadable/unexpected security-root state value must never be inferred as INACTIVE"


# --------------------------------------------------------------- store unavailable (security root)


def test_security_root_unavailable_fails_closed(tmp_path):
    """Security root unreachable (Postgres-backed security root
    pointed at an unreachable host) -> effective elevated authorization
    = DENY, never a silent allow."""
    home = str(tmp_path / "home-unavailable")
    os.makedirs(home, exist_ok=True)
    os.environ["ORCA_HOME"] = home
    os.environ["ORNEUR_HOME"] = home
    os.environ["ORNEUR_SECURITY_ROOT_DATABASE_URL"] = "postgresql://nonexistent-host-for-test:5432/nope"
    import orca.config as config_mod
    importlib.reload(config_mod)
    import orca.godmode.lease_store as ls
    importlib.reload(ls)
    import orca.godmode.kill_switch as ks
    importlib.reload(ks)
    import orca.godmode.security_root as security_root
    importlib.reload(security_root)

    epoch, state = security_root.get_epoch_and_state()
    assert state == "UNKNOWN"
    assert epoch is None
    assert ks.is_active() is True, "an unreachable security root must never be treated as kill-switch-inactive"


# --------------------------------------------------------------- lease revocation regression check


def test_lease_revocation_stale_restore_protection_still_works(tmp_path):
    """This phase's kill-switch/security-root work must not regress
    Phase 14A's already-fixed lease-revocation stale-restore
    protection (a completely separate mechanism -- revocation_ledger.py
    -- unaffected by kill_switch.py's rewrite)."""
    home = str(tmp_path / "home-lease-regression")
    os.makedirs(home, exist_ok=True)
    ls, ks, _ = _setup_home(home)
    lease = _issue_lease(home, "regress-1")

    godmode_dir = ls.LEASE_DIR.parent
    backup_dir = tmp_path / "backup"
    shutil.copytree(godmode_dir, backup_dir)

    assert ls.revoke(lease.lease_id) is True

    shutil.copy2(backup_dir / "leases" / "leases.db", ls._db_path())
    _setup_home(home)
    import orca.godmode.lease_store as ls2
    assert ls2.get(lease.lease_id).revocation_state.value == "ACTIVE", "sanity: restore reverted the row"

    from orca.godmode.revocation_ledger import reconcile_after_restore
    reconcile_after_restore()
    assert ls2.get(lease.lease_id).revocation_state.value == "REVOKED"
    assert ls2.consume_use(lease.lease_id) is False
