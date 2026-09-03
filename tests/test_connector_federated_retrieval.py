"""
Federated enterprise search: tenant-scoped, health-aware, honest partial
results (spec §33-34, §61, §66).
"""
from __future__ import annotations

import pytest

from orca.connectors.contracts import (
    ConnectorCapabilityKind,
    ConnectorIdentity,
    ConnectorInstance,
    ConnectorResult,
    ConnectorType,
    OutcomeStatus,
)
from orca.connectors.federated_retrieval import federated_search
from orca.connectors.registry import ConnectorRegistry, TenantIsolationError


def _instance(tenant_id, connector_type=ConnectorType.DOCUMENT_STORE):
    return ConnectorInstance(
        connector_type=connector_type, tenant_id=tenant_id, owner_principal_id="u1",
        enabled_capabilities=frozenset({ConnectorCapabilityKind.CONNECTOR_READ}),
    )


def _ok_read_fn(identity, instance, request):
    return ConnectorResult(request_id=request.request_id, status=OutcomeStatus.SUCCESS, normalized_content=[{"text": "found it"}])


def _failing_read_fn(identity, instance, request):
    raise ConnectionError("simulated provider outage")


def test_federated_search_queries_only_tenant_visible_connectors():
    registry = ConnectorRegistry()
    instance_a = _instance("org-A")
    instance_b = _instance("org-B")
    registry.register(instance_a)
    registry.register(instance_b)
    identity_a = ConnectorIdentity(tenant_id="org-A", principal_id="u1")

    result = federated_search(identity_a, registry, "query", read_fns={"DOCUMENT_STORE": _ok_read_fn})
    assert list(result.results_by_connector.keys()) == [instance_a.connector_instance_id]
    assert instance_b.connector_instance_id not in result.results_by_connector


def test_federated_search_skips_unhealthy_connector_honestly():
    registry = ConnectorRegistry()
    instance = _instance("org-A")
    registry.register(instance)
    for _ in range(5):
        registry.record_failure(instance.connector_instance_id, failure_class="TRANSIENT")
    identity = ConnectorIdentity(tenant_id="org-A", principal_id="u1")

    result = federated_search(identity, registry, "q", read_fns={"DOCUMENT_STORE": _ok_read_fn})
    assert instance.connector_instance_id in result.skipped_unhealthy
    assert result.is_partial


def test_federated_search_records_failed_connector_without_losing_others():
    registry = ConnectorRegistry()
    instance_good = _instance("org-A", ConnectorType.DOCUMENT_STORE)
    instance_bad = _instance("org-A", ConnectorType.TICKETING)
    registry.register(instance_good)
    registry.register(instance_bad)
    identity = ConnectorIdentity(tenant_id="org-A", principal_id="u1")

    result = federated_search(identity, registry, "q", read_fns={"DOCUMENT_STORE": _ok_read_fn, "TICKETING": _failing_read_fn})
    assert instance_good.connector_instance_id in result.results_by_connector
    assert instance_bad.connector_instance_id in result.failed_connectors
    assert result.is_partial


def test_federated_search_complete_when_all_succeed():
    registry = ConnectorRegistry()
    instance = _instance("org-A")
    registry.register(instance)
    identity = ConnectorIdentity(tenant_id="org-A", principal_id="u1")
    result = federated_search(identity, registry, "q", read_fns={"DOCUMENT_STORE": _ok_read_fn})
    assert not result.is_partial


def test_federated_search_explicit_cross_tenant_instance_list_blocked():
    """An attacker cannot bypass tenant scoping by supplying another
    tenant's connector_instance_id directly in the explicit list."""
    registry = ConnectorRegistry()
    instance_b = _instance("org-B")
    registry.register(instance_b)
    identity_a = ConnectorIdentity(tenant_id="org-A", principal_id="attacker")

    with pytest.raises(TenantIsolationError):
        federated_search(identity_a, registry, "q", read_fns={"DOCUMENT_STORE": _ok_read_fn}, connector_instance_ids=[instance_b.connector_instance_id])
