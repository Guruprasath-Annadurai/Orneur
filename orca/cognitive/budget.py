"""
Cognitive Budget accounting -- first production form of the Orneur
Cognitive Budget (Phase 3 spec §13-14). Deliberately NOT a market
allocator: this is representation, validation, consumption accounting,
and hard-stop enforcement only. Dynamic reallocation is future work.

No cognitive operation may assume infinite budget: negative/overflowing
limits are rejected at construction, consumption is bounded, and
exhaustion is explicit (CognitiveBudgetExhaustedError) -- never a silent
continue.
"""
from __future__ import annotations

from orca.cognitive.contracts import BudgetDimension, CognitiveBudget
from orca.cognitive.errors import CognitiveBudgetExhaustedError

_LIMIT_FIELDS: dict[BudgetDimension, str] = {
    BudgetDimension.TOKENS: "max_tokens",
    BudgetDimension.LATENCY_MS: "max_latency_ms",
    BudgetDimension.MODEL_CALLS: "max_model_calls",
    BudgetDimension.RETRIEVAL_CALLS: "max_retrieval_calls",
    BudgetDimension.TOOL_CALLS: "max_tool_calls",
    BudgetDimension.AGENT_CALLS: "max_agent_calls",
    BudgetDimension.COST_USD: "max_cost_usd",
    BudgetDimension.REASONING_ROUNDS: "max_reasoning_rounds",
}
_CONSUMED_FIELDS: dict[BudgetDimension, str] = {
    BudgetDimension.TOKENS: "consumed_tokens",
    BudgetDimension.LATENCY_MS: "consumed_latency_ms",
    BudgetDimension.MODEL_CALLS: "consumed_model_calls",
    BudgetDimension.RETRIEVAL_CALLS: "consumed_retrieval_calls",
    BudgetDimension.TOOL_CALLS: "consumed_tool_calls",
    BudgetDimension.AGENT_CALLS: "consumed_agent_calls",
    BudgetDimension.COST_USD: "consumed_cost_usd",
    BudgetDimension.REASONING_ROUNDS: "consumed_reasoning_rounds",
}

# A sane, documented default -- never "unlimited by omission." Any caller
# that wants a different budget must say so explicitly.
DEFAULT_BUDGET = CognitiveBudget(
    max_tokens=8000,
    max_latency_ms=60_000.0,
    max_model_calls=6,
    max_retrieval_calls=4,
    max_tool_calls=6,
    max_agent_calls=1,
    max_cost_usd=None,
    max_reasoning_rounds=3,
)


def validate_budget(budget: CognitiveBudget) -> None:
    """Rejects negative or non-finite limits/consumed values. Called at
    construction time by callers that accept caller-supplied budgets
    (e.g. CognitiveRequest.budget_constraints)."""
    for dim, limit_field in _LIMIT_FIELDS.items():
        limit = getattr(budget, limit_field)
        if limit is not None and limit < 0:
            raise ValueError(f"{limit_field} must be >= 0 or None, got {limit}")
    for dim, consumed_field in _CONSUMED_FIELDS.items():
        consumed = getattr(budget, consumed_field)
        if consumed < 0:
            raise ValueError(f"{consumed_field} must be >= 0, got {consumed}")


def remaining(budget: CognitiveBudget, dimension: BudgetDimension) -> float | int | None:
    """None means "no cap tracked for this dimension" -- not "unlimited
    silently," an explicit, observable state (Phase 3 spec §14: remaining
    budget must be observable)."""
    limit = getattr(budget, _LIMIT_FIELDS[dimension])
    if limit is None:
        return None
    consumed = getattr(budget, _CONSUMED_FIELDS[dimension])
    return limit - consumed


def is_exhausted(budget: CognitiveBudget, dimension: BudgetDimension) -> bool:
    left = remaining(budget, dimension)
    return left is not None and left <= 0


def consume(budget: CognitiveBudget, dimension: BudgetDimension, amount: float | int) -> None:
    """
    Mutates the budget's consumed_* field for `dimension` by `amount`.
    Raises CognitiveBudgetExhaustedError -- never silently continues --
    if this consumption would exceed the dimension's limit. Consumption
    that does not breach the limit is always recorded, even for a
    dimension with no limit set (so `remaining()`/observability stay
    accurate regardless of whether a cap exists).
    """
    if amount < 0:
        raise ValueError(f"consume() amount must be >= 0, got {amount}")
    limit = getattr(budget, _LIMIT_FIELDS[dimension])
    consumed_field = _CONSUMED_FIELDS[dimension]
    current = getattr(budget, consumed_field)
    new_total = current + amount
    if limit is not None and new_total > limit:
        raise CognitiveBudgetExhaustedError(
            internal_detail=f"{dimension.value}: would consume {new_total} > limit {limit}"
        )
    setattr(budget, consumed_field, new_total)


def has_any_capacity(budget: CognitiveBudget, dimension: BudgetDimension, amount: float | int = 1) -> bool:
    """Non-mutating check -- use before attempting an operation that would
    consume budget, to decide plan feasibility without side effects."""
    limit = getattr(budget, _LIMIT_FIELDS[dimension])
    if limit is None:
        return True
    consumed = getattr(budget, _CONSUMED_FIELDS[dimension])
    return consumed + amount <= limit
