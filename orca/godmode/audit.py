"""
Elevation audit logging (Phase 10 spec §43-44). Mirrors
`orca.connectors.audit`'s exact discipline: redact free-text fields,
filter strictly by tenant, never log a secret (no field on
`ElevationAuditEvent` can hold a raw signature/secret value -- the
`signature` field on `CapabilityLease` is never copied into an audit
event).
"""
from __future__ import annotations

from orca.connectors.security import redact_secrets
from orca.godmode.contracts import ElevationAuditEvent, ElevationAuditEventType

_AUDIT_LOG: list[ElevationAuditEvent] = []


def record_elevation_event(
    *, event_type: ElevationAuditEventType, principal_id: str, tenant_id: str,
    capability: str = "", resource_scope: str = "", operation_scope: str = "",
    lease_id: str | None = None, issuer: str | None = None, trace_id: str | None = None, result: str = "",
) -> ElevationAuditEvent:
    event = ElevationAuditEvent(
        event_type=event_type, principal_id=principal_id, tenant_id=tenant_id,
        lease_id=lease_id, capability=redact_secrets(capability), resource_scope=redact_secrets(resource_scope),
        operation_scope=operation_scope, issuer=issuer, trace_id=trace_id, result=result,
    )
    _AUDIT_LOG.append(event)
    return event


def audit_events_for_tenant(tenant_id: str) -> list[ElevationAuditEvent]:
    return [e for e in _AUDIT_LOG if e.tenant_id == tenant_id]


def reset_audit_log_for_tests() -> None:
    _AUDIT_LOG.clear()
