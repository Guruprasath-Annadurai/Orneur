"""
WorldState projection (Phase 11 spec §6, §15, §33). Produces a
HYPOTHETICAL `WorldState` by applying `orca.deliberation.worldstate_ops.apply_update()`
-- the SAME real, typed operation machinery Phase 7 built -- to a real
`copy.deepcopy()` of the parent state, NEVER the live instance itself.

Structural guarantee: `project_worldstate()` never receives nor returns
a reference to the caller's original `WorldState` object -- it always
operates on and returns a distinct copy, so a caller cannot accidentally
alias predicted state onto the real one.
"""
from __future__ import annotations

import copy
from dataclasses import dataclass, field

from orca.deliberation.contracts import WorldState
from orca.deliberation.worldstate_ops import WorldStateOp, WorldStateUpdate, apply_update
from orca.simulation.contracts import PredictedEffect, _new_id, now_iso


@dataclass
class WorldStateProjection:
    """spec §33: simulation_id, parent WorldState ID, source action,
    assumptions, predicted changes -- a distinct typed record, never a
    silently-mutated live WorldState."""
    projection_id: str = field(default_factory=lambda: _new_id("wsproj"))
    parent_world_state_id: str = ""
    source_action_id: str = ""
    assumption_ids: list[str] = field(default_factory=list)
    projected_state: WorldState = field(default_factory=WorldState)
    created_at: str = field(default_factory=now_iso)


def project_worldstate(
    parent: WorldState, *, source_action_id: str, predicted_effects: list[PredictedEffect], assumption_ids: list[str] | None = None,
) -> WorldStateProjection:
    """
    Applies each `PredictedEffect` as an `ADD_OBSERVATION`-shaped update
    to a DEEP COPY of `parent` -- the parent argument itself is never
    mutated (verified directly: `parent.update_log`/`parent.known_facts`
    are unchanged after this call in every test). Each projected fact is
    prefixed `"SIMULATED:"` so a projected `WorldState`'s own
    `known_facts` list is never visually indistinguishable from a real
    observation's, even if a caller later mishandles provenance.
    """
    projected = copy.deepcopy(parent)
    for effect in predicted_effects:
        fact = f"SIMULATED:{effect.effect_type.value}:{effect.resource}->{effect.predicted_after_reference}"
        apply_update(
            projected,
            WorldStateUpdate(op=WorldStateOp.ADD_OBSERVATION, value=fact, source_ref=f"simulation:{source_action_id}:{effect.effect_id}"),
        )

    return WorldStateProjection(
        parent_world_state_id=parent.world_state_id, source_action_id=source_action_id,
        assumption_ids=list(assumption_ids or []), projected_state=projected,
    )
