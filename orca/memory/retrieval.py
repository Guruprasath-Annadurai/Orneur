"""
Memory retrieval / MemoryQuery execution (Phase 5 spec §33-35). Typed
query objects only -- never an arbitrary query string a model could
generate directly against a store (spec §33/§35). Ranking combines
lexical relevance, entity match, temporal relevance, scope, salience,
memory type, and epistemic state -- never embedding/lexical distance
alone (spec §34).
"""
from __future__ import annotations

import re
import time

from orca.memory import store as memory_store
from orca.memory.contracts import MemoryQuery, MemoryRecallResult, MemoryRecord, MemoryType
from orca.memory.salience import compute_salience, is_stale


def _claim_text(record: MemoryRecord) -> str:
    return getattr(record, "claim", None) or getattr(record, "task_context", None) or getattr(record, "name", None) or getattr(record, "event", "")


def _relevance(record: MemoryRecord, relevance_text: str) -> float:
    if not relevance_text:
        return 0.0
    query_words = {w.lower() for w in re.findall(r"\w+", relevance_text) if len(w) > 2}
    record_words = {w.lower() for w in re.findall(r"\w+", _claim_text(record)) if len(w) > 2}
    if not query_words or not record_words:
        return 0.0
    return len(query_words & record_words) / len(query_words)


def recall(query: MemoryQuery) -> MemoryRecallResult:
    start = time.monotonic()
    memory_types = query.memory_types or [MemoryType.SEMANTIC, MemoryType.ENTITY, MemoryType.PROCEDURAL, MemoryType.FAILURE]

    candidates: list[MemoryRecord] = []
    for memory_type in memory_types:
        candidates.extend(memory_store.list_records(memory_type, query.scope, query.scope_id))

    if query.entity:
        entity_key = query.entity.strip().lower()
        candidates = [r for r in candidates if entity_key in [e.lower() for e in getattr(r, "entities", [])] or entity_key == getattr(r, "entity_name", "").lower()]

    if query.epistemic_states:
        candidates = [r for r in candidates if r.epistemic_state in query.epistemic_states]

    if query.min_evidence_quality:
        candidates = [r for r in candidates if len(r.evidence_refs) >= query.min_evidence_quality]

    if query.time_range:
        start_ts, end_ts = query.time_range
        candidates = [r for r in candidates if (r.valid_from or r.created_at) >= start_ts and (r.valid_from or r.created_at) <= end_ts]

    stale_ids, refresh_needed_ids = [], []
    scored: list[tuple[float, MemoryRecord]] = []
    for record in candidates:
        claim_text = _claim_text(record)
        relevance = _relevance(record, query.relevance_text)
        salience = compute_salience(record, relevance_score=relevance, claim_text=claim_text)
        if is_stale(record, claim_text):
            stale_ids.append(record.memory_id)
            refresh_needed_ids.append(record.memory_id)
        scored.append((salience, record))

    scored.sort(key=lambda pair: pair[0], reverse=True)
    top = [r for _, r in scored[: query.limit]]

    return MemoryRecallResult(
        query_id=query.query_id, memories=top, stale_memory_ids=stale_ids,
        refresh_needed_ids=[i for i in refresh_needed_ids if i in {r.memory_id for r in top}],
        latency_ms=(time.monotonic() - start) * 1000,
    )
