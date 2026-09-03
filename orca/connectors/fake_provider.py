"""
FAKE_TEST_PROVIDER (Phase 9 spec §65-66, §70). An in-memory, no-network
connector used ONLY by the evaluation harness and test suite to exercise
identity/scope/policy/capability/audit/idempotency/OUTCOME_UNKNOWN
end-to-end -- never presented as real connectivity to any real provider
(CODE_HOST/MESSAGING/CALENDAR/TICKETING/CRM/DATABASE all lack real
credentials in this codebase, per CURRENT_CONNECTOR_ARCHITECTURE.md).
"""
from __future__ import annotations

import time
from dataclasses import dataclass, field

from orca.connectors.contracts import (
    ConnectorIdentity,
    ConnectorInstance,
    ConnectorObjectRef,
    ConnectorReadRequest,
    ConnectorResult,
    ConnectorWriteRequest,
    DataSensitivity,
    OutcomeStatus,
)


@dataclass
class FakeProviderState:
    """Per-tenant, in-memory object store -- keyed by
    (tenant_id, connector_instance_id) so cross-tenant leakage is
    structurally impossible even within the fake provider's own state."""
    objects: dict[tuple[str, str], dict[str, dict]] = field(default_factory=dict)
    idempotency_keys_seen: dict[tuple[str, str], set[str]] = field(default_factory=dict)
    simulate_network_break_after_send: bool = False


def fake_read(identity: ConnectorIdentity, instance: ConnectorInstance, request: ConnectorReadRequest, state: FakeProviderState) -> ConnectorResult:
    if instance.tenant_id != identity.tenant_id:
        raise PermissionError("tenant mismatch reached fake_provider adapter -- this must never happen past policy")
    key = (instance.tenant_id, instance.connector_instance_id)
    objects = state.objects.get(key, {})
    matched = [obj for obj in objects.values() if request.query.lower() in obj.get("text", "").lower()]
    object_refs = [ConnectorObjectRef(connector_instance_id=instance.connector_instance_id, provider_object_id=obj["id"], resource_scope=instance.scope.resource_path) for obj in matched]
    return ConnectorResult(request_id=request.request_id, status=OutcomeStatus.SUCCESS, object_refs=object_refs, normalized_content=matched, sensitivity=DataSensitivity.INTERNAL)


def fake_write(identity: ConnectorIdentity, instance: ConnectorInstance, request: ConnectorWriteRequest, state: FakeProviderState) -> ConnectorResult:
    """
    Supports idempotency-key deduplication (spec §14) and a simulated
    OUTCOME_UNKNOWN race (spec §13, §35): if
    `state.simulate_network_break_after_send` is True, the write IS
    applied to the fake remote state (as a real provider's write might
    have actually landed) but the RESPONSE is reported as
    `OUTCOME_UNKNOWN` -- exactly the "sent, then connection broke before
    confirmation" scenario, never silently reported as `FAILURE` (which
    would risk an unsafe blind retry of a non-idempotent write) or
    `SUCCESS` (which would be a claim this function cannot actually back).
    """
    if instance.tenant_id != identity.tenant_id:
        raise PermissionError("tenant mismatch reached fake_provider adapter -- this must never happen past policy")

    key = (instance.tenant_id, instance.connector_instance_id)
    seen = state.idempotency_keys_seen.setdefault(key, set())
    if request.idempotency_key and request.idempotency_key in seen:
        # Already applied -- return the existing object, never a duplicate.
        objects = state.objects.get(key, {})
        existing = objects.get(request.idempotency_key)
        object_refs = [ConnectorObjectRef(connector_instance_id=instance.connector_instance_id, provider_object_id=request.idempotency_key, resource_scope=instance.scope.resource_path)] if existing else []
        return ConnectorResult(request_id=request.request_id, status=OutcomeStatus.SUCCESS, object_refs=object_refs, normalized_content=[existing] if existing else [])

    obj_id = request.idempotency_key or f"obj-{int(time.time() * 1000)}"
    objects = state.objects.setdefault(key, {})
    objects[obj_id] = {"id": obj_id, "text": request.arguments.get("text", "")}
    if request.idempotency_key:
        seen.add(request.idempotency_key)

    if state.simulate_network_break_after_send:
        return ConnectorResult(request_id=request.request_id, status=OutcomeStatus.OUTCOME_UNKNOWN, error_class="NETWORK_BREAK_AFTER_SEND")

    object_refs = [ConnectorObjectRef(connector_instance_id=instance.connector_instance_id, provider_object_id=obj_id, resource_scope=instance.scope.resource_path)]
    return ConnectorResult(request_id=request.request_id, status=OutcomeStatus.SUCCESS, object_refs=object_refs, normalized_content=[objects[obj_id]])
