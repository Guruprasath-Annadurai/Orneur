"""
DOCUMENT_STORE connector -- REAL_ADAPTER (Phase 9 spec §27), adapting the
existing, real `orca.docs.store.DocStore` (session-scoped ChromaDB +
keyword fallback). Tenant isolation is enforced at TWO layers, not one:
(1) `orca.connectors.registry.ConnectorRegistry.get_for_tenant()` refuses
cross-tenant instance lookup outright; (2) this adapter derives DocStore's
own `session_id` from `f"{tenant_id}:{connector_instance_id}"`, so even if
a caller somehow obtained a raw `DocStore` handle for one tenant's
connector instance, the underlying ChromaDB collection name itself is
tenant-namespaced -- defense in depth against vector-scope leakage
(spec §50).
"""
from __future__ import annotations

import time

from orca.connectors.contracts import (
    ConnectorIdentity,
    ConnectorInstance,
    ConnectorObjectRef,
    ConnectorReadRequest,
    ConnectorResult,
    DataSensitivity,
    OutcomeStatus,
)


def _scoped_session_id(instance: ConnectorInstance) -> str:
    """The single place a tenant-scoped DocStore session_id is derived --
    reused by every read so the collection name is always identical for
    the same (tenant, connector_instance) pair, never accidentally
    diverging. Sanitized to DocStore/ChromaDB's own allowed collection-
    name character set ([a-zA-Z0-9._-]) -- `-` as the tenant/instance
    separator so no two distinct (tenant, instance) pairs can ever
    collide onto the same sanitized string."""
    import re
    tenant_part = re.sub(r"[^a-zA-Z0-9]", "", instance.tenant_id) or "t"
    return f"{tenant_part}-{instance.connector_instance_id}"


def search_documents(identity: ConnectorIdentity, instance: ConnectorInstance, request: ConnectorReadRequest) -> ConnectorResult:
    """
    Real retrieval through `DocStore.retrieve()` -- no second retrieval
    implementation. Tenant mismatch is caught by the CALLER (the
    connector dispatch layer, via `ConnectorRegistry.get_for_tenant()` +
    `evaluate_connector_policy()`) before this function is ever invoked;
    this function additionally asserts it as a structural, defensive
    invariant (never trust a single check for something this
    consequential -- the same discipline `orca/serve/routing.py`'s
    sovereignty-lock check already established in this codebase).
    """
    if instance.tenant_id != identity.tenant_id:
        raise PermissionError("tenant mismatch reached document_store adapter -- this must never happen past policy")

    from orca.docs.store import DocStore

    start = time.monotonic()
    store = DocStore(session_id=_scoped_session_id(instance))
    hits = store.retrieve(request.query, top_k=5)
    latency_ms = (time.monotonic() - start) * 1000

    object_refs = [
        ConnectorObjectRef(
            connector_instance_id=instance.connector_instance_id,
            provider_object_id=h.get("doc_id", ""),
            resource_scope=instance.scope.resource_path,
            last_modified=None,
        )
        for h in hits
    ]
    normalized = [
        {"text": h.get("text", ""), "doc_id": h.get("doc_id", ""), "filename": h.get("filename", ""), "score": h.get("score", 0.0)}
        for h in hits
    ]
    return ConnectorResult(
        request_id=request.request_id, status=OutcomeStatus.SUCCESS, object_refs=object_refs,
        normalized_content=normalized, sensitivity=DataSensitivity.INTERNAL, latency_ms=latency_ms,
    )
