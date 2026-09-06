"""
Phase 5: SemanticMemory (legacy diskcache) session-scoped deletion, and
account_delete.py's extended cascade covering both the legacy semantic
facts store and the new Memory Continuum stores -- fixes the audit's
finding that SemanticMemory was entirely missing from the deletion
cascade (docs/orneur/phase-5/CURRENT_MEMORY_ARCHITECTURE.md).
"""
from __future__ import annotations

import uuid

from orca.brain.memory import SemanticMemory
from orca.memory import episodic, store
from orca.memory.contracts import MemoryEpisode, MemoryScope, SemanticMemoryRecord
from orca.serve.account_delete import _delete_session_data


def test_semantic_memory_deletes_only_the_target_session_block():
    sm = SemanticMemory()
    sid1, sid2 = uuid.uuid4().hex, uuid.uuid4().hex
    sm.store_fact(f"session_{sid1[:8]}", "summary A")
    sm.store_fact("all_sessions_summary", f"[Session {sid1[:8]}]\nsummary A\n\n[Session {sid2[:8]}]\nsummary B")

    removed = sm.delete_session_facts(sid1)
    assert removed
    remaining = sm.recall_fact("all_sessions_summary")
    assert sid1[:8] not in remaining
    assert sid2[:8] in remaining
    assert sm.recall_fact(f"session_{sid1[:8]}") is None

    sm.delete_session_facts(sid2)  # cleanup


def test_account_deletion_cascade_covers_semantic_memory_and_memory_continuum():
    session_id = f"test-{uuid.uuid4().hex[:8]}"
    sm = SemanticMemory()
    sm.store_fact(f"session_{session_id[:8]}", "a distilled summary")

    ep = episodic.append_episode(MemoryEpisode(scope=MemoryScope.SESSION, scope_id=session_id, event="something significant happened"))
    record = SemanticMemoryRecord(claim="A remembered fact.", scope=MemoryScope.SESSION, scope_id=session_id)
    store.save(record)

    result = _delete_session_data(session_id)

    assert result["semantic_facts_deleted"] is True
    assert sm.recall_fact(f"session_{session_id[:8]}") is None
    assert result["memory_continuum_deleted"]["typed_records_deleted"].get("SEMANTIC", 0) >= 1
    assert episodic.list_episodes(MemoryScope.SESSION, session_id) == []
    assert store.list_records(record.memory_type, MemoryScope.SESSION, session_id) == []
