"""
Phase 9 spec §66's required tenant/scope isolation scenarios.
"""
from __future__ import annotations

import pytest

from orca.connectors.contracts import (
    ConnectorCapabilityKind,
    ConnectorIdentity,
    ConnectorInstance,
    ConnectorReadRequest,
    ConnectorScope,
    ConnectorType,
)
from orca.connectors.document_store import search_documents, _scoped_session_id
from orca.connectors.policy import evaluate_connector_policy
from orca.connectors.registry import ConnectorRegistry, TenantIsolationError


def _instance(tenant_id="org-1", read_write="READ_ONLY", capabilities=None):
    return ConnectorInstance(
        connector_type=ConnectorType.DOCUMENT_STORE, tenant_id=tenant_id, owner_principal_id="u1",
        enabled_capabilities=capabilities or frozenset({ConnectorCapabilityKind.CONNECTOR_READ}),
        read_write_mode=read_write, scope=ConnectorScope(resource_path="docs"),
    )


def test_tenant_a_cannot_read_tenant_b_connector():
    registry = ConnectorRegistry()
    instance_b = _instance(tenant_id="org-B")
    registry.register(instance_b)

    identity_a = ConnectorIdentity(tenant_id="org-A", principal_id="attacker")
    with pytest.raises(TenantIsolationError):
        registry.get_for_tenant(identity_a.tenant_id, instance_b.connector_instance_id)


def test_tenant_a_cannot_even_enumerate_tenant_b_instances():
    registry = ConnectorRegistry()
    registry.register(_instance(tenant_id="org-A"))
    registry.register(_instance(tenant_id="org-B"))
    listed = registry.list_for_tenant("org-A")
    assert all(i.tenant_id == "org-A" for i in listed)
    assert len(listed) == 1


def test_policy_denies_cross_tenant_even_if_capability_would_otherwise_allow():
    instance = _instance(tenant_id="org-B")
    identity = ConnectorIdentity(tenant_id="org-A", principal_id="attacker")
    decision = evaluate_connector_policy(identity=identity, instance=instance, requested_capability=ConnectorCapabilityKind.CONNECTOR_READ)
    assert decision.state.value == "DENY"
    assert "tenant mismatch" in decision.reasons[0]


def test_document_store_adapter_refuses_cross_tenant_even_if_policy_were_somehow_skipped():
    """Defense in depth: the adapter itself independently checks tenant
    match, never trusting that policy already ran."""
    instance = _instance(tenant_id="org-B")
    bad_identity = ConnectorIdentity(tenant_id="org-A", principal_id="attacker")
    request = ConnectorReadRequest(identity=bad_identity, connector_instance_id=instance.connector_instance_id, query="x")
    with pytest.raises(PermissionError):
        search_documents(bad_identity, instance, request)


def test_read_only_connector_structurally_rejects_write():
    instance = _instance(read_write="READ_ONLY", capabilities=frozenset({ConnectorCapabilityKind.CONNECTOR_READ}))
    assert instance.structurally_rejects_write() is True

    identity = ConnectorIdentity(tenant_id=instance.tenant_id, principal_id="u1")
    decision = evaluate_connector_policy(identity=identity, instance=instance, requested_capability=ConnectorCapabilityKind.CONNECTOR_WRITE)
    assert decision.state.value == "DENY"


def test_write_requires_explicit_write_capability_even_on_read_write_connector():
    instance = _instance(read_write="READ_WRITE", capabilities=frozenset({ConnectorCapabilityKind.CONNECTOR_READ}))  # write NOT enabled
    identity = ConnectorIdentity(tenant_id=instance.tenant_id, principal_id="u1")
    decision = evaluate_connector_policy(identity=identity, instance=instance, requested_capability=ConnectorCapabilityKind.CONNECTOR_WRITE)
    assert decision.state.value == "DENY"


def test_write_allowed_when_properly_configured_and_not_sensitive():
    instance = _instance(read_write="READ_WRITE", capabilities=frozenset({ConnectorCapabilityKind.CONNECTOR_READ, ConnectorCapabilityKind.CONNECTOR_WRITE}))
    identity = ConnectorIdentity(tenant_id=instance.tenant_id, principal_id="u1")
    decision = evaluate_connector_policy(identity=identity, instance=instance, requested_capability=ConnectorCapabilityKind.CONNECTOR_WRITE)
    assert decision.state.value == "ALLOW"


def test_sensitive_write_requires_approval():
    from orca.connectors.contracts import DataSensitivity
    instance = _instance(read_write="READ_WRITE", capabilities=frozenset({ConnectorCapabilityKind.CONNECTOR_READ, ConnectorCapabilityKind.CONNECTOR_WRITE}))
    identity = ConnectorIdentity(tenant_id=instance.tenant_id, principal_id="u1")
    decision = evaluate_connector_policy(identity=identity, instance=instance, requested_capability=ConnectorCapabilityKind.CONNECTOR_WRITE, sensitivity=DataSensitivity.SENSITIVE)
    assert decision.state.value == "REQUIRE_APPROVAL"
