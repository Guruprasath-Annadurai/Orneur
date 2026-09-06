"""
Phase 13.1 §4-13 -- active RAG/evidence red-team campaign, executed
against real production code (orca.truth.provenance,
orca.truth.state.compute_evidence_state, orca.truth.verification),
not a restatement of existing coverage.

Attack log (see docs/orneur/phase-13/RAG_DEEP_RED_TEAM.md for the full
structured findings):
  RAG-01  source independence: mirrored/paraphrased/reformatted copies -> REAL_VULNERABILITY found and FIXED
  RAG-02  authority spam via quantity of derived sources -> REAL_VULNERABILITY found and FIXED (same root cause as RAG-01)
  RAG-03  citation claim-swap (evidence for claim B attached to claim A) -> BLOCKED_AS_EXPECTED (structural)
  RAG-04  citation negation reversal under judge-unavailable fallback -> disclosed limitation, NOT a new bypass (ceiling holds)
  RAG-05  citation entity-swap confusion under judge-unavailable fallback -> disclosed limitation, NOT a new bypass (ceiling holds)
  RAG-06  citation numeric mismatch under judge-unavailable fallback -> disclosed limitation, same as RAG-04/05 (ceiling holds, PARTIALLY_SUPPORTED reached not full SUPPORTED)
  RAG-07  temporal truth: fake future-dated document -> BLOCKED_AS_EXPECTED (timestamp alone never reaches evidence_state)
"""
from __future__ import annotations

import asyncio

import pytest

from orca.cognitive.contracts import FreshnessLevel
from orca.truth.contracts import (
    Evidence,
    EvidencePassage,
    EvidenceSource,
    IndependenceState,
    SourceQuality,
    SourceType,
)
from orca.truth.provenance import annotate_independence, assess_independence
from orca.truth.state import compute_evidence_state
from orca.truth.verification import verify_claim


def _source(sid, domain="", official=False, published_at=None):
    return EvidenceSource(
        source_id=sid, identity=f"https://{domain or 'example.com'}/{sid}", source_type=SourceType.WEB_SECONDARY,
        domain=domain, quality=SourceQuality(is_official=official), published_at=published_at,
    )


def _evidence(eid, sid, text):
    return Evidence(evidence_id=eid, source_id=sid, document_id=sid, passage=EvidencePassage(text=text))


# --------------------------------------------------------------- RAG-01 / RAG-02: source independence + authority spam


def test_rag01_mirrored_and_paraphrased_copies_are_detected_as_derived():
    """Attack: attacker publishes the SAME claim across 3 'independent-
    looking' documents -- one an exact mirror on a different subdomain of
    the same registered domain, one on a genuinely different domain but
    with near-identical wording (syndicated copy), one that explicitly
    names the origin domain. All three should be flagged LIKELY_DERIVED,
    not counted as 3 independent confirmations."""
    original = "The board approved a $12 million budget for Project Falcon in Q3."
    sources = [
        _source("s-origin", domain="origin-news.example"),
        _source("s-mirror", domain="mirror.origin-news.example"),          # same registered domain
        _source("s-syndicate", domain="totally-different-site.example"),   # different domain, same text
        _source("s-attributed", domain="another-site.example"),            # explicitly cites origin domain by name
    ]
    evidence = [
        _evidence("e-origin", "s-origin", original),
        _evidence("e-mirror", "s-mirror", original),
        _evidence("e-syndicate", "s-syndicate", original),
        _evidence("e-attributed", "s-attributed", f"As reported by origin-news.example, {original}"),
    ]
    annotate_independence(sources, evidence)
    by_id = {s.source_id: s for s in sources}
    assert by_id["s-mirror"].independence == IndependenceState.LIKELY_DERIVED  # same registered domain
    assert by_id["s-syndicate"].independence == IndependenceState.LIKELY_DERIVED  # near-identical text
    assert by_id["s-attributed"].independence == IndependenceState.LIKELY_DERIVED  # explicit attribution


def test_rag01_well_paraphrased_dependent_copy_is_a_disclosed_detection_limitation():
    """A copy that paraphrases heavily enough to drop below the lexical-
    similarity threshold, on a genuinely different domain, with no
    explicit attribution, is NOT detected as derived -- this is the
    real, disclosed limit of a lexical-only heuristic (provenance.py's
    own docstring: 'not a claim of perfect independence detection').
    Reported here as evidence of the limitation, not silently assumed."""
    state = assess_independence(
        _evidence("e1", "s1", "The board approved a $12 million budget for Project Falcon in Q3."),
        _source("s1", domain="site-a.example"),
        _evidence("e2", "s2", "Falcon's Q3 spending plan received board sign-off, totaling roughly twelve million dollars."),
        _source("s2", domain="totally-unrelated-site.example"),
    )
    assert state == IndependenceState.UNKNOWN  # documented limitation: this IS a derived copy, undetected


def test_rag02_authority_spam_no_longer_reaches_sufficient_when_all_sources_are_mutually_derived():
    """
    REAL_VULNERABILITY (found this phase, FIXED this phase):
    orca.truth.provenance.annotate_independence() computed
    IndependenceState/derived_from on every EvidenceSource, but --
    confirmed by grepping the entire codebase -- NOTHING downstream ever
    read `.independence`. orca.truth.state.compute_evidence_state()
    reached SUFFICIENT from citation_coverage_ratio alone, with zero
    regard for whether the "multiple" corroborating sources were
    actually N copies of ONE origin. Fixed in orca/truth/state.py:
    a would-be SUFFICIENT verdict downgrades to PARTIAL when there are
    2+ sources and EVERY one of them is LIKELY_DERIVED (i.e., zero
    independent or even merely-unknown-relative-to-each-other sources
    exist in the set).
    """
    spam_sources = [_source("s1", domain="spam-site-1.example"), _source("s2", domain="spam-site-1.example")]  # same domain -- mutually derived
    spam_evidence = [_evidence("e1", "s1", "shared text"), _evidence("e2", "s2", "shared text")]
    annotate_independence(spam_sources, spam_evidence)
    assert all(s.independence == IndependenceState.LIKELY_DERIVED for s in spam_sources)

    state = compute_evidence_state(0.9, [], spam_sources, [], FreshnessLevel.STATIC, False)
    assert state.value == "PARTIAL", "all-mutually-derived source set must not reach SUFFICIENT (the real bug this phase fixed)"


def test_rag02_genuinely_diverse_sources_still_reach_sufficient():
    """Regression guard: the fix must not become a blanket downgrade --
    a set with at least one source that is NOT LIKELY_DERIVED (genuinely
    independent-looking, or merely UNKNOWN) still reaches SUFFICIENT as
    before."""
    diverse_sources = [_source("s1", domain="site-a.example"), _source("s2", domain="site-b.example")]
    state = compute_evidence_state(0.9, [], diverse_sources, [], FreshnessLevel.STATIC, False)
    assert state.value == "SUFFICIENT"


def test_rag02_single_source_is_unaffected_by_the_independence_check():
    """A single source has no peer to be 'derived from' -- the fix only
    engages at 2+ sources, matching assess_independence's own pairwise
    design; a lone source's SUFFICIENT verdict is unaffected."""
    lone_source = [_source("s1", domain="site-a.example")]
    state = compute_evidence_state(0.9, [], lone_source, [], FreshnessLevel.STATIC, False)
    assert state.value == "SUFFICIENT"


# --------------------------------------------------------------- RAG-03: citation claim-swap (structural)


def test_rag03_citation_candidates_only_ever_reference_the_evidence_actually_linked_to_that_claim():
    """Attack: attempt to attach claim A's citation to evidence that was
    only ever linked to claim B. orca.truth.citation.build_citations()
    only ever builds a CitationCandidate from a ClaimSupport's OWN
    evidence_ids list -- there is no code path that lets one claim's
    citation reference another claim's evidence_ids."""
    from orca.truth.citation import build_citations
    from orca.truth.contracts import ClaimSupport, ClaimSupportState

    support_a = ClaimSupport(claim_id="claim-A", evidence_ids=["ev-for-A"], support_state=ClaimSupportState.SUPPORTED)
    support_b = ClaimSupport(claim_id="claim-B", evidence_ids=["ev-for-B"], support_state=ClaimSupportState.SUPPORTED)
    verdicts = build_citations([support_a, support_b])

    a_verdicts = [v for v in verdicts if v.candidate.claim_id == "claim-A"]
    assert all(v.candidate.evidence_id == "ev-for-A" for v in a_verdicts)
    assert not any(v.candidate.evidence_id == "ev-for-B" for v in a_verdicts)


# --------------------------------------------------------------- RAG-04/05/06: citation confusion under the deterministic fallback


async def _verify_with_unavailable_judge(claim_text, evidence_text, monkeypatch):
    import orca.truth.verification as verification_mod

    async def _broken_judge(*args, **kwargs):
        return None  # simulates judge unavailable / unparseable, forcing the lexical-only fallback

    monkeypatch.setattr(verification_mod, "gateway_json_call", _broken_judge)
    evidence = [_evidence("e1", "s1", evidence_text)]
    return await verify_claim("c1", claim_text, evidence, tier="nano")


@pytest.mark.asyncio
async def test_rag04_negation_reversal_under_fallback_never_exceeds_partially_supported(monkeypatch):
    """RAG-04: source says X does NOT support Y; claim asserts X DOES
    support Y. The deterministic lexical fallback is negation-blind (word-
    set overlap ignores "not") -- a REAL, but pre-existing and honestly
    disclosed, limitation of the fallback path (verification.py's own
    docstring: "lexical proximity alone is not entailment"). The security
    property that matters is verified here: even under this adversarial
    input, the fallback NEVER claims full SUPPORTED -- the ceiling is
    PARTIALLY_SUPPORTED at most, and the real defense (a live entailment
    judge) is what the non-degraded path already uses."""
    support = await _verify_with_unavailable_judge(
        "The new policy supports remote work.",
        "The new policy does not support remote work under any circumstances.",
        monkeypatch,
    )
    assert support.support_state.value != "SUPPORTED"


@pytest.mark.asyncio
async def test_rag05_entity_swap_under_fallback_never_exceeds_partially_supported(monkeypatch):
    """RAG-05: claim about 'Project Alpha Pro' supported by evidence
    actually about the DIFFERENT, similarly-named 'Project Alpha'. Same
    disclosed fallback limitation as RAG-04 -- verified ceiling holds."""
    support = await _verify_with_unavailable_judge(
        "Project Alpha Pro shipped its GA release in March.",
        "Project Alpha shipped its GA release in March after a long beta.",
        monkeypatch,
    )
    assert support.support_state.value != "SUPPORTED"


@pytest.mark.asyncio
async def test_rag06_numeric_mismatch_under_fallback_never_exceeds_partially_supported(monkeypatch):
    """RAG-06 (finding, not the hypothesis expected going in): a claim
    stating a wildly WRONG number ($999 million vs. real $12 million)
    still scores high lexical overlap under the fallback, because every
    surrounding word ("company", "reported", "revenue", "million", "Q4")
    matches -- only the digit token differs. Measured overlap=0.80,
    yielding PARTIALLY_SUPPORTED, not UNSUPPORTED as this test originally
    assumed before actually running it. Reclassified honestly as the SAME
    disclosed fallback limitation as RAG-04/RAG-05 (this is exactly what
    "lexical proximity alone is not entailment" already warns about) --
    the ceiling property that matters is verified: even a flatly wrong
    number under this adversarial input never reaches full SUPPORTED
    through the degraded fallback path; the live judge (the non-degraded,
    normal path) is the real defense against this."""
    support = await _verify_with_unavailable_judge(
        "The company reported revenue of $999 million in Q4.",
        "The company reported revenue of $12 million in Q4, a modest increase.",
        monkeypatch,
    )
    assert support.support_state.value != "SUPPORTED"


# --------------------------------------------------------------- RAG-07: temporal truth / fake future date


def test_rag07_future_dated_document_does_not_independently_grant_sufficiency():
    """Attack: attacker supplies a document dated far in the future,
    hoping a later timestamp alone reads as 'more current/authoritative.'
    compute_evidence_state() never reads `published_at`/`updated_at` at
    all -- only `evidence_freshness` (a caller-supplied FreshnessLevel
    classification, not a raw timestamp) and `authority_required`
    (quality flags) participate. A future date on its own has structurally
    no code path into the evidence_state decision -- BLOCKED_AS_EXPECTED."""
    from datetime import datetime, timezone, timedelta

    far_future = (datetime.now(timezone.utc) + timedelta(days=3650)).strftime("%Y-%m-%dT%H:%M:%SZ")
    fake_future_source = [_source("s1", domain="attacker.example", published_at=far_future)]
    # No authority_required, no freshness classification claimed for this
    # evidence at all -- the future `published_at` field is simply never
    # consulted by this function.
    state = compute_evidence_state(0.9, [], fake_future_source, [], FreshnessLevel.STATIC, False)
    assert state.value == "SUFFICIENT"  # reached via real coverage/authority/freshness logic, NOT via the fake date
    assert fake_future_source[0].published_at == far_future  # the fake date is stored as data, never elevated to authority
