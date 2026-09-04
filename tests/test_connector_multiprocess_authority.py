"""
Phase 13.3 §13-19 -- connector-specific multiprocess authority E2E.
Uses Phase 9's deterministic FAKE_TEST_PROVIDER (no real SaaS, no
network) through the REAL connector elevation path
(`orca.godmode.connector_elevation.evaluate_connector_policy_with_elevation`),
not direct `orca.godmode.lease_store` calls -- every worker below goes
through the exact same authorization boundary a real connector write
caller would.
"""
from __future__ import annotations

import multiprocessing
import os
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
    import orca.godmode.kill_switch as kill_switch_mod
    importlib.reload(kill_switch_mod)
    import orca.godmode.resolution as resolution_mod
    importlib.reload(resolution_mod)


@pytest.fixture(autouse=True)
def _restore_env_after_test():
    prev_home = os.environ.get("ORCA_HOME")
    prev_orneur_home = os.environ.get("ORNEUR_HOME")
    yield
    for key, prev in [("ORCA_HOME", prev_home), ("ORNEUR_HOME", prev_orneur_home)]:
        if prev is not None:
            os.environ[key] = prev
        else:
            os.environ.pop(key, None)
    import importlib
    import orca.config as config_mod
    importlib.reload(config_mod)
    import orca.godmode.lease_store as lease_store_mod
    importlib.reload(lease_store_mod)
    import orca.godmode.kill_switch as kill_switch_mod
    importlib.reload(kill_switch_mod)
    import orca.godmode.resolution as resolution_mod
    importlib.reload(resolution_mod)


def _issue_connector_lease(home: str, lease_id: str, resource_scope: str, arguments: dict, tenant_id: str = "org-1", max_uses: int = 1):
    _setup_shared_home(home)
    from orca.godmode.contracts import CapabilityDomain, GodmodeApproval, LeaseIssuerClass
    from orca.godmode.issuance import issue_lease
    from orca.godmode.canonical import hash_arguments
    approval = GodmodeApproval(
        approval_id=f"ap-{lease_id}", principal_id="u1", tenant_id=tenant_id, capability_domain=CapabilityDomain.CONNECTOR,
        capability="CONNECTOR_WRITE", resource_scope=resource_scope, operation_scope="close", arguments_hash=hash_arguments(arguments),
        duration_s=300, reason="connector multiprocess test", approved_by="human:tester",
        expires_at=(datetime.now(timezone.utc) + timedelta(seconds=300)).strftime("%Y-%m-%dT%H:%M:%SZ"),
    )
    return issue_lease(approval=approval, issuer=LeaseIssuerClass.HUMAN_APPROVAL, issuer_id="human:tester", max_uses=max_uses)


def _connector_write_worker(lease_id: str, home: str, resource: str, arguments: dict, tenant_id: str, marker_dir: str, start_barrier, result_queue):
    """The REAL caller path: evaluate_connector_policy_with_elevation()
    first (the actual authorization boundary), and ONLY if it returns
    ALLOW does this worker cross into fake_write() -- mirroring exactly
    how a real connector-write tool implementation is structured. A
    marker file is created ONLY on the ALLOW branch, immediately before
    the write, so cross-process evidence of "which process actually
    crossed the authorization boundary" survives independently of each
    process's own in-memory FakeProviderState (which cannot be shared
    across processes) -- this is what proves the finding is about
    authorization, not provider-side idempotency (spec §15)."""
    _setup_shared_home(home)
    from orca.connectors.contracts import ConnectorCapabilityKind, ConnectorIdentity, ConnectorInstance, ConnectorScope, ConnectorType, ConnectorWriteRequest
    from orca.connectors.fake_provider import FakeProviderState, fake_write
    from orca.godmode.connector_elevation import evaluate_connector_policy_with_elevation

    instance = ConnectorInstance(
        connector_instance_id="fixed-ticketing-instance", connector_type=ConnectorType.TICKETING, tenant_id="org-1", owner_principal_id="u1",
        read_write_mode="READ_ONLY", enabled_capabilities=frozenset({ConnectorCapabilityKind.CONNECTOR_READ}),
        scope=ConnectorScope(resource_path="ticket/42"),
    )
    identity = ConnectorIdentity(tenant_id=tenant_id, principal_id="u1")

    start_barrier.wait()
    decision = evaluate_connector_policy_with_elevation(
        identity=identity, instance=instance, requested_capability=ConnectorCapabilityKind.CONNECTOR_WRITE,
        resource=resource, operation="close", lease_id=lease_id, arguments=arguments,
    )
    if decision.state.value != "ALLOW":
        result_queue.put((os.getpid(), "DENY", None))
        return

    marker_path = os.path.join(marker_dir, f"write-{os.getpid()}.marker")
    with open(marker_path, "w") as f:
        f.write("crossed authorization boundary")

    state = FakeProviderState()
    result = fake_write(identity, instance, ConnectorWriteRequest(identity=identity, connector_instance_id=instance.connector_instance_id, arguments=arguments), state)
    result_queue.put((os.getpid(), "ALLOW", result.status.value))


def _run_connector_race(home: str, lease_id: str, resource: str, arguments: dict, marker_dir: str, n_processes: int, tenant_ids: list[str] | None = None) -> list[tuple]:
    ctx = multiprocessing.get_context("spawn")
    barrier = ctx.Barrier(n_processes)
    result_queue = ctx.Queue()
    tenants = tenant_ids or ["org-1"] * n_processes
    processes = [
        ctx.Process(target=_connector_write_worker, args=(lease_id, home, resource, arguments, tenants[i], marker_dir, barrier, result_queue))
        for i in range(n_processes)
    ]
    for p in processes:
        p.start()
    for p in processes:
        p.join(timeout=30)
    results = []
    while not result_queue.empty():
        results.append(result_queue.get())
    return results


# --------------------------------------------------------------- §13-15: core connector multiprocess E2E


def test_connector_multiprocess_exactly_one_reaches_privileged_write(tmp_path):
    """
    Spec §13-15: one exact connector elevated write, one CapabilityLease
    (max_uses=1), two independent worker processes, synchronized
    concurrent start, both going through the REAL connector elevation
    path (not direct lease_store calls). Required: exactly one process
    reaches connector privileged write execution; the other is denied
    because the lease is exhausted; uses_remaining=0; NOT because
    provider idempotency suppressed a second write (each process has its
    own independent FakeProviderState -- there is no shared idempotency
    cache between them at all, so a double-write would be fully visible
    if authorization had failed to gate it).
    """
    home = str(tmp_path / "home-connector-mp")
    os.makedirs(home, exist_ok=True)
    marker_dir = str(tmp_path / "markers")
    os.makedirs(marker_dir, exist_ok=True)
    arguments = {"text": "closed"}
    resource = "ticket/42"

    # resource_scope must match _connector_write_worker's fixed
    # connector_instance_id ("fixed-ticketing-instance") -- both the lease
    # and every worker's ConnectorInstance use this same explicit,
    # non-random id so the scope genuinely matches across processes.
    lease = _issue_connector_lease(home, "connector-mp-1", resource_scope=f"fixed-ticketing-instance:{resource}", arguments=arguments)

    results = _run_connector_race(home, lease.lease_id, resource, arguments, marker_dir, n_processes=2)

    allows = [r for r in results if r[1] == "ALLOW"]
    denies = [r for r in results if r[1] == "DENY"]
    assert len(allows) == 1, f"expected exactly 1 ALLOW, got {len(allows)}: {results}"
    assert len(denies) == 1, f"expected exactly 1 DENY, got {len(denies)}: {results}"
    assert allows[0][2] == "SUCCESS"

    marker_files = os.listdir(marker_dir)
    assert len(marker_files) == 1, f"expected exactly 1 process to have crossed the authorization boundary (1 marker file), found {len(marker_files)}: {marker_files}"

    _setup_shared_home(home)
    from orca.godmode.lease_store import get
    assert get(lease.lease_id).uses_remaining == 0


# --------------------------------------------------------------- §16: wrong-action control


def test_connector_wrong_action_process_denies_without_consuming_use(tmp_path):
    """Spec §16: one process attempts the APPROVED connector arguments,
    the other attempts DIFFERENT arguments against the same lease.
    Required: the wrong-action process is denied WITHOUT consuming a use
    (Phase 10.1 exact-action binding); the correct-action process may
    still consume exactly once, regardless of which process runs first
    (resolve_and_consume_lease's own pre-check-then-atomic-consume design
    already guarantees a failed match never burns a use)."""
    home = str(tmp_path / "home-connector-wrong-action")
    os.makedirs(home, exist_ok=True)
    marker_dir = str(tmp_path / "markers-wrong-action")
    os.makedirs(marker_dir, exist_ok=True)
    approved_arguments = {"text": "closed"}
    wrong_arguments = {"text": "deleted"}
    resource = "ticket/42"

    lease = _issue_connector_lease(home, "connector-wrong-action-1", resource_scope=f"fixed-ticketing-instance:{resource}", arguments=approved_arguments, max_uses=1)

    # Run sequentially (not racing) so the outcome is deterministic and
    # attributable: the wrong-action attempt first, proving it does NOT
    # consume the use the correct attempt still needs.
    ctx = multiprocessing.get_context("spawn")
    barrier = ctx.Barrier(1)
    result_queue = ctx.Queue()
    wrong_worker = ctx.Process(target=_connector_write_worker, args=(lease.lease_id, home, resource, wrong_arguments, "org-1", marker_dir, barrier, result_queue))
    wrong_worker.start()
    wrong_worker.join(timeout=30)
    wrong_result = result_queue.get()
    assert wrong_result[1] == "DENY", f"wrong-action attempt should be denied, got {wrong_result}"

    _setup_shared_home(home)
    from orca.godmode.lease_store import get
    assert get(lease.lease_id).uses_remaining == 1, "a denied (wrong-argument) attempt must NOT consume a use"

    barrier2 = ctx.Barrier(1)
    correct_worker = ctx.Process(target=_connector_write_worker, args=(lease.lease_id, home, resource, approved_arguments, "org-1", marker_dir, barrier2, result_queue))
    correct_worker.start()
    correct_worker.join(timeout=30)
    correct_result = result_queue.get()
    assert correct_result[1] == "ALLOW", f"correct-action attempt should succeed, got {correct_result}"

    assert get(lease.lease_id).uses_remaining == 0


# --------------------------------------------------------------- §17: wrong-tenant control


def test_connector_wrong_tenant_process_denies_without_consuming_use(tmp_path):
    """Spec §17: same lease, one process uses the WRONG tenant. Required:
    wrong-tenant attempt denied and does not consume a use; correct
    tenant can still execute once."""
    home = str(tmp_path / "home-connector-wrong-tenant")
    os.makedirs(home, exist_ok=True)
    marker_dir = str(tmp_path / "markers-wrong-tenant")
    os.makedirs(marker_dir, exist_ok=True)
    arguments = {"text": "closed"}
    resource = "ticket/42"

    lease = _issue_connector_lease(home, "connector-wrong-tenant-1", resource_scope=f"fixed-ticketing-instance:{resource}", arguments=arguments, tenant_id="org-1", max_uses=1)

    ctx = multiprocessing.get_context("spawn")
    barrier = ctx.Barrier(1)
    result_queue = ctx.Queue()
    wrong_tenant_worker = ctx.Process(target=_connector_write_worker, args=(lease.lease_id, home, resource, arguments, "org-WRONG-TENANT", marker_dir, barrier, result_queue))
    wrong_tenant_worker.start()
    wrong_tenant_worker.join(timeout=30)
    wrong_result = result_queue.get()
    assert wrong_result[1] == "DENY", f"wrong-tenant attempt should be denied, got {wrong_result}"

    _setup_shared_home(home)
    from orca.godmode.lease_store import get
    assert get(lease.lease_id).uses_remaining == 1, "a denied (wrong-tenant) attempt must NOT consume a use"

    barrier2 = ctx.Barrier(1)
    correct_worker = ctx.Process(target=_connector_write_worker, args=(lease.lease_id, home, resource, arguments, "org-1", marker_dir, barrier2, result_queue))
    correct_worker.start()
    correct_worker.join(timeout=30)
    correct_result = result_queue.get()
    assert correct_result[1] == "ALLOW", f"correct-tenant attempt should succeed, got {correct_result}"
    assert get(lease.lease_id).uses_remaining == 0


# --------------------------------------------------------------- §18: connector revocation race


def _revoke_worker_connector(lease_id: str, home: str, start_barrier, result_queue):
    _setup_shared_home(home)
    from orca.godmode.lease_store import revoke
    start_barrier.wait()
    result_queue.put(("revoke", revoke(lease_id)))


def test_connector_revocation_race_no_write_after_committed_revocation(tmp_path):
    """Spec §18: connector worker races a parent revoking the SAME
    lease. Required: post-race, the lease is durably revoked and any
    FURTHER connector write attempt is denied -- reuses the same
    real-barrier synchronization pattern already established in
    tests/test_godmode_distributed_atomicity.py's revocation race test,
    applied here through the connector elevation path specifically."""
    home = str(tmp_path / "home-connector-revoke-race")
    os.makedirs(home, exist_ok=True)
    marker_dir = str(tmp_path / "markers-revoke-race")
    os.makedirs(marker_dir, exist_ok=True)
    arguments = {"text": "closed"}
    resource = "ticket/42"

    lease = _issue_connector_lease(home, "connector-revoke-race-1", resource_scope=f"fixed-ticketing-instance:{resource}", arguments=arguments, max_uses=5)

    ctx = multiprocessing.get_context("spawn")
    barrier = ctx.Barrier(2)
    result_queue = ctx.Queue()
    p1 = ctx.Process(target=_connector_write_worker, args=(lease.lease_id, home, resource, arguments, "org-1", marker_dir, barrier, result_queue))
    p2 = ctx.Process(target=_revoke_worker_connector, args=(lease.lease_id, home, barrier, result_queue))
    p1.start(); p2.start()
    p1.join(timeout=30); p2.join(timeout=30)

    # Regardless of which order the race resolved in, the post-race
    # durable state must be revoked, and any FURTHER attempt must deny.
    _setup_shared_home(home)
    from orca.godmode.lease_store import is_revoked
    assert is_revoked(lease.lease_id)

    barrier2 = ctx.Barrier(1)
    result_queue2 = ctx.Queue()
    followup_worker = ctx.Process(target=_connector_write_worker, args=(lease.lease_id, home, resource, arguments, "org-1", marker_dir, barrier2, result_queue2))
    followup_worker.start()
    followup_worker.join(timeout=30)
    followup_result = result_queue2.get()
    assert followup_result[1] == "DENY", f"a connector write attempted after committed revocation must be denied, got {followup_result}"
