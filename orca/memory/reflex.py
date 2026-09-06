"""
Memory Reflex foundation (Phase 5 spec §28). Controlled, typed triggers
only -- explicitly NOT an arbitrary rule engine. A trigger fires when its
`condition_tags` are a subset of the caller-supplied context tags (a
simple, bounded, auditable match -- no expression language, no
user-authored code). Permission/scope-aware: evaluate_reflexes() always
recalls through the same Memory Firewall as any other retrieval path.
"""
from __future__ import annotations

from dataclasses import dataclass, field

from orca.memory import firewall as memory_firewall
from orca.memory import retrieval as memory_retrieval
from orca.memory.contracts import MemoryQuery, MemoryRecord, MemoryScope, MemoryType

MAX_TRIGGERS_EVALUATED = 20


@dataclass
class ReflexTrigger:
    name: str
    condition_tags: frozenset[str]
    memory_types: list[MemoryType] = field(default_factory=list)
    entity: str | None = None
    relevance_text: str = ""
    limit: int = 3


class MemoryReflexRegistry:
    def __init__(self):
        self._triggers: list[ReflexTrigger] = []

    def register(self, trigger: ReflexTrigger) -> None:
        if len(self._triggers) >= MAX_TRIGGERS_EVALUATED:
            raise ValueError(f"MemoryReflexRegistry is bounded to {MAX_TRIGGERS_EVALUATED} triggers")
        self._triggers.append(trigger)

    def matching(self, context_tags: set[str]) -> list[ReflexTrigger]:
        return [t for t in self._triggers if t.condition_tags.issubset(context_tags)]

    def evaluate(self, context_tags: set[str], scope: MemoryScope, scope_id: str) -> list[MemoryRecord]:
        """Runs every matching trigger's recall through the standard
        MemoryQuery -> Memory Firewall path -- a reflex never bypasses
        the firewall just because it fired automatically."""
        recalled: list[MemoryRecord] = []
        for trigger in self.matching(context_tags):
            query = MemoryQuery(
                scope=scope, scope_id=scope_id, memory_types=trigger.memory_types,
                entity=trigger.entity, relevance_text=trigger.relevance_text, limit=trigger.limit,
            )
            result = memory_retrieval.recall(query)
            allowed, _verdicts = memory_firewall.filter_recall(result.memories, scope, scope_id)
            recalled.extend(allowed)
        return recalled
