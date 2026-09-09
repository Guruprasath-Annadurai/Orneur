"""
Phase 15.9 -- Cognitive Court role/risk/verdict tests, including
adversarial scenarios 9-10 (spec section 32).
"""
from __future__ import annotations

import pytest

from orca.mission import acceptance_criteria as ac_module
from orca.mission import requirements as requirements_module
from orca.mission.acceptance_criteria import VerificationMethod
from orca.mission.anti_gaming import AntiGamingFinding, FindingCategory, Severity
from orca.mission.cognitive_court import (
    CourtConfigurationError,
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
from orca.mission.verification import VerificationOutcome, VerificationRecord
from orca.mission.verification_aggregation import RequiredVerificationScope

_UNIT_TEST_SCOPE = RequiredVerificationScope(requirement_level_categories=frozenset({"UNIT_TEST"}))
_CRIT_SCOPE = RequiredVerificationScope(criterion_ids=frozenset({"c1", "c2"}))


def _finding(**overrides):
    defaults = dict(
        finding_id="f1", mission_id="m1", revision="rev2", baseline_revision="rev1",
        category=FindingCategory.ASSERTION_WEAKENED, severity=Severity.CRITICAL, file_path="orca/godmode/x.py",
        description="Security check weakened.", detector_id="detect_assertion_weakening",
        confidence_basis="AST comparison.", security_relevance=True, blocking=True,
    )
    defaults.update(overrides)
    return AntiGamingFinding(**defaults)


def _record(requirement_id="REQ-X-1", outcome=VerificationOutcome.PASS, mission_id="m1", revision="rev2", **overrides):
    defaults = dict(
        id=f"ver_{requirement_id}_{mission_id}_{revision}", mission_id=mission_id, requirement_id=requirement_id,
        criterion_id=None, category="UNIT_TEST", verification_method="UNIT_TEST", verifier_id="UnitTestVerifier",
        started_at="2026-01-01T00:00:00Z", outcome=outcome, revision=revision,
        evidence_refs=("x",) if outcome == VerificationOutcome.PASS else (),
    )
    defaults.update(overrides)
    return VerificationRecord(**defaults)


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
    # Phase 15.9.1 closure item 7: "full court" now genuinely means
    # every role, including PERFORMANCE_CRITIC -- which was
    # previously omitted from the branch commented as "full court."
    roles = roles_for_risk(RiskLevel.CRITICAL)
    assert CourtRole.SECURITY_CRITIC in roles
    assert CourtRole.FALSIFIER in roles
    assert CourtRole.PERFORMANCE_CRITIC in roles
    assert CourtRole.ARBITER in roles
    assert set(roles) == {
        CourtRole.CONSTRUCTOR, CourtRole.FALSIFIER, CourtRole.SECURITY_CRITIC,
        CourtRole.REGRESSION_CRITIC, CourtRole.TEST_CRITIC, CourtRole.PERFORMANCE_CRITIC, CourtRole.ARBITER,
    }


def test_roles_for_risk_full_court_at_high_also_includes_performance():
    roles = roles_for_risk(RiskLevel.HIGH)
    assert CourtRole.PERFORMANCE_CRITIC in roles


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
        findings=(_finding(),), required_verification_records={"REQ-X-1": (_record(),)},
        required_requirement_ids=("REQ-X-1",),
        required_scopes_by_requirement={"REQ-X-1": _UNIT_TEST_SCOPE},
    )
    assert decision.verdict is CourtVerdict.REJECT
    assert decision.verification_refs == ()


def test_arbiter_unverified_required_verification_blocks_accept():
    all_accept = (CriticOutput(role=CourtRole.TEST_CRITIC, conclusion=CriticConclusion.SUPPORTS_ACCEPT,
                                reasoning_summary="fine"),)
    decision = arbiter_decide(
        mission_id="m1", revision="rev2", risk_level=RiskLevel.STANDARD, critic_outputs=all_accept,
        findings=(), required_verification_records={"REQ-X-1": (_record(outcome=VerificationOutcome.UNVERIFIED),)},
        required_requirement_ids=("REQ-X-1",),
        required_scopes_by_requirement={"REQ-X-1": _UNIT_TEST_SCOPE},
    )
    assert decision.verdict is CourtVerdict.NEED_MORE_EVIDENCE
    assert decision.verification_refs == ()


def test_arbiter_owner_approval_required_returns_human_approval_required():
    decision = arbiter_decide(
        mission_id="m1", revision="rev2", risk_level=RiskLevel.HIGH, critic_outputs=(),
        findings=(), required_verification_records={}, required_requirement_ids=("REQ-X-1",),
        required_scopes_by_requirement={"REQ-X-1": _UNIT_TEST_SCOPE},
        owner_approval_required=True,
    )
    assert decision.verdict is CourtVerdict.HUMAN_APPROVAL_REQUIRED


def test_arbiter_accepts_when_all_conditions_met():
    all_accept = (CriticOutput(role=CourtRole.TEST_CRITIC, conclusion=CriticConclusion.SUPPORTS_ACCEPT,
                                reasoning_summary="fine"),)
    record = _record()
    decision = arbiter_decide(
        mission_id="m1", revision="rev2", risk_level=RiskLevel.STANDARD, critic_outputs=all_accept,
        findings=(), required_verification_records={"REQ-X-1": (record,)},
        required_requirement_ids=("REQ-X-1",),
        required_scopes_by_requirement={"REQ-X-1": _UNIT_TEST_SCOPE},
    )
    assert decision.verdict is CourtVerdict.ACCEPT
    # verification_refs is populated with the REAL record id that
    # supported the ACCEPT -- never empty for a genuine accept.
    assert decision.verification_refs == (record.id,)


def test_arbiter_disagreement_at_high_risk_escalates_not_averages():
    conflicting = (
        CriticOutput(role=CourtRole.SECURITY_CRITIC, conclusion=CriticConclusion.SUPPORTS_REJECT,
                     reasoning_summary="risky"),
        CriticOutput(role=CourtRole.TEST_CRITIC, conclusion=CriticConclusion.SUPPORTS_ACCEPT,
                     reasoning_summary="looks fine"),
    )
    decision = arbiter_decide(
        mission_id="m1", revision="rev2", risk_level=RiskLevel.HIGH, critic_outputs=conflicting,
        findings=(), required_verification_records={"REQ-X-1": (_record(),)},
        required_requirement_ids=("REQ-X-1",),
        required_scopes_by_requirement={"REQ-X-1": _UNIT_TEST_SCOPE},
    )
    assert decision.verdict is CourtVerdict.ESCALATE


def test_arbiter_no_opinions_needs_more_evidence_not_accept():
    only_constructor = (CriticOutput(role=CourtRole.CONSTRUCTOR, conclusion=CriticConclusion.NOT_REQUIRED,
                                      reasoning_summary="summary only"),)
    decision = arbiter_decide(
        mission_id="m1", revision="rev2", risk_level=RiskLevel.STANDARD, critic_outputs=only_constructor,
        findings=(), required_verification_records={"REQ-X-1": (_record(),)},
        required_requirement_ids=("REQ-X-1",),
        required_scopes_by_requirement={"REQ-X-1": _UNIT_TEST_SCOPE},
    )
    assert decision.verdict is CourtVerdict.NEED_MORE_EVIDENCE


# ── Phase 15.9.1 closure: revision/mission-bound evidence ───────────

def test_arbiter_stale_revision_record_does_not_support_accept():
    # A PASS record for revision "rev1" cannot support an ACCEPT
    # decision being made about "rev2" -- filter_current_context()
    # excludes it, so the requirement aggregates to UNVERIFIED.
    stale_record = _record(revision="rev1")
    all_accept = (CriticOutput(role=CourtRole.TEST_CRITIC, conclusion=CriticConclusion.SUPPORTS_ACCEPT,
                                reasoning_summary="fine"),)
    decision = arbiter_decide(
        mission_id="m1", revision="rev2", risk_level=RiskLevel.STANDARD, critic_outputs=all_accept,
        findings=(), required_verification_records={"REQ-X-1": (stale_record,)},
        required_requirement_ids=("REQ-X-1",),
        required_scopes_by_requirement={"REQ-X-1": _UNIT_TEST_SCOPE},
    )
    assert decision.verdict is not CourtVerdict.ACCEPT
    assert decision.verdict is CourtVerdict.NEED_MORE_EVIDENCE
    assert decision.verification_refs == ()


def test_arbiter_cross_mission_record_does_not_support_accept():
    # A PASS record for mission "m2" cannot support an ACCEPT
    # decision being made about mission "m1".
    other_mission_record = _record(mission_id="m2")
    all_accept = (CriticOutput(role=CourtRole.TEST_CRITIC, conclusion=CriticConclusion.SUPPORTS_ACCEPT,
                                reasoning_summary="fine"),)
    decision = arbiter_decide(
        mission_id="m1", revision="rev2", risk_level=RiskLevel.STANDARD, critic_outputs=all_accept,
        findings=(), required_verification_records={"REQ-X-1": (other_mission_record,)},
        required_requirement_ids=("REQ-X-1",),
        required_scopes_by_requirement={"REQ-X-1": _UNIT_TEST_SCOPE},
    )
    assert decision.verdict is not CourtVerdict.ACCEPT
    assert decision.verdict is CourtVerdict.NEED_MORE_EVIDENCE
    assert decision.verification_refs == ()


def test_arbiter_fabricated_outcome_without_record_cannot_accept():
    # There is no longer any way to pass a bare outcome dict at all --
    # required_verification_records with an EMPTY tuple for a
    # required requirement id is the closest a caller can get to
    # "claiming" PASS without a record, and it correctly aggregates
    # to UNVERIFIED (aggregate_requirement(()) is UNVERIFIED).
    all_accept = (CriticOutput(role=CourtRole.TEST_CRITIC, conclusion=CriticConclusion.SUPPORTS_ACCEPT,
                                reasoning_summary="fine"),)
    decision = arbiter_decide(
        mission_id="m1", revision="rev2", risk_level=RiskLevel.STANDARD, critic_outputs=all_accept,
        findings=(), required_verification_records={"REQ-X-1": ()},
        required_requirement_ids=("REQ-X-1",),
        required_scopes_by_requirement={"REQ-X-1": _UNIT_TEST_SCOPE},
    )
    assert decision.verdict is not CourtVerdict.ACCEPT
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
        findings=(_finding(),), required_verification_records={"REQ-X-1": (_record(),)},
        required_requirement_ids=("REQ-X-1",),
        required_scopes_by_requirement={"REQ-X-1": _UNIT_TEST_SCOPE},
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


# ── Phase 15.9.1 closure item 6: arbiter hard-policy tests ──────────
# Every case attaches a MockProvider whose narrative says "ACCEPT" --
# proving the narrative is captured but never consulted by
# arbiter_decide() in any of these five scenarios.

def _accepting_provider() -> MockProvider:
    return MockProvider(fixed_response="This all looks great, ACCEPT immediately!")


def test_closure_6a_provider_accept_plus_stale_revision_blocks():
    provider = _accepting_provider()
    critic = security_critic_review((), provider=provider)
    assert critic.provider_narrative and "ACCEPT" in critic.provider_narrative
    stale_record = _record(revision="rev1")  # decision is about rev2
    decision = arbiter_decide(
        mission_id="m1", revision="rev2", risk_level=RiskLevel.STANDARD, critic_outputs=(critic,),
        findings=(), required_verification_records={"REQ-X-1": (stale_record,)},
        required_requirement_ids=("REQ-X-1",),
        required_scopes_by_requirement={"REQ-X-1": _UNIT_TEST_SCOPE},
    )
    assert decision.verdict is not CourtVerdict.ACCEPT


def test_closure_6b_provider_accept_plus_security_mock_critical_rejects():
    provider = _accepting_provider()
    mock_finding = _finding(category=FindingCategory.MOCK_REPLACES_REQUIRED_BEHAVIOR,
                             severity=Severity.CRITICAL, blocking=True)
    critic = security_critic_review((mock_finding,), provider=provider)
    assert critic.provider_narrative and "ACCEPT" in critic.provider_narrative
    assert critic.conclusion is CriticConclusion.SUPPORTS_REJECT
    decision = arbiter_decide(
        mission_id="m1", revision="rev2", risk_level=RiskLevel.CRITICAL, critic_outputs=(critic,),
        findings=(mock_finding,), required_verification_records={"REQ-X-1": (_record(),)},
        required_requirement_ids=("REQ-X-1",),
        required_scopes_by_requirement={"REQ-X-1": _UNIT_TEST_SCOPE},
    )
    assert decision.verdict is CourtVerdict.REJECT


def test_closure_6c_provider_accept_plus_deny_to_allow_mutation_rejects():
    provider = _accepting_provider()
    mutation_finding = _finding(category=FindingCategory.EXPECTED_BEHAVIOR_CHANGED,
                                 severity=Severity.CRITICAL, blocking=True)
    critic = security_critic_review((mutation_finding,), provider=provider)
    assert critic.provider_narrative and "ACCEPT" in critic.provider_narrative
    decision = arbiter_decide(
        mission_id="m1", revision="rev2", risk_level=RiskLevel.CRITICAL, critic_outputs=(critic,),
        findings=(mutation_finding,), required_verification_records={"REQ-X-1": (_record(),)},
        required_requirement_ids=("REQ-X-1",),
        required_scopes_by_requirement={"REQ-X-1": _UNIT_TEST_SCOPE},
    )
    assert decision.verdict is CourtVerdict.REJECT


def test_closure_6d_provider_accept_plus_no_real_record_cannot_accept():
    provider = _accepting_provider()
    critic = security_critic_review((), provider=provider)
    assert critic.provider_narrative and "ACCEPT" in critic.provider_narrative
    decision = arbiter_decide(
        mission_id="m1", revision="rev2", risk_level=RiskLevel.STANDARD, critic_outputs=(critic,),
        findings=(), required_verification_records={"REQ-X-1": ()},  # no record at all
        required_requirement_ids=("REQ-X-1",),
        required_scopes_by_requirement={"REQ-X-1": _UNIT_TEST_SCOPE},
    )
    assert decision.verdict is not CourtVerdict.ACCEPT
    assert decision.verdict is CourtVerdict.NEED_MORE_EVIDENCE


def test_closure_6e_all_correct_current_revision_evidence_no_blocker_accept_still_possible():
    provider = _accepting_provider()
    critic = security_critic_review((), provider=provider)
    record = _record(mission_id="m1", revision="rev2")
    decision = arbiter_decide(
        mission_id="m1", revision="rev2", risk_level=RiskLevel.STANDARD, critic_outputs=(critic,),
        findings=(), required_verification_records={"REQ-X-1": (record,)},
        required_requirement_ids=("REQ-X-1",),
        required_scopes_by_requirement={"REQ-X-1": _UNIT_TEST_SCOPE},
    )
    assert decision.verdict is CourtVerdict.ACCEPT
    assert decision.verification_refs == (record.id,)


# ── Phase 15.9.2 closure item 1: empty required set must never vacuously ACCEPT ──

def test_closure_15_9_2_a_empty_required_set_with_accepting_critic_cannot_accept():
    all_accept = (CriticOutput(role=CourtRole.TEST_CRITIC, conclusion=CriticConclusion.SUPPORTS_ACCEPT,
                                reasoning_summary="fine"),)
    with pytest.raises(CourtConfigurationError):
        arbiter_decide(
            mission_id="m1", revision="rev2", risk_level=RiskLevel.STANDARD, critic_outputs=all_accept,
            findings=(), required_verification_records={}, required_requirement_ids=(),
            required_scopes_by_requirement={},
        )


def test_closure_15_9_2_b_empty_required_set_with_accepting_provider_narrative_cannot_accept():
    provider = _accepting_provider()
    critic = security_critic_review((), provider=provider)
    assert critic.provider_narrative and "ACCEPT" in critic.provider_narrative
    with pytest.raises(CourtConfigurationError):
        arbiter_decide(
            mission_id="m1", revision="rev2", risk_level=RiskLevel.STANDARD, critic_outputs=(critic,),
            findings=(), required_verification_records={}, required_requirement_ids=(),
            required_scopes_by_requirement={},
        )


def test_closure_15_9_2_c_one_real_required_requirement_with_matching_pass_record_still_accepts():
    all_accept = (CriticOutput(role=CourtRole.TEST_CRITIC, conclusion=CriticConclusion.SUPPORTS_ACCEPT,
                                reasoning_summary="fine"),)
    record = _record(mission_id="m1", revision="rev2")
    decision = arbiter_decide(
        mission_id="m1", revision="rev2", risk_level=RiskLevel.STANDARD, critic_outputs=all_accept,
        findings=(), required_verification_records={"REQ-X-1": (record,)},
        required_requirement_ids=("REQ-X-1",),
        required_scopes_by_requirement={"REQ-X-1": _UNIT_TEST_SCOPE},
    )
    assert decision.verdict is CourtVerdict.ACCEPT
    assert decision.verification_refs != ()


def test_closure_15_9_2_d_one_required_requirement_zero_records_needs_more_evidence():
    all_accept = (CriticOutput(role=CourtRole.TEST_CRITIC, conclusion=CriticConclusion.SUPPORTS_ACCEPT,
                                reasoning_summary="fine"),)
    decision = arbiter_decide(
        mission_id="m1", revision="rev2", risk_level=RiskLevel.STANDARD, critic_outputs=all_accept,
        findings=(), required_verification_records={"REQ-X-1": ()},
        required_requirement_ids=("REQ-X-1",),
        required_scopes_by_requirement={"REQ-X-1": _UNIT_TEST_SCOPE},
    )
    assert decision.verdict is CourtVerdict.NEED_MORE_EVIDENCE
    assert decision.verification_refs == ()


def test_closure_15_9_2_accept_decision_verification_refs_never_empty():
    # Defense-in-depth invariant (spec section 3): any ACCEPT decision
    # that depended on required verification must carry a non-empty
    # verification_refs -- an ACCEPT can never be produced with an
    # empty required set (see test A above), so any ACCEPT this
    # function returns necessarily has real refs.
    all_accept = (CriticOutput(role=CourtRole.TEST_CRITIC, conclusion=CriticConclusion.SUPPORTS_ACCEPT,
                                reasoning_summary="fine"),)
    record = _record(mission_id="m1", revision="rev2")
    decision = arbiter_decide(
        mission_id="m1", revision="rev2", risk_level=RiskLevel.STANDARD, critic_outputs=all_accept,
        findings=(), required_verification_records={"REQ-X-1": (record,)},
        required_requirement_ids=("REQ-X-1",),
        required_scopes_by_requirement={"REQ-X-1": _UNIT_TEST_SCOPE},
    )
    assert decision.verdict is CourtVerdict.ACCEPT
    assert decision.verification_refs != ()


# ── Phase 15.9.2 closure item 2: mission Court path must never be unscoped ──

def test_closure_15_9_2_mission_id_none_cannot_accept():
    all_accept = (CriticOutput(role=CourtRole.TEST_CRITIC, conclusion=CriticConclusion.SUPPORTS_ACCEPT,
                                reasoning_summary="fine"),)
    record = _record(mission_id="m1", revision="rev2")
    with pytest.raises(CourtConfigurationError):
        arbiter_decide(
            mission_id=None, revision="rev2", risk_level=RiskLevel.STANDARD, critic_outputs=all_accept,
            findings=(), required_verification_records={"REQ-X-1": (record,)},
            required_requirement_ids=("REQ-X-1",),
            required_scopes_by_requirement={"REQ-X-1": _UNIT_TEST_SCOPE},
        )


def test_closure_15_9_2_mission_id_empty_string_cannot_accept():
    all_accept = (CriticOutput(role=CourtRole.TEST_CRITIC, conclusion=CriticConclusion.SUPPORTS_ACCEPT,
                                reasoning_summary="fine"),)
    record = _record(mission_id="m1", revision="rev2")
    with pytest.raises(CourtConfigurationError):
        arbiter_decide(
            mission_id="", revision="rev2", risk_level=RiskLevel.STANDARD, critic_outputs=all_accept,
            findings=(), required_verification_records={"REQ-X-1": (record,)},
            required_requirement_ids=("REQ-X-1",),
            required_scopes_by_requirement={"REQ-X-1": _UNIT_TEST_SCOPE},
        )


def test_closure_15_9_2_revision_empty_string_cannot_accept():
    all_accept = (CriticOutput(role=CourtRole.TEST_CRITIC, conclusion=CriticConclusion.SUPPORTS_ACCEPT,
                                reasoning_summary="fine"),)
    record = _record(mission_id="m1", revision="rev2")
    with pytest.raises(CourtConfigurationError):
        arbiter_decide(
            mission_id="m1", revision="", risk_level=RiskLevel.STANDARD, critic_outputs=all_accept,
            findings=(), required_verification_records={"REQ-X-1": (record,)},
            required_requirement_ids=("REQ-X-1",),
            required_scopes_by_requirement={"REQ-X-1": _UNIT_TEST_SCOPE},
        )


# ── Phase 15.9.3 closure item 1/4: requirement-id dict-key spoofing ──

def test_closure_15_9_3_a_dict_key_spoofing_cannot_support_accept():
    # required_requirement_ids=("REQ-B",) but the ONLY record supplied
    # under that key genuinely claims requirement_id="REQ-A" -- the
    # dict placement must not be trusted as the record's identity.
    all_accept = (CriticOutput(role=CourtRole.TEST_CRITIC, conclusion=CriticConclusion.SUPPORTS_ACCEPT,
                                reasoning_summary="fine"),)
    spoofed_record = _record(requirement_id="REQ-A", mission_id="m1", revision="rev2")
    decision = arbiter_decide(
        mission_id="m1", revision="rev2", risk_level=RiskLevel.STANDARD, critic_outputs=all_accept,
        findings=(), required_verification_records={"REQ-B": (spoofed_record,)},
        required_requirement_ids=("REQ-B",),
        required_scopes_by_requirement={"REQ-B": _UNIT_TEST_SCOPE},
    )
    assert decision.verdict is not CourtVerdict.ACCEPT
    assert decision.verdict is CourtVerdict.NEED_MORE_EVIDENCE
    assert decision.verification_refs == ()


def test_closure_15_9_3_b_correct_dict_key_and_requirement_id_still_accepts():
    all_accept = (CriticOutput(role=CourtRole.TEST_CRITIC, conclusion=CriticConclusion.SUPPORTS_ACCEPT,
                                reasoning_summary="fine"),)
    real_record = _record(requirement_id="REQ-B", mission_id="m1", revision="rev2")
    decision = arbiter_decide(
        mission_id="m1", revision="rev2", risk_level=RiskLevel.STANDARD, critic_outputs=all_accept,
        findings=(), required_verification_records={"REQ-B": (real_record,)},
        required_requirement_ids=("REQ-B",),
        required_scopes_by_requirement={"REQ-B": _UNIT_TEST_SCOPE},
    )
    assert decision.verdict is CourtVerdict.ACCEPT
    assert decision.verification_refs == (real_record.id,)


def test_closure_15_9_3_c_wrong_pass_ignored_correct_fail_dominates():
    all_accept = (CriticOutput(role=CourtRole.TEST_CRITIC, conclusion=CriticConclusion.SUPPORTS_ACCEPT,
                                reasoning_summary="fine"),)
    correct_fail = _record(requirement_id="REQ-B", mission_id="m1", revision="rev2",
                            outcome=VerificationOutcome.FAIL)
    wrong_pass = _record(requirement_id="REQ-A", mission_id="m1", revision="rev2")
    decision = arbiter_decide(
        mission_id="m1", revision="rev2", risk_level=RiskLevel.STANDARD, critic_outputs=all_accept,
        findings=(), required_verification_records={"REQ-B": (correct_fail, wrong_pass)},
        required_requirement_ids=("REQ-B",),
        required_scopes_by_requirement={"REQ-B": _UNIT_TEST_SCOPE},
    )
    assert decision.verdict is not CourtVerdict.ACCEPT
    assert decision.verification_refs == ()


def test_closure_15_9_3_d_provider_accept_narrative_cannot_override_spoofed_record():
    provider = _accepting_provider()
    critic = security_critic_review((), provider=provider)
    assert critic.provider_narrative and "ACCEPT" in critic.provider_narrative
    spoofed_record = _record(requirement_id="REQ-A", mission_id="m1", revision="rev2")
    decision = arbiter_decide(
        mission_id="m1", revision="rev2", risk_level=RiskLevel.STANDARD, critic_outputs=(critic,),
        findings=(), required_verification_records={"REQ-B": (spoofed_record,)},
        required_requirement_ids=("REQ-B",),
        required_scopes_by_requirement={"REQ-B": _UNIT_TEST_SCOPE},
    )
    assert decision.verdict is not CourtVerdict.ACCEPT


# ── Phase 15.9.3 closure item 2: required-criterion completeness ────

@pytest.fixture(autouse=True)
def _clean_criteria_registries():
    requirements_module.reset_registry_for_tests()
    ac_module.reset_registry_for_tests()
    yield
    requirements_module.reset_registry_for_tests()
    ac_module.reset_registry_for_tests()


def _register_req_with_two_criteria(req_id="REQ-CRIT-X-001"):
    requirements_module.register(requirements_module.Requirement(
        id=req_id, source_section="test", statement="Two criteria must both be verified",
        acceptance_criteria=("first", "second"),
    ))
    ac_module.register_criterion(
        criterion_id="c1", requirement_id=req_id, description="First criterion",
        verification_method=VerificationMethod.UNIT_TEST,
    )
    ac_module.register_criterion(
        criterion_id="c2", requirement_id=req_id, description="Second criterion",
        verification_method=VerificationMethod.UNIT_TEST,
    )


def test_closure_15_9_3_missing_required_criterion_cannot_accept():
    _register_req_with_two_criteria()
    all_accept = (CriticOutput(role=CourtRole.TEST_CRITIC, conclusion=CriticConclusion.SUPPORTS_ACCEPT,
                                reasoning_summary="fine"),)
    c1_only = _record(requirement_id="REQ-CRIT-X-001", criterion_id="c1", mission_id="m1", revision="rev2")
    decision = arbiter_decide(
        mission_id="m1", revision="rev2", risk_level=RiskLevel.STANDARD, critic_outputs=all_accept,
        findings=(), required_verification_records={"REQ-CRIT-X-001": (c1_only,)},
        required_requirement_ids=("REQ-CRIT-X-001",),
        required_scopes_by_requirement={"REQ-CRIT-X-001": _CRIT_SCOPE},
    )
    assert decision.verdict is not CourtVerdict.ACCEPT
    assert decision.verdict is CourtVerdict.NEED_MORE_EVIDENCE
    assert decision.verification_refs == ()


def test_closure_15_9_3_both_required_criteria_present_can_accept():
    _register_req_with_two_criteria()
    all_accept = (CriticOutput(role=CourtRole.TEST_CRITIC, conclusion=CriticConclusion.SUPPORTS_ACCEPT,
                                reasoning_summary="fine"),)
    c1 = _record(requirement_id="REQ-CRIT-X-001", criterion_id="c1", mission_id="m1", revision="rev2")
    c2 = _record(requirement_id="REQ-CRIT-X-001", criterion_id="c2", mission_id="m1", revision="rev2")
    decision = arbiter_decide(
        mission_id="m1", revision="rev2", risk_level=RiskLevel.STANDARD, critic_outputs=all_accept,
        findings=(), required_verification_records={"REQ-CRIT-X-001": (c1, c2)},
        required_requirement_ids=("REQ-CRIT-X-001",),
        required_scopes_by_requirement={"REQ-CRIT-X-001": _CRIT_SCOPE},
    )
    assert decision.verdict is CourtVerdict.ACCEPT
    assert set(decision.verification_refs) == {c1.id, c2.id}


def test_closure_15_9_3_provider_accept_narrative_cannot_override_missing_criterion():
    _register_req_with_two_criteria()
    provider = _accepting_provider()
    critic = security_critic_review((), provider=provider)
    assert critic.provider_narrative and "ACCEPT" in critic.provider_narrative
    c1_only = _record(requirement_id="REQ-CRIT-X-001", criterion_id="c1", mission_id="m1", revision="rev2")
    decision = arbiter_decide(
        mission_id="m1", revision="rev2", risk_level=RiskLevel.STANDARD, critic_outputs=(critic,),
        findings=(), required_verification_records={"REQ-CRIT-X-001": (c1_only,)},
        required_requirement_ids=("REQ-CRIT-X-001",),
        required_scopes_by_requirement={"REQ-CRIT-X-001": _CRIT_SCOPE},
    )
    assert decision.verdict is not CourtVerdict.ACCEPT


# ── Phase 15.9.4 closure: authoritative verification scope must be explicit ──
# Fail-open fallback closed: arbiter_decide() no longer consults the
# Phase 15.7 AcceptanceCriterion registry or falls back to whatever
# records happen to exist -- required_scopes_by_requirement is now the
# ONLY source of truth for expected verification scope on this path.

def test_closure_15_9_4_a_no_scope_supplied_for_required_requirement_raises():
    all_accept = (CriticOutput(role=CourtRole.TEST_CRITIC, conclusion=CriticConclusion.SUPPORTS_ACCEPT,
                                reasoning_summary="fine"),)
    record = _record(mission_id="m1", revision="rev2")
    with pytest.raises(CourtConfigurationError):
        arbiter_decide(
            mission_id="m1", revision="rev2", risk_level=RiskLevel.STANDARD, critic_outputs=all_accept,
            findings=(), required_verification_records={"REQ-X-1": (record,)},
            required_requirement_ids=("REQ-X-1",),
            required_scopes_by_requirement={},  # REQ-X-1 has no entry -- must fail closed
        )


def test_closure_15_9_4_c_registry_populated_but_scope_omitted_still_rejects():
    # Even though the Phase 15.7 AcceptanceCriterion registry is fully
    # populated in this process, arbiter_decide() must not secretly
    # consult it -- omitting the explicit scope must still fail closed.
    _register_req_with_two_criteria()
    all_accept = (CriticOutput(role=CourtRole.TEST_CRITIC, conclusion=CriticConclusion.SUPPORTS_ACCEPT,
                                reasoning_summary="fine"),)
    c1 = _record(requirement_id="REQ-CRIT-X-001", criterion_id="c1", mission_id="m1", revision="rev2")
    c2 = _record(requirement_id="REQ-CRIT-X-001", criterion_id="c2", mission_id="m1", revision="rev2")
    with pytest.raises(CourtConfigurationError):
        arbiter_decide(
            mission_id="m1", revision="rev2", risk_level=RiskLevel.STANDARD, critic_outputs=all_accept,
            findings=(), required_verification_records={"REQ-CRIT-X-001": (c1, c2)},
            required_requirement_ids=("REQ-CRIT-X-001",),
            required_scopes_by_requirement={},  # registry HAS c1/c2, but no explicit scope supplied
        )


def test_closure_15_9_4_d_restart_simulated_explicit_scope_both_pass_can_accept():
    # Simulates a process restart: the AcceptanceCriterion registry is
    # explicitly reset/empty here (this test never registers c1/c2),
    # yet ACCEPT is still correctly reachable because the scope is
    # supplied explicitly -- the decision does not depend on
    # accidental in-process registry state.
    all_accept = (CriticOutput(role=CourtRole.TEST_CRITIC, conclusion=CriticConclusion.SUPPORTS_ACCEPT,
                                reasoning_summary="fine"),)
    c1 = _record(requirement_id="REQ-CRIT-X-001", criterion_id="c1", mission_id="m1", revision="rev2")
    c2 = _record(requirement_id="REQ-CRIT-X-001", criterion_id="c2", mission_id="m1", revision="rev2")
    decision = arbiter_decide(
        mission_id="m1", revision="rev2", risk_level=RiskLevel.STANDARD, critic_outputs=all_accept,
        findings=(), required_verification_records={"REQ-CRIT-X-001": (c1, c2)},
        required_requirement_ids=("REQ-CRIT-X-001",),
        required_scopes_by_requirement={"REQ-CRIT-X-001": _CRIT_SCOPE},
    )
    assert decision.verdict is CourtVerdict.ACCEPT
    assert set(decision.verification_refs) == {c1.id, c2.id}


def test_closure_15_9_4_e_restart_simulated_explicit_scope_c1_only_is_unverified():
    all_accept = (CriticOutput(role=CourtRole.TEST_CRITIC, conclusion=CriticConclusion.SUPPORTS_ACCEPT,
                                reasoning_summary="fine"),)
    c1_only = _record(requirement_id="REQ-CRIT-X-001", criterion_id="c1", mission_id="m1", revision="rev2")
    decision = arbiter_decide(
        mission_id="m1", revision="rev2", risk_level=RiskLevel.STANDARD, critic_outputs=all_accept,
        findings=(), required_verification_records={"REQ-CRIT-X-001": (c1_only,)},
        required_requirement_ids=("REQ-CRIT-X-001",),
        required_scopes_by_requirement={"REQ-CRIT-X-001": _CRIT_SCOPE},
    )
    assert decision.verdict is not CourtVerdict.ACCEPT
    assert decision.verdict is CourtVerdict.NEED_MORE_EVIDENCE


def test_closure_15_9_4_f_requirement_level_category_scope_partial_is_unverified():
    all_accept = (CriticOutput(role=CourtRole.TEST_CRITIC, conclusion=CriticConclusion.SUPPORTS_ACCEPT,
                                reasoning_summary="fine"),)
    unit_only = _record(requirement_id="REQ-CAT-001", mission_id="m1", revision="rev2")  # category=UNIT_TEST
    scope = RequiredVerificationScope(requirement_level_categories=frozenset({"UNIT_TEST", "SECURITY_TEST"}))
    decision = arbiter_decide(
        mission_id="m1", revision="rev2", risk_level=RiskLevel.STANDARD, critic_outputs=all_accept,
        findings=(), required_verification_records={"REQ-CAT-001": (unit_only,)},
        required_requirement_ids=("REQ-CAT-001",),
        required_scopes_by_requirement={"REQ-CAT-001": scope},
    )
    assert decision.verdict is not CourtVerdict.ACCEPT
    assert decision.verdict is CourtVerdict.NEED_MORE_EVIDENCE


def test_closure_15_9_4_g_requirement_level_category_scope_complete_can_accept():
    all_accept = (CriticOutput(role=CourtRole.TEST_CRITIC, conclusion=CriticConclusion.SUPPORTS_ACCEPT,
                                reasoning_summary="fine"),)
    unit_pass = _record(requirement_id="REQ-CAT-001", mission_id="m1", revision="rev2", category="UNIT_TEST")
    security_pass = _record(requirement_id="REQ-CAT-001", mission_id="m1", revision="rev2",
                             category="SECURITY_TEST", id="ver_security_pass")
    scope = RequiredVerificationScope(requirement_level_categories=frozenset({"UNIT_TEST", "SECURITY_TEST"}))
    decision = arbiter_decide(
        mission_id="m1", revision="rev2", risk_level=RiskLevel.STANDARD, critic_outputs=all_accept,
        findings=(), required_verification_records={"REQ-CAT-001": (unit_pass, security_pass)},
        required_requirement_ids=("REQ-CAT-001",),
        required_scopes_by_requirement={"REQ-CAT-001": scope},
    )
    assert decision.verdict is CourtVerdict.ACCEPT
    assert set(decision.verification_refs) == {unit_pass.id, security_pass.id}


def test_closure_15_9_4_h_unexpected_extra_category_does_not_substitute_for_missing_required():
    all_accept = (CriticOutput(role=CourtRole.TEST_CRITIC, conclusion=CriticConclusion.SUPPORTS_ACCEPT,
                                reasoning_summary="fine"),)
    unit_pass = _record(requirement_id="REQ-CAT-001", mission_id="m1", revision="rev2", category="UNIT_TEST")
    extra_pass = _record(requirement_id="REQ-CAT-001", mission_id="m1", revision="rev2",
                          category="PERFORMANCE_TEST", id="ver_extra_pass")
    scope = RequiredVerificationScope(requirement_level_categories=frozenset({"UNIT_TEST", "SECURITY_TEST"}))
    decision = arbiter_decide(
        mission_id="m1", revision="rev2", risk_level=RiskLevel.STANDARD, critic_outputs=all_accept,
        findings=(), required_verification_records={"REQ-CAT-001": (unit_pass, extra_pass)},
        required_requirement_ids=("REQ-CAT-001",),
        required_scopes_by_requirement={"REQ-CAT-001": scope},
    )
    assert decision.verdict is not CourtVerdict.ACCEPT
    assert decision.verdict is CourtVerdict.NEED_MORE_EVIDENCE


def test_closure_15_9_4_i_provider_accept_narrative_cannot_override_absent_scope():
    provider = _accepting_provider()
    critic = security_critic_review((), provider=provider)
    assert critic.provider_narrative and "ACCEPT" in critic.provider_narrative
    record = _record(mission_id="m1", revision="rev2")
    with pytest.raises(CourtConfigurationError):
        arbiter_decide(
            mission_id="m1", revision="rev2", risk_level=RiskLevel.STANDARD, critic_outputs=(critic,),
            findings=(), required_verification_records={"REQ-X-1": (record,)},
            required_requirement_ids=("REQ-X-1",),
            required_scopes_by_requirement={},
        )


def test_closure_15_9_4_j_matching_mission_revision_requirement_and_complete_scope_still_accepts():
    all_accept = (CriticOutput(role=CourtRole.TEST_CRITIC, conclusion=CriticConclusion.SUPPORTS_ACCEPT,
                                reasoning_summary="fine"),)
    record = _record(mission_id="m1", revision="rev2")
    decision = arbiter_decide(
        mission_id="m1", revision="rev2", risk_level=RiskLevel.STANDARD, critic_outputs=all_accept,
        findings=(), required_verification_records={"REQ-X-1": (record,)},
        required_requirement_ids=("REQ-X-1",),
        required_scopes_by_requirement={"REQ-X-1": _UNIT_TEST_SCOPE},
    )
    assert decision.verdict is CourtVerdict.ACCEPT
    assert decision.verification_refs == (record.id,)
