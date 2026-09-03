from __future__ import annotations

import pytest

from orca.cognitive.contracts import CognitiveBudget, RiskLevel, ComplexityLevel
from orca.cognitive.errors import CognitiveBudgetExhaustedError
from orca.deliberation.budget_market import allocate_budget
from orca.society.budget_ledger import SocietyBudgetLedger


def _ledger(max_model_calls: int = 6) -> SocietyBudgetLedger:
    budget = CognitiveBudget(max_model_calls=max_model_calls)
    allocation = allocate_budget(uncertainty=0.5, risk=RiskLevel.LOW, evidence_conflict=False, complexity=ComplexityLevel.MEDIUM)
    return SocietyBudgetLedger(budget=budget, allocation=allocation)


def test_constructor_and_falsifier_always_get_at_least_one_call():
    ledger = _ledger(max_model_calls=2)
    assert ledger.caps["constructor"] >= 1
    assert ledger.caps["falsifier"] >= 1


def test_reservation_consumes_the_parent_budget_too():
    ledger = _ledger(max_model_calls=6)
    ledger.reserve("constructor", 1)
    assert ledger.budget.consumed_model_calls == 1


def test_reservation_before_launch_not_after():
    """Reserve must raise BEFORE any simulated call runs if capacity is
    insufficient -- never discovered after the fact (spec §25)."""
    ledger = _ledger(max_model_calls=1)
    ledger.caps["retrieval"] = 0
    with pytest.raises(CognitiveBudgetExhaustedError):
        ledger.reserve("retrieval", 1)
    assert ledger.budget.consumed_model_calls == 0  # never consumed on a failed reservation


def test_release_returns_budget_to_both_sub_ledger_and_parent():
    ledger = _ledger(max_model_calls=6)
    reservation = ledger.reserve("constructor", 1)
    assert ledger.budget.consumed_model_calls == 1
    ledger.release_reservation(reservation)
    assert ledger.budget.consumed_model_calls == 0
    assert ledger.spent["constructor"] == 0


def test_release_is_idempotent():
    ledger = _ledger(max_model_calls=6)
    reservation = ledger.reserve("constructor", 1)
    ledger.release_reservation(reservation)
    ledger.release_reservation(reservation)  # must not double-release
    assert ledger.budget.consumed_model_calls == 0


def test_reallocation_moves_only_unspent_capacity_and_is_recorded():
    """retrieval -> counter_evidence: both RETRIEVAL_CALLS, a legitimate
    same-dimension move (Phase 7.2: cross-dimension moves are refused --
    see test_reallocation_refuses_cross_dimension_moves below)."""
    ledger = _ledger(max_model_calls=10)
    retrieval_cap = ledger.caps["retrieval"]
    record = ledger.reallocate("retrieval", "counter_evidence", retrieval_cap, reason="no retrieval needed")
    assert ledger.caps["retrieval"] == 0
    assert record.reason == "no retrieval needed"
    assert ledger.reallocations[-1] is record


def test_reallocation_cannot_move_more_than_unspent():
    ledger = _ledger(max_model_calls=10)
    with pytest.raises(ValueError):
        ledger.reallocate("retrieval", "counter_evidence", ledger.caps["retrieval"] + 100, reason="bad")


def test_reallocation_refuses_cross_dimension_moves():
    """Phase 7.2 spec §15: unused RETRIEVAL_CALLS capacity must never be
    converted into MODEL_CALLS capacity just because both are "budget"."""
    ledger = _ledger(max_model_calls=10)
    with pytest.raises(ValueError):
        ledger.reallocate("retrieval", "falsifier", 1, reason="attack")


def test_budget_exhaustion_stops_optional_work():
    ledger = _ledger(max_model_calls=2)  # only enough for constructor+falsifier minimums
    ledger.reserve("constructor", 1)
    ledger.reserve("falsifier", 1)
    with pytest.raises(CognitiveBudgetExhaustedError):
        ledger.reserve("verification", 1)
