"""
Operationalizes the Phase 6 Cognitive Budget Market policy (Phase 7
spec §24-27). Phase 6 explicitly disclosed the allocator as policy-only --
"Court still spends a fixed, small, hard-bounded amount regardless of the
allocator's output" (docs/orneur/phase-6/COGNITIVE_BUDGET_MARKET.md). This
module is what closes that gap: `allocate_budget()`'s percentages become
real per-purpose call caps, reserved BEFORE parallel role calls launch
(spec §25) and consumed against the SAME `orca.cognitive.budget.consume`/
`release` ledger every other Kernel budget dimension already uses -- no
second, parallel accounting authority.
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

# Constructor and Falsifier must always get at least 1 call each, or Court
# could not run its single mandatory round at all -- everything else is a
# genuinely optional purpose that may legitimately cap at 0 (spec §27:
# "stop optional role calls" when budget is tight).
_MINIMUM_ONE = {"constructor", "falsifier"}


@dataclass
class BudgetReservation:
    purpose: str
    amount: int
    released: bool = False


@dataclass
class ReallocationRecord:
    from_purpose: str
    to_purpose: str
    amount: int
    reason: str


@dataclass
class SocietyBudgetLedger:
    """
    Wraps one `CognitiveBudget` for the duration of a single Court/Society
    invocation. `budget.max_model_calls` is the total pool this ledger
    distributes across purposes -- distribution is a real cap per purpose,
    not a decorative number (spec §24's explicit requirement).
    """
    budget: CognitiveBudget
    allocation: BudgetAllocation
    caps: dict[str, int] = field(default_factory=dict)
    spent: dict[str, int] = field(default_factory=dict)
    reallocations: list[ReallocationRecord] = field(default_factory=list)

    def __post_init__(self) -> None:
        pool = self.budget.max_model_calls if self.budget.max_model_calls is not None else 6
        for purpose, field_name in _PURPOSE_TO_ALLOCATION_FIELD.items():
            weight = getattr(self.allocation, field_name, 0.0)
            minimum = 1 if purpose in _MINIMUM_ONE else 0
            self.caps[purpose] = max(minimum, round(weight * pool))
            self.spent[purpose] = 0

    def remaining_for(self, purpose: str) -> int:
        return self.caps.get(purpose, 0) - self.spent.get(purpose, 0)

    def reserve(self, purpose: str, amount: int = 1) -> BudgetReservation:
        """
        Reserves BEFORE the model call is launched (spec §25) -- never
        after the fact. Raises CognitiveBudgetExhaustedError (the same
        exception every other Kernel budget check raises) if either this
        purpose's own cap or the parent CognitiveBudget's MODEL_CALLS
        dimension would be exceeded.
        """
        if self.remaining_for(purpose) < amount:
            raise CognitiveBudgetExhaustedError(
                internal_detail=f"society budget purpose '{purpose}' exhausted: needs {amount}, has {self.remaining_for(purpose)} remaining"
            )
        consume(self.budget, BudgetDimension.MODEL_CALLS, amount)
        self.spent[purpose] = self.spent.get(purpose, 0) + amount
        return BudgetReservation(purpose=purpose, amount=amount)

    def release_reservation(self, reservation: BudgetReservation) -> None:
        """Releases unused reservation on cancellation/failure (spec §25/§66)
        -- gives back both this purpose's sub-cap and the parent ledger."""
        if reservation.released:
            return
        release(self.budget, BudgetDimension.MODEL_CALLS, reservation.amount)
        self.spent[reservation.purpose] = max(0, self.spent.get(reservation.purpose, 0) - reservation.amount)
        reservation.released = True

    def reallocate(self, from_purpose: str, to_purpose: str, amount: int, reason: str) -> ReallocationRecord:
        """
        Bounded reallocation (spec §26) -- only unspent capacity may move,
        and every move is recorded (from/to/amount/reason), never a
        silent, untracked shuffle.
        """
        available = self.remaining_for(from_purpose)
        if available < amount:
            raise ValueError(f"cannot reallocate {amount} call(s) from '{from_purpose}': only {available} unspent")
        self.caps[from_purpose] -= amount
        self.caps[to_purpose] = self.caps.get(to_purpose, 0) + amount
        record = ReallocationRecord(from_purpose=from_purpose, to_purpose=to_purpose, amount=amount, reason=reason)
        self.reallocations.append(record)
        return record

    def is_exhausted(self, purpose: str) -> bool:
        return self.remaining_for(purpose) <= 0
