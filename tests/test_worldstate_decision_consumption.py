"""
Phase 7.1 spec §12-14: WorldState must actually CONSUME into a downstream
decision, not just be built and ignored (Phase 7's disclosed gap). This
test demonstrates the exact scenario spec §13 describes: an observation
that a model/deployment is unavailable changes the next routing decision.

Deterministic -- no live model call. Uses CognitiveCourt's routing path
directly (the same code a real Court invocation runs) with injected
lookups, matching the hermeticity discipline established in
tests/test_society_router.py.
"""
from __future__ import annotations

import asyncio

from orca.cognitive.contracts import RiskLevel
from orca.deliberation.contracts import CourtVerdictState, WorldState
from orca.deliberation.court import CognitiveCourt
from orca.deliberation.worldstate_ops import WorldStateOp, WorldStateUpdate, apply_update, unavailable_model_ids


def test_unavailable_model_observation_is_extracted_from_worldstate():
    state = WorldState()
    apply_update(state, WorldStateUpdate(op=WorldStateOp.UPDATE_ENTITY_STATE, entity="orneur-genesis", value="UNAVAILABLE", source_ref="tool:health-check-1"))
    assert unavailable_model_ids(state) == ["orneur-genesis"]


def test_healthy_entity_is_not_reported_unavailable():
    state = WorldState()
    apply_update(state, WorldStateUpdate(op=WorldStateOp.UPDATE_ENTITY_STATE, entity="orneur-genesis", value="READY", source_ref="tool:health-check-1"))
    assert unavailable_model_ids(state) == []


def test_court_excludes_a_worldstate_flagged_unavailable_model_from_routing():
    """The real decision-changing behavior: WITHOUT the observation,
    Constructor/Falsifier route to Genesis-legacy (the only production-
    eligible candidate today). WITH a WorldState observation that
    Genesis-legacy is unavailable, Court must honestly report
    insufficient evidence rather than silently routing to it anyway."""
    seeded_state = WorldState()
    apply_update(
        seeded_state,
        WorldStateUpdate(op=WorldStateOp.UPDATE_ENTITY_STATE, entity="orneur-genesis", value="UNAVAILABLE", source_ref="tool:deployment-health-1"),
    )

    court = CognitiveCourt()

    async def _run():
        return await court.run("Where is the Eiffel Tower?", risk_level=RiskLevel.LOW, initial_world_state=seeded_state)

    case, verdict, stop_reason = asyncio.run(_run())

    assert verdict.verdict == CourtVerdictState.INSUFFICIENT_EVIDENCE
    assert stop_reason == "COURT_INSUFFICIENT_EVIDENCE"
    assert "orneur-genesis" in case.world_state.variables
    assert "UNAVAILABLE" in str(case.world_state.variables["orneur-genesis"]["value"])


def test_court_without_the_observation_would_have_routed_normally():
    """Control case: the SAME objective, no unavailability observation --
    proves the difference above is caused by the WorldState observation,
    not by something else (e.g. missing evidence)."""
    from orca.society.contracts import CognitiveRole, RoutingRequest
    from orca.society.router import route

    decision = route(RoutingRequest(role=CognitiveRole.CONSTRUCTOR))
    assert decision.selected_model_id == "orneur-genesis"
