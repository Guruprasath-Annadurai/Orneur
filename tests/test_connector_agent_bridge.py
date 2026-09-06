"""
Agent Runtime <-> Connector Fabric bridge: tool visibility, defense-in-
depth re-checking, read/write capability derivation (spec §10, §39-40).
"""
from __future__ import annotations

from orca.agent.contracts import Capability, SideEffectClass
from orca.connectors.agent_bridge import authorized_connector_tool_specs, connector_tool_spec, make_connector_read_fn
from orca.connectors.contracts import ConnectorCapabilityKind, ConnectorIdentity, ConnectorInstance, ConnectorResult, ConnectorType, OutcomeStatus
from orca.connectors.registry import ConnectorRegistry, TenantIsolationError


def _read_only_instance(tenant_id="org-1"):
    return ConnectorInstance(
        connector_type=ConnectorType.DOCUMENT_STORE, tenant_id=tenant_id, owner_principal_id="u1",
        enabled_capabilities=frozenset({ConnectorCapabilityKind.CONNECTOR_READ}), read_write_mode="READ_ONLY",
    )


def _read_write_instance(tenant_id="org-1"):
    return ConnectorInstance(
        connector_type=ConnectorType.TICKETING, tenant_id=tenant_id, owner_principal_id="u1",
        enabled_capabilities=frozenset({ConnectorCapabilityKind.CONNECTOR_READ, ConnectorCapabilityKind.CONNECTOR_WRITE}),
        read_write_mode="READ_WRITE",
    )


def test_connector_tool_spec_read_only_derives_read_only_side_effect():
    spec = connector_tool_spec(_read_only_instance(), tool_id="t1")
    assert spec.side_effect_class == SideEffectClass.READ_ONLY
    assert Capability.CONNECTOR_READ in spec.required_capabilities


def test_connector_tool_spec_read_write_derives_external_side_effect():
    spec = connector_tool_spec(_read_write_instance(), tool_id="t2")
    assert spec.side_effect_class == SideEffectClass.EXTERNAL_SIDE_EFFECT
    assert Capability.CONNECTOR_WRITE in spec.required_capabilities


def test_authorized_connector_tool_specs_only_shows_tenant_visible_healthy():
    """spec §39: planner sees ONLY tenant-authorized, healthy connectors --
    another tenant's connector never appears here at all."""
    registry = ConnectorRegistry()
    instance_a = _read_only_instance("org-A")
    instance_b = _read_only_instance("org-B")
    registry.register(instance_a)
    registry.register(instance_b)
    identity_a = ConnectorIdentity(tenant_id="org-A", principal_id="u1")

    specs = authorized_connector_tool_specs(registry, identity_a)
    tool_ids = list(specs.keys())
    assert any(instance_a.connector_instance_id in t for t in tool_ids)
    assert not any(instance_b.connector_instance_id in t for t in tool_ids)


def test_authorized_connector_tool_specs_excludes_unhealthy_connector():
    registry = ConnectorRegistry()
    instance = _read_only_instance("org-A")
    registry.register(instance)
    for _ in range(5):
        registry.record_failure(instance.connector_instance_id, failure_class="TRANSIENT")
    identity = ConnectorIdentity(tenant_id="org-A", principal_id="u1")

    specs = authorized_connector_tool_specs(registry, identity)
    assert specs == {}


def test_make_connector_read_fn_rechecks_tenant_even_if_caller_bypassed_earlier_checks():
    """Defense in depth: the callable itself re-verifies tenant/policy,
    never trusting that AgentRuntime's own policy check already ran."""
    registry = ConnectorRegistry()
    instance = _read_only_instance("org-B")
    registry.register(instance)
    attacker_identity = ConnectorIdentity(tenant_id="org-A", principal_id="attacker")

    def _read_fn(identity, instance, request):
        return ConnectorResult(status=OutcomeStatus.SUCCESS, normalized_content=[{"text": "should never be reached"}])

    tool_fn = make_connector_read_fn(registry, attacker_identity, instance.connector_instance_id, _read_fn)
    try:
        result = tool_fn("query")
        assert False, "expected TenantIsolationError, got a result instead"
    except TenantIsolationError:
        pass


def test_make_connector_read_fn_denies_when_policy_denies():
    registry = ConnectorRegistry()
    instance = ConnectorInstance(
        connector_type=ConnectorType.DOCUMENT_STORE, tenant_id="org-1", owner_principal_id="u1",
        enabled_capabilities=frozenset(),  # CONNECTOR_READ not enabled
    )
    registry.register(instance)
    identity = ConnectorIdentity(tenant_id="org-1", principal_id="u1")

    def _read_fn(identity, instance, request):
        return ConnectorResult(status=OutcomeStatus.SUCCESS, normalized_content=[{"text": "x"}])

    tool_fn = make_connector_read_fn(registry, identity, instance.connector_instance_id, _read_fn)
    result = tool_fn("query")
    assert "denied" in result.lower()


def test_make_connector_read_fn_returns_readable_message_when_unhealthy():
    registry = ConnectorRegistry()
    instance = _read_only_instance("org-1")
    registry.register(instance)
    for _ in range(5):
        registry.record_failure(instance.connector_instance_id, failure_class="TRANSIENT")
    identity = ConnectorIdentity(tenant_id="org-1", principal_id="u1")

    def _read_fn(identity, instance, request):
        return ConnectorResult(status=OutcomeStatus.SUCCESS, normalized_content=[{"text": "x"}])

    tool_fn = make_connector_read_fn(registry, identity, instance.connector_instance_id, _read_fn)
    result = tool_fn("query")
    assert "unhealthy" in result.lower() or "offline" in result.lower()
