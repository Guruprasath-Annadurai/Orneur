"""
Connector Policy Engine (Phase 9 spec §11). Platform policy remains
authoritative -- remote provider permissions are never the sole
authorization layer. Fully deterministic, no model call, mirroring
`orca.agent.policy`'s discipline exactly.
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

# Sensitivity classes that always require explicit approval for a WRITE
# operation, regardless of capability -- never bypassed by a permissive
# remote-provider scope (spec §42).
_ALWAYS_REQUIRE_APPROVAL_SENSITIVITY = {DataSensitivity.SENSITIVE}


def evaluate_connector_policy(
    *,
    identity: ConnectorIdentity,
    instance: ConnectorInstance,
    requested_capability: ConnectorCapabilityKind,
    sensitivity: DataSensitivity = DataSensitivity.INTERNAL,
) -> ConnectorPolicyDecision:
    """
    Hard tenant check FIRST (spec §7's critical invariant), before
    anything else is even considered -- a cross-tenant request is DENIED
    unconditionally, never degraded to REQUIRE_APPROVAL.
    """
    reasons: list[str] = []

    if instance.tenant_id != identity.tenant_id:
        return ConnectorPolicyDecision(
            state=ConnectorPolicyDecisionState.DENY,
            reasons=[f"tenant mismatch: connector belongs to tenant '{instance.tenant_id}', requester is tenant '{identity.tenant_id}'"],
        )

    if requested_capability not in instance.enabled_capabilities:
        return ConnectorPolicyDecision(state=ConnectorPolicyDecisionState.DENY, reasons=[f"connector instance does not have capability {requested_capability.value} enabled"])

    if requested_capability == ConnectorCapabilityKind.CONNECTOR_WRITE and instance.structurally_rejects_write():
        return ConnectorPolicyDecision(state=ConnectorPolicyDecisionState.DENY, reasons=["connector instance is READ_ONLY -- write structurally rejected"])

    if requested_capability in (ConnectorCapabilityKind.CONNECTOR_WRITE, ConnectorCapabilityKind.CONNECTOR_DELETE):
        if sensitivity in _ALWAYS_REQUIRE_APPROVAL_SENSITIVITY:
            reasons.append(f"{sensitivity.value} data write always requires approval")
            return ConnectorPolicyDecision(state=ConnectorPolicyDecisionState.REQUIRE_APPROVAL, reasons=reasons)

    reasons.append(f"{requested_capability.value} permitted for tenant '{identity.tenant_id}' on connector '{instance.connector_instance_id}'")
    return ConnectorPolicyDecision(state=ConnectorPolicyDecisionState.ALLOW, reasons=reasons)
