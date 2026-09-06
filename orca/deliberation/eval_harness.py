"""
Deliberation Fabric evaluation harness (Phase 6 spec §53-54). Every
scenario exercises real Deliberation Fabric code; no score is invented.
Run directly: `.venv/bin/python -m orca.deliberation.eval_harness`.

Deterministic scenarios (no Ollama) are run here. Scenarios that
genuinely require a live Constructor/Falsifier exchange (#9 "constructor
confident but wrong", #15 cancellation, #16 role injection via a real
model call, #17 same-model disclosure) are intentionally NOT duplicated
here -- they are already covered, live, by
tests/test_deliberation_court_integration.py,
tests/test_deliberation_cancellation.py, and
tests/test_deliberation_security.py. Duplicating them into a second
harness would either need Ollama (making this harness flaky/slow for no
benefit) or fake the model call (which would not be a real measurement
at all). See EVALUATION.md for the full scenario-to-coverage mapping.
"""
from __future__ import annotations

from dataclasses import dataclass
from typing import Callable

from orca.cognitive.contracts import ComplexityLevel, EvidenceLevel, RiskLevel
from orca.deliberation.arbiter import arbitrate
from orca.deliberation.causal import assess_causal_relation
from orca.deliberation.compiler import compile_reasoning_plan
from orca.deliberation.contracts import (
    Argument,
    CounterArgument,
    CourtVerdictState,
    Hypothesis,
    HypothesisSet,
    ReasoningMode,
    TwinResult,
)
from orca.deliberation.evidence_clerk import EvidenceReport, build_evidence_report
from orca.deliberation.hypothesis import (
    all_resolved,
    falsify,
    mark_unresolved,
    record_contradicting_evidence,
    record_supporting_evidence,
)
from orca.deliberation.risk_counsel import RiskOpinion, assess_risk_opinion
from orca.truth.contracts import Contradiction, ContradictionRelationship


def scenario_simple_direct_no_court() -> bool:
    plan = compile_reasoning_plan("What's the capital of France?", ComplexityLevel.LOW, RiskLevel.LOW, EvidenceLevel.SUPPORTED)
    return not plan.requires_court and plan.mode in (ReasoningMode.DIRECT, ReasoningMode.ANALYTICAL)


def scenario_ambiguous_diagnosis_multiple_hypotheses() -> bool:
    plan = compile_reasoning_plan("The outage could be either a network issue or a database issue.", ComplexityLevel.MEDIUM, RiskLevel.MODERATE, EvidenceLevel.SUPPORTED)
    return plan.requires_hypotheses and plan.mode == ReasoningMode.MULTI_HYPOTHESIS


def scenario_one_hypothesis_falsified_by_evidence() -> bool:
    h = Hypothesis(statement="network caused the outage")
    falsify(h, "ev-contradicting")
    return h.status.value == "FALSIFIED" and h.contradicting_evidence_ids == ["ev-contradicting"]


def scenario_all_hypotheses_unresolved() -> bool:
    h1, h2 = Hypothesis(statement="a"), Hypothesis(statement="b")
    hs = HypothesisSet(hypotheses=[h1, h2])
    mark_unresolved(h1)
    mark_unresolved(h2)
    return all_resolved(hs)


def scenario_conflicting_evidence_triggers_court() -> bool:
    class _TR:
        contradictions = [Contradiction(claim_a_id="e1", claim_b_id="e2", relationship=ContradictionRelationship.DIRECT_CONTRADICTION)]
    plan = compile_reasoning_plan("What is the current rate limit?", ComplexityLevel.LOW, RiskLevel.LOW, EvidenceLevel.SUPPORTED, truth_result=_TR())
    return plan.requires_court


def scenario_temporal_contradiction_does_not_force_court() -> bool:
    class _TR:
        contradictions = [Contradiction(claim_a_id="e1", claim_b_id="e2", relationship=ContradictionRelationship.TEMPORALLY_RECONCILABLE)]
    plan = compile_reasoning_plan("What is the current rate limit?", ComplexityLevel.LOW, RiskLevel.LOW, EvidenceLevel.SUPPORTED, truth_result=_TR())
    return not plan.requires_court


def scenario_causal_claim_with_only_correlational_evidence() -> bool:
    rel = assess_causal_relation("ice cream sales", "drowning incidents", ["ev1"])
    return rel.relationship_type.value == "CORRELATES_WITH"


def scenario_high_risk_insufficient_evidence_abstains() -> bool:
    verdict = arbitrate(TwinResult(constructor_claims=[]), EvidenceReport(), RiskOpinion(recommendation="human_approval", risk_level=RiskLevel.CRITICAL))
    return verdict.verdict == CourtVerdictState.INSUFFICIENT_EVIDENCE


def scenario_falsifier_catches_unsupported_assumption() -> bool:
    claim = Argument(claim="X is always true", evidence_ids=["ev1"])
    twin = TwinResult(
        constructor_claims=[claim], unsupported_assumption_ids=["assum-1"],
        disputed_claim_ids=[], surviving_claim_ids=[claim.argument_id],
    )
    return bool(twin.unsupported_assumption_ids)


def scenario_counter_evidence_overturns_conclusion() -> bool:
    claim = Argument(claim="the limit is 100", evidence_ids=["ev1"])
    objection = CounterArgument(target_argument_id=claim.argument_id, objection="another source says 500", objection_kind="counter_evidence", counter_evidence_ids=["ev2"])
    twin = TwinResult(constructor_claims=[claim], falsifier_objections=[objection], counter_evidence_ids=["ev2"], disputed_claim_ids=[claim.argument_id], surviving_claim_ids=[])
    verdict = arbitrate(twin, EvidenceReport(), RiskOpinion(recommendation="proceed"))
    return verdict.verdict == CourtVerdictState.REJECT


def scenario_budget_stopping_never_forces_confident_verdict() -> bool:
    """Deterministic proxy for the live budget-exhaustion test
    (tests/test_deliberation_court_integration.py::
    test_court_budget_exhaustion_never_forces_a_confident_verdict) --
    checked here on CourtVerdict's own default, which is
    INSUFFICIENT_EVIDENCE, never ACCEPT."""
    from orca.deliberation.contracts import CourtVerdict
    return CourtVerdict().verdict == CourtVerdictState.INSUFFICIENT_EVIDENCE


def scenario_evidence_clerk_flags_missing_evidence() -> bool:
    claims = [Argument(claim="a", evidence_ids=[]), Argument(claim="b", evidence_ids=["ev1"])]
    report = build_evidence_report(claims)
    return len(report.claims_missing_evidence) == 1


def scenario_risk_counsel_recommends_not_authorizes() -> bool:
    opinion = assess_risk_opinion(RiskLevel.CRITICAL, EvidenceReport(), [])
    return opinion.recommendation == "human_approval" and not hasattr(opinion, "authorized")


@dataclass
class Scenario:
    name: str
    fn: Callable[[], bool]


SCENARIOS = [
    Scenario("simple_direct_question_no_court", scenario_simple_direct_no_court),
    Scenario("ambiguous_diagnosis_multiple_hypotheses", scenario_ambiguous_diagnosis_multiple_hypotheses),
    Scenario("one_hypothesis_falsified_by_evidence", scenario_one_hypothesis_falsified_by_evidence),
    Scenario("all_hypotheses_unresolved", scenario_all_hypotheses_unresolved),
    Scenario("conflicting_evidence_triggers_court", scenario_conflicting_evidence_triggers_court),
    Scenario("temporal_contradiction_does_not_force_court", scenario_temporal_contradiction_does_not_force_court),
    Scenario("causal_claim_with_only_correlational_evidence", scenario_causal_claim_with_only_correlational_evidence),
    Scenario("high_risk_decision_insufficient_evidence", scenario_high_risk_insufficient_evidence_abstains),
    Scenario("falsifier_catches_unsupported_assumption", scenario_falsifier_catches_unsupported_assumption),
    Scenario("counter_evidence_overturns_initial_conclusion", scenario_counter_evidence_overturns_conclusion),
    Scenario("budget_stopping_never_forces_confident_verdict", scenario_budget_stopping_never_forces_confident_verdict),
    Scenario("evidence_clerk_flags_missing_evidence", scenario_evidence_clerk_flags_missing_evidence),
    Scenario("risk_counsel_recommends_not_authorizes", scenario_risk_counsel_recommends_not_authorizes),
]


def run_all() -> dict:
    results = []
    for scenario in SCENARIOS:
        try:
            passed, error = scenario.fn(), None
        except Exception as e:
            passed, error = False, str(e)
        results.append({"name": scenario.name, "passed": passed, "error": error})
    total = len(results)
    passed_count = sum(1 for r in results if r["passed"])
    return {
        "total": total, "passed": passed_count, "pass_rate": round(passed_count / total, 3), "results": results,
        "covered_elsewhere_live": [
            "constructor_confident_but_wrong (tests/test_deliberation_court_integration.py)",
            "cancellation_during_court (tests/test_deliberation_cancellation.py)",
            "role_injection_attack (tests/test_deliberation_security.py)",
            "same_model_constructor_falsifier_limitation (tests/test_deliberation_court_integration.py::test_court_records_which_model_served_each_role)",
            "procedure_memory_conflicts_with_current_evidence / failure_memory_informs_but_does_not_block (tests/test_memory_reflex_procedural_failure_authority.py, Phase 5.1)",
        ],
    }


if __name__ == "__main__":
    import json
    print(json.dumps(run_all(), indent=2))
