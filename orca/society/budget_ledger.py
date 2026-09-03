"""
Operationalizes the Phase 6 Cognitive Budget Market policy (Phase 7
spec §24-27; dimension-corrected Phase 7.2 spec §2-6). Phase 6 explicitly
disclosed the allocator as policy-only -- "Court still spends a fixed,
small, hard-bounded amount regardless of the allocator's output"
(docs/orneur/phase-6/COGNITIVE_BUDGET_MARKET.md). This module is what
closes that gap: `allocate_budget()`'s percentages become real per-purpose
caps, reserved BEFORE the operation launches (spec §25/§7) and consumed
against the SAME `orca.cognitive.budget.consume`/`release` ledger every
other Kernel budget dimension already uses -- no second, parallel
accounting authority.

Phase 7.2 fix: Phase 7.1 computed every purpose's cap as a percentage of
`budget.max_model_calls` alone, even for purposes (`retrieval`,
`counter_evidence`) that actually consume the SEPARATE `RETRIEVAL_CALLS`
dimension (see docs/orneur/phase-7/BUDGET_DIMENSION_AUDIT.md's finding,
made by reading `orca.truth.counter_evidence.find_counter_evidence`'s
actual body -- it is retrieval-only, no model/judge step exists). Every
purpose now declares its real `BudgetDimension`, reserves/releases against
THAT dimension specifically, and reallocation between purposes of
DIFFERENT dimensions is refused outright (spec §15: never convert
RETRIEVAL_CALLS into MODEL_CALLS just because both are "budget").
"""
from __future__ import annotations

from dataclasses import dataclass, field

from orca.cognitive.budget import consume, release
from orca.cognitive.contracts import BudgetDimension, CognitiveBudget
from orca.cognitive.errors import CognitiveBudgetExhaustedError
from orca.deliberation.budget_market import BudgetAllocation

# Purpose -> BudgetAllocation field it draws its weight from. constructor
# and falsifier both draw from `reasoning`/`falsification` respectively --
# not new allocator dimensions, reusing exactly what Phase 6 already
# computes.
_PURPOSE_TO_ALLOCATION_FIELD: dict[str, str] = {
    "constructor": "reasoning",
    "falsifier": "falsification",
    "verification": "verification",
    "counter_evidence": "counter_evidence",
    "retrieval": "retrieval",
    "optional_second_model": "agents",
    "replanning": "reasoning",
}

# The REAL resource dimension each purpose actually consumes (Phase 7.2
# spec §2, verified by reading the code -- see BUDGET_DIMENSION_AUDIT.md).
# `retrieval`/`counter_evidence` are RETRIEVAL_CALLS; everything else that
# involves an LLM inference call is MODEL_CALLS.
_PURPOSE_TO_DIMENSION: dict[str, BudgetDimension] = {
    "constructor": BudgetDimension.MODEL_CALLS,
    "falsifier": BudgetDimension.MODEL_CALLS,
    "verification": BudgetDimension.MODEL_CALLS,
    "replanning": BudgetDimension.MODEL_CALLS,
    "optional_second_model": BudgetDimension.MODEL_CALLS,
    "retrieval": BudgetDimension.RETRIEVAL_CALLS,
    "counter_evidence": BudgetDimension.RETRIEVAL_CALLS,
}

# Which CognitiveBudget field holds each dimension's cap -- mirrors
# orca.cognitive.budget._LIMIT_FIELDS exactly (not re-derived from a
# private import, to keep this module decoupled from that internal dict's
# shape) for the two dimensions Society purposes actually use today.
_DIMENSION_TO_LIMIT_FIELD: dict[BudgetDimension, str] = {
    BudgetDimension.MODEL_CALLS: "max_model_calls",
    BudgetDimension.RETRIEVAL_CALLS: "max_retrieval_calls",
}

# Honest fallback pool sizes if the CognitiveBudget doesn't track a cap
# for a dimension at all (max_*=None -- "no cap tracked"); matches
# DEFAULT_BUDGET's own values so an untracked dimension doesn't silently
# behave as "unlimited" for purpose-cap sizing purposes.
_DEFAULT_POOL: dict[BudgetDimension, int] = {
    BudgetDimension.MODEL_CALLS: 6,
    BudgetDimension.RETRIEVAL_CALLS: 4,
}

# Constructor and Falsifier must always get at least 1 call each, or Court
# could not run its single mandatory round at all -- everything else is a
# genuinely optional purpose that may legitimately cap at 0 (spec §27:
# "stop optional role calls" when budget is tight).
_MINIMUM_ONE = {"constructor", "falsifier"}


@dataclass
class BudgetReservation:
    purpose: str
    dimension: BudgetDimension
    amount: int
    released: bool = False


@dataclass
class ReallocationRecord:
    from_purpose: str
    to_purpose: str
    dimension: BudgetDimension
    amount: int
    reason: str


@dataclass
class SocietyBudgetLedger:
    """
    Wraps one `CognitiveBudget` for the duration of a single Court/Society/
    Truth-Fabric/replanning invocation. Each purpose's cap is a real
    percentage of ITS OWN dimension's remaining capacity in the shared
    `CognitiveBudget` -- distribution is a real cap per purpose, not a
    decorative number (spec §24), and never a second independent budget
    universe (spec §3): every `reserve()`/`release_reservation()` call
    ultimately calls `orca.cognitive.budget.consume`/`release` against the
    SAME `CognitiveBudget` object every other Kernel dimension check uses.
    """
    budget: CognitiveBudget
    allocation: BudgetAllocation
    caps: dict[str, int] = field(default_factory=dict)
    spent: dict[str, int] = field(default_factory=dict)
    reallocations: list[ReallocationRecord] = field(default_factory=list)

    def __post_init__(self) -> None:
        for purpose, field_name in _PURPOSE_TO_ALLOCATION_FIELD.items():
            dimension = _PURPOSE_TO_DIMENSION[purpose]
            limit_field = _DIMENSION_TO_LIMIT_FIELD[dimension]
            pool = getattr(self.budget, limit_field, None)
            if pool is None:
                pool = _DEFAULT_POOL[dimension]
            weight = getattr(self.allocation, field_name, 0.0)
            minimum = 1 if purpose in _MINIMUM_ONE else 0
            self.caps[purpose] = max(minimum, round(weight * pool))
            self.spent[purpose] = 0

    def dimension_for(self, purpose: str) -> BudgetDimension:
        return _PURPOSE_TO_DIMENSION[purpose]

    def remaining_for(self, purpose: str) -> int:
        return self.caps.get(purpose, 0) - self.spent.get(purpose, 0)

    def reserve(self, purpose: str, amount: int = 1) -> BudgetReservation:
        """
        Reserves BEFORE the operation is launched (spec §7/§25) -- never
        after the fact. Raises CognitiveBudgetExhaustedError (the same
        exception every other Kernel budget check raises) if either this
        purpose's own cap or the parent CognitiveBudget's dimension would
        be exceeded. The operation being gated must NOT start if this
        raises (spec §7's "if unavailable, do not execute").
        """
        if self.remaining_for(purpose) < amount:
            raise CognitiveBudgetExhaustedError(
                internal_detail=f"society budget purpose '{purpose}' exhausted: needs {amount}, has {self.remaining_for(purpose)} remaining"
            )
        dimension = _PURPOSE_TO_DIMENSION[purpose]
        consume(self.budget, dimension, amount)
        self.spent[purpose] = self.spent.get(purpose, 0) + amount
        return BudgetReservation(purpose=purpose, dimension=dimension, amount=amount)

    def release_reservation(self, reservation: BudgetReservation) -> None:
        """Releases unused reservation on cancellation/failure (spec §13/§23)
        -- gives back both this purpose's sub-cap and the parent ledger, in
        the SAME dimension it was reserved from. Consumed (already-run)
        work is never refunded -- only call this for a reservation that
        was made but the gated operation never actually ran."""
        if reservation.released:
            return
        release(self.budget, reservation.dimension, reservation.amount)
        self.spent[reservation.purpose] = max(0, self.spent.get(reservation.purpose, 0) - reservation.amount)
        reservation.released = True

    def reallocate(self, from_purpose: str, to_purpose: str, amount: int, reason: str) -> ReallocationRecord:
        """
        Bounded reallocation (spec §15/§26) -- only unspent capacity may
        move, every move is recorded (from/to/amount/reason/dimension),
        and a move between purposes of DIFFERENT dimensions is refused
        outright: unused RETRIEVAL_CALLS capacity is never converted into
        MODEL_CALLS capacity just because both are "budget" (spec §15's
        explicit example). Cross-dimensional conversion is deliberately
        deferred, not implemented.
        """
        from_dimension = _PURPOSE_TO_DIMENSION[from_purpose]
        to_dimension = _PURPOSE_TO_DIMENSION[to_purpose]
        if from_dimension != to_dimension:
            raise ValueError(
                f"cannot reallocate across dimensions: '{from_purpose}' is {from_dimension.value}, "
                f"'{to_purpose}' is {to_dimension.value} -- cross-dimensional conversion is not implemented"
            )
        available = self.remaining_for(from_purpose)
        if available < amount:
            raise ValueError(f"cannot reallocate {amount} unit(s) from '{from_purpose}': only {available} unspent")
        self.caps[from_purpose] -= amount
        self.caps[to_purpose] = self.caps.get(to_purpose, 0) + amount
        record = ReallocationRecord(from_purpose=from_purpose, to_purpose=to_purpose, dimension=from_dimension, amount=amount, reason=reason)
        self.reallocations.append(record)
        return record

    def is_exhausted(self, purpose: str) -> bool:
        return self.remaining_for(purpose) <= 0

    def trace(self) -> list[dict]:
        """Structured budget trace (spec §17) -- purpose/dimension/
        reserved/consumed/remaining only, no private reasoning text."""
        return [
            {
                "purpose": purpose,
                "dimension": _PURPOSE_TO_DIMENSION[purpose].value,
                "reserved": self.caps.get(purpose, 0),
                "consumed": self.spent.get(purpose, 0),
                "remaining": self.remaining_for(purpose),
            }
            for purpose in self.caps
        ]
