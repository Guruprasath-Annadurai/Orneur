"""
Citation engine (Phase 4 spec §26-28) -- generates CitationCandidates ONLY
from evidence a ClaimVerifier actually found supporting, and produces
CitationVerdicts + coverage metrics. This is what makes citation
enforcement claim-linked rather than marker-presence-only (the limitation
documented for orca/docs/citation_check.py in CURRENT_TRUTH_PIPELINE.md).
"""
from __future__ import annotations

from orca.truth.contracts import (
    AtomicClaim,
    CitationCandidate,
    CitationVerdict,
    CitationVerdictState,
    ClaimSupport,
    ClaimSupportState,
)

_SUPPORT_TO_VERDICT: dict[ClaimSupportState, CitationVerdictState] = {
    ClaimSupportState.SUPPORTED: CitationVerdictState.SUPPORTED,
    ClaimSupportState.PARTIALLY_SUPPORTED: CitationVerdictState.PARTIAL,
    ClaimSupportState.CONTRADICTED: CitationVerdictState.CONTRADICTED,
    # UNSUPPORTED and UNKNOWN both map to UNSUPPORTED verdicts -- an
    # unresolved claim must never be presented as if it had a verified
    # citation (spec §27: "Do not emit unsupported citations as authoritative").
    ClaimSupportState.UNSUPPORTED: CitationVerdictState.UNSUPPORTED,
    ClaimSupportState.UNKNOWN: CitationVerdictState.UNSUPPORTED,
}


def build_citations(claim_supports: list[ClaimSupport]) -> list[CitationVerdict]:
    """
    One CitationCandidate/CitationVerdict per (claim, evidence) pair the
    verifier actually linked -- never attaches a source just because it
    appeared somewhere in retrieval context (spec §26).
    """
    verdicts: list[CitationVerdict] = []
    for support in claim_supports:
        verdict_state = _SUPPORT_TO_VERDICT[support.support_state]
        for evidence_id in support.evidence_ids:
            candidate = CitationCandidate(claim_id=support.claim_id, source_id="", evidence_id=evidence_id)
            verdicts.append(CitationVerdict(candidate=candidate, verdict=verdict_state, reasons=list(support.reasons)))
    return verdicts


def reject_unsupported(verdicts: list[CitationVerdict]) -> list[CitationVerdict]:
    """Only SUPPORTED/PARTIAL citations may be presented as authoritative
    to a user; UNSUPPORTED/CONTRADICTED are filtered out here rather than
    left for a caller to forget to check (spec §27)."""
    return [v for v in verdicts if v.verdict in (CitationVerdictState.SUPPORTED, CitationVerdictState.PARTIAL)]


def compute_citation_coverage(claims: list[AtomicClaim], claim_supports: list[ClaimSupport]) -> dict:
    """Spec §28: factual claims, supported factual claims, claims with
    verified citations, unsupported claims."""
    support_by_claim = {s.claim_id: s for s in claim_supports}
    total = len(claims)
    supported = sum(1 for c in claims if support_by_claim.get(c.claim_id, ClaimSupport(c.claim_id, [], ClaimSupportState.UNKNOWN)).support_state == ClaimSupportState.SUPPORTED)
    partially_supported = sum(1 for c in claims if support_by_claim.get(c.claim_id, ClaimSupport(c.claim_id, [], ClaimSupportState.UNKNOWN)).support_state == ClaimSupportState.PARTIALLY_SUPPORTED)
    unsupported = sum(1 for c in claims if support_by_claim.get(c.claim_id, ClaimSupport(c.claim_id, [], ClaimSupportState.UNKNOWN)).support_state in (ClaimSupportState.UNSUPPORTED, ClaimSupportState.UNKNOWN))
    contradicted = sum(1 for c in claims if support_by_claim.get(c.claim_id, ClaimSupport(c.claim_id, [], ClaimSupportState.UNKNOWN)).support_state == ClaimSupportState.CONTRADICTED)

    return {
        "total_claims": total,
        "supported_claims": supported,
        "partially_supported_claims": partially_supported,
        "unsupported_claims": unsupported,
        "contradicted_claims": contradicted,
        "citation_coverage_ratio": round((supported + partially_supported) / total, 3) if total else None,
    }
