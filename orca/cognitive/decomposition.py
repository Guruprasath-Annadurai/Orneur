"""
Bounded, deterministic request decomposition (Phase 3 spec §22). Produces
flat SubObjective lists with simple sequential dependency chains -- NOT
recursive agent decomposition, which is explicitly future (Agent Runtime)
work. Depth is always exactly 1 in Phase 3 (no sub-objective ever spawns
its own sub-objectives); MAX_NESTING_DEPTH exists to document that bound
for whatever later phase adds real nesting, not because anything here
produces more than one level today.
"""
from __future__ import annotations

import re

from orca.cognitive.contracts import SubObjective, _new_id

MAX_SUB_OBJECTIVES = 6
MAX_NESTING_DEPTH = 1

_SPLIT_RE = re.compile(r"\s*(?:;|\band then\b|\bthen\b|\bafter that\b)\s*", re.IGNORECASE)


def decompose(objective: str) -> list[SubObjective]:
    """
    Splits on explicit sequential connectors only (";", "and then",
    "then", "after that") -- never on plain "and" (too likely to split a
    single coherent request, e.g. "compare X and Y"). Each resulting part
    depends on the previous one, modeling the sequential intent the
    connector itself expressed. Returns a single SubObjective (no real
    decomposition) when no connector is found or only one part remains
    after truncation to MAX_SUB_OBJECTIVES.
    """
    parts = [p.strip() for p in _SPLIT_RE.split(objective) if p.strip()]
    parts = parts[:MAX_SUB_OBJECTIVES]
    if len(parts) <= 1:
        return [SubObjective(sub_objective_id=_new_id("sub"), description=objective)]

    sub_objectives: list[SubObjective] = []
    previous_id: str | None = None
    for part in parts:
        sub_id = _new_id("sub")
        sub_objectives.append(SubObjective(
            sub_objective_id=sub_id,
            description=part,
            depends_on=[previous_id] if previous_id else [],
        ))
        previous_id = sub_id
    return sub_objectives
