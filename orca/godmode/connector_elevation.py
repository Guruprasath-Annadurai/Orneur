"""
Connector elevation (Phase 10 spec §23). A connector write lease binds to
tenant + connector instance + resource + operation -- it can never
switch connector, switch tenant, or widen to a broader resource, because
`resolve_lease()`'s tenant/capability/scope checks are exact-match, and
the resource_scope passed in here is always
`f"{connector_instance_id}:{resource_path}"` (never just the resource
path alone), so a lease issued for one connector instance structurally
cannot match a request against a different one even if the resource path
happens to coincide.

`orca.connectors.policy.evaluate_connector_policy()` remains
authoritative and untouched (Phase 9 spec, unchanged) -- this module
only ever WRAPS it, exactly like `orca.godmode.policy` wraps
`orca.agent.policy`.
"""
from __future__ import annotations

from orca.connectors.contracts import (
    ConnectorCapabilityKind,
    ConnectorIdentity,
    ConnectorInstance,
    ConnectorPolicyDecision,
    ConnectorPolicyDecisionState,
    DataSensitivity,
)
from orca.connectors.policy import evaluate_connector_policy
from orca.godmode.contracts import CapabilityDomain
from orca.godmode.resolution import resolve_lease


def _connector_resource_scope(instance: ConnectorInstance, resource: str) -> str:
    """The lease's resource_scope must include the connector instance id
    -- never just the bare resource path -- so a lease cannot silently
    apply to a same-named resource on a DIFFERENT connector instance."""
    return f"{instance.connector_instance_id}:{resource}"


def evaluate_connector_policy_with_elevation(
    *, identity: ConnectorIdentity, instance: ConnectorInstance, requested_capability: ConnectorCapabilityKind,
    resource: str, operation: str, lease_id: str | None = None, sensitivity: DataSensitivity = DataSensitivity.INTERNAL,
) -> ConnectorPolicyDecision:
    normal = evaluate_connector_policy(identity=identity, instance=instance, requested_capability=requested_capability, sensitivity=sensitivity)
    if normal.state == ConnectorPolicyDecisionState.ALLOW:
        return normal

    # Tenant mismatch is never elevation-eligible -- the base policy
    # already denied unconditionally for this, and no lease resolution
    # is even attempted (defense in depth: resolve_lease() would also
    # reject a cross-tenant lease, but we don't give it the chance to be
    # asked at all here).
    if instance.tenant_id != identity.tenant_id:
        return normal

    if lease_id is None:
        return normal

    lease_decision = resolve_lease(
        lease_id, tenant_id=identity.tenant_id, capability_domain=CapabilityDomain.CONNECTOR,
        capability=requested_capability.value, resource_scope=_connector_resource_scope(instance, resource),
        operation_scope=operation,
    )
    if lease_decision.state.value != "ALLOW":
        return ConnectorPolicyDecision(state=ConnectorPolicyDecisionState.DENY, reasons=normal.reasons + lease_decision.reasons)

    return ConnectorPolicyDecision(state=ConnectorPolicyDecisionState.ALLOW, reasons=normal.reasons + [f"elevated via lease {lease_id}"] + lease_decision.reasons)
