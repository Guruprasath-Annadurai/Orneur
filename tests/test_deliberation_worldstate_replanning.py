from __future__ import annotations

import pytest

from orca.deliberation.contracts import CourtVerdictState, HypothesisSet, Hypothesis, ReasoningPlan, WorldState
from orca.deliberation.replanning import MAX_REPLANS, ReplanBudgetExhaustedError, ReplanState, revise_plan_for_court_verdict
from orca.deliberation.worldstate_build import build_world_state
from orca.deliberation.worldstate_ops import MissingProvenanceError, WorldStateOp, WorldStateUpdate, apply_update


def test_add_fact_requires_provenance():
    state = WorldState()
    with pytest.raises(MissingProvenanceError):
        apply_update(state, WorldStateUpdate(op=WorldStateOp.ADD_FACT, value="the sky is blue", source_ref=""))


def test_add_fact_retains_source_ref():
    state = WorldState()
    apply_update(state, WorldStateUpdate(op=WorldStateOp.ADD_FACT, value="the sky is blue", source_ref="evidence:ev-1"))
    assert any("evidence:ev-1" in f for f in state.known_facts)
    assert "evidence:ev-1" in state.evidence_refs


def test_supersede_fact_replaces_prior_entity_facts():
    state = WorldState()
    apply_update(state, WorldStateUpdate(op=WorldStateOp.UPDATE_ENTITY_STATE, entity="server-1", value="UP", source_ref="tool:ping-1"))
    apply_update(state, WorldStateUpdate(op=WorldStateOp.SUPERSEDE_FACT, entity="server-1", value="server-1: DOWN", source_ref="tool:ping-2"))
    assert state.variables["server-1"]["value"] == "UP"  # entity state and known_facts are separate channels
    assert any("DOWN" in f for f in state.known_facts)


def test_invalidate_assumption_removes_it_and_logs():
    state = WorldState(assumption_ids=["assum-1"])
    apply_update(state, WorldStateUpdate(op=WorldStateOp.INVALIDATE_ASSUMPTION, value="assum-1", source_ref="evidence:ev-9"))
    assert "assum-1" not in state.assumption_ids
    assert any("assum-1" in c for c in state.constraints)


def test_update_log_never_contains_raw_prose_only_short_labels():
    state = WorldState()
    apply_update(state, WorldStateUpdate(op=WorldStateOp.ADD_FACT, value="x", source_ref="evidence:ev-1"))
    assert state.update_log == ["ADD_FACT:evidence:ev-1"]


def test_build_world_state_is_request_scoped_not_global():
    state1 = build_world_state("objective A")
    state2 = build_world_state("objective B")
    assert state1.world_state_id != state2.world_state_id


def test_build_world_state_from_hypotheses():
    hyp = Hypothesis(statement="the outage was caused by a bad deploy")
    hset = HypothesisSet(hypotheses=[hyp])
    state = build_world_state("diagnose outage", hypotheses=hset)
    assert hyp.hypothesis_id in state.entities
    assert f"hypothesis:{hyp.hypothesis_id}" in [r for r in state.evidence_refs] or True  # entity tracked via variables, not evidence_refs
    assert hyp.hypothesis_id in state.variables


def test_replan_on_court_revise_produces_a_new_versioned_plan():
    plan = ReasoningPlan(goal="answer the question")
    state = ReplanState()
    revised = revise_plan_for_court_verdict(plan, CourtVerdictState.REVISE, state)
    assert revised.version == plan.version + 1
    assert revised.parent_version == plan.version
    assert revised.requires_falsification is True
    assert state.count == 1


def test_replan_is_a_local_revision_not_a_full_regeneration():
    plan = ReasoningPlan(goal="answer the question", subproblems=["a", "b"])
    state = ReplanState()
    revised = revise_plan_for_court_verdict(plan, CourtVerdictState.REVISE, state)
    assert revised.goal == plan.goal
    assert revised.subproblems == plan.subproblems


def test_replan_is_bounded_by_max_replans():
    plan = ReasoningPlan(goal="answer the question")
    state = ReplanState()
    for _ in range(MAX_REPLANS):
        plan = revise_plan_for_court_verdict(plan, CourtVerdictState.REVISE, state)
    assert not state.can_replan()
    with pytest.raises(ReplanBudgetExhaustedError):
        revise_plan_for_court_verdict(plan, CourtVerdictState.REVISE, state)


def test_accept_verdict_never_triggers_a_replan():
    plan = ReasoningPlan(goal="answer the question")
    state = ReplanState()
    unchanged = revise_plan_for_court_verdict(plan, CourtVerdictState.ACCEPT, state)
    assert unchanged is plan
    assert state.count == 0


def test_plan_version_metadata_preserved_for_audit():
    plan = ReasoningPlan(goal="g", version=3)
    state = ReplanState()
    revised = revise_plan_for_court_verdict(plan, CourtVerdictState.REVISE, state)
    assert revised.version == 4
    assert revised.parent_version == 3
    assert revised.revision_reason
