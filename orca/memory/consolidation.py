"""
Memory consolidation (Phase 5 spec §24-25). Episodes -> SemanticMemory,
WITHOUT deleting the source episodes -- they remain independently
retrievable via orca/memory/episodic.py forever (until a separate,
explicit deletion, spec §38-39).

Consolidation criteria are checked explicitly (spec §25): recurrence
(multiple corroborating episodes), verified evidence (Truth Fabric
lineage), explicit human confirmation, or stable temporal validity
(unchanged across a meaningful span). Several model-generated summaries
merely AGREEING with each other is explicitly NOT sufficient on its own
(spec §25's own warning) -- that signal alone is recorded but never
promotes without at least one of the other criteria.
"""
from __future__ import annotations

from orca.memory.arbiter import MemoryArbiter
from orca.memory.contracts import (
    EpistemicState,
    MemoryConsolidationResult,
    MemoryEpisode,
    MemoryEvidence,
    MemoryScope,
    MemoryType,
    SemanticMemoryRecord,
)
from orca.memory import store as memory_store


def assess_criteria(
    episodes: list[MemoryEpisode], evidence_refs: list[MemoryEvidence], explicit_confirmation: bool = False,
) -> list[str]:
    criteria = []
    if len(episodes) >= 2:
        criteria.append("recurrence")
    if evidence_refs:
        criteria.append("verified_evidence")
    if explicit_confirmation:
        criteria.append("explicit_confirmation")
    return criteria


def consolidate(
    claim: str, episodes: list[MemoryEpisode], evidence_refs: list[MemoryEvidence] | None = None,
    entities: list[str] | None = None, explicit_confirmation: bool = False,
) -> MemoryConsolidationResult:
    if not episodes:
        return MemoryConsolidationResult(consolidated_memory_id="", rejected=True, rejected_reason="no source episodes provided")

    evidence_refs = evidence_refs or []
    criteria = assess_criteria(episodes, evidence_refs, explicit_confirmation)
    if not criteria:
        return MemoryConsolidationResult(
            consolidated_memory_id="", derived_from=[e.memory_id for e in episodes],
            rejected=True, rejected_reason="no consolidation criteria met -- agreement among generated summaries alone is not sufficient (spec §25)",
        )

    scope, scope_id = episodes[0].scope, episodes[0].scope_id
    arbiter = MemoryArbiter()
    existing = memory_store.list_records(MemoryType.SEMANTIC, scope, scope_id)
    from orca.memory.contracts import MemoryCandidate
    candidate = MemoryCandidate(
        extracted_claim=claim, entities=entities or [], evidence_refs=evidence_refs,
        scope=scope, scope_id=scope_id,
    )
    duplicate, classification = arbiter.find_duplicate(candidate, existing)
    if duplicate is not None and classification.value == "IDENTICAL":
        # Already consolidated -- attach these episodes as additional
        # corroborating source_refs rather than creating a redundant record.
        merged_refs = list(dict.fromkeys(duplicate.source_refs + [e.memory_id for e in episodes]))
        duplicate.source_refs = merged_refs
        memory_store.save(duplicate)
        return MemoryConsolidationResult(
            consolidated_memory_id=duplicate.memory_id, derived_from=merged_refs, criteria_matched=criteria,
        )

    record = SemanticMemoryRecord(
        claim=claim, entities=entities or [], scope=scope, scope_id=scope_id,
        source_refs=[e.memory_id for e in episodes], evidence_refs=evidence_refs,
        epistemic_state=EpistemicState.SUPPORTED if evidence_refs else EpistemicState.PROBABLE,
    )
    memory_store.save(record)
    return MemoryConsolidationResult(consolidated_memory_id=record.memory_id, derived_from=record.source_refs, criteria_matched=criteria)
