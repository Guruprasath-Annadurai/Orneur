"""
Sync/tombstone/permission-revocation lifecycle + audit logging
(spec §51-55).
"""
from __future__ import annotations

import pytest

from orca.connectors.audit import audit_events_for_tenant, record_audit_event, reset_audit_log_for_tests
from orca.connectors.contracts import ConnectorIdentity, ConnectorInstance, ConnectorType
from orca.connectors.lifecycle import PermissionRevocationTracker, SimpleSyncStateStore


@pytest.fixture(autouse=True)
def _reset_audit_log():
    reset_audit_log_for_tests()
    yield
    reset_audit_log_for_tests()


def test_tombstoned_object_filtered_out_of_results():
    """spec §52: a deleted remote object must not keep being served."""
    store = SimpleSyncStateStore()
    results = [{"id": "obj-1", "text": "a"}, {"id": "obj-2", "text": "b"}]
    store.tombstone("conn-1", "obj-1")
    filtered = store.filter_out_tombstoned("conn-1", results)
    assert [r["id"] for r in filtered] == ["obj-2"]
    assert store.is_tombstoned("conn-1", "obj-1")
    assert not store.is_tombstoned("conn-1", "obj-2")


def test_tombstone_scoped_per_connector_instance():
    store = SimpleSyncStateStore()
    store.tombstone("conn-1", "obj-1")
    assert not store.is_tombstoned("conn-2", "obj-1")


def test_permission_revocation_marks_previously_cached_entries_stale():
    """spec §53: a cached entry recorded against an older permission
    version must be treated as stale after revocation -- even though it
    was valid when cached."""
    tracker = PermissionRevocationTracker()
    cached_version = tracker.current_version("conn-1")
    assert not tracker.is_stale("conn-1", cached_version)

    tracker.revoke("conn-1")
    assert tracker.is_stale("conn-1", cached_version)


def test_permission_revocation_monotonic_and_scoped():
    tracker = PermissionRevocationTracker()
    v1 = tracker.revoke("conn-1")
    v2 = tracker.revoke("conn-1")
    assert v2 > v1
    assert tracker.current_version("conn-2") == 0


def test_audit_event_records_and_redacts_operation():
    instance = ConnectorInstance(connector_type=ConnectorType.DOCUMENT_STORE, tenant_id="org-1", owner_principal_id="u1")
    identity = ConnectorIdentity(tenant_id="org-1", principal_id="u1")
    event = record_audit_event(
        identity=identity, instance=instance, operation="search api_key: sk-abcdefghijklmnopqrstuvwxyz1234567890",
        read_write="READ", policy_decision="ALLOW", result_status="SUCCESS",
    )
    assert "sk-abcdefghijklmnopqrstuvwxyz1234567890" not in event.operation
    assert "[REDACTED]" in event.operation


def test_audit_events_filtered_strictly_by_tenant():
    instance_a = ConnectorInstance(connector_type=ConnectorType.DOCUMENT_STORE, tenant_id="org-A", owner_principal_id="u1")
    instance_b = ConnectorInstance(connector_type=ConnectorType.DOCUMENT_STORE, tenant_id="org-B", owner_principal_id="u2")
    record_audit_event(identity=ConnectorIdentity(tenant_id="org-A", principal_id="u1"), instance=instance_a, operation="read", read_write="READ", policy_decision="ALLOW", result_status="SUCCESS")
    record_audit_event(identity=ConnectorIdentity(tenant_id="org-B", principal_id="u2"), instance=instance_b, operation="read", read_write="READ", policy_decision="ALLOW", result_status="SUCCESS")

    events_a = audit_events_for_tenant("org-A")
    assert len(events_a) == 1
    assert events_a[0].tenant_id == "org-A"
