"""
Phase 14A.1 -- kill-switch stale-restore security closure.

Reproduces, before any fix reasoning, the exact vulnerability the
Phase 14 report flagged as still open: restoring an authority backup
taken before a kill-switch activation silently re-enables Godmode.

Real reproduction steps (see the first test below):
    1. kill switch initially OFF
    2. backup authority state (the whole godmode directory)
    3. activate kill switch
    4. verify elevated action denies
    5. restore old pre-activation backup
    6. attempt elevated authorization again

Pre-fix result, confirmed by direct execution before
`kill_switch_ledger.py` existed: the restored kill switch read back
INACTIVE, and a subsequent elevated authorization attempt returned
ALLOW. This test file keeps that raw reproduction alive (with
reconciliation deliberately skipped) specifically so a future change
cannot silently regress the fix without a test noticing.
"""
from __future__ import annotations

import importlib
import multiprocessing
import os
import shutil
import time
import uuid

import pytest


@pytest.fixture(autouse=True)
def _restore_env_after_test():
    prev = {k: os.environ.get(k) for k in ("ORCA_HOME", "ORNEUR_HOME", "ORNEUR_GODMODE_DATABASE_URL", "GODMODE_TEST_CRASH_CHECKPOINT", "GODMODE_TEST_CRASH_SIGNAL_FILE")}
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


def _setup_home(home: str, *, postgres: bool = False):
    os.environ["ORCA_HOME"] = home
    os.environ["ORNEUR_HOME"] = home
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


# --------------------------------------------------------------- §2: raw reproduction (SQLite)


def test_raw_vulnerability_stale_restore_resurrects_disabled_kill_switch(tmp_path):
    """The exact scenario from spec §2, with reconciliation deliberately
    SKIPPED -- this is the raw, unfixed bug, kept alive as a permanent
    regression sentinel. If this test ever starts failing (i.e. the raw
    restore stops resurrecting the kill switch on its own), that's fine
    -- but it should only happen because of a deliberate, reviewed
    architecture change, never silently."""
    home = str(tmp_path / "home-raw")
    os.makedirs(home, exist_ok=True)
    ls, ks, resolution = _setup_home(home)
    # max_uses=5 (see _issue_lease) so this ONE lease, issued BEFORE the
    # backup, survives being checked multiple times across this test --
    # a lease issued AFTER the backup would not exist in the restored
    # snapshot at all, which would make step 6 below DENY for the wrong
    # reason ("lease not found") rather than proving anything about the
    # kill switch specifically.
    lease = _issue_lease(home, "raw-1")

    # 1. kill switch initially OFF
    assert ks.is_active() is False
    assert _try_elevated(resolution, lease.lease_id) == "ALLOW"

    # 2. backup authority state (the whole godmode directory) -- taken
    # AFTER consuming one use above, so the restored snapshot reflects
    # "lease exists, 4 uses remaining, kill switch off."
    godmode_dir = ls.LEASE_DIR.parent
    backup_dir = tmp_path / "backup_pre_activation"
    shutil.copytree(godmode_dir, backup_dir)

    # 3. activate kill switch
    ks.activate(reason="raw reproduction test")
    assert ks.is_active() is True

    # 4. verify elevated action denies (same lease -- kill switch is
    # checked before any lease-specific state, so it correctly denies
    # regardless of uses_remaining)
    assert _try_elevated(resolution, lease.lease_id) == "DENY"

    # 5. restore old pre-activation backup (godmode_state table only --
    # NOT the separate kill_switch_ledger.jsonl file, which lives in
    # the same directory; to isolate exactly what spec §2 describes
    # ("restore old pre-activation backup" of the AUTHORITY STATE),
    # remove only the ledger file from the restored copy first so this
    # test proves the RAW vulnerability, not a scenario where the fix's
    # own ledger happens to still be present.
    shutil.rmtree(godmode_dir)
    shutil.copytree(backup_dir, godmode_dir)
    (godmode_dir / "kill_switch_ledger.jsonl").unlink(missing_ok=True)
    _setup_home(home)
    import orca.godmode.kill_switch as ks2
    import orca.godmode.resolution as resolution2

    assert ks2.is_active() is False, "the raw restored state IS expected to read back INACTIVE -- this IS the bug"

    # 6. attempt elevated authorization again (same lease -- it exists
    # in the restored snapshot since the backup was taken after issuing
    # it, with 4 uses remaining)
    assert _try_elevated(resolution2, lease.lease_id) == "ALLOW", "without reconciliation, the stale restore resurrects Godmode -- confirms the finding is real"


# --------------------------------------------------------------- §7-8: the fix, SQLite


def test_reconcile_after_restore_keeps_kill_switch_active_sqlite(tmp_path):
    """The actual fix: after the identical stale restore, running the
    mandatory `kill_switch_ledger.reconcile_after_restore()` step
    re-derives ACTIVE from the ledger (which was NOT part of the
    restored backup -- see the raw test above for why removing it there
    isolates the raw bug) and elevated authorization remains denied."""
    home = str(tmp_path / "home-fixed")
    os.makedirs(home, exist_ok=True)
    ls, ks, resolution = _setup_home(home)
    lease = _issue_lease(home, "fixed-1")

    godmode_dir = ls.LEASE_DIR.parent
    backup_dir = tmp_path / "backup_pre_activation"
    shutil.copytree(godmode_dir, backup_dir)

    ks.activate(reason="fix verification test")
    assert ks.is_active() is True

    from orca.godmode.kill_switch_ledger import _ledger_path
    assert _ledger_path().exists(), "activate() must have recorded this event in the append-only ledger"

    # Stale restore of the STATE TABLE ONLY (leases.db) -- the ledger
    # file, a sibling in the same directory, is left untouched, exactly
    # matching the documented requirement that it live outside the
    # backup/restore unit for the state table itself.
    leases_db = ls._db_path()
    backup_db = backup_dir / "leases" / "leases.db"
    shutil.copy2(backup_db, leases_db)
    _setup_home(home)
    import orca.godmode.kill_switch as ks2
    import orca.godmode.resolution as resolution2

    assert ks2.is_active() is False, "sanity: the restored table alone DOES read back INACTIVE before reconciliation"

    from orca.godmode.kill_switch_ledger import reconcile_after_restore
    summary = reconcile_after_restore()
    assert summary["action"] == "reconciled_to_ACTIVE"

    assert ks2.is_active() is True, "reconciliation must re-apply ACTIVE"
    assert _try_elevated(resolution2, lease.lease_id) == "DENY", "after reconciliation, elevated authorization must remain denied -- no silent Godmode re-enable"


# --------------------------------------------------------------- §9: Postgres

_TEST_DSN = "postgresql://ag@localhost/orneur_phase14_test"


def _postgres_reachable() -> bool:
    try:
        import psycopg
        conn = psycopg.connect(_TEST_DSN, connect_timeout=2)
        conn.close()
        return True
    except Exception:
        return False


@pytest.mark.skipif(not _postgres_reachable(), reason="no local PostgreSQL reachable -- this test proves the fix against a real local server, not a fabricated one")
def test_reconcile_after_restore_keeps_kill_switch_active_postgres(tmp_path):
    """Same invariant, real local Postgres backend -- not a unit mock."""
    home = str(tmp_path / "home-pg")
    os.makedirs(home, exist_ok=True)
    ls, ks, resolution = _setup_home(home, postgres=True)
    lease_id = f"pg-ks-{uuid.uuid4().hex[:10]}"
    lease = _issue_lease(home, lease_id, postgres=True)

    # Unlike SQLite (a fresh tmp file per test), Postgres's
    # kill_switch_state is a single persistent row (id=1) SHARED across
    # every test run against this same database -- explicitly reset to
    # a known INACTIVE "pre-activation" snapshot first, rather than
    # trusting whatever a previous run of this test happened to leave
    # behind (a real isolation gap this test found while being written).
    ks.deactivate()
    pre_row = ("INACTIVE", None, None)

    ks.activate(reason="postgres fix verification")
    assert ks.is_active() is True

    # Stale "restore": overwrite the live row back to its pre-activation
    # value (or delete it if it never existed), simulating a restore of
    # an old Postgres dump that predates the activation -- the ledger
    # file (local, not in Postgres) is untouched.
    import psycopg
    conn = psycopg.connect(_TEST_DSN)
    cur = conn.cursor()
    if pre_row is None:
        cur.execute("DELETE FROM kill_switch_state WHERE id = 1")
    else:
        cur.execute("UPDATE kill_switch_state SET state=%s, activated_at=%s, reason=%s WHERE id=1", pre_row)
    conn.commit()
    conn.close()

    assert ks.is_active() is False, "sanity: the stale-restored Postgres row reads back INACTIVE before reconciliation"

    from orca.godmode.kill_switch_ledger import reconcile_after_restore
    summary = reconcile_after_restore()
    assert summary["action"] == "reconciled_to_ACTIVE"
    assert ks.is_active() is True
    assert _try_elevated(resolution, lease.lease_id) == "DENY"


# --------------------------------------------------------------- §10: multiprocess


def _worker_check_kill_switch(home: str, lease_id: str, result_queue, *, postgres: bool = False):
    _setup_home(home, postgres=postgres)
    from orca.godmode.contracts import CapabilityDomain
    import orca.godmode.resolution as resolution_mod
    decision = resolution_mod.resolve_and_consume_lease(
        lease_id=lease_id, tenant_id="t1", capability_domain=CapabilityDomain.CONNECTOR,
        capability="CONNECTOR_WRITE", resource_scope="conn-1", operation_scope="write", arguments={},
    )
    result_queue.put(decision.state.value)


def test_multiprocess_worker_reloading_stale_restored_state_still_denies_after_reconciliation(tmp_path):
    """Spec §10: worker A activates (in-process, simulating the
    authoritative activation); a SEPARATE real OS process (worker B)
    reloads from a stale-restored copy of the state table. Required:
    once reconciliation has run (a mandatory post-restore step per
    spec §7 -- run here in the parent before spawning worker B, exactly
    as an operator's restore procedure would), worker B -- a fresh
    process that never itself called activate() -- still cannot
    authorize an elevated action."""
    home = str(tmp_path / "home-mp")
    os.makedirs(home, exist_ok=True)
    ls, ks, resolution = _setup_home(home)
    lease = _issue_lease(home, "mp-1")

    godmode_dir = ls.LEASE_DIR.parent
    backup_dir = tmp_path / "backup_pre_activation"
    shutil.copytree(godmode_dir, backup_dir)

    ks.activate(reason="multiprocess test")
    assert ks.is_active() is True

    # Stale restore + mandatory reconciliation, in the parent process
    # (simulating the operator's restore procedure completing BEFORE
    # any worker is allowed to serve traffic again).
    leases_db = ls._db_path()
    shutil.copy2(backup_dir / "leases" / "leases.db", leases_db)
    from orca.godmode.kill_switch_ledger import reconcile_after_restore
    reconcile_after_restore()
    assert ks.is_active() is True

    ctx = multiprocessing.get_context("spawn")
    result_queue = ctx.Queue()
    worker = ctx.Process(target=_worker_check_kill_switch, args=(home, lease.lease_id, result_queue))
    worker.start()
    worker.join(timeout=15)
    assert worker.exitcode == 0
    assert result_queue.get(timeout=5) == "DENY", "worker B, a genuinely separate process, must see the reconciled ACTIVE state and deny"


# --------------------------------------------------------------- §11: restart


def test_restart_activation_survives_module_reload(tmp_path):
    """Spec §11: restart/reload after activation -- ACTIVE survives, no
    module-level stale-path bug (the exact class of bug Phase 14A found
    in the first revocation_ledger.py -- explicitly re-checked here for
    the new kill_switch_ledger.py and kill_switch.py, neither of which
    hold any module-level ORCA_HOME-derived path constant)."""
    home = str(tmp_path / "home-restart")
    os.makedirs(home, exist_ok=True)
    _, ks, _ = _setup_home(home)
    ks.activate(reason="restart test")
    assert ks.is_active() is True

    # Simulate a full process restart: reload every module involved,
    # exactly as a fresh process import would do.
    _setup_home(home)
    import orca.godmode.kill_switch as ks2
    assert ks2.is_active() is True, "activation must survive a restart/reload"


# --------------------------------------------------------------- §12: crash consistency


def _ks_activate_worker(home: str, checkpoint: str, signal_file: str):
    os.environ["GODMODE_TEST_CRASH_CHECKPOINT"] = checkpoint
    os.environ["GODMODE_TEST_CRASH_SIGNAL_FILE"] = signal_file
    _setup_home(home)
    import orca.godmode.kill_switch as ks
    try:
        ks.activate(reason="crash injection test")
    except Exception:
        pass


def _run_and_kill_at_checkpoint(target, args, home: str, checkpoint: str, tmp_path) -> None:
    signal_file = str(tmp_path / f"crash-signal-{checkpoint}-{time.time_ns()}")
    ctx = multiprocessing.get_context("spawn")
    p = ctx.Process(target=target, args=(*args, home, checkpoint, signal_file))
    p.start()
    deadline = time.time() + 15
    while time.time() < deadline and not os.path.exists(signal_file):
        time.sleep(0.02)
    assert os.path.exists(signal_file), f"child never reached checkpoint {checkpoint!r}"
    assert p.is_alive()
    p.kill()
    p.join(timeout=10)
    assert not p.is_alive()


@pytest.mark.parametrize("checkpoint", ["AFTER_BEGIN_IMMEDIATE", "AFTER_UPDATE_BEFORE_COMMIT", "AFTER_COMMIT"])
def test_crash_during_kill_switch_activation_leaves_valid_linearized_state(tmp_path, checkpoint):
    """Spec §12: real SIGKILL at each transaction checkpoint during
    kill-switch activation (reusing Phase 13.3's exact crash-injection
    mechanism). Required: after recovery, state is one valid linearized
    result (INACTIVE if pre-commit, ACTIVE if AFTER_COMMIT), and
    PRAGMA integrity_check passes from a fresh connection."""
    home = str(tmp_path / f"home-crash-{checkpoint}")
    os.makedirs(home, exist_ok=True)
    ls, ks, _ = _setup_home(home)
    assert ks.is_active() is False

    _run_and_kill_at_checkpoint(_ks_activate_worker, (), home, checkpoint, tmp_path)

    _setup_home(home)
    import orca.godmode.kill_switch as ks2
    import sqlite3
    conn = sqlite3.connect(str(ls._db_path()))
    integrity = conn.execute("PRAGMA integrity_check").fetchone()[0]
    conn.close()
    assert integrity == "ok"

    state = ks2.is_active()
    if checkpoint == "AFTER_COMMIT":
        assert state is True, "if the activation transaction committed, ACTIVE must remain effective"
    else:
        assert state is False, "if the activation transaction never committed, state must remain INACTIVE -- never a torn state"


# --------------------------------------------------------------- §18: corruption


def test_corrupted_kill_switch_state_fails_closed(tmp_path):
    """Spec §18: malformed kill-switch state must fail closed -- never
    be inferred as INACTIVE. A garbage value in the `state` column
    (anything other than the exact string "INACTIVE") must be treated
    as active, by construction of `is_active()`'s own comparison."""
    home = str(tmp_path / "home-corrupt")
    os.makedirs(home, exist_ok=True)
    ls, ks, _ = _setup_home(home)
    ks.activate(reason="setup")

    import sqlite3
    conn = sqlite3.connect(str(ls._db_path()))
    conn.execute("UPDATE kill_switch_state SET state = 'GARBAGE_NOT_A_REAL_STATE' WHERE id = 1")
    conn.commit()
    conn.close()

    _setup_home(home)
    import orca.godmode.kill_switch as ks2
    assert ks2.is_active() is True, "an unreadable/unexpected state value must never be inferred as INACTIVE"


# --------------------------------------------------------------- §19: store unavailable


def test_authority_store_unavailable_fails_closed(tmp_path):
    """Spec §19: distributed authority backend unavailable -> effective
    elevated authorization = DENY. Point ORNEUR_GODMODE_DATABASE_URL at
    an unreachable Postgres host -- ks_get_state() must return UNKNOWN,
    and is_active() must treat that as active (deny elevated actions),
    never silently fall back to allow."""
    home = str(tmp_path / "home-unavailable")
    os.makedirs(home, exist_ok=True)
    os.environ["ORCA_HOME"] = home
    os.environ["ORNEUR_HOME"] = home
    os.environ["ORNEUR_GODMODE_DATABASE_URL"] = "postgresql://nonexistent-host-for-test:5432/nope"
    import orca.config as config_mod
    importlib.reload(config_mod)
    import orca.godmode.lease_store as ls
    importlib.reload(ls)
    import orca.godmode.kill_switch as ks
    importlib.reload(ks)

    state, _, _ = ls.ks_get_state()
    assert state == "UNKNOWN"
    assert ks.is_active() is True, "an unreachable authority store must never be treated as kill-switch-inactive"


# --------------------------------------------------------------- §20: lease revocation regression check


def test_lease_revocation_stale_restore_protection_still_works(tmp_path):
    """Spec §20: this phase's kill-switch work must not regress Phase
    14A's already-fixed lease-revocation stale-restore protection."""
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
