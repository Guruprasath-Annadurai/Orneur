# Phase 9 — Connector Content as Truth Fabric Evidence

`orca.connectors.truth_bridge.connector_result_to_evidence(instance, result)`
returns `list[tuple[Evidence, EvidenceSource]]` -- following the SAME
pairing convention already established by
`orca.truth.evidence.evidence_from_document_chunk()`/
`evidence_from_search_result()`. `Evidence` itself only ever carries a
`source_id` string, never the source object, so both halves must be
retained by the caller (e.g. to register the source with whatever
Evidence store/index Truth Fabric uses downstream).

## Contextual authority, not a single global rank

Connector families are NOT all given "internal = automatically
authoritative" status. `_HIGH_AUTHORITY_TYPES` (DOCUMENT_STORE,
CODE_HOST, TICKETING, DATABASE, CRM, INTERNAL_API, OBJECT_STORAGE) map to
`SourceType.UPLOADED_DOCUMENT`; MESSAGING and CALENDAR map to
`SourceType.WEB_COMMUNITY` (informal context, never automatically
authoritative) -- both are Truth Fabric's EXISTING `SourceType` values,
never a new enum value Truth Fabric's own authority/freshness logic
wouldn't know how to weigh (spec §36-37).

## Full provenance preserved

Every `Evidence.origin_metadata` carries `connector_instance_id`,
`provider_object_id`, `resource_scope`, `version`, `last_modified`, and
`connector_type` -- verified directly in
`tests/test_connector_truth_memory_bridges.py`.

## Real bug found and fixed

The initial implementation constructed an `EvidenceSource` but discarded
it, returning only `list[Evidence]` -- since `Evidence` has no `source`
field, the `source_type` classification was silently lost entirely.
Fixed to return `(Evidence, EvidenceSource)` pairs.
