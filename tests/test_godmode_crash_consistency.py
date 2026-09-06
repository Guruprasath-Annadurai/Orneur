"""
Phase 13.3 -- hard-crash consistency for orca.godmode.lease_store's
SQLite-backed authority store. A REAL OS process is SIGKILL'd while
provably inside an authority-store transaction, at a precisely chosen
checkpoint -- not simulated by raising a Python exception.

Mechanism (spec §3-4): `orca.godmode.lease_store._test_checkpoint()` is a
test-only hook, inert unless `GODMODE_TEST_CRASH_CHECKPOINT` is set to
the exact checkpoint name -- never set in production. When active, the
child process writes a "ready" signal file the instant it reaches that
checkpoint, then blocks for up to 30s (far longer than needed), giving
the parent test a wide, reliable window to send SIGKILL before the child
can proceed. SIGKILL is used throughout (`multiprocessing.Process.kill()`,
available and effective on this macOS/POSIX environment -- SIGKILL
cannot be caught, blocked, or ignored, so this is the strongest real
process-termination mechanism available, distinct from SIGTERM which a
process could in principle intercept).
"""
from __future__ import annotations

import multiprocessing
import os
import sqlite3
import time
from datetime import datetime, timedelta, timezone

import pytest


def _setup_shared_home(home: str) -> None:
    os.environ["ORCA_HOME"] = home
    os.environ["ORNEUR_HOME"] = home
    import importlib
    import orca.config as config_mod
    importlib.reload(config_mod)
    import orca.godmode.lease_store as lease_store_mod
    importlib.reload(lease_store_mod)


@pytest.fixture(autouse=True)
def _restore_env_after_test():
    prev_home = os.environ.get("ORCA_HOME")
    prev_orneur_home = os.environ.get("ORNEUR_HOME")
    prev_checkpoint = os.environ.get("GODMODE_TEST_CRASH_CHECKPOINT")
    prev_signal_file = os.environ.get("GODMODE_TEST_CRASH_SIGNAL_FILE")
    yield
    for key, prev in [
        ("ORCA_HOME", prev_home), ("ORNEUR_HOME", prev_orneur_home),
        ("GODMODE_TEST_CRASH_CHECKPOINT", prev_checkpoint), ("GODMODE_TEST_CRASH_SIGNAL_FILE", prev_signal_file),
    ]:
        if prev is not None:
            os.environ[key] = prev
        else:
            os.environ.pop(key, None)
    import importlib
    import orca.config as config_mod
    importlib.reload(config_mod)
    import orca.godmode.lease_store as lease_store_mod
    importlib.reload(lease_store_mod)


def _issue_lease(home: str, max_uses: int, lease_id: str, delegable: bool = False, duration_s: float = 300):
    _setup_shared_home(home)
    from orca.godmode.contracts import CapabilityDomain, GodmodeApproval, LeaseIssuerClass
    from orca.godmode.issuance import issue_lease
    from orca.godmode.canonical import hash_arguments
    approval = GodmodeApproval(
        approval_id=f"ap-{lease_id}", principal_id="u1", tenant_id="t1", capability_domain=CapabilityDomain.CONNECTOR,
        capability="CONNECTOR_WRITE", resource_scope="conn-1", operation_scope="write", arguments_hash=hash_arguments({}),
        duration_s=duration_s, reason="crash consistency test", approved_by="human:tester",
        expires_at=(datetime.now(timezone.utc) + timedelta(seconds=duration_s)).strftime("%Y-%m-%dT%H:%M:%SZ"),
    )
    return issue_lease(approval=approval, issuer=LeaseIssuerClass.HUMAN_APPROVAL, issuer_id="human:tester", max_uses=max_uses, delegable=delegable)


def _consume_worker_for_crash(lease_id: str, home: str, checkpoint: str, signal_file: str):
    os.environ["GODMODE_TEST_CRASH_CHECKPOINT"] = checkpoint
    os.environ["GODMODE_TEST_CRASH_SIGNAL_FILE"] = signal_file
    _setup_shared_home(home)
    from orca.godmode.lease_store import consume_use
    consume_use(lease_id)  # never returns under test -- killed while blocked at the checkpoint


def _revoke_worker_for_crash(lease_id: str, home: str, checkpoint: str, signal_file: str):
    os.environ["GODMODE_TEST_CRASH_CHECKPOINT"] = checkpoint
    os.environ["GODMODE_TEST_CRASH_SIGNAL_FILE"] = signal_file
    _setup_shared_home(home)
    from orca.godmode.lease_store import revoke
    revoke(lease_id)


def _delegate_worker_for_crash(parent_lease_id: str, child_max_uses: int, home: str, checkpoint: str, signal_file: str):
    os.environ["GODMODE_TEST_CRASH_CHECKPOINT"] = checkpoint
    os.environ["GODMODE_TEST_CRASH_SIGNAL_FILE"] = signal_file
    _setup_shared_home(home)
    from orca.godmode.delegation import delegate_lease
    try:
        delegate_lease(parent_lease_id, child_principal_id="crash-child", child_max_uses=child_max_uses, child_duration_s=100, reason="crash test")
    except Exception:
        pass  # the delegation itself completing/failing is irrelevant -- we kill before it can return


def _run_and_kill_at_checkpoint(target, args_without_home_checkpoint_signal, home: str, checkpoint: str, tmp_path) -> None:
    """Spawns `target` with (*args, home, checkpoint, signal_file), waits
    for the real readiness signal file, then SIGKILLs the child. Returns
    once the child is confirmed dead."""
    signal_file = str(tmp_path / f"crash-signal-{checkpoint}-{time.time_ns()}")
    ctx = multiprocessing.get_context("spawn")
    p = ctx.Process(target=target, args=(*args_without_home_checkpoint_signal, home, checkpoint, signal_file))
    p.start()

    deadline = time.time() + 15
    while time.time() < deadline:
        if os.path.exists(signal_file):
            break
        time.sleep(0.02)
    else:
        p.kill()
        p.join(timeout=5)
        raise AssertionError(f"child process never reached checkpoint {checkpoint!r} within timeout -- signal file was never created")

    assert p.is_alive(), "child died on its own before we could SIGKILL it at the intended checkpoint"
    p.kill()  # SIGKILL on POSIX -- cannot be caught, blocked, or ignored
    p.join(timeout=10)
    assert not p.is_alive(), "child process did not die after SIGKILL"


def _integrity_check_from_fresh_process(home: str) -> str:
    """Re-opens the SQLite store from a genuinely NEW connection (spec
    §9: 'do not rely only on the process that performed the test') and
    runs PRAGMA integrity_check."""
    _setup_shared_home(home)
    from orca.godmode.lease_store import _db_path
    conn = sqlite3.connect(str(_db_path()))
    try:
        result = conn.execute("PRAGMA integrity_check").fetchone()[0]
    finally:
        conn.close()
    return result


# --------------------------------------------------------------- §5: crash before commit


@pytest.mark.parametrize("checkpoint", ["AFTER_BEGIN_IMMEDIATE", "AFTER_RECORD_READ", "AFTER_MUTABLE_VALIDATION", "AFTER_UPDATE_BEFORE_COMMIT"])
def test_crash_before_commit_never_creates_extra_or_negative_authority(tmp_path, checkpoint):
    """
    Spec §5: kill a real process while it is provably INSIDE a
    consume_use() transaction, at each pre-commit checkpoint in turn.
    Required: uses_remaining is EITHER still 1 (rolled back) or 0
    (committed) -- NEVER negative, NEVER resurrected above 1, and the
    TOTAL number of successful consumptions across the killed attempt +
    any subsequent fresh attempt never exceeds max_uses=1.
    """
    home = str(tmp_path / f"home-{checkpoint}")
    os.makedirs(home, exist_ok=True)
    lease = _issue_lease(home, max_uses=1, lease_id=f"precommit-{checkpoint}")

    _run_and_kill_at_checkpoint(_consume_worker_for_crash, (lease.lease_id,), home, checkpoint, tmp_path)

    assert _integrity_check_from_fresh_process(home) == "ok"

    _setup_shared_home(home)
    from orca.godmode.lease_store import get, consume_use
    recovered = get(lease.lease_id)
    assert recovered is not None, "lease record must survive a mid-transaction crash, not disappear"
    assert recovered.uses_remaining in (0, 1), f"checkpoint {checkpoint}: uses_remaining={recovered.uses_remaining}, must be 0 or 1"
    assert recovered.uses_remaining >= 0

    # A fresh consume attempt after recovery: if the crashed transaction
    # had already committed (rare for early checkpoints, expected for
    # AFTER_UPDATE_BEFORE_COMMIT depending on exact timing), this must
    # DENY; if it rolled back, this must SUCCEED exactly once.
    second_attempt_result = consume_use(lease.lease_id)
    final = get(lease.lease_id)
    total_successful_consumptions = (1 if recovered.uses_remaining == 0 else 0) + (1 if second_attempt_result else 0)
    assert total_successful_consumptions <= 1, (
        f"checkpoint {checkpoint}: total successful consumptions across crash+recovery = {total_successful_consumptions}, "
        f"must never exceed max_uses=1"
    )
    assert final.uses_remaining == 0
    assert final.uses_remaining >= 0


# --------------------------------------------------------------- §6: crash after commit


def test_crash_after_commit_does_not_resurrect_or_allow_blind_retry_of_the_privileged_action(tmp_path):
    """
    Spec §6: the child commits the consume, then is killed at
    AFTER_COMMIT (before it could return a result to any caller, and
    before any audit/log completion that might have followed). The
    commit is already durable -- this is exactly the "outcome unknown to
    the caller, but NOT unknown to the store" case. Required:
    uses_remaining=0, and a further consume attempt DENIES -- the
    store's own atomicity means blindly retrying the LEASE CHECK is
    always safe (it will correctly deny), which is precisely why no
    special OUTCOME_UNKNOWN abstraction is needed here (spec §12): the
    real discipline this enforces is that a CALLER must not re-execute
    the underlying PRIVILEGED ACTION just because it didn't observe a
    response -- that policy question lives above this module, and this
    module's own contract already makes "check again" safe by construction.
    """
    home = str(tmp_path / "home-postcommit")
    os.makedirs(home, exist_ok=True)
    lease = _issue_lease(home, max_uses=1, lease_id="postcommit-1")

    _run_and_kill_at_checkpoint(_consume_worker_for_crash, (lease.lease_id,), home, "AFTER_COMMIT", tmp_path)

    assert _integrity_check_from_fresh_process(home) == "ok"

    _setup_shared_home(home)
    from orca.godmode.lease_store import get, consume_use
    recovered = get(lease.lease_id)
    assert recovered.uses_remaining == 0, "the commit at AFTER_COMMIT is already durable -- must be observed as consumed"
    assert not consume_use(lease.lease_id), "a lease already committed-consumed must deny any further attempt, crash or not"


# --------------------------------------------------------------- §7: crash during revocation


@pytest.mark.parametrize("checkpoint", ["AFTER_BEGIN_IMMEDIATE", "AFTER_UPDATE_BEFORE_COMMIT", "AFTER_COMMIT"])
def test_crash_during_revocation_leaves_a_valid_linearized_state(tmp_path, checkpoint):
    """Spec §7: no malformed hybrid state after a crash mid-revocation --
    the lease is EITHER still ACTIVE (rolled back) or REVOKED (committed),
    never anything else, and if REVOKED, future consumes must deny."""
    home = str(tmp_path / f"home-revoke-crash-{checkpoint}")
    os.makedirs(home, exist_ok=True)
    lease = _issue_lease(home, max_uses=5, lease_id=f"revoke-crash-{checkpoint}")

    _run_and_kill_at_checkpoint(_revoke_worker_for_crash, (lease.lease_id,), home, checkpoint, tmp_path)

    assert _integrity_check_from_fresh_process(home) == "ok"

    _setup_shared_home(home)
    from orca.godmode.lease_store import get, consume_use
    from orca.godmode.contracts import LeaseRevocationState
    recovered = get(lease.lease_id)
    assert recovered is not None
    assert recovered.revocation_state in (LeaseRevocationState.ACTIVE, LeaseRevocationState.REVOKED)
    if recovered.revocation_state == LeaseRevocationState.REVOKED:
        assert not consume_use(lease.lease_id), "a committed-REVOKED lease must deny consumption after recovery"


# --------------------------------------------------------------- §8: crash during delegation reservation


@pytest.mark.parametrize("checkpoint", ["AFTER_BEGIN_IMMEDIATE", "AFTER_UPDATE_BEFORE_COMMIT", "AFTER_COMMIT"])
def test_crash_during_delegation_reservation_never_duplicates_authority(tmp_path, checkpoint):
    """Spec §8: parent max_uses=5, child process begins reserve_uses(3)
    (via the real delegate_lease() path), killed around pre/post-commit
    boundaries. After restart, remaining parent uses must be EITHER 5
    (rolled back) or 2 (committed) -- never any other value, never
    duplicated authority."""
    home = str(tmp_path / f"home-delegation-crash-{checkpoint}")
    os.makedirs(home, exist_ok=True)
    parent = _issue_lease(home, max_uses=5, lease_id=f"delegation-crash-parent-{checkpoint}", delegable=True)

    _run_and_kill_at_checkpoint(_delegate_worker_for_crash, (parent.lease_id, 3), home, checkpoint, tmp_path)

    assert _integrity_check_from_fresh_process(home) == "ok"

    _setup_shared_home(home)
    from orca.godmode.lease_store import get
    recovered = get(parent.lease_id)
    assert recovered is not None
    assert recovered.uses_remaining in (5, 2), f"checkpoint {checkpoint}: parent uses_remaining={recovered.uses_remaining}, must be 5 (rolled back) or 2 (committed 5-3)"
    assert recovered.uses_remaining >= 0
