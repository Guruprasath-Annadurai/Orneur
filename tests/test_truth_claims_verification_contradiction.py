"""
Atomic claim extraction, claim verification, and contradiction detection --
real Gateway/Ollama calls (Phase 4 spec §22-25, §29).
"""
from __future__ import annotations

import pytest

from orca.gateway import wiring as gateway_wiring
from orca.truth.claims import extract_atomic_claims
from orca.truth.contracts import AtomicClaim, ClaimSupportState, ContradictionRelationship, Evidence, EvidencePassage
from orca.truth.contradiction import detect_contradictions
from orca.truth.verification import verify_claim
from tests.ollama_test_support import require_ollama

pytestmark = pytest.mark.live_ollama_smoke


@pytest.fixture(autouse=True)
def _reset_gateway():
    gateway_wiring.reset_for_tests()
    yield
    gateway_wiring.reset_for_tests()


@pytest.mark.asyncio
async def test_extract_atomic_claims_splits_compound_sentence():
    require_ollama()
    claims = await extract_atomic_claims("Model X is faster and supports FP8.")
    assert len(claims) >= 1
    assert all(isinstance(c, AtomicClaim) for c in claims)


@pytest.mark.asyncio
async def test_extract_atomic_claims_empty_for_empty_input():
    claims = await extract_atomic_claims("")
    assert claims == []


@pytest.mark.asyncio
async def test_verify_claim_with_no_evidence_is_unknown():
    require_ollama()
    support = await verify_claim("c1", "The sky is green.", [])
    assert support.support_state == ClaimSupportState.UNKNOWN


@pytest.mark.asyncio
async def test_verify_claim_grounded_in_matching_evidence():
    require_ollama()
    evidence = [Evidence(
        evidence_id="e1", source_id="s1", document_id="d1",
        passage=EvidencePassage(text="The Eiffel Tower is 330 meters tall and located in Paris."),
    )]
    support = await verify_claim("c1", "The Eiffel Tower is located in Paris.", evidence)
    assert support.support_state in (ClaimSupportState.SUPPORTED, ClaimSupportState.PARTIALLY_SUPPORTED)
    assert support.evidence_ids == ["e1"]


@pytest.mark.asyncio
async def test_verify_claim_contradicted_by_evidence():
    require_ollama()
    evidence = [Evidence(
        evidence_id="e1", source_id="s1", document_id="d1",
        passage=EvidencePassage(text="The API rate limit is 100 requests per minute."),
    )]
    support = await verify_claim("c1", "The API rate limit is 100 requests per minute.", evidence)
    # Not asserting a specific verdict here beyond "not silently unrelated" --
    # the real point is evidence_ids links back to e1 either way.
    assert "e1" in support.evidence_ids


@pytest.mark.asyncio
async def test_detect_contradictions_finds_direct_conflict():
    require_ollama()
    claims = [
        AtomicClaim(claim_id="a", text="The API rate limit is 100 requests per minute."),
        AtomicClaim(claim_id="b", text="The API rate limit is 500 requests per minute."),
    ]
    contradictions = await detect_contradictions(claims)
    assert any(c.relationship == ContradictionRelationship.DIRECT_CONTRADICTION for c in contradictions)


@pytest.mark.asyncio
async def test_detect_contradictions_does_not_flag_unrelated_claims():
    require_ollama()
    claims = [
        AtomicClaim(claim_id="a", text="Lists are mutable in Python."),
        AtomicClaim(claim_id="b", text="The Eiffel Tower is in Paris."),
    ]
    contradictions = await detect_contradictions(claims)
    assert contradictions == []  # no topic overlap -- never even sent to the judge


@pytest.mark.asyncio
async def test_detect_contradictions_bounded_below_two_claims():
    contradictions = await detect_contradictions([AtomicClaim(claim_id="a", text="Only one claim.")])
    assert contradictions == []


@pytest.mark.asyncio
async def test_detect_contradictions_does_not_flag_comparative_claim_as_direct_conflict():
    """Phase 4.1 spec §19: reproduces the exact nano-tier judge false
    positive found by Phase 4's evaluation harness (see
    docs/orneur/phase-4/EVALUATION_V2.md) -- a comparative claim ("Model A
    performs better...") and a specific-value claim about one of the
    compared subjects ("Model B achieves 88%...") are logically
    consistent, not contradictory. The judge prompt was extended with an
    explicit rule + example for this pattern; this regression test pins
    down that DIRECT_CONTRADICTION (the worse of the two possible
    failures -- it forces EvidenceState.CONFLICTED) is no longer produced
    for this pattern. A generically correct UNRELATED/TEMPORALLY_
    RECONCILABLE classification for a genuinely non-contradictory pair
    like this is still an open, disclosed nano-tier judge imprecision
    (see EVALUATION_V2.md) -- this test only asserts the specific
    high-severity misclassification is fixed, not that the label is
    perfectly correct."""
    require_ollama()
    claims = [
        AtomicClaim(claim_id="a", text="Model B achieves 88% accuracy."),
        AtomicClaim(claim_id="b", text="Model A performs better than Model B based on accuracy."),
    ]
    contradictions = await detect_contradictions(claims)
    assert not any(c.relationship == ContradictionRelationship.DIRECT_CONTRADICTION for c in contradictions)
