"""
Evidence sufficiency state (Phase 4 spec §30) -- the single value
CognitiveKernel (or a caller of Truth Fabric directly) uses to decide
answer / search more / verify more / abstain. Deterministic combination
of citation coverage, contradictions, authority, and freshness -- never
hides insufficient evidence behind fluent prose (computed BEFORE any
answer text is judged, from the evidence/claims themselves).
"""
from __future__ import annotations

from orca.cognitive.contracts import FreshnessLevel
from orca.truth.contracts import Contradiction, ContradictionRelationship, EvidenceSource, EvidenceState

_FRESH_ENOUGH_FOR = {
    FreshnessLevel.REAL_TIME: {FreshnessLevel.REAL_TIME},
    FreshnessLevel.CURRENT: {FreshnessLevel.REAL_TIME, FreshnessLevel.CURRENT},
    FreshnessLevel.RECENT: {FreshnessLevel.REAL_TIME, FreshnessLevel.CURRENT, FreshnessLevel.RECENT},
    FreshnessLevel.LONG_LIVED: set(FreshnessLevel),
    FreshnessLevel.STATIC: set(FreshnessLevel),
}


def compute_evidence_state(
    citation_coverage_ratio: float | None,
    contradictions: list[Contradiction],
    sources: list[EvidenceSource],
    evidence_freshness: list[FreshnessLevel],
    freshness_required: FreshnessLevel,
    authority_required: bool,
) -> EvidenceState:
    if citation_coverage_ratio is None:
        return EvidenceState.INSUFFICIENT

    if any(c.relationship == ContradictionRelationship.DIRECT_CONTRADICTION for c in contradictions):
        return EvidenceState.CONFLICTED

    if authority_required and sources and not any(s.quality.is_official or s.quality.is_primary for s in sources):
        return EvidenceState.LOW_AUTHORITY

    fresh_enough = _FRESH_ENOUGH_FOR.get(freshness_required, set(FreshnessLevel))
    if evidence_freshness and not any(f in fresh_enough for f in evidence_freshness):
        return EvidenceState.STALE

    if citation_coverage_ratio >= 0.8:
        return EvidenceState.SUFFICIENT
    if citation_coverage_ratio > 0.0:
        return EvidenceState.PARTIAL
    return EvidenceState.INSUFFICIENT
