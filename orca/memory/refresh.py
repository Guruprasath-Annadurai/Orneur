"""
Truth Fabric refresh for stale memory (Phase 5 spec §32). A stale
recalled memory is never silently used as current truth -- when it's
actually relevant to a STRICT/AUDIT_GRADE request, this module asks
Truth Fabric to re-verify it, and supersedes the old record with a new
one carrying the fresh evidence (never an in-place overwrite -- spec
§16's SUPERSEDES relationship, same pattern orca/memory/arbiter.py's
supersede() already implements for any other update).
"""
from __future__ import annotations

from orca.cognitive.contracts import ComplexityLevel, EvidenceLevel, FreshnessLevel
from orca.cognitive.intent import compile_intent
from orca.memory.arbiter import MemoryArbiter
from orca.memory.contracts import MemoryEvidence, SemanticMemoryRecord, _now_iso
from orca.truth.contracts import EvidenceState, TruthRequest
from orca.truth.truth_fabric import TruthFabric


async def refresh_stale_memory(record: SemanticMemoryRecord, doc_store=None, budget=None) -> SemanticMemoryRecord:
    """Runs TruthFabric.assess_evidence() against the memory's own claim
    as the objective. If fresh SUFFICIENT/PARTIAL evidence is found, the
    old record is superseded by a new one carrying the new evidence
    lineage. If Truth Fabric finds nothing (or the same INSUFFICIENT
    result), the old record is returned UNCHANGED except its
    last_verified_at (the memory is still stale, but the check itself
    is recorded, not silently skipped)."""
    fabric = TruthFabric()
    intent = compile_intent(record.claim)
    request = TruthRequest(objective=record.claim, evidence_requirement=EvidenceLevel.SUPPORTED, freshness_requirement=FreshnessLevel.CURRENT)
    result = await fabric.assess_evidence(request, intent, ComplexityLevel.LOW, doc_store=doc_store, budget=budget)

    if result.evidence_state in (EvidenceState.INSUFFICIENT, EvidenceState.LOW_AUTHORITY) or not result.evidence:
        record.last_verified_at = _now_iso()
        return record

    new_evidence_refs = [
        MemoryEvidence(truth_request_id=result.request_id, truth_evidence_id=ev.evidence_id, note="refreshed via Truth Fabric")
        for ev in result.evidence
    ]
    from orca.memory.contracts import EpistemicState
    new_record = SemanticMemoryRecord(
        claim=record.claim, entities=list(record.entities), scope=record.scope, scope_id=record.scope_id,
        privacy=record.privacy, source_refs=list(record.source_refs), evidence_refs=new_evidence_refs,
        epistemic_state=EpistemicState.SUPPORTED, last_verified_at=_now_iso(),
    )

    MemoryArbiter().supersede(record, new_record)
    return new_record
