"""
ConnectorRegistry health/circuit-breaker behavior (spec §19-20).
"""
from __future__ import annotations

from orca.connectors.contracts import ConnectorHealthState, ConnectorInstance, ConnectorType
from orca.connectors.registry import ConnectorRegistry


def _instance():
    return ConnectorInstance(connector_type=ConnectorType.DOCUMENT_STORE, tenant_id="org-1", owner_principal_id="u1")


def test_new_instance_starts_healthy_and_routable():
    registry = ConnectorRegistry()
    instance = _instance()
    registry.register(instance)
    assert registry.is_routable(instance.connector_instance_id)


def test_auth_failure_marks_unauthorized_and_unroutable():
    registry = ConnectorRegistry()
    instance = _instance()
    registry.register(instance)
    registry.record_failure(instance.connector_instance_id, failure_class="AUTH_FAILURE")
    assert registry.health_for(instance.connector_instance_id).state == ConnectorHealthState.UNAUTHORIZED
    assert not registry.is_routable(instance.connector_instance_id)


def test_rate_limit_marks_rate_limited_and_unroutable():
    registry = ConnectorRegistry()
    instance = _instance()
    registry.register(instance)
    registry.record_failure(instance.connector_instance_id, failure_class="RATE_LIMIT")
    assert registry.health_for(instance.connector_instance_id).state == ConnectorHealthState.RATE_LIMITED
    assert not registry.is_routable(instance.connector_instance_id)


def test_transient_failures_below_threshold_stay_routable():
    registry = ConnectorRegistry()
    instance = _instance()
    registry.register(instance)
    for _ in range(4):
        registry.record_failure(instance.connector_instance_id, failure_class="TRANSIENT")
    assert registry.is_routable(instance.connector_instance_id)


def test_transient_failures_at_threshold_go_offline():
    registry = ConnectorRegistry()
    instance = _instance()
    registry.register(instance)
    for _ in range(5):
        registry.record_failure(instance.connector_instance_id, failure_class="TRANSIENT")
    assert registry.health_for(instance.connector_instance_id).state == ConnectorHealthState.OFFLINE
    assert not registry.is_routable(instance.connector_instance_id)


def test_success_resets_transient_failure_count_and_state():
    registry = ConnectorRegistry()
    instance = _instance()
    registry.register(instance)
    for _ in range(4):
        registry.record_failure(instance.connector_instance_id, failure_class="TRANSIENT")
    registry.record_success(instance.connector_instance_id)
    health = registry.health_for(instance.connector_instance_id)
    assert health.consecutive_failures == 0
    assert health.state == ConnectorHealthState.HEALTHY
    assert registry.is_routable(instance.connector_instance_id)
