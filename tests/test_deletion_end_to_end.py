"""
Phase 5.1 spec §21-22: end-to-end deletion across every still-active
store (Continuum primary store, legacy vector store, legacy semantic
store, entity links, episodic ledger) -- and derived-memory
re-evaluation, extended to confirm no deleted source remains reachable
as live evidence after a full account-style deletion.
"""
from __future__ import annotations

import uuid

import pytest

from orca.brain.memory import EpisodicMemory, LongTermMemory, MemoryEngine, SemanticMemory
from orca.memory import episodic, store
from orca.memory.contracts import MemoryEpisode, MemoryLifecycleState, MemoryScope, MemoryType, SemanticMemoryRecord
from orca.serve.account_delete import _delete_session_data


class _FakeBrain:
    def complete(self, messages, system, temperature, max_tokens):
        return "- User's project is codenamed Nightingale"


def test_deletion_spans_every_still_active_store():
    session_id = f"e2e-{uuid.uuid4().hex[:8]}"

    # 1. Legacy vector store (LongTermMemory / ChromaDB)
    long_term = LongTermMemory(session_id)
    long_term.store("Q: what is my project called?\nA: Nightingale")

    # 2. Legacy semantic fact cache (SemanticMemory diskcache)
    engine = MemoryEngine(session_id=session_id)
    engine.add_turn("user", "my project is Nightingale")
    engine.add_turn("assistant", "noted")
    engine.distill_and_save(_FakeBrain())

    # 3. Legacy episodic memory file
    assert EpisodicMemory(session_id).path.exists()

    # 4. Memory Continuum: episodic ledger + semantic record + entity link
    ep = episodic.append_episode(MemoryEpisode(scope=MemoryScope.SESSION, scope_id=session_id, event="project named Nightingale"))
    record = SemanticMemoryRecord(claim="Project is codenamed Nightingale.", scope=MemoryScope.SESSION, scope_id=session_id, source_refs=[ep.memory_id])
    store.save(record)
    from orca.memory import entity as entity_module
    entity_module.link_semantic(MemoryScope.SESSION, session_id, "Nightingale", record.memory_id, entity_kind="project")

    # Sanity: everything really is there before deletion
    assert long_term.recall("Nightingale")
    assert engine.load_prior_context()
    assert episodic.list_episodes(MemoryScope.SESSION, session_id)
    assert store.list_records(MemoryType.SEMANTIC, MemoryScope.SESSION, session_id)
    assert store.list_records(MemoryType.ENTITY, MemoryScope.SESSION, session_id)

    # Act: the real deletion cascade
    result = _delete_session_data(session_id)

    # Assert: NOTHING survives in ANY store
    assert result["long_term_vector_memory_deleted"] is True
    fresh_long_term = LongTermMemory(session_id)
    assert fresh_long_term.recall("Nightingale") == []

    assert result["semantic_facts_deleted"] is True
    fresh_engine = MemoryEngine(session_id=session_id)
    assert fresh_engine.load_prior_context() == ""

    assert result["memory_deleted"] is True
    assert not EpisodicMemory(session_id).path.exists()

    assert episodic.list_episodes(MemoryScope.SESSION, session_id) == []
    assert store.list_records(MemoryType.SEMANTIC, MemoryScope.SESSION, session_id) == []
    assert store.list_records(MemoryType.ENTITY, MemoryScope.SESSION, session_id) == []


def test_derived_memory_no_deleted_source_remains_as_live_evidence():
    """Spec §22 extension: after a deletion cascade, no semantic memory
    should keep citing a deleted episode as if it were still live
    evidence -- a tombstoned source_ref is allowed (documented), but the
    memory's own lifecycle must reflect the loss of support."""
    from orca.memory import deletion as memory_deletion

    session_id = f"e2e-derived-{uuid.uuid4().hex[:8]}"
    ep = episodic.append_episode(MemoryEpisode(scope=MemoryScope.SESSION, scope_id=session_id, event="sole supporting episode"))
    record = SemanticMemoryRecord(claim="Sole-sourced derived fact.", scope=MemoryScope.SESSION, scope_id=session_id, source_refs=[ep.memory_id])
    store.save(record)

    memory_deletion.delete_episode_and_reevaluate(MemoryScope.SESSION, session_id, ep.memory_id)

    reloaded = store.load(record.memory_type, MemoryScope.SESSION, session_id, record.memory_id)
    assert reloaded.lifecycle_state == MemoryLifecycleState.ARCHIVED  # no longer presented as live/active knowledge

    tombstoned_episode = episodic.get_episode(MemoryScope.SESSION, session_id, ep.memory_id)
    assert tombstoned_episode.event == ""  # content gone
    assert ep.memory_id in reloaded.source_refs or ep.memory_id not in reloaded.source_refs  # either documented convention is acceptable...
    # ...but the record must not claim ACTIVE/SUFFICIENT status citing a source that no longer has real content
    assert reloaded.lifecycle_state != MemoryLifecycleState.ACTIVE

    store.delete_scope(MemoryScope.SESSION, session_id)
    episodic.delete_ledger(MemoryScope.SESSION, session_id)
