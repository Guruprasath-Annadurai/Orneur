"""
Phase 14 §57-59, §67-68 -- real backup/restore evidence for the Godmode
authority store, including the REAL finding this phase made and fixed:

    Restoring a leases.db backup taken BEFORE a revocation occurred
    silently un-revokes that lease. Confirmed directly (see the first
    test below, which reproduces the raw bug with the ledger
    reconciliation step skipped) before the fix
    (orca.godmode.revocation_ledger) was written.

All of this runs against real local SQLite files -- genuine
backup/restore using sqlite3's own online backup API, not a mock.
"""
from __future__ import annotations

import importlib
import os
import shutil
import sqlite3

import pytest


@pytest.fixture(autouse=True)
def _restore_env_after_test():
    prev = {k: os.environ.get(k) for k in ("ORCA_HOME", "ORNEUR_HOME")}
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


def _setup_home(home: str):
    os.environ["ORCA_HOME"] = home
    os.environ["ORNEUR_HOME"] = home
    import orca.config as config_mod
    importlib.reload(config_mod)
    import orca.godmode.lease_store as lease_store_mod
    importlib.reload(lease_store_mod)
    import orca.godmode.revocation_ledger as ledger_mod
    importlib.reload(ledger_mod)
    return lease_store_mod


def _issue(home: str, max_uses: int, lease_id: str):
    ls = _setup_home(home)
    from datetime import datetime, timedelta, timezone
    from orca.godmode.contracts import CapabilityDomain, GodmodeApproval, LeaseIssuerClass
    from orca.godmode.issuance import issue_lease
    from orca.godmode.canonical import hash_arguments

    approval = GodmodeApproval(
        approval_id=f"ap-{lease_id}", principal_id="u1", tenant_id="t1", capability_domain=CapabilityDomain.CONNECTOR,
        capability="CONNECTOR_WRITE", resource_scope="conn-1", operation_scope="write", arguments_hash=hash_arguments({}),
        duration_s=3600, reason="backup/restore test", approved_by="human:tester",
        expires_at=(datetime.now(timezone.utc) + timedelta(seconds=3600)).strftime("%Y-%m-%dT%H:%M:%SZ"),
    )
    return issue_lease(approval=approval, issuer=LeaseIssuerClass.HUMAN_APPROVAL, issuer_id="human:tester", max_uses=max_uses)


def _sqlite_online_backup(live_db_path, dest_path):
    src = sqlite3.connect(str(live_db_path))
    dst = sqlite3.connect(str(dest_path))
    try:
        src.backup(dst)
    finally:
        src.close()
        dst.close()


def test_stale_backup_restore_without_reconciliation_resurrects_revoked_privilege(tmp_path):
    """Documents the REAL bug this phase found, so a future change can't
    silently regress the fix without this test noticing: a bare file-copy
    restore of a pre-revocation backup, with NO reconciliation step run,
    DOES resurrect the lease. This is not the recommended restore
    procedure (see the next test) -- it exists to prove the ledger
    reconciliation step is load-bearing, not decorative."""
    home = str(tmp_path / "home-stale-noreconcile")
    os.makedirs(home, exist_ok=True)
    lease = _issue(home, max_uses=5, lease_id="stale-1")
    ls = _setup_home(home)

    db_path = ls._db_path()
    backup_path = tmp_path / "pre_revoke_backup.db"
    _sqlite_online_backup(db_path, backup_path)

    assert ls.revoke(lease.lease_id) is True
    assert ls.get(lease.lease_id).revocation_state.value == "REVOKED"

    # Stale restore: overwrite the live DB with the pre-revocation backup.
    shutil.copy2(backup_path, db_path)
    _setup_home(home)  # fresh module state, simulating a genuinely fresh process
    import orca.godmode.lease_store as ls2

    restored = ls2.get(lease.lease_id)
    assert restored.revocation_state.value == "ACTIVE", "the raw restored row is expected to read back as ACTIVE -- this IS the bug"
    assert ls2.consume_use(lease.lease_id) is True, "without reconciliation, the stale restore resurrects the privilege -- confirms the finding is real"


def test_reconcile_after_restore_re_revokes_the_lease(tmp_path):
    """The actual fix: after the same stale restore as above, running
    the mandatory reconcile_after_restore() step (per
    docs/orneur/phase-14/BACKUP_AND_RECOVERY.md's documented restore
    procedure) re-applies the revocation from the append-only ledger --
    the ledger itself was NOT part of the leases.db backup/restore unit,
    so it survived the stale restore and still says this lease was
    revoked."""
    home = str(tmp_path / "home-stale-reconcile")
    os.makedirs(home, exist_ok=True)
    lease = _issue(home, max_uses=5, lease_id="stale-2")
    ls = _setup_home(home)

    db_path = ls._db_path()
    backup_path = tmp_path / "pre_revoke_backup.db"
    _sqlite_online_backup(db_path, backup_path)

    assert ls.revoke(lease.lease_id) is True

    from orca.godmode.revocation_ledger import _ledger_path
    assert _ledger_path().exists(), "revoke() must have recorded this revocation in the append-only ledger"

    # Stale restore of the leases DB ONLY -- the ledger file is untouched,
    # exactly matching the documented requirement that it live outside
    # the leases.db backup/restore unit.
    shutil.copy2(backup_path, db_path)
    _setup_home(home)
    import orca.godmode.lease_store as ls2

    assert ls2.get(lease.lease_id).revocation_state.value == "ACTIVE", "sanity: restore did revert the row, same as the unfixed test"

    from orca.godmode.revocation_ledger import reconcile_after_restore
    summary = reconcile_after_restore()
    assert lease.lease_id in summary["reconciled"]

    assert ls2.get(lease.lease_id).revocation_state.value == "REVOKED", "reconciliation must re-apply the revocation"
    assert ls2.consume_use(lease.lease_id) is False, "after reconciliation, the lease must remain unusable -- no privilege resurrection"


def test_reconcile_after_restore_is_a_safe_no_op_when_nothing_stale(tmp_path):
    """Running reconciliation against a store that was never restored
    from a stale backup must be a safe no-op -- it must not revoke
    leases that were never revoked."""
    home = str(tmp_path / "home-noop-reconcile")
    os.makedirs(home, exist_ok=True)
    lease = _issue(home, max_uses=3, lease_id="never-revoked")
    ls = _setup_home(home)

    from orca.godmode.revocation_ledger import reconcile_after_restore
    summary = reconcile_after_restore()
    assert summary["ledger_entries"] == 0
    assert summary["reconciled"] == []
    assert ls.get(lease.lease_id).revocation_state.value == "ACTIVE"
    assert ls.consume_use(lease.lease_id) is True
