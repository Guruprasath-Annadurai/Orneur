"""
Phase 6: EvidenceClerk, RiskCounsel, Arbiter -- deterministic, no
Ollama. Court orchestration itself (live-Ollama) is covered separately
in tests/test_deliberation_court_integration.py.
"""
from __future__ import annotations

from orca.cognitive.contracts import RiskLevel
from orca.deliberation.arbiter import arbitrate
from orca.deliberation.contracts import Argument, CounterArgument, CourtVerdictState, TwinResult
from orca.deliberation.evidence_clerk import build_evidence_report
from orca.deliberation.risk_counsel import assess_risk_opinion


def _twin(claims, objections=None, counter_evidence=None, unsupported=None, unresolved=None):
    objections = objections or []
    disputed = {o.target_argument_id for o in objections}
    surviving = [c.argument_id for c in claims if c.argument_id not in disputed]
    return TwinResult(
        constructor_claims=claims, falsifier_objections=objections,
        counter_evidence_ids=counter_evidence or [], unsupported_assumption_ids=unsupported or [],
        disputed_claim_ids=list(disputed), surviving_claim_ids=surviving, unresolved_questions=unresolved or [],
    )


# ── EvidenceClerk ────────────────────────────────────────────────────

def test_evidence_clerk_flags_claims_missing_evidence():
    claims = [Argument(claim="a", evidence_ids=["ev1"]), Argument(claim="b", evidence_ids=[])]
    report = build_evidence_report(claims)
    assert len(report.claims_with_evidence) == 1
    assert len(report.claims_missing_evidence) == 1
    assert "1 claim" in report.missing_evidence_note


def test_evidence_clerk_does_not_decide_anything():
    """EvidenceClerk's output has no verdict/accept/reject field at
    all -- structurally cannot decide the case."""
    from dataclasses import fields
    field_names = {f.name for f in fields(build_evidence_report([]).__class__)}
    assert not any("verdict" in f or "accept" in f or "reject" in f for f in field_names)


# ── RiskCounsel ──────────────────────────────────────────────────────

def test_risk_counsel_critical_always_recommends_human_approval():
    from orca.deliberation.evidence_clerk import EvidenceReport
    opinion = assess_risk_opinion(RiskLevel.CRITICAL, EvidenceReport(), [])
    assert opinion.recommendation == "human_approval"


def test_risk_counsel_never_authorizes():
    """Structural check: RiskOpinion has no field granting permission."""
    from dataclasses import fields
    from orca.deliberation.risk_counsel import RiskOpinion
    field_names = {f.name for f in fields(RiskOpinion)}
    assert not any("authoriz" in f or "grant" in f or "permit" in f for f in field_names)


def test_risk_counsel_low_risk_clean_evidence_recommends_proceed():
    from orca.deliberation.evidence_clerk import EvidenceReport
    opinion = assess_risk_opinion(RiskLevel.LOW, EvidenceReport(), [])
    assert opinion.recommendation == "proceed"


def test_risk_counsel_high_risk_with_contradiction_recommends_more_verification():
    from orca.deliberation.evidence_clerk import EvidenceReport
    report = EvidenceReport(direct_contradiction_count=1)
    opinion = assess_risk_opinion(RiskLevel.HIGH, report, [])
    assert opinion.recommendation == "more_verification"


# ── Arbiter ──────────────────────────────────────────────────────────

def test_arbiter_no_claims_is_insufficient_evidence():
    from orca.deliberation.evidence_clerk import EvidenceReport
    from orca.deliberation.risk_counsel import RiskOpinion
    verdict = arbitrate(_twin([]), EvidenceReport(), RiskOpinion(recommendation="proceed"))
    assert verdict.verdict == CourtVerdictState.INSUFFICIENT_EVIDENCE


def test_arbiter_clean_claims_no_disputes_is_accept():
    from orca.deliberation.evidence_clerk import EvidenceReport
    from orca.deliberation.risk_counsel import RiskOpinion
    claims = [Argument(claim="a", evidence_ids=["ev1"])]
    verdict = arbitrate(_twin(claims), EvidenceReport(claims_with_evidence=[claims[0].argument_id]), RiskOpinion(recommendation="proceed"))
    assert verdict.verdict == CourtVerdictState.ACCEPT
    assert claims[0].argument_id in verdict.accepted_claim_ids


def test_arbiter_all_disputed_with_counter_evidence_is_reject():
    from orca.deliberation.evidence_clerk import EvidenceReport
    from orca.deliberation.risk_counsel import RiskOpinion
    claim = Argument(claim="a", evidence_ids=["ev1"])
    objection = CounterArgument(target_argument_id=claim.argument_id, objection="wrong", objection_kind="counter_evidence", counter_evidence_ids=["ev2"])
    twin = _twin([claim], objections=[objection], counter_evidence=["ev2"])
    verdict = arbitrate(twin, EvidenceReport(), RiskOpinion(recommendation="proceed"))
    assert verdict.verdict == CourtVerdictState.REJECT


def test_arbiter_partial_dispute_is_revise():
    from orca.deliberation.evidence_clerk import EvidenceReport
    from orca.deliberation.risk_counsel import RiskOpinion
    c1, c2 = Argument(claim="a", evidence_ids=["ev1"]), Argument(claim="b", evidence_ids=["ev2"])
    objection = CounterArgument(target_argument_id=c1.argument_id, objection="issue", objection_kind="edge_case")
    twin = _twin([c1, c2], objections=[objection])
    verdict = arbitrate(twin, EvidenceReport(), RiskOpinion(recommendation="proceed"))
    assert verdict.verdict == CourtVerdictState.REVISE
    assert c2.argument_id in verdict.accepted_claim_ids
    assert c1.argument_id in verdict.unresolved_claim_ids


def test_arbiter_critical_unresolved_contradiction_blocks_accept_at_high_risk():
    """Spec §39: for AUDIT_GRADE/high-risk decisions, a critical
    unresolved contradiction must normally prevent ACCEPT, even with
    otherwise-clean, undisputed claims."""
    from orca.deliberation.evidence_clerk import EvidenceReport
    from orca.deliberation.risk_counsel import RiskOpinion
    claim = Argument(claim="a", evidence_ids=["ev1"])
    report = EvidenceReport(direct_contradiction_count=1)
    verdict = arbitrate(_twin([claim]), report, RiskOpinion(recommendation="proceed", risk_level=RiskLevel.HIGH), audit_grade=False)
    assert verdict.verdict == CourtVerdictState.INSUFFICIENT_EVIDENCE


def test_arbiter_human_approval_recommendation_blocks_accept():
    from orca.deliberation.evidence_clerk import EvidenceReport
    from orca.deliberation.risk_counsel import RiskOpinion
    claim = Argument(claim="a", evidence_ids=["ev1"])
    verdict = arbitrate(_twin([claim]), EvidenceReport(), RiskOpinion(recommendation="human_approval", risk_level=RiskLevel.CRITICAL))
    assert verdict.verdict == CourtVerdictState.INSUFFICIENT_EVIDENCE


def test_arbiter_never_stores_raw_chain_of_thought():
    """Structural check on CourtVerdict's own field set (spec §19)."""
    from dataclasses import fields
    from orca.deliberation.contracts import CourtVerdict
    field_names = {f.name for f in fields(CourtVerdict)}
    assert not any("raw" in f or "chain_of_thought" in f or "thinking" in f for f in field_names)
