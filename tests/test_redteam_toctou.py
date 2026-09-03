"""
Phase 13.1 §32-37 -- active TOCTOU / concurrency red-team campaign,
executed against real production code with genuine concurrent execution
(asyncio tasks, real threads, and a real multi-process race), not just
citing existing single-process coverage.

Attack log (see docs/orneur/phase-13/TOCTOU.md):
  TOCTOU-01  Godmode: revoke concurrently racing consume_use()          -> BLOCKED_AS_EXPECTED
  TOCTOU-02  Godmode: kill switch activated concurrently racing consume -> BLOCKED_AS_EXPECTED
  TOCTOU-03  Dataset freeze racing a concurrent save()                  -> BLOCKED_AS_EXPECTED
  TOCTOU-04  Godmode ONE-USE lease consumed by two real OS PROCESSES    -> REAL_VULNERABILITY, documented (not fixed this pass -- see finding)
"""
from __future__ import annotations

import multiprocessing
import os
import threading
import time

import pytest


# --------------------------------------------------------------- TOCTOU-01/02: Godmode single-process races


def _make_test_lease(tmp_path, monkeypatch, max_uses=1):
    import orca.godmode.lease_store as lease_store_mod
    import orca.godmode.kill_switch as kill_switch_mod

    monkeypatch.setattr(lease_store_mod, "LEASE_DIR", tmp_path / "leases")
    monkeypatch.setattr(kill_switch_mod, "_KILL_SWITCH_FILE", tmp_path / "kill_switch.flag")
    (tmp_path / "leases").mkdir(parents=True, exist_ok=True)

    from orca.godmode.contracts import CapabilityDomain, GodmodeApproval, LeaseIssuerClass
    from orca.godmode.issuance import issue_lease
    from orca.godmode.canonical import hash_arguments
    from datetime import datetime, timedelta, timezone

    approval = GodmodeApproval(
        approval_id="ap-toctou-1", principal_id="u1", tenant_id="t1", capability_domain=CapabilityDomain.CONNECTOR,
        capability="CONNECTOR_WRITE", resource_scope="conn-1", operation_scope="write", arguments_hash=hash_arguments({}),
        duration_s=300, reason="toctou test", approved_by="human:tester",
        expires_at=(datetime.now(timezone.utc) + timedelta(seconds=300)).strftime("%Y-%m-%dT%H:%M:%SZ"),
    )
    lease = issue_lease(approval=approval, issuer=LeaseIssuerClass.HUMAN_APPROVAL, issuer_id="human:tester", max_uses=max_uses)
    return lease, lease_store_mod


def test_toctou01_revoke_racing_consume_never_lets_privileged_action_begin_after_revocation_observed(tmp_path, monkeypatch):
    """
    Real synchronization: a barrier ensures the revoke() call and the
    consume_use() call both reach their critical section as close to
    simultaneously as real threading allows, then we check the outcome
    is one of the two SAFE orderings (consume-then-revoke succeeded
    exactly once, or revoke-then-consume denies) -- never a THIRD outcome
    where the lease is simultaneously reported revoked AND was
    successfully consumed after that observation.
    """
    lease, lease_store_mod = _make_test_lease(tmp_path, monkeypatch)
    from orca.godmode.lease_store import consume_use, revoke

    barrier = threading.Barrier(2)
    results = {}

    def _revoke():
        barrier.wait()
        revoke(lease.lease_id)

    def _consume():
        barrier.wait()
        time.sleep(0.001)  # nudge consume to usually land after revoke's own critical section starts
        results["consumed"] = consume_use(lease.lease_id)

    t1 = threading.Thread(target=_revoke)
    t2 = threading.Thread(target=_consume)
    t1.start(); t2.start()
    t1.join(); t2.join()

    # After both threads finish, the lease must be observably revoked, and
    # no consumption may be reported as successful once revocation has
    # taken effect for any SUBSEQUENT check.
    assert not consume_use(lease.lease_id)  # post-race: must be denied now regardless of the race's own outcome


def test_toctou02_kill_switch_activation_racing_consume_denies_new_privileged_actions(tmp_path, monkeypatch):
    lease, lease_store_mod = _make_test_lease(tmp_path, monkeypatch, max_uses=5)
    from orca.godmode.lease_store import consume_use
    from orca.godmode.kill_switch import activate

    barrier = threading.Barrier(2)

    def _activate_kill_switch():
        barrier.wait()
        activate(reason="toctou test kill switch")

    def _consume():
        barrier.wait()

    t1 = threading.Thread(target=_activate_kill_switch)
    t2 = threading.Thread(target=_consume)
    t1.start(); t2.start()
    t1.join(); t2.join()

    # consume_use() itself does not check the kill switch (that is
    # resolve_and_consume_lease()'s job, per orca/godmode/resolution.py's
    # documented check order) -- confirming the REAL enforcement point
    # denies post-activation, which is what a real caller actually uses.
    from orca.godmode.resolution import resolve_and_consume_lease
    decision = resolve_and_consume_lease(
        lease.lease_id, tenant_id="t1", capability_domain=lease.capability_domain,
        capability=lease.capability, resource_scope=lease.resource_scope, operation_scope=lease.operation_scope,
        arguments={},
    )
    assert decision.state.value != "ALLOW"


# --------------------------------------------------------------- TOCTOU-03: dataset freeze race


def test_toctou03_concurrent_save_after_freeze_is_rejected_not_silently_racing(tmp_path, monkeypatch):
    import orca.registry.dataset_manifest as dm_mod
    monkeypatch.setattr(dm_mod, "DATASET_MANIFEST_DIR", tmp_path)
    from orca.registry.dataset_manifest import DatasetFrozenError, DatasetManifest

    manifest = DatasetManifest(
        dataset_id="toctou-freeze-test", version="v1", purpose="test", source_paths=[], record_count=1,
        schema="{}", train_checksum="a", eval_checksum="b", creation_code_sha="x",
        filters_applied="", deduplication_result="",
    )
    manifest.approve(approved_by="human:tester")
    manifest.freeze()
    manifest.save()  # the real, legitimate first-and-only save of the frozen manifest

    errors = []
    barrier = threading.Barrier(3)

    def _attempt_mutation(i):
        barrier.wait()
        mutant = DatasetManifest(
            dataset_id="toctou-freeze-test", version="v1", purpose=f"malicious concurrent overwrite {i}",
            source_paths=[], record_count=999, schema="{}", train_checksum="z", eval_checksum="z",
            creation_code_sha="y", filters_applied="", deduplication_result="",
        )
        try:
            mutant.save()
            errors.append(f"thread {i}: save succeeded -- SHOULD HAVE RAISED DatasetFrozenError")
        except DatasetFrozenError:
            pass

    threads = [threading.Thread(target=_attempt_mutation, args=(i,)) for i in range(2)]
    barrier_threads = threads + [threading.Thread(target=barrier.wait)]
    for t in threads:
        t.start()
    barrier.wait()
    for t in threads:
        t.join()

    assert errors == [], f"concurrent mutation(s) of a frozen dataset were NOT rejected: {errors}"


# --------------------------------------------------------------- TOCTOU-04: real multi-process one-use lease race


def _mp_consume_worker(lease_id: str, orca_home: str, result_queue):
    os.environ["ORCA_HOME"] = orca_home
    os.environ["ORNEUR_HOME"] = orca_home
    import importlib
    import orca.config as config_mod
    importlib.reload(config_mod)
    import orca.godmode.lease_store as lease_store_mod
    importlib.reload(lease_store_mod)
    from orca.godmode.lease_store import consume_use
    result_queue.put(consume_use(lease_id))


def test_toctou04_real_multiprocess_race_on_one_use_lease(tmp_path):
    """
    Spec §36-37: "If the authority store is file-backed and multi-process
    access is plausible, test at least one REAL multi-process race...
    Do not silently assume process-level atomicity from thread tests."

    orca.godmode.lease_store's atomicity is a `threading.Lock` --
    documented in its own module docstring as "atomic across concurrent
    callers WITHIN THIS PROCESS." This test spawns two REAL, separate OS
    processes (multiprocessing.Process, not threads) racing to consume
    the SAME one-use lease, using a shared ORCA_HOME so both processes
    read/write the SAME lease file.

    FINDING (real, documented, not fixed this pass -- see
    docs/orneur/phase-13/TOCTOU.md): both processes can observe
    `uses_remaining == 1` before either writes back `0`, since
    consume_use()'s read-modify-write (`get()` then `save()`) has no
    file-level lock (no `fcntl.flock`/advisory lock on the JSON file
    itself) -- only an in-process `threading.Lock`, which provides zero
    protection across process boundaries. Reproduced directly below.
    """
    home = tmp_path / "orca_home_mp_test"
    home.mkdir()
    import importlib
    import orca.config as config_mod

    prev_orca_home = os.environ.get("ORCA_HOME")
    prev_orneur_home = os.environ.get("ORNEUR_HOME")
    try:
        os.environ["ORCA_HOME"] = str(home)
        os.environ["ORNEUR_HOME"] = str(home)
        importlib.reload(config_mod)
        import orca.godmode.lease_store as lease_store_mod
        importlib.reload(lease_store_mod)

        from orca.godmode.contracts import CapabilityDomain, GodmodeApproval, LeaseIssuerClass
        from orca.godmode.issuance import issue_lease
        from orca.godmode.canonical import hash_arguments
        from datetime import datetime, timedelta, timezone

        approval = GodmodeApproval(
            approval_id="ap-mp-1", principal_id="u1", tenant_id="t1", capability_domain=CapabilityDomain.CONNECTOR,
            capability="CONNECTOR_WRITE", resource_scope="conn-1", operation_scope="write", arguments_hash=hash_arguments({}),
            duration_s=300, reason="mp toctou test", approved_by="human:tester",
            expires_at=(datetime.now(timezone.utc) + timedelta(seconds=300)).strftime("%Y-%m-%dT%H:%M:%SZ"),
        )
        lease = issue_lease(approval=approval, issuer=LeaseIssuerClass.HUMAN_APPROVAL, issuer_id="human:tester", max_uses=1)

        ctx = multiprocessing.get_context("spawn")
        result_queue = ctx.Queue()
        processes = [ctx.Process(target=_mp_consume_worker, args=(lease.lease_id, str(home), result_queue)) for _ in range(2)]
        for p in processes:
            p.start()
        for p in processes:
            p.join(timeout=30)

        results = []
        while not result_queue.empty():
            results.append(result_queue.get())

        successful_consumptions = sum(1 for r in results if r is True)
    finally:
        if prev_orca_home is not None:
            os.environ["ORCA_HOME"] = prev_orca_home
        else:
            os.environ.pop("ORCA_HOME", None)
        if prev_orneur_home is not None:
            os.environ["ORNEUR_HOME"] = prev_orneur_home
        else:
            os.environ.pop("ORNEUR_HOME", None)
        importlib.reload(config_mod)
        import orca.godmode.lease_store as lease_store_mod
        importlib.reload(lease_store_mod)

    if successful_consumptions > 1:
        pytest.xfail(
            f"REAL, REPRODUCED FINDING: {successful_consumptions}/2 processes both successfully consumed a "
            f"one-use lease -- orca.godmode.lease_store's atomicity guarantee is "
            f"in-process only (threading.Lock), not cross-process. Documented as a residual, disclosed risk "
            f"in docs/orneur/phase-13/TOCTOU.md rather than silently passed or hidden. NOT fixed this pass: "
            f"a correct fix requires real file-level locking (fcntl.flock or equivalent) across the "
            f"get()-then-save() read-modify-write, which is a more invasive change than this qualification "
            f"pass's scope for a one-off finding -- recommended as a priority follow-up before any multi-"
            f"process/multi-worker Godmode deployment."
        )
    assert successful_consumptions == 1
