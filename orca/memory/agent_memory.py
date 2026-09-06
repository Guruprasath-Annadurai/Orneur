"""
Agent memory scoping (Phase 5 spec §23). Subagents do NOT get
unrestricted access to all user/session memory. An agent's own learning
stays MemoryScope.AGENT-scoped (isolated by agent_id) unless a caller
explicitly promotes it into the parent session's scope -- promotion is
never automatic.
"""
from __future__ import annotations

from orca.cognitive.contracts import PrivacyClass
from orca.memory import firewall as memory_firewall
from orca.memory import retrieval as memory_retrieval
from orca.memory import store as memory_store
from orca.memory.arbiter import MemoryArbiter
from orca.memory.contracts import MemoryCandidate, MemoryQuery, MemoryRecord, MemoryScope, MemoryType, PromotionDecision


def agent_scoped_recall(
    agent_id: str, relevance_text: str, allowed_memory_types: list[MemoryType] | None = None, limit: int = 3,
) -> list[MemoryRecord]:
    """An agent recalls only from its OWN agent-scoped memory by default
    -- never the parent session's or another agent's. `allowed_memory_types`
    is the agent's capability boundary (spec §23: "obey capabilities");
    omitting it defaults to the full type list, which callers should
    narrow per the agent's actual task."""
    query = MemoryQuery(
        scope=MemoryScope.AGENT, scope_id=agent_id, memory_types=allowed_memory_types or [], relevance_text=relevance_text, limit=limit,
    )
    result = memory_retrieval.recall(query)
    allowed, _verdicts = memory_firewall.filter_recall(result.memories, MemoryScope.AGENT, agent_id)
    return allowed


def record_agent_learning(agent_id: str, claim: str, entities: list[str] | None = None) -> MemoryCandidate:
    """Agent-local temporary learning -- scoped to the agent, not
    promoted anywhere else, unless promote_to_session() is called
    explicitly."""
    candidate = MemoryCandidate(extracted_claim=claim, entities=entities or [], scope=MemoryScope.AGENT, scope_id=agent_id, privacy=PrivacyClass.STANDARD)
    arbiter = MemoryArbiter()
    existing = memory_store.list_records(MemoryType.SEMANTIC, MemoryScope.AGENT, agent_id)
    decision, reasons = arbiter.decide_promotion(candidate, existing)
    candidate.promotion_decision = decision
    candidate.reasons = reasons
    if decision == PromotionDecision.PROMOTED:
        arbiter.promote(candidate)
    return candidate


def promote_to_session(agent_id: str, memory_id: str, session_id: str) -> MemoryRecord | None:
    """The ONLY way agent-local learning reaches the parent session's
    memory -- an explicit call, never automatic (spec §23)."""
    record = memory_store.load(MemoryType.SEMANTIC, MemoryScope.AGENT, agent_id, memory_id)
    if record is None:
        return None
    record.scope, record.scope_id = MemoryScope.SESSION, session_id
    memory_store.save(record)
    # save() writes under the NEW scope's path -- remove the old
    # agent-scoped copy so promotion doesn't leave a duplicate behind.
    memory_store.delete_record(MemoryType.SEMANTIC, MemoryScope.AGENT, agent_id, memory_id)
    return record
