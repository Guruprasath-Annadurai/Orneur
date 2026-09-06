"""
EntityMemory (Phase 5 spec §19). Links OUT to other memory records by
reference -- never a growing, mutable JSON blob per entity. Distinct
from orca/brain/knowledge_graph.py's KnowledgeGraph (LLM-extracted
subject-predicate-object triples for in-conversation reasoning) -- this
module is the Memory Continuum's own accumulation of WHICH memory
records (semantic/episodic/procedural/failure) relate to a given named
entity, adapted behind a new interface per spec §58 rather than
replacing KnowledgeGraph.
"""
from __future__ import annotations

from orca.memory.contracts import EntityMemoryRecord, MemoryScope, MemoryType
from orca.memory import store as memory_store


def _normalize(name: str) -> str:
    return " ".join(name.strip().lower().split())


def get_or_create(scope: MemoryScope, scope_id: str, entity_name: str, entity_kind: str = "concept") -> EntityMemoryRecord:
    key = _normalize(entity_name)
    for record in memory_store.list_records(MemoryType.ENTITY, scope, scope_id):
        if _normalize(record.entity_name) == key:
            return record
    record = EntityMemoryRecord(entity_name=entity_name, entity_kind=entity_kind, scope=scope, scope_id=scope_id)
    memory_store.save(record)
    return record


def link_semantic(scope: MemoryScope, scope_id: str, entity_name: str, semantic_memory_id: str, entity_kind: str = "concept") -> EntityMemoryRecord:
    record = get_or_create(scope, scope_id, entity_name, entity_kind)
    if semantic_memory_id not in record.semantic_memory_ids:
        record.semantic_memory_ids.append(semantic_memory_id)
        memory_store.save(record)
    return record


def link_episode(scope: MemoryScope, scope_id: str, entity_name: str, episode_id: str, entity_kind: str = "concept") -> EntityMemoryRecord:
    record = get_or_create(scope, scope_id, entity_name, entity_kind)
    if episode_id not in record.episode_ids:
        record.episode_ids.append(episode_id)
        memory_store.save(record)
    return record


def link_procedure(scope: MemoryScope, scope_id: str, entity_name: str, procedure_memory_id: str, entity_kind: str = "concept") -> EntityMemoryRecord:
    record = get_or_create(scope, scope_id, entity_name, entity_kind)
    if procedure_memory_id not in record.procedure_ids:
        record.procedure_ids.append(procedure_memory_id)
        memory_store.save(record)
    return record


def link_failure(scope: MemoryScope, scope_id: str, entity_name: str, failure_memory_id: str, entity_kind: str = "concept") -> EntityMemoryRecord:
    record = get_or_create(scope, scope_id, entity_name, entity_kind)
    if failure_memory_id not in record.failure_ids:
        record.failure_ids.append(failure_memory_id)
        memory_store.save(record)
    return record
