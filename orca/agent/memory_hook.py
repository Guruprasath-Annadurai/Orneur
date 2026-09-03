"""
Explicit, bounded Memory Continuum runtime integration for agent planning
(Phase 8.1 spec §15-18). Reuses the EXISTING Phase 5/5.1 recall +
Firewall path directly -- no second retrieval implementation. Advisory
only (spec §16): never authorizes a tool, never overrides Policy, never
overrides current WorldState or a fresh TruthResult.
"""
from __future__ import annotations

from dataclasses import dataclass, field


@dataclass
class MemoryAdvisory:
    advisory_text: str = ""
    memory_ids: list[str] = field(default_factory=list)
    failure_records: list = field(default_factory=list)
    procedural_records: list = field(default_factory=list)


def recall_advisory_context(objective: str, scope_id: str, limit: int = 5) -> MemoryAdvisory:
    """
    Queries FailureMemory/ProceduralMemory for context relevant to
    `objective`, through the SAME typed `MemoryQuery` -> `recall()` ->
    `Firewall.filter_recall()` path Phase 5/5.1 already established --
    never a raw string query, never a bypass of the Firewall (spec §15).
    """
    from orca.memory.contracts import MemoryQuery, MemoryScope, MemoryType
    from orca.memory.firewall import filter_recall
    from orca.memory.retrieval import recall

    query = MemoryQuery(
        scope=MemoryScope.SESSION, scope_id=scope_id,
        memory_types=[MemoryType.FAILURE, MemoryType.PROCEDURAL],
        relevance_text=objective, limit=limit,
    )
    result = recall(query)
    allowed, _verdicts = filter_recall(result.memories, query.scope, query.scope_id)
    if not allowed:
        return MemoryAdvisory()

    failure_records = [r for r in allowed if r.memory_type == MemoryType.FAILURE]
    procedural_records = [r for r in allowed if r.memory_type == MemoryType.PROCEDURAL]

    parts = []
    for r in failure_records:
        parts.append(f"prior failure: {r.failure_mode} (task: {r.task_context[:120]}; correction: {r.correction[:200]})")
    for r in procedural_records:
        parts.append(f"known procedure '{r.name}': steps={r.steps[:5]}")

    return MemoryAdvisory(
        advisory_text="; ".join(parts)[:1500],
        memory_ids=[r.memory_id for r in allowed],
        failure_records=failure_records,
        procedural_records=procedural_records,
    )


def procedural_record_is_compatible(record, *, allowed_tool_ids: frozenset[str]) -> bool:
    """
    Spec §18: a recalled procedure is only reused if its steps are
    compatible with CURRENTLY available tools -- never executed blindly.
    A conservative, real check: every step must at least mention one of
    the currently-allowed tool ids (a stricter, versioned compatibility
    model is future work -- this is a real, if simple, compatibility
    gate, not a rubber stamp).
    """
    if not record.steps:
        return False
    return all(any(tool_id in step for tool_id in allowed_tool_ids) for step in record.steps)
