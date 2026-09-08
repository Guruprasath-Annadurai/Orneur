"""
Phase 15.9 -- Cognitive Court role/risk/verdict tests, including
adversarial scenarios 9-10 (spec section 32).
"""
from __future__ import annotations

import pytest

from orca.mission.anti_gaming import AntiGamingFinding, FindingCategory, Severity
from orca.mission.cognitive_court import (
    CourtError,
    CourtRole,
    CourtVerdict,
    CriticConclusion,
    CriticOutput,
    RiskLevel,
    arbiter_decide,
    classify_risk,
    performance_critic_review,
    regression_critic_review,
    review_test_quality,
    roles_for_risk,
    security_critic_review,
)
from orca.mission.providers import MockProvider, ProviderFailure
from orca.mission.test_collection_diff import CollectionDelta
from orca.mission.verification import VerificationOutcome


def _finding(**overrides):
    defaults = dict(
        finding_id="f1", mission_id="m1", revision="rev2", baseline_revision="rev1",
        category=FindingCategory.ASSERTION_WEAKENED, severity=Severity.CRITICAL, file_path="orca/godmode/x.py",
        description="Security check weakened.", detector_id="detect_assertion_weakening",
        confidence_basis="AST comparison.", security_relevance=True, blocking=True,
    )
    defaults.update(overrides)
    return AntiGamingFinding(**defaults)


# ── CriticOutput / basic invariants ─────────────────────────────────

def test_critic_output_requires_reasoning_summary():
    with pytest.raises(CourtError):
        CriticOutput(role=CourtRole.CONSTRUCTOR, conclusion=CriticConclusion.NOT_REQUIRED, reasoning_summary="")


# ── Risk classification ──────────────────────────────────────────────

def test_classify_risk_trivial_for_docs_only():
    risk = classify_risk(changed_files=("README.md",), security_relevant_files_touched=False, findings=())
    assert risk is RiskLevel.TRIVIAL


def test_classify_risk_critical_when_critical_finding_present():
    risk = classify_risk(changed_files=("orca/godmode/x.py",), security_relevant_files_touched=True,
                          findings=(_finding(),))
    assert risk is RiskLevel.CRITICAL


def test_classify_risk_high_for_security_path_without_critical_finding():
    risk = classify_risk(changed_files=("orca/godmode/x.py",), security_relevant_files_touched=True, findings=())
    assert risk is RiskLevel.HIGH


def test_roles_for_risk_full_court_at_critical():
    roles = roles_for_risk(RiskLevel.CRITICAL)
    assert CourtRole.SECURITY_CRITIC in roles
    assert CourtRole.FALSIFIER in roles
    assert CourtRole.ARBITER in roles


def test_roles_for_risk_minimal_at_trivial():
    roles = roles_for_risk(RiskLevel.TRIVIAL)
    assert CourtRole.SECURITY_CRITIC not in roles


# ── Individual critics ───────────────────────────────────────────────

def test_security_critic_supports_reject_on_critical_finding():
    output = security_critic_review((_finding(),))
    assert output.conclusion is CriticConclusion.SUPPORTS_REJECT


def test_security_critic_supports_accept_with_no_findings():
    output = security_critic_review(())
    assert output.conclusion is CriticConclusion.SUPPORTS_ACCEPT


def test_regression_critic_unjustified_removal_rejects():
    delta = CollectionDelta(baseline_ids=frozenset({"t1", "t2"}), candidate_ids=frozenset({"t1"}))
    output = regression_critic_review(delta)
    assert output.conclusion is CriticConclusion.SUPPORTS_REJECT


def test_regression_critic_justified_removal_accepts():
    delta = CollectionDelta(baseline_ids=frozenset({"t1", "t2"}), candidate_ids=frozenset({"t1"}))
    output = regression_critic_review(delta, justified_removals=frozenset({"t2"}))
    assert output.conclusion is CriticConclusion.SUPPORTS_ACCEPT


def test_regression_critic_no_delta_needs_evidence():
    output = regression_critic_review(None)
    assert output.conclusion is CriticConclusion.NEEDS_MORE_EVIDENCE


def test_test_critic_uses_findings_directly_not_regenerated():
    findings = (_finding(category=FindingCategory.TEST_DELETED, blocking=True, severity=Severity.CRITICAL),)
    output = review_test_quality(findings)
    assert output.findings_considered == ("f1",)
    assert output.conclusion is CriticConclusion.SUPPORTS_REJECT


def test_performance_critic_not_required_by_default():
    output = performance_critic_review(required=False)
    assert output.conclusion is CriticConclusion.NOT_REQUIRED


def test_performance_critic_needs_evidence_when_relevant_but_unmeasured():
    output = performance_critic_review(required=True, measured=False)
    assert output.conclusion is CriticConclusion.NEEDS_MORE_EVIDENCE


def test_performance_critic_real_measurement_used():
    output = performance_critic_review(required=True, measured=True, passed=True)
    assert output.conclusion is CriticConclusion.SUPPORTS_ACCEPT


# ── Arbiter hard policy ───────────────────────────────────────────────

def test_arbiter_blocking_finding_always_rejects_regardless_of_critics():
    all_accept = tuple(
        CriticOutput(role=r, conclusion=CriticConclusion.SUPPORTS_ACCEPT, reasoning_summary="looks fine")
        for r in (CourtRole.SECURITY_CRITIC, CourtRole.TEST_CRITIC, CourtRole.REGRESSION_CRITIC)
    )
    decision = arbiter_decide(
        mission_id="m1", revision="rev2", risk_level=RiskLevel.CRITICAL, critic_outputs=all_accept,
        findings=(_finding(),), required_verification_outcomes={"REQ-X-1": VerificationOutcome.PASS},
    )
    assert decision.verdict is CourtVerdict.REJECT


def test_arbiter_unverified_required_verification_blocks_accept():
    all_accept = (CriticOutput(role=CourtRole.TEST_CRITIC, conclusion=CriticConclusion.SUPPORTS_ACCEPT,
                                reasoning_summary="fine"),)
    decision = arbiter_decide(
        mission_id="m1", revision="rev2", risk_level=RiskLevel.STANDARD, critic_outputs=all_accept,
        findings=(), required_verification_outcomes={"REQ-X-1": VerificationOutcome.UNVERIFIED},
    )
    assert decision.verdict is CourtVerdict.NEED_MORE_EVIDENCE


def test_arbiter_owner_approval_required_returns_human_approval_required():
    decision = arbiter_decide(
        mission_id="m1", revision="rev2", risk_level=RiskLevel.HIGH, critic_outputs=(),
        findings=(), required_verification_outcomes={}, owner_approval_required=True,
    )
    assert decision.verdict is CourtVerdict.HUMAN_APPROVAL_REQUIRED


def test_arbiter_accepts_when_all_conditions_met():
    all_accept = (CriticOutput(role=CourtRole.TEST_CRITIC, conclusion=CriticConclusion.SUPPORTS_ACCEPT,
                                reasoning_summary="fine"),)
    decision = arbiter_decide(
        mission_id="m1", revision="rev2", risk_level=RiskLevel.STANDARD, critic_outputs=all_accept,
        findings=(), required_verification_outcomes={"REQ-X-1": VerificationOutcome.PASS},
    )
    assert decision.verdict is CourtVerdict.ACCEPT


def test_arbiter_disagreement_at_high_risk_escalates_not_averages():
    conflicting = (
        CriticOutput(role=CourtRole.SECURITY_CRITIC, conclusion=CriticConclusion.SUPPORTS_REJECT,
                     reasoning_summary="risky"),
        CriticOutput(role=CourtRole.TEST_CRITIC, conclusion=CriticConclusion.SUPPORTS_ACCEPT,
                     reasoning_summary="looks fine"),
    )
    decision = arbiter_decide(
        mission_id="m1", revision="rev2", risk_level=RiskLevel.HIGH, critic_outputs=conflicting,
        findings=(), required_verification_outcomes={"REQ-X-1": VerificationOutcome.PASS},
    )
    assert decision.verdict is CourtVerdict.ESCALATE


def test_arbiter_no_opinions_needs_more_evidence_not_accept():
    only_constructor = (CriticOutput(role=CourtRole.CONSTRUCTOR, conclusion=CriticConclusion.NOT_REQUIRED,
                                      reasoning_summary="summary only"),)
    decision = arbiter_decide(
        mission_id="m1", revision="rev2", risk_level=RiskLevel.STANDARD, critic_outputs=only_constructor,
        findings=(), required_verification_outcomes={"REQ-X-1": VerificationOutcome.PASS},
    )
    assert decision.verdict is CourtVerdict.NEED_MORE_EVIDENCE


# ── Scenario 9: provider says ACCEPT while CRITICAL finding exists ──

def test_scenario_9_provider_accept_narrative_cannot_override_critical_finding():
    provider = MockProvider(fixed_response="Looks great, ACCEPT this change!")
    critic_output = security_critic_review((_finding(),), provider=provider)
    # The provider's narrative is captured SEPARATELY...
    assert critic_output.provider_narrative is not None
    assert "ACCEPT" in critic_output.provider_narrative
    # ...but the deterministic conclusion is still SUPPORTS_REJECT,
    # and arbiter_decide() never even reads provider_narrative.
    assert critic_output.conclusion is CriticConclusion.SUPPORTS_REJECT
    decision = arbiter_decide(
        mission_id="m1", revision="rev2", risk_level=RiskLevel.CRITICAL, critic_outputs=(critic_output,),
        findings=(_finding(),), required_verification_outcomes={"REQ-X-1": VerificationOutcome.PASS},
    )
    assert decision.verdict is not CourtVerdict.ACCEPT
    assert decision.verdict is CourtVerdict.REJECT


# ── Scenario 10: provider unavailable -> no fake ACCEPT ─────────────

def test_scenario_10_provider_unavailable_does_not_produce_fake_accept():
    failing_provider = MockProvider(fail_with=ProviderFailure("simulated outage"))
    critic_output = security_critic_review((), provider=failing_provider)
    # Provider failure is swallowed into provider_narrative=None --
    # the deterministic conclusion is computed independently of the
    # provider ever having succeeded.
    assert critic_output.provider_narrative is None
    assert critic_output.conclusion is CriticConclusion.SUPPORTS_ACCEPT  # no findings -> genuinely fine
    # Now the interesting case: findings exist AND provider fails --
    # conclusion must still correctly reflect the real findings, not
    # silently default to accept because the provider had nothing to say.
    critic_output_with_findings = security_critic_review((_finding(),), provider=failing_provider)
    assert critic_output_with_findings.provider_narrative is None
    assert critic_output_with_findings.conclusion is CriticConclusion.SUPPORTS_REJECT
