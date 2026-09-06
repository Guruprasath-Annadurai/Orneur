"""
Agent Runtime <-> Connector Fabric bridge (Phase 9 spec §10, §39-40).
Canonical flow: AgentAction -> ToolRegistry -> Capability Engine ->
Policy Engine -> Connector Adapter -> Result -> Observation -> WorldState.
No connector may bypass AgentRuntime authority when used by an agent --
`connector_read_tool()`/`connector_write_tool()` are the ONLY functions
that turn a `ConnectorInstance` into something `AgentToolRegistry` can
invoke, and they ALWAYS re-run `orca.connectors.policy.evaluate_connector_policy()`
even though `orca.agent.policy.evaluate_policy()` has already run first
-- defense in depth, two independent authorities, never one standing in
for the other.
"""
from __future__ import annotations

from orca.agent.contracts import ActionRiskLevel, Capability, SideEffectClass, ToolSpec
from orca.connectors.contracts import (
    ConnectorCapabilityKind,
    ConnectorIdentity,
    ConnectorInstance,
    ConnectorReadRequest,
    ConnectorScope,
    OutcomeStatus,
)
from orca.connectors.policy import evaluate_connector_policy
from orca.connectors.registry import ConnectorRegistry, TenantIsolationError


def authorized_connector_tool_specs(registry: ConnectorRegistry, identity: ConnectorIdentity) -> dict[str, ToolSpec]:
    """
    Spec §39: `AgentPlanner` should see ONLY connector tools authorized
    for the current tenant -- never every installed connector with
    security relying solely on later denial. Returns tool_id -> ToolSpec
    for every HEALTHY, tenant-visible connector instance; an unhealthy or
    other-tenant instance never appears here at all (not merely denied
    later).
    """
    specs = {}
    for instance in registry.list_for_tenant(identity.tenant_id):
        if not registry.is_routable(instance.connector_instance_id):
            continue
        tool_id = f"connector_{instance.connector_instance_id}"
        specs[tool_id] = connector_tool_spec(instance, tool_id=tool_id)
    return specs


def connector_tool_spec(instance: ConnectorInstance, *, tool_id: str) -> ToolSpec:
    """Builds the `ToolSpec` an `AgentToolRegistry` entry needs -- the
    connector's OWN `read_write_mode` determines the declared
    `side_effect_class`, never the tool name."""
    side_effect = SideEffectClass.READ_ONLY if instance.structurally_rejects_write() else SideEffectClass.EXTERNAL_SIDE_EFFECT
    capability = Capability.CONNECTOR_READ if side_effect == SideEffectClass.READ_ONLY else Capability.CONNECTOR_WRITE
    return ToolSpec(
        tool_id=tool_id,
        description=f"Enterprise connector ({instance.connector_type.value}) scoped to {instance.scope.resource_path}",
        required_capabilities=frozenset({capability}),
        side_effect_class=side_effect,
        risk_class=ActionRiskLevel.MEDIUM if side_effect != SideEffectClass.READ_ONLY else ActionRiskLevel.LOW,
        timeout_s=20.0, idempotent=(side_effect == SideEffectClass.READ_ONLY),
    )


def make_connector_read_fn(registry: ConnectorRegistry, identity: ConnectorIdentity, connector_instance_id: str, read_fn):
    """
    Returns a plain callable suitable for `AgentToolRegistry.register()`.
    Re-checks tenant/scope/capability via `orca.connectors.policy`
    INSIDE the callable -- even though `AgentRuntime._authorize()` already
    ran `orca.agent.policy.evaluate_policy()` before this callable is ever
    invoked, this is a SEPARATE, independent authority that never trusts
    the caller already checked (spec §7's "never trust a single check").
    """
    def _tool(query: str) -> str:
        instance = registry.get_for_tenant(identity.tenant_id, connector_instance_id)   # raises TenantIsolationError on mismatch
        decision = evaluate_connector_policy(identity=identity, instance=instance, requested_capability=ConnectorCapabilityKind.CONNECTOR_READ)
        if decision.state.value != "ALLOW":
            return f"Connector access denied: {'; '.join(decision.reasons)}"
        if not registry.is_routable(connector_instance_id):
            return "Connector is currently unhealthy/offline -- not routed."
        request = ConnectorReadRequest(identity=identity, connector_instance_id=connector_instance_id, scope=instance.scope, query=query)
        result = read_fn(identity, instance, request)
        registry.record_success(connector_instance_id)
        if result.status != OutcomeStatus.SUCCESS:
            return f"Connector read returned {result.status.value}: {result.error_class or ''}"
        return str(result.normalized_content)
    return _tool
