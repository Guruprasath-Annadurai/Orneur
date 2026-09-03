"""
Connector -> Truth Fabric evidence bridge and Connector -> Memory
Continuum bridge (spec §35-38, §57-59).
"""
from __future__ import annotations

from orca.connectors.contracts import ConnectorInstance, ConnectorObjectRef, ConnectorResult, ConnectorType, DataSensitivity, OutcomeStatus
from orca.connectors.memory_bridge import connector_result_to_memory_candidate
from orca.connectors.truth_bridge import connector_result_to_evidence


def _result_with_content(text="the contract expires in 2027"):
    obj_ref = ConnectorObjectRef(connector_instance_id="conn-1", provider_object_id="obj-1", resource_scope="docs", version="v3", last_modified="2026-08-01T00:00:00Z")
    return ConnectorResult(status=OutcomeStatus.SUCCESS, object_refs=[obj_ref], normalized_content=[{"text": text}], sensitivity=DataSensitivity.INTERNAL)


def test_connector_result_to_evidence_preserves_full_provenance():
    instance = ConnectorInstance(connector_type=ConnectorType.DOCUMENT_STORE, tenant_id="org-1", owner_principal_id="u1")
    result = _result_with_content()
    pairs = connector_result_to_evidence(instance, result)
    assert len(pairs) == 1
    ev, source = pairs[0]
    assert ev.origin_metadata["connector_instance_id"] == "conn-1"
    assert ev.origin_metadata["provider_object_id"] == "obj-1"
    assert ev.origin_metadata["version"] == "v3"
    assert ev.origin_metadata["connector_type"] == "DOCUMENT_STORE"
    assert ev.source_id == source.source_id


def test_connector_result_to_evidence_high_authority_types_map_to_uploaded_document():
    from orca.truth.contracts import SourceType
    instance = ConnectorInstance(connector_type=ConnectorType.CODE_HOST, tenant_id="org-1", owner_principal_id="u1")
    _, source = connector_result_to_evidence(instance, _result_with_content())[0]
    assert source.source_type == SourceType.UPLOADED_DOCUMENT


def test_connector_result_to_evidence_messaging_maps_to_web_community():
    from orca.truth.contracts import SourceType
    instance = ConnectorInstance(connector_type=ConnectorType.MESSAGING, tenant_id="org-1", owner_principal_id="u1")
    _, source = connector_result_to_evidence(instance, _result_with_content())[0]
    assert source.source_type == SourceType.WEB_COMMUNITY


def test_connector_result_to_evidence_empty_result_yields_no_evidence():
    instance = ConnectorInstance(connector_type=ConnectorType.DOCUMENT_STORE, tenant_id="org-1", owner_principal_id="u1")
    empty_result = ConnectorResult(status=OutcomeStatus.SUCCESS, object_refs=[], normalized_content=[])
    assert connector_result_to_evidence(instance, empty_result) == []


def test_connector_result_to_memory_candidate_uses_tenant_scope():
    from orca.memory.contracts import MemoryScope
    instance = ConnectorInstance(connector_type=ConnectorType.DOCUMENT_STORE, tenant_id="org-1", owner_principal_id="u1")
    candidate = connector_result_to_memory_candidate(instance, _result_with_content(), tenant_id="org-1")
    assert candidate is not None
    assert candidate.scope == MemoryScope.TENANT
    assert candidate.scope_id == "org-1"


def test_connector_result_to_memory_candidate_none_when_no_content():
    instance = ConnectorInstance(connector_type=ConnectorType.DOCUMENT_STORE, tenant_id="org-1", owner_principal_id="u1")
    empty_result = ConnectorResult(status=OutcomeStatus.SUCCESS, normalized_content=[])
    assert connector_result_to_memory_candidate(instance, empty_result, tenant_id="org-1") is None


def test_memory_firewall_enforces_tenant_scope_isolation_for_connector_memory():
    """Verifies orca.memory.firewall (built in Phase 5, unchanged here)
    correctly enforces TENANT-scope isolation for a real connector-derived
    memory record -- zero changes needed to the Firewall itself."""
    from orca.memory import firewall
    from orca.memory.contracts import MemoryEpisode, MemoryScope

    record = MemoryEpisode(scope=MemoryScope.TENANT, scope_id="org-1", event="connector-derived fact")

    same_tenant = firewall.check(record, requesting_scope=MemoryScope.TENANT, requesting_scope_id="org-1")
    cross_tenant = firewall.check(record, requesting_scope=MemoryScope.TENANT, requesting_scope_id="org-2")
    assert same_tenant.allowed is True
    assert cross_tenant.allowed is False
    assert "scope_mismatch" in cross_tenant.reasons
