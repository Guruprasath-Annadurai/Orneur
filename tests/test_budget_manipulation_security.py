"""
Phase 7.2 spec §25-26: user/model/retrieved content cannot set unlimited
budget, negative usage, a larger parent allowance, free reallocation, or a
fake reservation release. System policy remains authoritative.
"""
from __future__ import annotations

import dataclasses

import pytest

from orca.cognitive.budget import consume, release, validate_budget
from orca.cognitive.contracts import BudgetDimension, CognitiveBudget, ComplexityLevel, RiskLevel
from orca.cognitive.errors import CognitiveBudgetExhaustedError
from orca.deliberation.budget_market import allocate_budget
from orca.society.budget_ledger import SocietyBudgetLedger


def test_cognitive_budget_rejects_negative_limits_at_construction():
    """A caller cannot construct a CognitiveBudget claiming unlimited/
    negative capacity and have it silently accepted."""
    budget = CognitiveBudget(max_model_calls=-1)
    with pytest.raises(ValueError):
        validate_budget(budget)


def test_consume_rejects_negative_amount():
    budget = CognitiveBudget(max_model_calls=6)
    with pytest.raises(ValueError):
        consume(budget, BudgetDimension.MODEL_CALLS, -5)


def test_release_never_drops_consumption_below_zero():
    """A fake/duplicate release attempt (more than was ever consumed)
    must not produce a negative consumed total that could be exploited to
    claim more capacity than actually exists."""
    budget = CognitiveBudget(max_model_calls=6)
    release(budget, BudgetDimension.MODEL_CALLS, 100)  # nothing was ever consumed
    assert budget.consumed_model_calls == 0
    assert budget.consumed_model_calls >= 0


def test_fake_reservation_release_cannot_be_replayed_for_extra_capacity():
    """Releasing the SAME reservation object twice must not hand back
    capacity twice (a 'free reallocation' attack via double-release)."""
    budget = CognitiveBudget(max_model_calls=2)
    allocation = allocate_budget(uncertainty=0.5, risk=RiskLevel.LOW, evidence_conflict=False, complexity=ComplexityLevel.MEDIUM)
    ledger = SocietyBudgetLedger(budget=budget, allocation=allocation)

    reservation = ledger.reserve("constructor", 1)
    assert budget.consumed_model_calls == 1
    ledger.release_reservation(reservation)
    assert budget.consumed_model_calls == 0
    ledger.release_reservation(reservation)
    ledger.release_reservation(reservation)
    # Replaying the release must never drive consumption negative or
    # manufacture phantom capacity -- the underlying CognitiveBudget's own
    # `release()` floors at zero (orca.cognitive.budget.release).
    assert budget.consumed_model_calls == 0

    # Real remaining capacity is still exactly the parent's max_model_calls (2),
    # never inflated by the replayed releases above.
    ledger.reserve("constructor", 1)
    ledger.reserve("falsifier", 1)
    with pytest.raises(CognitiveBudgetExhaustedError):
        ledger.reserve("constructor", 1)  # a 3rd unit -- budget is genuinely exhausted at 2


def test_caller_cannot_widen_a_purpose_cap_beyond_the_parent_dimension_via_reservation():
    """reserve() checks BOTH the purpose's own cap AND the parent
    CognitiveBudget's real dimension cap -- a caller cannot bypass the
    parent limit merely because a purpose's own cap looks unspent."""
    budget = CognitiveBudget(max_model_calls=1)
    allocation = allocate_budget(uncertainty=0.5, risk=RiskLevel.LOW, evidence_conflict=False, complexity=ComplexityLevel.MEDIUM)
    ledger = SocietyBudgetLedger(budget=budget, allocation=allocation)
    ledger.caps["constructor"] = 100  # attacker-controlled-looking widened purpose cap

    ledger.reserve("constructor", 1)  # consumes the only real MODEL_CALLS unit
    with pytest.raises(CognitiveBudgetExhaustedError):
        ledger.reserve("constructor", 1)  # purpose cap says "plenty left" but parent budget is exhausted


def test_reallocation_cannot_manufacture_capacity_beyond_the_parent_pool():
    budget = CognitiveBudget(max_retrieval_calls=4)
    allocation = allocate_budget(uncertainty=0.5, risk=RiskLevel.LOW, evidence_conflict=False, complexity=ComplexityLevel.MEDIUM)
    ledger = SocietyBudgetLedger(budget=budget, allocation=allocation)
    total_before = sum(cap for p, cap in ledger.caps.items() if p in ("retrieval", "counter_evidence"))

    with pytest.raises(ValueError):
        ledger.reallocate("retrieval", "counter_evidence", amount=total_before + 1, reason="attack")


def test_routing_request_has_no_field_that_could_set_unlimited_budget():
    from orca.society.contracts import RoutingRequest
    field_names = {f.name for f in dataclasses.fields(RoutingRequest)}
    assert not (field_names & {"max_budget", "unlimited_budget", "budget_override", "cost_ceiling"})
