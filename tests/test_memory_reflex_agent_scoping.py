"""
Phase 5: Memory Reflex (bounded, typed triggers -- not an arbitrary rule
engine) and agent memory scoping (agents never get unrestricted access
to session/user memory; promotion out of agent scope is explicit only).
"""
from __future__ import annotations

import uuid

import pytest

from orca.memory import agent_memory, store
from orca.memory.contracts import MemoryScope, MemoryType, PromotionDecision, SemanticMemoryRecord
from orca.memory.reflex import MemoryReflexRegistry, ReflexTrigger


@pytest.fixture
def sid():
    scope_id = f"test-{uuid.uuid4().hex[:8]}"
    yield scope_id
    store.delete_scope(MemoryScope.SESSION, scope_id)


def test_reflex_registry_is_bounded():
    registry = MemoryReflexRegistry()
    for i in range(20):
        registry.register(ReflexTrigger(name=f"t{i}", condition_tags=frozenset({f"tag{i}"})))
    with pytest.raises(ValueError):
        registry.register(ReflexTrigger(name="overflow", condition_tags=frozenset({"x"})))


def test_reflex_fires_only_on_matching_condition_tags(sid):
    record = SemanticMemoryRecord(claim="Canary must run before promote for Novus deployments.", scope=MemoryScope.SESSION, scope_id=sid)
    store.save(record)

    registry = MemoryReflexRegistry()
    registry.register(ReflexTrigger(
        name="novus_production_deploy", condition_tags=frozenset({"production_deployment", "model_family_novus"}),
        memory_types=[MemoryType.SEMANTIC], relevance_text="deployment procedure",
    ))

    no_match = registry.evaluate({"production_deployment"}, MemoryScope.SESSION, sid)  # missing model_family_novus
    assert no_match == []

    full_match = registry.evaluate({"production_deployment", "model_family_novus"}, MemoryScope.SESSION, sid)
    assert any(r.memory_id == record.memory_id for r in full_match)


def test_agent_memory_isolated_from_session_scope(sid):
    agent_id = f"agent-{uuid.uuid4().hex[:8]}"
    session_record = SemanticMemoryRecord(claim="Session-scoped secret.", scope=MemoryScope.SESSION, scope_id=sid)
    store.save(session_record)

    candidate = agent_memory.record_agent_learning(agent_id, "Agent learned something on its own.")
    assert candidate.promotion_decision == PromotionDecision.PROMOTED

    agent_results = agent_memory.agent_scoped_recall(agent_id, "secret")
    assert not any(r.claim == "Session-scoped secret." for r in agent_results if hasattr(r, "claim"))

    store.delete_scope(MemoryScope.AGENT, agent_id)


def test_agent_learning_requires_explicit_promotion_to_reach_session(sid):
    agent_id = f"agent-{uuid.uuid4().hex[:8]}"
    candidate = agent_memory.record_agent_learning(agent_id, "A fact the agent discovered.")
    agent_records = store.list_records(MemoryType.SEMANTIC, MemoryScope.AGENT, agent_id)
    assert len(agent_records) == 1
    memory_id = agent_records[0].memory_id

    # Before promotion: invisible in session scope
    session_records_before = store.list_records(MemoryType.SEMANTIC, MemoryScope.SESSION, sid)
    assert not any(r.memory_id == memory_id for r in session_records_before)

    promoted = agent_memory.promote_to_session(agent_id, memory_id, sid)
    assert promoted is not None

    session_records_after = store.list_records(MemoryType.SEMANTIC, MemoryScope.SESSION, sid)
    assert any(r.memory_id == memory_id for r in session_records_after)
    # No orphaned duplicate left behind at the old agent scope
    assert store.list_records(MemoryType.SEMANTIC, MemoryScope.AGENT, agent_id) == []
