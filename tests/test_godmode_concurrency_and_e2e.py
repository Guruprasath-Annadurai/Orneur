"""
Phase 10 spec §36 (concurrent one-use lease race), §60-61 (connector and
filesystem Godmode end-to-end), §13-14 (expiration/revocation live
checks before every action, not just at session creation).
"""
from __future__ import annotations

import threading
import time

from orca.connectors.contracts import (
    ConnectorCapabilityKind,
    ConnectorIdentity,
    ConnectorInstance,
    ConnectorReadRequest,
    ConnectorResult,
    ConnectorType,
    ConnectorWriteRequest,
    OutcomeStatus,
)
from orca.godmode.connector_elevation import evaluate_connector_policy_with_elevation
from orca.godmode.contracts import CapabilityDomain, ElevatedCapabilityRequest, LeaseIssuerClass
from orca.godmode.file_elevation import elevated_write_file
from orca.godmode.issuance import issue_lease, make_approval
from orca.godmode.lease_store import consume_use, get


def _issue(**overrides):
    defaults = dict(capability_domain=CapabilityDomain.FILE, capability="FILE_WRITE", resource_scope="/x", operation_scope="write", tenant_id="org-1")
    defaults.update(overrides)
    req = ElevatedCapabilityRequest(principal_id="u1", reason="test", **defaults)
    approval = make_approval(request=req, approved_by="human-1", duration_s=120)
    return issue_lease(approval=approval, issuer=LeaseIssuerClass.HUMAN_APPROVAL, issuer_id="human-1", max_uses=1)


def test_concurrent_actions_racing_a_one_use_lease_only_one_succeeds():
    """spec §36: no TOCTOU over lease consumption."""
    lease = _issue()
    results = []
    barrier = threading.Barrier(8)

    def _attempt():
        barrier.wait()
        results.append(consume_use(lease.lease_id))

    threads = [threading.Thread(target=_attempt) for _ in range(8)]
    for t in threads:
        t.start()
    for t in threads:
        t.join()

    assert results.count(True) == 1
    assert results.count(False) == 7
    assert get(lease.lease_id).uses_remaining == 0


def test_expiry_checked_before_every_action_not_only_at_session_creation():
    """spec §13: a lease valid at issuance but expired by the time of a
    LATER action must be denied on that later action, not just checked
    once up front."""
    short = _issue(resource_scope="/workspace/project-x")
    # forcibly expire by re-signing with a past expiry (simulates "already
    # expired by the time of a second action")
    from orca.godmode.contracts import now_iso
    from orca.godmode.integrity import apply_signature
    from orca.godmode.lease_store import save
    short.expires_at = "2020-01-01T00:00:00Z"
    apply_signature(short)
    save(short)

    from orca.godmode.resolution import resolve_lease
    first_check = resolve_lease(short.lease_id, tenant_id="org-1", capability_domain=CapabilityDomain.FILE, capability="FILE_WRITE", resource_scope="/workspace/project-x", operation_scope="write", arguments={})
    assert first_check.state.value == "DENY"
    assert not first_check.expiry_ok


def test_connector_godmode_end_to_end():
    """spec §60: normal write denied -> approved narrow elevated lease ->
    exact write allowed -> different resource denied -> lease expires ->
    next write denied. Uses Phase 9's fake provider, no real SaaS creds."""
    from orca.connectors.fake_provider import FakeProviderState, fake_write

    instance = ConnectorInstance(
        connector_type=ConnectorType.TICKETING, tenant_id="org-1", owner_principal_id="u1",
        read_write_mode="READ_ONLY", enabled_capabilities=frozenset({ConnectorCapabilityKind.CONNECTOR_READ}),
    )
    identity = ConnectorIdentity(tenant_id="org-1", principal_id="u1")

    normal = evaluate_connector_policy_with_elevation(identity=identity, instance=instance, requested_capability=ConnectorCapabilityKind.CONNECTOR_WRITE, resource="ticket/42", operation="close", lease_id=None, arguments={})
    assert normal.state.value == "DENY"

    lease = _issue(capability_domain=CapabilityDomain.CONNECTOR, capability="CONNECTOR_WRITE", resource_scope=f"{instance.connector_instance_id}:ticket/42", operation_scope="close")

    elevated = evaluate_connector_policy_with_elevation(identity=identity, instance=instance, requested_capability=ConnectorCapabilityKind.CONNECTOR_WRITE, resource="ticket/42", operation="close", lease_id=lease.lease_id, arguments={})
    assert elevated.state.value == "ALLOW"

    state = FakeProviderState()
    result = fake_write(identity, instance, ConnectorWriteRequest(identity=identity, connector_instance_id=instance.connector_instance_id, arguments={"text": "closed"}), state)
    assert result.status == OutcomeStatus.SUCCESS

    different_resource = evaluate_connector_policy_with_elevation(identity=identity, instance=instance, requested_capability=ConnectorCapabilityKind.CONNECTOR_WRITE, resource="ticket/999", operation="close", lease_id=lease.lease_id, arguments={})
    assert different_resource.state.value == "DENY"

    from orca.godmode.contracts import now_iso
    from orca.godmode.integrity import apply_signature
    from orca.godmode.lease_store import save
    lease.expires_at = "2020-01-01T00:00:00Z"
    apply_signature(lease)
    save(lease)
    expired_check = evaluate_connector_policy_with_elevation(identity=identity, instance=instance, requested_capability=ConnectorCapabilityKind.CONNECTOR_WRITE, resource="ticket/42", operation="close", lease_id=lease.lease_id, arguments={})
    assert expired_check.state.value == "DENY"


def test_file_godmode_end_to_end(tmp_path):
    """spec §61: normal write outside standard allowed subpath denied ->
    narrow elevation for one temp/project path -> exact write succeeds ->
    sibling/outside path denied -> no access to sensitive system files."""
    project_root = tmp_path / "project-a"
    project_root.mkdir()
    sibling_root = tmp_path / "project-b"
    sibling_root.mkdir()

    req = ElevatedCapabilityRequest(principal_id="u1", tenant_id="org-1", capability_domain=CapabilityDomain.FILE, capability="FILE_WRITE", resource_scope=str(project_root), operation_scope="write", reason="fix config")
    approval = make_approval(request=req, approved_by="human-1", duration_s=120)
    lease = issue_lease(approval=approval, issuer=LeaseIssuerClass.HUMAN_APPROVAL, issuer_id="human-1")

    ok, msg = elevated_write_file(lease_id=lease.lease_id, tenant_id="org-1", path=str(project_root / "config.yaml"), content="k: v")
    assert ok

    ok2, msg2 = elevated_write_file(lease_id=lease.lease_id, tenant_id="org-1", path=str(sibling_root / "config.yaml"), content="malicious")
    assert not ok2

    ok3, msg3 = elevated_write_file(lease_id="lease-does-not-exist", tenant_id="org-1", path=str(project_root / "x.yaml"), content="x")
    assert not ok3

    ok4, msg4 = elevated_write_file(lease_id=lease.lease_id, tenant_id="org-1", path="/etc/passwd_fake_target_never_written", content="root:x:0:0")
    assert not ok4
