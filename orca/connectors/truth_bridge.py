"""
Connector -> Truth Fabric evidence bridge (Phase 9 spec §35-37, §57-59).
Connector-derived content becomes real `orca.truth.contracts.Evidence`,
preserving full provenance (connector instance, provider object ID,
version, timestamp) -- never injected as unconditionally-trusted prompt
text (spec §23's "do not inject raw remote content directly as trusted
prompt authority").
"""
from __future__ import annotations

from orca.connectors.contracts import ConnectorInstance, ConnectorResult, ConnectorType

# Spec §36: enterprise sources have CONTEXTUAL authority, never a single
# global "internal = trusted" rank. Reuses Truth Fabric's EXISTING
# SourceType taxonomy (no new enum value that Truth Fabric's own
# authority/freshness logic wouldn't already know how to weigh) --
# document/code/ticketing/database/CRM/internal-API sources map to
# UPLOADED_DOCUMENT (primary-ish, tenant-provided); messaging/calendar map
# to WEB_COMMUNITY (informal context, never automatically authoritative).
_HIGH_AUTHORITY_TYPES = {
    ConnectorType.DOCUMENT_STORE, ConnectorType.CODE_HOST, ConnectorType.TICKETING,
    ConnectorType.DATABASE, ConnectorType.CRM, ConnectorType.INTERNAL_API, ConnectorType.OBJECT_STORAGE,
}


def connector_result_to_evidence(instance: ConnectorInstance, result: ConnectorResult) -> list:
    """Returns `list[tuple[orca.truth.contracts.Evidence, EvidenceSource]]`
    -- following the SAME (Evidence, EvidenceSource) pairing convention as
    `orca.truth.evidence.evidence_from_document_chunk()`/
    `evidence_from_search_result()`: `Evidence` itself only carries a
    `source_id` string, never the source object, so the caller must retain
    both halves (e.g. to register the source_type with whatever Evidence
    store/index Truth Fabric uses downstream). Imported lazily to avoid a
    hard import cycle between orca.connectors and orca.truth."""
    from orca.truth.contracts import Evidence, EvidencePassage, EvidenceSource, FreshnessLevel, SourceType

    source_type = SourceType.UPLOADED_DOCUMENT if instance.connector_type in _HIGH_AUTHORITY_TYPES else SourceType.WEB_COMMUNITY
    pairs = []
    for i, (obj_ref, content) in enumerate(zip(result.object_refs, result.normalized_content)):
        source = EvidenceSource(
            source_id=f"connector:{obj_ref.connector_instance_id}:{obj_ref.provider_object_id}", identity=obj_ref.provider_object_id,
            source_type=source_type, publisher=instance.connector_type.value,
        )
        passage = EvidencePassage(text=str(content.get("text", content))[:2000], location=obj_ref.resource_scope)
        evidence = Evidence(
            evidence_id=f"ev-{obj_ref.connector_instance_id}-{i}", source_id=source.source_id,
            document_id=obj_ref.provider_object_id, passage=passage,
            freshness=FreshnessLevel.STATIC,
            origin_metadata={
                "connector_instance_id": obj_ref.connector_instance_id, "provider_object_id": obj_ref.provider_object_id,
                "resource_scope": obj_ref.resource_scope, "version": obj_ref.version, "last_modified": obj_ref.last_modified,
                "connector_type": instance.connector_type.value,
            },
        )
        pairs.append((evidence, source))
    return pairs
