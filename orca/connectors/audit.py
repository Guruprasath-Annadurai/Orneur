"""
Connector audit logging (Phase 9 spec §54-55). Every connector action
emits a structured `ConnectorAuditEvent` -- who, tenant, connector,
operation, read/write, policy decision, approval reference, result,
timestamp, trace ID. Secrets are never included (reuses
`orca.connectors.security.redact_secrets` on any free-text fields before
storage).
"""
from __future__ import annotations

from orca.connectors.contracts import ConnectorAuditEvent, ConnectorIdentity, ConnectorInstance
from orca.connectors.security import redact_secrets

_AUDIT_LOG: list[ConnectorAuditEvent] = []


def record_audit_event(
    *, identity: ConnectorIdentity, instance: ConnectorInstance, operation: str, read_write: str,
    policy_decision: str, result_status: str, approval_ref: str | None = None, trace_id: str | None = None,
) -> ConnectorAuditEvent:
    event = ConnectorAuditEvent(
        tenant_id=identity.tenant_id, principal_id=identity.principal_id,
        connector_instance_id=instance.connector_instance_id, operation=redact_secrets(operation),
        read_write=read_write, policy_decision=policy_decision, approval_ref=approval_ref,
        result_status=result_status, trace_id=trace_id,
    )
    _AUDIT_LOG.append(event)
    return event


def audit_events_for_tenant(tenant_id: str) -> list[ConnectorAuditEvent]:
    """Never returns another tenant's audit events -- filtered strictly,
    matching ConnectorRegistry's own discipline."""
    return [e for e in _AUDIT_LOG if e.tenant_id == tenant_id]


def reset_audit_log_for_tests() -> None:
    _AUDIT_LOG.clear()
