"""
Citation engine (claim-linked, never marker-presence-only) and evidence
sufficiency state -- pure, deterministic (Phase 4 spec §26-30).
"""
from __future__ import annotations

from orca.cognitive.contracts import FreshnessLevel
from orca.truth.citation import build_citations, compute_citation_coverage, reject_unsupported
from orca.truth.contracts import (
    AtomicClaim,
    CitationVerdictState,
    ClaimSupport,
    ClaimSupportState,
    Contradiction,
    ContradictionRelationship,
    EvidenceSource,
    SourceQuality,
    SourceType,
)
from orca.truth.state import compute_evidence_state


def _claim(cid="c1", text="A claim"):
    return AtomicClaim(claim_id=cid, text=text)


def test_unsupported_claim_produces_no_accepted_citation():
    support = ClaimSupport(claim_id="c1", evidence_ids=["e1"], support_state=ClaimSupportState.UNSUPPORTED)
    verdicts = build_citations([support])
    accepted = reject_unsupported(verdicts)
    assert len(verdicts) == 1
    assert verdicts[0].verdict == CitationVerdictState.UNSUPPORTED
    assert accepted == []


def test_supported_claim_produces_accepted_citation():
    support = ClaimSupport(claim_id="c1", evidence_ids=["e1"], support_state=ClaimSupportState.SUPPORTED)
    verdicts = build_citations([support])
    accepted = reject_unsupported(verdicts)
    assert len(accepted) == 1
    assert accepted[0].verdict == CitationVerdictState.SUPPORTED


def test_unknown_support_state_never_yields_a_supported_citation():
    """Regression guard: UNKNOWN must map to UNSUPPORTED, never silently
    upgraded (spec §27 -- 'do not emit unsupported citations as authoritative')."""
    support = ClaimSupport(claim_id="c1", evidence_ids=["e1"], support_state=ClaimSupportState.UNKNOWN)
    verdicts = build_citations([support])
    assert all(v.verdict != CitationVerdictState.SUPPORTED for v in verdicts)


def test_citation_candidate_only_from_evidence_the_verifier_actually_linked():
    """A claim with an evidence_id that appeared in retrieval but was
    never actually linked by the verifier must not appear as a citation."""
    support = ClaimSupport(claim_id="c1", evidence_ids=[], support_state=ClaimSupportState.UNSUPPORTED)
    verdicts = build_citations([support])
    assert verdicts == []  # no evidence_ids -- no candidates generated at all


def test_citation_coverage_counts():
    claims = [_claim("c1"), _claim("c2"), _claim("c3")]
    supports = [
        ClaimSupport(claim_id="c1", evidence_ids=["e1"], support_state=ClaimSupportState.SUPPORTED),
        ClaimSupport(claim_id="c2", evidence_ids=["e2"], support_state=ClaimSupportState.PARTIALLY_SUPPORTED),
        ClaimSupport(claim_id="c3", evidence_ids=[], support_state=ClaimSupportState.UNSUPPORTED),
    ]
    coverage = compute_citation_coverage(claims, supports)
    assert coverage["total_claims"] == 3
    assert coverage["supported_claims"] == 1
    assert coverage["partially_supported_claims"] == 1
    assert coverage["unsupported_claims"] == 1
    assert coverage["citation_coverage_ratio"] == round(2 / 3, 3)


def test_coverage_ratio_none_when_no_claims():
    coverage = compute_citation_coverage([], [])
    assert coverage["citation_coverage_ratio"] is None


# ── Evidence state ───────────────────────────────────────────────────────

def _source(official=False, community=False):
    return EvidenceSource(
        source_id="s1", identity="x", source_type=SourceType.WEB_SECONDARY,
        quality=SourceQuality(is_official=official, is_community=community),
    )


def test_no_coverage_is_insufficient():
    state = compute_evidence_state(None, [], [], [], FreshnessLevel.STATIC, False)
    assert state.value == "INSUFFICIENT"


def test_direct_contradiction_overrides_good_coverage():
    contradiction = Contradiction(claim_a_id="c1", claim_b_id="c2", relationship=ContradictionRelationship.DIRECT_CONTRADICTION)
    state = compute_evidence_state(0.95, [contradiction], [], [], FreshnessLevel.STATIC, False)
    assert state.value == "CONFLICTED"


def test_temporally_reconcilable_does_not_trigger_conflicted():
    contradiction = Contradiction(claim_a_id="c1", claim_b_id="c2", relationship=ContradictionRelationship.TEMPORALLY_RECONCILABLE)
    state = compute_evidence_state(0.95, [contradiction], [], [], FreshnessLevel.STATIC, False)
    assert state.value != "CONFLICTED"


def test_authority_required_but_no_official_source_is_low_authority():
    state = compute_evidence_state(0.9, [], [_source(official=False)], [], FreshnessLevel.STATIC, True)
    assert state.value == "LOW_AUTHORITY"


def test_authority_required_and_official_source_present_is_sufficient():
    state = compute_evidence_state(0.9, [], [_source(official=True)], [], FreshnessLevel.STATIC, True)
    assert state.value == "SUFFICIENT"


def test_stale_evidence_for_real_time_requirement():
    state = compute_evidence_state(0.9, [], [], [FreshnessLevel.STATIC], FreshnessLevel.REAL_TIME, False)
    assert state.value == "STALE"


def test_partial_coverage_is_partial_state():
    state = compute_evidence_state(0.4, [], [], [], FreshnessLevel.STATIC, False)
    assert state.value == "PARTIAL"
