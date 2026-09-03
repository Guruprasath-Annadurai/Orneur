"""
DOCUMENT_STORE connector adapter: real DocStore-backed retrieval, tenant-
namespaced ChromaDB collection naming, vector-isolation adversarial test,
deleted-object-no-longer-retrievable (spec §27, §50, §52, §66).
"""
from __future__ import annotations

import pytest

from orca.connectors.contracts import ConnectorIdentity, ConnectorInstance, ConnectorReadRequest, ConnectorScope, ConnectorType
from orca.connectors.document_store import _scoped_session_id, search_documents
from orca.connectors.lifecycle import SimpleSyncStateStore


def _instance(tenant_id="org-1", connector_instance_id=None):
    kwargs = dict(connector_type=ConnectorType.DOCUMENT_STORE, tenant_id=tenant_id, owner_principal_id="u1", scope=ConnectorScope(resource_path="docs"))
    if connector_instance_id:
        kwargs["connector_instance_id"] = connector_instance_id
    return ConnectorInstance(**kwargs)


def _ingest(store, text: str, *, doc_id: str, filename: str):
    from orca.docs.chunker import chunk_text
    chunks = chunk_text(text, doc_id=doc_id, filename=filename)
    store.add_chunks(chunks, doc_id=doc_id, filename=filename)


def test_scoped_session_id_is_chromadb_safe():
    import re
    instance = _instance(tenant_id="org-1:weird/chars!")
    session_id = _scoped_session_id(instance)
    assert re.match(r"^[a-zA-Z0-9._-]+$", session_id)


def test_scoped_session_id_differs_across_tenants_same_connector_instance_id():
    """Two different tenants somehow sharing the same connector_instance_id
    (should never happen via the registry, but this is a defense-in-depth
    structural check on the naming function itself) must never collide."""
    instance_a = _instance(tenant_id="org-A", connector_instance_id="conn-shared")
    instance_b = _instance(tenant_id="org-B", connector_instance_id="conn-shared")
    assert _scoped_session_id(instance_a) != _scoped_session_id(instance_b)


def test_search_documents_real_docstore_round_trip():
    """Real, non-mocked DocStore write + retrieve through the connector
    adapter -- proves the REAL_ADAPTER classification is genuine."""
    from orca.docs.store import DocStore

    instance = _instance(tenant_id="org-real-1")
    store = DocStore(session_id=_scoped_session_id(instance))
    _ingest(store, "The quarterly revenue figure is $4.2 million.", doc_id="q3-report", filename="q3-report.txt")

    identity = ConnectorIdentity(tenant_id="org-real-1", principal_id="u1")
    request = ConnectorReadRequest(identity=identity, connector_instance_id=instance.connector_instance_id, query="quarterly revenue")
    result = search_documents(identity, instance, request)
    assert result.normalized_content
    assert any("4.2 million" in c["text"] for c in result.normalized_content)


def test_search_documents_vector_isolation_across_tenants():
    """Adversarial: a document ingested under tenant A's connector
    collection must never surface when tenant B searches -- even with the
    exact same query text and even if tenant B somehow obtained a
    ConnectorInstance record with the SAME connector_instance_id (the
    tenant-namespaced collection name is the actual isolation boundary)."""
    from orca.docs.store import DocStore

    shared_id = "conn-vectest-shared"
    instance_a = _instance(tenant_id="org-vec-A", connector_instance_id=shared_id)
    instance_b = _instance(tenant_id="org-vec-B", connector_instance_id=shared_id)

    store_a = DocStore(session_id=_scoped_session_id(instance_a))
    _ingest(store_a, "Tenant A's confidential merger plan details.", doc_id="secret-a", filename="secret-a.txt")

    identity_b = ConnectorIdentity(tenant_id="org-vec-B", principal_id="u2")
    request = ConnectorReadRequest(identity=identity_b, connector_instance_id=shared_id, query="confidential merger plan")
    result = search_documents(identity_b, instance_b, request)
    assert not any("Tenant A" in c.get("text", "") for c in result.normalized_content)


def test_deleted_object_no_longer_retrievable_via_tombstone():
    """spec §52: after a remote delete is observed, the object must not
    keep surfacing from a cached/indexed search result set even if the
    underlying index hasn't been fully re-synced yet."""
    from orca.docs.store import DocStore

    instance = _instance(tenant_id="org-del-1")
    store = DocStore(session_id=_scoped_session_id(instance))
    _ingest(store, "This document will be deleted from the source system.", doc_id="doomed", filename="doomed.txt")

    identity = ConnectorIdentity(tenant_id="org-del-1", principal_id="u1")
    request = ConnectorReadRequest(identity=identity, connector_instance_id=instance.connector_instance_id, query="deleted from the source")
    result = search_documents(identity, instance, request)
    assert result.normalized_content

    sync_store = SimpleSyncStateStore()
    deleted_doc_id = result.normalized_content[0]["doc_id"]
    sync_store.tombstone(instance.connector_instance_id, deleted_doc_id)

    filtered = sync_store.filter_out_tombstoned(instance.connector_instance_id, result.normalized_content, id_field="doc_id")
    assert filtered == []


def test_search_documents_cross_tenant_read_raises_permission_error():
    instance = _instance(tenant_id="org-B")
    bad_identity = ConnectorIdentity(tenant_id="org-A", principal_id="attacker")
    request = ConnectorReadRequest(identity=bad_identity, connector_instance_id=instance.connector_instance_id, query="anything")
    with pytest.raises(PermissionError):
        search_documents(bad_identity, instance, request)
