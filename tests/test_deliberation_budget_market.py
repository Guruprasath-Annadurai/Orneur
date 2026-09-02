"""Phase 6: Cognitive Budget Market foundation -- deterministic, testable."""
from __future__ import annotations

from orca.cognitive.contracts import ComplexityLevel, RiskLevel
from orca.deliberation.budget_market import allocate_budget


def test_allocation_always_sums_to_one():
    for uncertainty in (0.0, 0.3, 0.5, 0.9, 1.0):
        for risk in RiskLevel:
            a = allocate_budget(uncertainty, risk, evidence_conflict=False, complexity=ComplexityLevel.LOW)
            assert abs(sum(a.as_dict().values()) - 1.0) < 1e-6


def test_low_uncertainty_favors_reasoning():
    low = allocate_budget(0.1, RiskLevel.LOW, False, ComplexityLevel.LOW)
    high = allocate_budget(0.9, RiskLevel.LOW, False, ComplexityLevel.LOW)
    assert low.reasoning > high.reasoning


def test_evidence_conflict_favors_retrieval_and_falsification():
    no_conflict = allocate_budget(0.5, RiskLevel.LOW, False, ComplexityLevel.LOW)
    conflict = allocate_budget(0.5, RiskLevel.LOW, True, ComplexityLevel.LOW)
    assert conflict.retrieval > no_conflict.retrieval
    assert conflict.falsification > no_conflict.falsification


def test_high_risk_favors_verification():
    low_risk = allocate_budget(0.5, RiskLevel.LOW, False, ComplexityLevel.LOW)
    high_risk = allocate_budget(0.5, RiskLevel.CRITICAL, False, ComplexityLevel.LOW)
    assert high_risk.verification > low_risk.verification


def test_low_remaining_latency_reduces_optional_deliberation():
    plenty_of_time = allocate_budget(0.5, RiskLevel.LOW, False, ComplexityLevel.LOW, remaining_latency_ms=60000)
    low_time = allocate_budget(0.5, RiskLevel.LOW, False, ComplexityLevel.LOW, remaining_latency_ms=500)
    assert low_time.falsification <= plenty_of_time.falsification
    assert low_time.simulation <= plenty_of_time.simulation
    assert low_time.reasoning > plenty_of_time.reasoning
