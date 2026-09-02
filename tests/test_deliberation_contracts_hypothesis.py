"""
Phase 6: deliberation contracts, ReasoningCompiler, HypothesisSpace,
CausalGraph, Counterfactual engine. Deterministic -- no Ollama.
"""
from __future__ import annotations

from orca.cognitive.contracts import ComplexityLevel, EvidenceLevel, RiskLevel
from orca.deliberation.causal import CausalGraph, assess_causal_relation
from orca.deliberation.compiler import compile_reasoning_plan
from orca.deliberation.contracts import (
    CausalRelationType,
    Hypothesis,
    HypothesisSet,
    HypothesisStatus,
    ReasoningMode,
)
from orca.deliberation.counterfactual import CounterfactualSet, build_counterfactual
from orca.deliberation.hypothesis import (
    all_resolved,
    distinguishing_evidence_need,
    falsify,
    mark_unresolved,
    record_contradicting_evidence,
    record_supporting_evidence,
)


# ── ReasoningCompiler ────────────────────────────────────────────────

def test_simple_low_risk_request_is_direct_no_court():
    plan = compile_reasoning_plan("What's the weather like?", ComplexityLevel.LOW, RiskLevel.LOW, EvidenceLevel.NONE)
    assert plan.mode == ReasoningMode.DIRECT
    assert not plan.requires_court


def test_high_complexity_alone_does_not_force_court():
    """Spec §6: complexity=HIGH must not, by itself, imply Court."""
    plan = compile_reasoning_plan("Explain this in depth.", ComplexityLevel.HIGH, RiskLevel.LOW, EvidenceLevel.LIGHT)
    assert not plan.requires_court


def test_audit_grade_triggers_court():
    plan = compile_reasoning_plan("What is the exact regulatory limit?", ComplexityLevel.LOW, RiskLevel.LOW, EvidenceLevel.AUDIT_GRADE)
    assert plan.requires_court
    assert plan.mode == ReasoningMode.COURT_REVIEW


def test_critical_risk_triggers_court():
    plan = compile_reasoning_plan("Should we drop this production table?", ComplexityLevel.LOW, RiskLevel.CRITICAL, EvidenceLevel.SUPPORTED)
    assert plan.requires_court


def test_ambiguous_objective_requires_hypotheses():
    plan = compile_reasoning_plan("The latency could be caused by either CPU or network.", ComplexityLevel.MEDIUM, RiskLevel.LOW, EvidenceLevel.SUPPORTED)
    assert plan.requires_hypotheses


def test_court_and_hypotheses_are_bounded():
    plan = compile_reasoning_plan("Should we drop this production table?", ComplexityLevel.HIGH, RiskLevel.CRITICAL, EvidenceLevel.AUDIT_GRADE)
    assert plan.max_rounds <= 3
    assert plan.max_hypotheses <= 4


# ── HypothesisSpace ──────────────────────────────────────────────────

def test_hypothesis_set_is_bounded():
    hs = HypothesisSet(max_hypotheses=2)
    assert hs.add(Hypothesis(statement="a"))
    assert hs.add(Hypothesis(statement="b"))
    assert not hs.add(Hypothesis(statement="c"))
    assert len(hs.hypotheses) == 2


def test_falsified_hypothesis_is_never_deleted():
    hs = HypothesisSet()
    h = Hypothesis(statement="wrong theory")
    hs.add(h)
    falsify(h, "ev1")
    assert h in hs.hypotheses
    assert h.status == HypothesisStatus.FALSIFIED


def test_supporting_evidence_moves_to_supported():
    h = Hypothesis(statement="theory")
    record_supporting_evidence(h, "ev1")
    assert h.status == HypothesisStatus.SUPPORTED


def test_more_contradicting_than_supporting_weakens():
    h = Hypothesis(statement="theory")
    record_supporting_evidence(h, "ev1")
    record_contradicting_evidence(h, "ev2")
    record_contradicting_evidence(h, "ev3")
    assert h.status == HypothesisStatus.WEAKENED


def test_falsified_status_is_terminal():
    h = Hypothesis(statement="theory")
    falsify(h, "ev1")
    record_supporting_evidence(h, "ev2")  # even later "support" doesn't un-falsify
    assert h.status == HypothesisStatus.FALSIFIED


def test_all_resolved_stop_condition():
    h1, h2 = Hypothesis(statement="a"), Hypothesis(statement="b")
    hs = HypothesisSet(hypotheses=[h1, h2])
    assert not all_resolved(hs)
    falsify(h1, "ev1")
    assert not all_resolved(hs)  # h2 still ACTIVE
    mark_unresolved(h2)
    assert all_resolved(hs)


def test_distinguishing_evidence_need_references_both_hypotheses():
    h1, h2 = Hypothesis(statement="CPU contention"), Hypothesis(statement="network latency")
    need = distinguishing_evidence_need(h1, h2)
    assert h1.hypothesis_id in need.distinguishes_hypothesis_ids
    assert h2.hypothesis_id in need.distinguishes_hypothesis_ids


# ── Causal graph ─────────────────────────────────────────────────────

def test_no_evidence_is_unknown_relationship():
    rel = assess_causal_relation("deploy", "outage", [])
    assert rel.relationship_type == CausalRelationType.UNKNOWN


def test_evidence_alone_without_mechanism_is_correlation_only():
    """Spec §24: never silently upgrade correlation into causation."""
    rel = assess_causal_relation("ice cream sales", "drowning incidents", ["ev1"])
    assert rel.relationship_type == CausalRelationType.CORRELATES_WITH


def test_controlled_comparison_justifies_causes():
    rel = assess_causal_relation("new deploy", "error rate spike", ["ev1"], controlled_comparison=True)
    assert rel.relationship_type == CausalRelationType.CAUSES


def test_single_signal_is_contributes_to_not_causes():
    rel = assess_causal_relation("cold weather", "increased heating use", ["ev1"], temporal_precedence=True)
    assert rel.relationship_type == CausalRelationType.CONTRIBUTES_TO


def test_causal_graph_is_bounded():
    graph = CausalGraph()
    from orca.deliberation.causal import MAX_RELATIONS_PER_GRAPH
    for i in range(MAX_RELATIONS_PER_GRAPH + 5):
        graph.add(assess_causal_relation(f"c{i}", f"e{i}", ["ev"]))
    assert len(graph.relations) == MAX_RELATIONS_PER_GRAPH


def test_correlation_only_filter():
    graph = CausalGraph()
    graph.add(assess_causal_relation("a", "b", ["ev1"]))  # correlation only
    graph.add(assess_causal_relation("c", "d", ["ev2"], controlled_comparison=True))  # causal
    assert len(graph.correlation_only()) == 1


# ── Counterfactual engine ────────────────────────────────────────────

def test_counterfactual_carries_uncertainty_note():
    cf = build_counterfactual("service was deployed at 10:00", "the deploy had not happened", "no error spike would likely have occurred")
    assert cf.uncertainty_note
    assert "not an observed outcome" in cf.uncertainty_note


def test_counterfactual_set_is_bounded():
    from orca.deliberation.counterfactual import MAX_COUNTERFACTUALS_PER_REQUEST
    cf_set = CounterfactualSet()
    for i in range(MAX_COUNTERFACTUALS_PER_REQUEST + 3):
        cf_set.add(build_counterfactual(f"baseline{i}", f"change{i}", f"consequence{i}"))
    assert len(cf_set.items) == MAX_COUNTERFACTUALS_PER_REQUEST
