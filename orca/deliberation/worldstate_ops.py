"""
Typed WorldState update operations (Phase 7 spec §28-30). WorldState moves
from a Phase-6 contract-only definition to something actually populated
and consumed this phase -- but ONLY through these bounded operations.
Arbitrary model text must never mutate WorldState directly (spec §30):
every caller that wants to change a WorldState must go through
`apply_update()`, which enforces that a source/reference is always
present (spec §29 -- "WorldState must not erase provenance").

Explicitly NOT a persistent global world model (spec §28) -- every
WorldState instance is request/task-scoped, created fresh per
Court/Kernel invocation and discarded afterward; nothing here persists a
WorldState across requests.
"""
from __future__ import annotations

from dataclasses import dataclass, field
from datetime import datetime, timezone
from enum import Enum

from orca.deliberation.contracts import WorldState


def _now_iso() -> str:
    return datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")


class WorldStateOp(str, Enum):
    ADD_FACT = "ADD_FACT"
    SUPERSEDE_FACT = "SUPERSEDE_FACT"
    ADD_OBSERVATION = "ADD_OBSERVATION"
    INVALIDATE_ASSUMPTION = "INVALIDATE_ASSUMPTION"
    UPDATE_ENTITY_STATE = "UPDATE_ENTITY_STATE"


@dataclass
class WorldStateUpdate:
    op: WorldStateOp
    value: str = ""
    source_ref: str = ""     # memory ID / evidence ID / tool observation ID / "user_input:<...>" -- required, never blank (spec §29)
    entity: str | None = None
    applied_at: str = field(default_factory=_now_iso)


class MissingProvenanceError(ValueError):
    pass


def apply_update(state: WorldState, update: WorldStateUpdate) -> WorldState:
    """
    Mutates `state` in place and returns it. Refuses any update without a
    `source_ref` -- there is no code path in this function that can add a
    fact/observation/entity-state change without a provenance string
    attached, matching the same "structural, not conventional" discipline
    used throughout Deliberation Fabric.
    """
    if not update.source_ref:
        raise MissingProvenanceError(f"{update.op.value} requires a source_ref -- WorldState must not erase provenance (spec §29)")

    tagged_value = f"{update.value} [source={update.source_ref}]"

    if update.op == WorldStateOp.ADD_FACT:
        if tagged_value not in state.known_facts:
            state.known_facts.append(tagged_value)
        if update.source_ref not in state.evidence_refs:
            state.evidence_refs.append(update.source_ref)

    elif update.op == WorldStateOp.SUPERSEDE_FACT:
        if update.entity is not None:
            state.known_facts = [f for f in state.known_facts if not f.startswith(f"{update.entity}:")]
        if tagged_value not in state.known_facts:
            state.known_facts.append(tagged_value)
        if update.source_ref not in state.evidence_refs:
            state.evidence_refs.append(update.source_ref)

    elif update.op == WorldStateOp.ADD_OBSERVATION:
        if tagged_value not in state.known_facts:
            state.known_facts.append(tagged_value)
        if update.source_ref not in state.memory_refs and update.source_ref not in state.evidence_refs:
            state.evidence_refs.append(update.source_ref)

    elif update.op == WorldStateOp.INVALIDATE_ASSUMPTION:
        if update.value in state.assumption_ids:
            state.assumption_ids.remove(update.value)
        state.constraints.append(f"assumption {update.value} invalidated [source={update.source_ref}]")

    elif update.op == WorldStateOp.UPDATE_ENTITY_STATE:
        if update.entity is None:
            raise ValueError("UPDATE_ENTITY_STATE requires an entity")
        if update.entity not in state.entities:
            state.entities.append(update.entity)
        state.variables[update.entity] = {"value": update.value, "source_ref": update.source_ref, "as_of": update.applied_at}

    else:  # pragma: no cover -- exhaustive enum, defensive only
        raise ValueError(f"Unknown WorldStateOp: {update.op}")

    state.update_log.append(f"{update.op.value}:{update.source_ref}")
    return state
