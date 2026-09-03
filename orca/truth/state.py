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
from orca.truth.contracts import Contradiction, ContradictionRelationship, EvidenceSource, EvidenceState, IndependenceState

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
        # Phase 13.1 §5 finding: orca.truth.provenance.annotate_independence()
        # computes IndependenceState/derived_from on each EvidenceSource, but
        # nothing downstream ever consulted it -- an evidence set entirely
        # composed of mutually-derived copies (an attacker flooding retrieval
        # with N mirrors/paraphrases of the same one origin) reached
        # SUFFICIENT exactly as if it had genuinely independent corroboration.
        # Real, minimal fix: when there are 2+ sources and EVERY one of them
        # is marked LIKELY_DERIVED (no source in the set is independent of, or
        # even merely unknown-relative-to, the others), a would-be SUFFICIENT
        # result is not upheld -- there is, in truth, only ONE corroborating
        # origin behind however many copies retrieval surfaced. Any set with
        # at least one UNKNOWN or INDEPENDENT source is unaffected: this is
        # deliberately narrow (only the all-derived, zero-diversity case),
        # matching this module's existing "never assert more than the
        # evidence supports" discipline rather than inventing a new
        # confidence-scoring scheme.
        if len(sources) >= 2 and all(s.independence == IndependenceState.LIKELY_DERIVED for s in sources):
            return EvidenceState.PARTIAL
        return EvidenceState.SUFFICIENT
    if citation_coverage_ratio > 0.0:
        return EvidenceState.PARTIAL
    return EvidenceState.INSUFFICIENT
