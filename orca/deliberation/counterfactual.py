"""
Bounded Counterfactual engine (Phase 6 spec §25). Never presented as an
observed fact -- every Counterfactual carries an explicit
`uncertainty_note`, and this module caps how many can be generated per
request (spec §30's "bounded everything" discipline).
"""
from __future__ import annotations

from orca.deliberation.contracts import Counterfactual

MAX_COUNTERFACTUALS_PER_REQUEST = 3

_DEFAULT_UNCERTAINTY_NOTE = (
    "This is a counterfactual projection, not an observed outcome -- confidence "
    "depends entirely on how well `held_constant` actually isolates `changed_variable`."
)


def build_counterfactual(
    baseline_state: str, changed_variable: str, predicted_consequence: str,
    held_constant: list[str] | None = None, uncertainty_note: str | None = None,
) -> Counterfactual:
    return Counterfactual(
        baseline_state=baseline_state, changed_variable=changed_variable,
        held_constant=list(held_constant or []), predicted_consequence=predicted_consequence,
        uncertainty_note=uncertainty_note or _DEFAULT_UNCERTAINTY_NOTE,
    )


class CounterfactualSet:
    def __init__(self, max_items: int = MAX_COUNTERFACTUALS_PER_REQUEST):
        self._items: list[Counterfactual] = []
        self._max_items = max_items

    def add(self, counterfactual: Counterfactual) -> bool:
        if len(self._items) >= self._max_items:
            return False
        self._items.append(counterfactual)
        return True

    @property
    def items(self) -> list[Counterfactual]:
        return list(self._items)
