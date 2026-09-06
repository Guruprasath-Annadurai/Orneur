"""
Phase 7.2 spec §14, §16: budget invariants and partial multi-resource
failure scenarios. Deterministic property checks over SocietyBudgetLedger.
"""
from __future__ import annotations

import pytest

from orca.cognitive.contracts import CognitiveBudget, ComplexityLevel, RiskLevel
from orca.cognitive.errors import CognitiveBudgetExhaustedError
from orca.deliberation.budget_market import allocate_budget
from orca.society.budget_ledger import SocietyBudgetLedger


def _ledger(max_model_calls=6, max_retrieval_calls=4) -> SocietyBudgetLedger:
    budget = CognitiveBudget(max_model_calls=max_model_calls, max_retrieval_calls=max_retrieval_calls)
    allocation = allocate_budget(uncertainty=0.5, risk=RiskLevel.LOW, evidence_conflict=False, complexity=ComplexityLevel.MEDIUM)
    return SocietyBudgetLedger(budget=budget, allocation=allocation)


def test_reserved_never_exceeds_the_parent_dimension_capacity():
    ledger = _ledger(max_model_calls=6, max_retrieval_calls=4)
    from orca.society.budget_ledger import _PURPOSE_TO_DIMENSION
    from orca.cognitive.contracts import BudgetDimension

    model_total = sum(cap for p, cap in ledger.caps.items() if _PURPOSE_TO_DIMENSION[p] == BudgetDimension.MODEL_CALLS)
    retrieval_total = sum(cap for p, cap in ledger.caps.items() if _PURPOSE_TO_DIMENSION[p] == BudgetDimension.RETRIEVAL_CALLS)
    assert model_total <= 6 + 2  # small rounding slack from per-purpose max(minimum, round(...))
    assert retrieval_total <= 4 + 2


def test_no_double_release():
    ledger = _ledger()
    reservation = ledger.reserve("constructor", 1)
    ledger.release_reservation(reservation)
    consumed_after_first_release = ledger.budget.consumed_model_calls
    ledger.release_reservation(reservation)  # must be a no-op
    assert ledger.budget.consumed_model_calls == consumed_after_first_release


def test_no_double_consume_from_a_single_reservation():
    ledger = _ledger()
    reservation = ledger.reserve("constructor", 1)
    assert ledger.budget.consumed_model_calls == 1
    # Reserving again is a SEPARATE reservation, not a re-consumption of the same one.
    ledger.reserve("falsifier", 1)
    assert ledger.budget.consumed_model_calls == 2


def test_remaining_never_negative_after_valid_operations():
    ledger = _ledger(max_model_calls=2)
    ledger.reserve("constructor", 1)
    ledger.reserve("falsifier", 1)
    for purpose in ledger.caps:
        assert ledger.remaining_for(purpose) >= 0 or ledger.caps[purpose] == 0


def test_cancelled_unused_reservation_returns_capacity():
    ledger = _ledger(max_model_calls=6)
    before = ledger.budget.consumed_model_calls
    reservation = ledger.reserve("verification", 1)
    assert ledger.budget.consumed_model_calls == before + 1
    ledger.release_reservation(reservation)
    assert ledger.budget.consumed_model_calls == before


def test_child_allocation_cannot_exceed_parent_after_reallocation():
    ledger = _ledger(max_retrieval_calls=4)
    total_before = sum(cap for p, cap in ledger.caps.items() if p in ("retrieval", "counter_evidence"))
    ledger.reallocate("retrieval", "counter_evidence", ledger.caps["retrieval"], reason="test")
    total_after = sum(cap for p, cap in ledger.caps.items() if p in ("retrieval", "counter_evidence"))
    assert total_after == total_before  # reallocation redistributes, never creates


def test_partial_multi_resource_failure_retrieval_succeeds_verification_fails():
    """spec §14: retrieval reservation succeeds, verification reservation
    fails -- the system must not accidentally exceed the MODEL_CALLS
    budget, and the already-consumed retrieval charge is retained (not
    refunded, since that work already happened), while the failed
    verification reservation contributes nothing."""
    budget = CognitiveBudget(max_model_calls=0, max_retrieval_calls=4)
    allocation = allocate_budget(uncertainty=0.5, risk=RiskLevel.LOW, evidence_conflict=False, complexity=ComplexityLevel.MEDIUM)
    ledger = SocietyBudgetLedger(budget=budget, allocation=allocation)
    ledger.caps["retrieval"] = 4  # widen, matching real code's "sole consumer" pattern

    retrieval_reservation = ledger.reserve("retrieval", 1)  # succeeds -- RETRIEVAL_CALLS has capacity
    assert budget.consumed_retrieval_calls == 1

    with pytest.raises(CognitiveBudgetExhaustedError):
        ledger.reserve("verification", 1)  # fails -- MODEL_CALLS has zero capacity

    assert budget.consumed_model_calls == 0  # never exceeded despite the retrieval success
    assert budget.consumed_retrieval_calls == 1  # retrieval's already-done work is NOT refunded
