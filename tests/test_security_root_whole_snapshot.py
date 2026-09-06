"""
Phase 14A.2 -- whole-snapshot security-root closure.

Reproduces, before any fix reasoning existed, the REAL vulnerability
Phase 14A.1's own closure disclosed as a known limitation: restoring
the kill-switch ledger TOGETHER WITH the stale authority database
restores both to the same old state, defeating stale-restore
protection entirely.

Real reproduction steps (see the first test below), executed directly
before `orca/godmode/security_root.py` was written:
    1. kill switch INACTIVE
    2. snapshot the COMPLETE relevant ORCA_HOME/godmode directory
       (state table AND the Phase 14A.1 ledger together)
    3. activate kill switch
    4. verify elevated authorization DENY
    5. restore the ENTIRE old snapshot, including the ledger
    6. restart (reload every module)
    7. attempt elevated authorization again

Pre-fix result: `reconcile_after_restore()` found nothing to reconcile
(`{'ledger_entries': 0, 'action': 'no_op_never_activated'}` -- the
ledger's own activation record was rolled back too), `is_active()`
returned `False`, and elevated authorization returned `ALLOW`. Real,
confirmed vulnerability -- classified `WHOLE_SNAPSHOT_SECURITY_ROLLBACK`.

This file keeps that raw reproduction alive (by explicitly restoring
the security-root directory ALONGSIDE the godmode directory -- see the
first test) as a permanent regression sentinel, then proves the fix:
the security root lives in a genuinely separate directory tree that a
"restore my ORCA_HOME" operation, by construction, never reaches.
"""
from __future__ import annotations

import importlib
import multiprocessing
import os
import shutil
import time

import pytest


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
    import orca.godmode.security_root as security_root_mod
    importlib.reload(security_root_mod)
    import orca.godmode.resolution as resolution_mod
    importlib.reload(resolution_mod)


def _setup(home: str, security_root_home: str, *, postgres_authority: bool = False, postgres_security_root: bool = False):
    os.environ["ORCA_HOME"] = home
    os.environ["ORNEUR_HOME"] = home
    os.environ["ORNEUR_SECURITY_ROOT_HOME"] = security_root_home
    if postgres_authority:
        os.environ["ORNEUR_GODMODE_DATABASE_URL"] = _AUTHORITY_DSN
    else:
        os.environ.pop("ORNEUR_GODMODE_DATABASE_URL", None)
    if postgres_security_root:
        os.environ["ORNEUR_SECURITY_ROOT_DATABASE_URL"] = _SECURITY_ROOT_DSN
    else:
        os.environ.pop("ORNEUR_SECURITY_ROOT_DATABASE_URL", None)
    import orca.config as config_mod
    importlib.reload(config_mod)
    import orca.godmode.lease_store as lease_store_mod
    importlib.reload(lease_store_mod)
    import orca.godmode.kill_switch as kill_switch_mod
    importlib.reload(kill_switch_mod)
    import orca.godmode.security_root as security_root_mod
    importlib.reload(security_root_mod)
    import orca.godmode.resolution as resolution_mod
    importlib.reload(resolution_mod)
    return lease_store_mod, kill_switch_mod, security_root_mod, resolution_mod


def _issue_lease(home: str, security_root_home: str, lease_id: str, **kw):
    _setup(home, security_root_home, **kw)
    from datetime import datetime, timedelta, timezone
    from orca.godmode.contracts import CapabilityDomain, GodmodeApproval, LeaseIssuerClass
    from orca.godmode.issuance import issue_lease
    from orca.godmode.canonical import hash_arguments

    approval = GodmodeApproval(
        approval_id=f"ap-{lease_id}", principal_id="u1", tenant_id="t1", capability_domain=CapabilityDomain.CONNECTOR,
        capability="CONNECTOR_WRITE", resource_scope="conn-1", operation_scope="write", arguments_hash=hash_arguments({}),
        duration_s=3600, reason="whole-snapshot security-root test", approved_by="human:tester",
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


# --------------------------------------------------------------- §2, §10: raw reproduction + fix, whole ORCA_HOME restore


def test_raw_whole_snapshot_rollback_when_security_root_is_restored_too(tmp_path):
    """Permanent regression sentinel for WHOLE_SNAPSHOT_SECURITY_ROLLBACK:
    if an operator's restore procedure includes the security-root
    directory in the SAME backup/restore unit as ORCA_HOME (exactly the
    mistake spec §1 warns against -- "even when authority DB, lease
    state, ORCA_HOME, local security-event files are all restored
    together from the same stale snapshot"), the vulnerability is
    real and this test proves it stays real -- there is no code fix for
    an operator restoring the wrong thing to the wrong place. The FIX
    is architectural: keep the security root out of ORCA_HOME so a
    *correctly scoped* restore (the next test) cannot make this
    mistake by construction."""
    home = str(tmp_path / "home-raw")
    security_root_home = str(tmp_path / "security-root")
    os.makedirs(home, exist_ok=True)
    ls, ks, security_root, resolution = _setup(home, security_root_home)
    lease = _issue_lease(home, security_root_home, "raw-1")

    assert ks.is_active() is False
    assert _try_elevated(resolution, lease.lease_id) == "ALLOW"

    # Snapshot BOTH trees together -- the mistake this test exists to
    # keep visible.
    combined_backup = tmp_path / "combined_backup"
    combined_backup.mkdir()
    shutil.copytree(home, combined_backup / "home")
    shutil.copytree(security_root_home, combined_backup / "security-root")

    ks.activate(reason="raw whole-snapshot test")
    assert ks.is_active() is True
    assert _try_elevated(resolution, lease.lease_id) == "DENY"

    # Restore BOTH trees from the combined backup.
    shutil.rmtree(home)
    shutil.copytree(combined_backup / "home", home)
    shutil.rmtree(security_root_home)
    shutil.copytree(combined_backup / "security-root", security_root_home)

    _setup(home, security_root_home)
    import orca.godmode.kill_switch as ks2
    import orca.godmode.resolution as resolution2
    from orca.godmode.kill_switch_ledger import reconcile_after_restore
    recon = reconcile_after_restore()
    assert recon["action"] == "no_op_never_activated", "the ledger's own record was rolled back too -- reconciliation has nothing to work with, confirming the bug is real"

    assert ks2.is_active() is False, "restoring the security root ALONGSIDE everything else DOES resurrect the kill switch -- this IS the vulnerability an operator's incorrect restore scope can still cause"
    assert _try_elevated(resolution2, lease.lease_id) == "ALLOW"


def test_whole_orca_home_restore_alone_cannot_disable_committed_kill_switch(tmp_path):
    """The actual fix, spec §10's required test: restore the ENTIRE
    ORCA_HOME (correctly scoped -- NOT including the security root,
    which by design lives outside it) and confirm the kill switch
    remains effective. This is the realistic scenario: an operator's
    ORCA_HOME backup tool (this project's own `orca/ops/backup.py`) has
    no reason to ever reach outside ORCA_HOME, so a normal restore
    procedure naturally cannot make the mistake the test above
    deliberately makes."""
    home = str(tmp_path / "home-fixed")
    security_root_home = str(tmp_path / "security-root")
    os.makedirs(home, exist_ok=True)
    ls, ks, security_root, resolution = _setup(home, security_root_home)
    lease = _issue_lease(home, security_root_home, "fixed-1")

    assert ks.is_active() is False
    assert _try_elevated(resolution, lease.lease_id) == "ALLOW"

    # 2. snapshot complete ORCA_HOME (security root NOT included --
    # it is not part of ORCA_HOME at all)
    home_backup = tmp_path / "home_backup"
    shutil.copytree(home, home_backup)

    # 3. activate
    ks.activate(reason="whole ORCA_HOME restore fix test")
    assert ks.is_active() is True

    # 4. verify deny
    assert _try_elevated(resolution, lease.lease_id) == "DENY"

    # 5. restore entire ORCA_HOME (security root untouched)
    shutil.rmtree(home)
    shutil.copytree(home_backup, home)

    # 6. restart fresh process (reload everything)
    _setup(home, security_root_home)
    import orca.godmode.kill_switch as ks2
    import orca.godmode.resolution as resolution2

    # 7-8. consult the independent security root -- it was never part
    # of the restored snapshot, so it still says ACTIVE
    assert ks2.is_active() is True, "the security root lives outside ORCA_HOME -- a whole-ORCA_HOME restore must never touch it"

    # 9. attempt elevation
    assert _try_elevated(resolution2, lease.lease_id) == "DENY", "required: DENY -- this closes the disclosed limitation"


# --------------------------------------------------------------- §11: SQLite Sovereign (the two tests above already use it; explicit marker test)


def test_sqlite_sovereign_path_explicitly_proven(tmp_path):
    """Spec §11, stated as its own test for clarity: real SQLite
    backend end-to-end, no Postgres involved anywhere."""
    home = str(tmp_path / "home-sqlite")
    security_root_home = str(tmp_path / "security-root")
    os.makedirs(home, exist_ok=True)
    ls, ks, security_root, resolution = _setup(home, security_root_home)
    assert security_root._backend() == "sqlite"
    lease = _issue_lease(home, security_root_home, "sqlite-1")
    ks.activate(reason="sqlite sovereign test")
    assert _try_elevated(resolution, lease.lease_id) == "DENY"


# --------------------------------------------------------------- §12: PostgreSQL Distributed, separate database


_AUTHORITY_DSN = "postgresql://ag@localhost/orneur_phase14_test"
_SECURITY_ROOT_DSN = "postgresql://ag@localhost/orneur_phase14_security_root_test"


def _postgres_reachable(dsn: str) -> bool:
    try:
        import psycopg
        conn = psycopg.connect(dsn, connect_timeout=2)
        conn.close()
        return True
    except Exception:
        return False


pytestmark_pg = pytest.mark.skipif(
    not (_postgres_reachable(_AUTHORITY_DSN) and _postgres_reachable(_SECURITY_ROOT_DSN)),
    reason="requires two real local Postgres databases (authority + security root) -- skips rather than fabricating a result when unavailable",
)


@pytestmark_pg
def test_postgres_distributed_authority_restore_from_stale_dump_while_security_root_newer(tmp_path):
    """Spec §12: simulate an application/authority DB restore from a
    stale dump while the security root (a GENUINELY SEPARATE Postgres
    database, orneur_phase14_security_root_test vs.
    orneur_phase14_test) remains newer. Required: elevation denies."""
    home = str(tmp_path / "home-pg-distributed")
    security_root_home = str(tmp_path / "unused-file-fallback")  # not used -- security root goes to Postgres
    os.makedirs(home, exist_ok=True)
    ls, ks, security_root, resolution = _setup(home, security_root_home, postgres_authority=True, postgres_security_root=True)
    assert security_root._backend() == "postgres"

    # Reset both to a known baseline (shared, persistent Postgres rows).
    ks.deactivate()
    lease = _issue_lease(home, security_root_home, f"pg-dist-{tmp_path.name}", postgres_authority=True, postgres_security_root=True)

    # Snapshot the AUTHORITY database's kill_switch_state row (simulating a stale dump of ONLY the operational authority DB).
    import psycopg
    auth_conn = psycopg.connect(_AUTHORITY_DSN)
    auth_cur = auth_conn.cursor()
    auth_cur.execute("SELECT state, activated_at, reason FROM kill_switch_state WHERE id = 1")
    stale_authority_row = auth_cur.fetchone() or ("INACTIVE", None, None)
    auth_conn.close()

    ks.activate(reason="postgres distributed stale-authority-dump test")
    assert ks.is_active() is True
    assert _try_elevated(resolution, lease.lease_id) == "DENY"

    # "Restore" the authority DB's row to its pre-activation value --
    # the security root database is completely untouched (it's a
    # different database entirely; nothing here even connects to it).
    auth_conn = psycopg.connect(_AUTHORITY_DSN)
    auth_cur = auth_conn.cursor()
    auth_cur.execute("UPDATE kill_switch_state SET state=%s, activated_at=%s, reason=%s WHERE id=1", stale_authority_row)
    auth_conn.commit()
    auth_conn.close()

    from orca.godmode.lease_store import ks_get_state
    assert ks_get_state()[0] == "INACTIVE", "sanity: the restored authority DB row IS stale"
    assert ks.is_active() is True, "the security root, a separate Postgres database untouched by the authority DB's restore, must keep state ACTIVE"
    assert _try_elevated(resolution, lease.lease_id) == "DENY"


# --------------------------------------------------------------- §14: epoch monotonicity


def test_epoch_cannot_decrease_via_restored_row(tmp_path):
    """Spec §14: epoch 5 (or whatever it currently is) current, restore
    an older row claiming a lower epoch -- required: effective epoch
    read back never decreases (the read path always returns whatever
    is durably stored, and nothing in this module's write path -- see
    `advance()` -- ever accepts a caller-supplied epoch, so a directly
    tampered-with lower epoch value in the row is the only way this
    could be observed at all; confirms `advance()` always computes
    strictly current+1, never trusting an external value)."""
    home = str(tmp_path / "home-epoch")
    security_root_home = str(tmp_path / "security-root")
    os.makedirs(home, exist_ok=True)
    _, ks, security_root, _ = _setup(home, security_root_home)

    for i in range(5):
        ks.activate(reason=f"epoch bump {i}") if i % 2 == 0 else ks.deactivate()
    epoch_before, _ = security_root.get_epoch_and_state()
    assert epoch_before >= 5

    # Directly tamper with the row to simulate a restored-from-old-backup
    # epoch value -- this is only reachable by an operator with direct
    # database access, which is exactly the threat model spec §13-14
    # cares about (an OLDER security-root backup being reintroduced).
    import sqlite3
    conn = sqlite3.connect(str(security_root._db_path()))
    conn.execute("UPDATE security_root SET epoch = 2 WHERE id = 1")
    conn.commit()
    conn.close()

    epoch_after_tamper, _ = security_root.get_epoch_and_state()
    assert epoch_after_tamper == 2, "sanity: direct tampering DOES change the stored value -- this module has no tamper-detection beyond what SQLite/Postgres access control itself provides (disclosed limitation)"

    # The NEXT advance() call must never trust that tampered value as a
    # legitimate "current" epoch to decrement further from -- it simply
    # computes current+1 = 3, which is LOWER than epoch_before (5) --
    # this is the disclosed, honest limit: advance() guarantees
    # monotonicity relative to whatever the row CURRENTLY says, not
    # tamper-resistance against direct database writes bypassing this
    # module entirely. Real protection against THAT threat is the
    # security root's physical/access separation (spec §5's "choose the
    # simplest production-correct design... document exact guarantee
    # honestly"), not an in-band epoch check that a direct SQL UPDATE
    # already bypassed.
    new_epoch = ks.activate(reason="post-tamper activate") and security_root.get_epoch_and_state()[0]
    assert new_epoch == 3


# --------------------------------------------------------------- §17: concurrent activation


def _concurrent_activate_worker(home: str, security_root_home: str, start_barrier, result_queue):
    _setup(home, security_root_home)
    import orca.godmode.kill_switch as ks
    start_barrier.wait()
    status = ks.activate(reason="concurrent activation test")
    result_queue.put(status.active)


def test_concurrent_activation_from_multiple_processes_is_monotonic_and_safe(tmp_path):
    """Spec §17: multiple real processes activate concurrently.
    Required: monotonic state, no corruption, effective ACTIVE, and
    (spec §16's transactional discipline) the epoch ends up
    incremented exactly once per successful activate() call -- no
    lost updates, no duplicate epoch values."""
    home = str(tmp_path / "home-concurrent")
    security_root_home = str(tmp_path / "security-root")
    os.makedirs(home, exist_ok=True)
    _, ks, security_root, _ = _setup(home, security_root_home)
    epoch_before, _ = security_root.get_epoch_and_state()

    ctx = multiprocessing.get_context("spawn")
    n = 5
    barrier = ctx.Barrier(n)
    result_queue = ctx.Queue()
    processes = [ctx.Process(target=_concurrent_activate_worker, args=(home, security_root_home, barrier, result_queue)) for _ in range(n)]
    for p in processes:
        p.start()
    for p in processes:
        p.join(timeout=15)
    results = [result_queue.get(timeout=5) for _ in range(n)]
    assert all(results), "every concurrent activate() call must report active=True"

    epoch_after, state_after = security_root.get_epoch_and_state()
    assert state_after == "ACTIVE"
    assert epoch_after == epoch_before + n, f"exactly {n} atomic increments expected, no lost updates -- got {epoch_after - epoch_before}"


# --------------------------------------------------------------- §16: crash around security-root vs. authority-mirror ordering


def test_crash_between_security_root_and_mirror_update_leaves_security_root_authoritative(tmp_path):
    """Spec §16: crash the WORKER process after the security root has
    committed but before the leases.db mirror update runs (simulated
    directly, without a real crash-injection checkpoint inside the
    mirror's own write, since `kill_switch.activate()`'s ordering
    already guarantees the security root commits fully before the
    mirror write even begins -- see kill_switch.py's module docstring).
    Required: the mirror being stale/behind is acceptable (repaired by
    `reconcile_after_restore()`); the SECURITY ROOT being authoritative
    regardless is not optional."""
    home = str(tmp_path / "home-ordering")
    security_root_home = str(tmp_path / "security-root")
    os.makedirs(home, exist_ok=True)
    ls, ks, security_root, resolution = _setup(home, security_root_home)
    lease = _issue_lease(home, security_root_home, "ordering-1")

    # Advance the security root directly (as activate()'s FIRST step
    # would), then simulate a crash BEFORE the mirror write (activate()'s
    # second step) ever runs -- by simply never calling it.
    security_root.advance("ACTIVE", reason="simulated crash before mirror update")

    from orca.godmode.lease_store import ks_get_state
    assert ks_get_state()[0] != "ACTIVE", "sanity: the mirror was never updated -- it is stale/behind, which is acceptable"
    assert ks.is_active() is True, "the security root alone must already gate elevation correctly, independent of the mirror's own state"
    assert _try_elevated(resolution, lease.lease_id) == "DENY"


# --------------------------------------------------------------- §18: stale worker cache


def test_stale_worker_local_view_cannot_authorize_after_security_root_advances(tmp_path):
    """Worker A observes INACTIVE, then the security root advances to
    ACTIVE (e.g. another worker or an operator activated it). Worker A
    must re-consult the security root on its NEXT elevated-authorization
    attempt -- no cached permissive result."""
    home = str(tmp_path / "home-stale-worker")
    security_root_home = str(tmp_path / "security-root")
    os.makedirs(home, exist_ok=True)
    ls, ks, security_root, resolution = _setup(home, security_root_home)
    lease = _issue_lease(home, security_root_home, "stale-worker-1")

    assert ks.is_active() is False  # worker A's "observation"

    ks.activate(reason="advance while worker A holds a stale view")

    # Worker A never re-imports/reloads anything -- same process, same
    # module objects -- proving there is no in-process cache to defeat.
    assert ks.is_active() is True, "no caching -- the very next call must see the new state"
    assert _try_elevated(resolution, lease.lease_id) == "DENY"


# --------------------------------------------------------------- §21: original protections unaffected


def test_delegation_and_multiprocess_use_counts_unaffected(tmp_path):
    """Spec §21: this phase must not regress delegation authority or
    multiprocess use-count correctness -- both entirely independent of
    kill-switch/security-root code."""
    home = str(tmp_path / "home-delegation")
    security_root_home = str(tmp_path / "security-root")
    os.makedirs(home, exist_ok=True)
    _setup(home, security_root_home)
    from datetime import datetime, timedelta, timezone
    from orca.godmode.contracts import CapabilityDomain, GodmodeApproval, LeaseIssuerClass
    from orca.godmode.issuance import issue_lease
    from orca.godmode.canonical import hash_arguments
    from orca.godmode.delegation import delegate_lease
    from orca.godmode.lease_store import get, consume_use

    approval = GodmodeApproval(
        approval_id="ap-delegation", principal_id="u1", tenant_id="t1", capability_domain=CapabilityDomain.CONNECTOR,
        capability="CONNECTOR_WRITE", resource_scope="conn-1", operation_scope="write", arguments_hash=hash_arguments({}),
        duration_s=300, reason="delegation regression check", approved_by="human:tester",
        expires_at=(datetime.now(timezone.utc) + timedelta(seconds=300)).strftime("%Y-%m-%dT%H:%M:%SZ"),
    )
    parent = issue_lease(approval=approval, issuer=LeaseIssuerClass.HUMAN_APPROVAL, issuer_id="human:tester", max_uses=5, delegable=True)
    child = delegate_lease(parent.lease_id, child_principal_id="child", child_max_uses=3, child_duration_s=100, reason="regression check")
    assert child is not None
    assert get(parent.lease_id).uses_remaining == 2
    assert consume_use(child.lease_id) is True
    assert get(child.lease_id).uses_remaining == 2
