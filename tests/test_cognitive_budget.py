"""
Cognitive Budget: representation, validation, consumption accounting, and
hard-stop enforcement (Phase 3 spec §13-14). No operation may assume
infinite budget; exhaustion must be explicit, never a silent continue.
"""
from __future__ import annotations

import pytest

from orca.cognitive.budget import DEFAULT_BUDGET, consume, has_any_capacity, is_exhausted, remaining, validate_budget
from orca.cognitive.contracts import BudgetDimension, CognitiveBudget
from orca.cognitive.errors import CognitiveBudgetExhaustedError


def test_default_budget_has_no_negative_or_missing_caps():
    validate_budget(DEFAULT_BUDGET)  # must not raise
    assert DEFAULT_BUDGET.max_model_calls is not None


def test_negative_limit_rejected():
    with pytest.raises(ValueError):
        validate_budget(CognitiveBudget(max_tokens=-1))


def test_negative_consumed_rejected():
    with pytest.raises(ValueError):
        validate_budget(CognitiveBudget(consumed_tokens=-5))


def test_consume_negative_amount_rejected():
    budget = CognitiveBudget(max_tokens=100)
    with pytest.raises(ValueError):
        consume(budget, BudgetDimension.TOKENS, -1)


def test_consume_within_limit_updates_ledger():
    budget = CognitiveBudget(max_model_calls=3)
    consume(budget, BudgetDimension.MODEL_CALLS, 1)
    assert budget.consumed_model_calls == 1
    assert remaining(budget, BudgetDimension.MODEL_CALLS) == 2


def test_consume_exceeding_limit_raises_and_does_not_mutate():
    budget = CognitiveBudget(max_model_calls=1)
    consume(budget, BudgetDimension.MODEL_CALLS, 1)
    with pytest.raises(CognitiveBudgetExhaustedError):
        consume(budget, BudgetDimension.MODEL_CALLS, 1)
    # Rejected consumption must not have been silently applied.
    assert budget.consumed_model_calls == 1


def test_is_exhausted_true_at_exact_limit():
    budget = CognitiveBudget(max_tool_calls=2)
    consume(budget, BudgetDimension.TOOL_CALLS, 2)
    assert is_exhausted(budget, BudgetDimension.TOOL_CALLS)


def test_remaining_is_none_when_dimension_uncapped():
    budget = CognitiveBudget()  # no caps set at all
    assert remaining(budget, BudgetDimension.TOKENS) is None
    assert not is_exhausted(budget, BudgetDimension.TOKENS)


def test_has_any_capacity_without_mutating():
    budget = CognitiveBudget(max_agent_calls=1)
    assert has_any_capacity(budget, BudgetDimension.AGENT_CALLS, 1)
    assert budget.consumed_agent_calls == 0  # non-mutating check
    consume(budget, BudgetDimension.AGENT_CALLS, 1)
    assert not has_any_capacity(budget, BudgetDimension.AGENT_CALLS, 1)


def test_consume_uncapped_dimension_always_records_and_never_raises():
    budget = CognitiveBudget()
    consume(budget, BudgetDimension.COST_USD, 500.0)
    assert budget.consumed_cost_usd == 500.0
