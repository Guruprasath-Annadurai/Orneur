"""
Reality reconciliation (Phase 11 spec §58-62). Compares predicted
effects against a real, post-execution `orca.agent.contracts.Observation`
-- one of the most important Phase-11 mechanisms per the spec's own
framing: it is the only place a simulation's honesty gets checked
against what actually happened.
"""
from __future__ import annotations

from orca.agent.contracts import Observation
from orca.simulation.contracts import (
    FailureCandidateRecord,
    PredictedEffect,
    RealityDiff,
    RealityDiffStatus,
    SimulationFailureCandidateKind,
)


def reconcile(*, simulation_id: str, predicted_effects: list[PredictedEffect], observation: Observation) -> RealityDiff:
    """
    Deterministic, string-containment-based comparison -- deliberately
    simple and auditable rather than a model judging "did this match."
    `observation.status` drives the coarse classification; per-effect
    resource mentions in `observation.facts` refine it to
    `PARTIAL_MATCH`/`MISSING_EXPECTED_EFFECT` when some but not all
    predicted resources appear.
    """
    if observation.status not in ("OK", "ERROR", "CANCELLED", "DEDUPED"):
        return RealityDiff(simulation_id=simulation_id, action_id=observation.action_id, status=RealityDiffStatus.OUTCOME_UNKNOWN, predicted_effect_ids=[e.effect_id for e in predicted_effects], actual_observation_summary="unrecognized observation status", severity="MEDIUM", follow_up_required=True)

    if observation.status in ("CANCELLED",):
        return RealityDiff(simulation_id=simulation_id, action_id=observation.action_id, status=RealityDiffStatus.OUTCOME_UNKNOWN, predicted_effect_ids=[e.effect_id for e in predicted_effects], actual_observation_summary="action was cancelled -- true outcome unknown", severity="MEDIUM", follow_up_required=True)

    observed_text = " ".join(observation.facts).lower()
    matched = [e for e in predicted_effects if e.resource.lower() in observed_text]
    missing = [e for e in predicted_effects if e.resource.lower() not in observed_text]

    if observation.status == "ERROR":
        status = RealityDiffStatus.MISSING_EXPECTED_EFFECT if predicted_effects else RealityDiffStatus.UNEXPECTED_EFFECT
        return RealityDiff(
            simulation_id=simulation_id, action_id=observation.action_id, status=status,
            predicted_effect_ids=[e.effect_id for e in predicted_effects],
            actual_observation_summary=f"execution reported ERROR: {(observation.error or '')[:200]}",
            differences=[f"predicted {e.resource} but execution failed" for e in predicted_effects],
            severity="HIGH", follow_up_required=True,
        )

    if not predicted_effects:
        return RealityDiff(simulation_id=simulation_id, action_id=observation.action_id, status=RealityDiffStatus.MATCHED, actual_observation_summary="no effects were predicted and none required matching", severity="LOW", follow_up_required=False)

    if not missing:
        return RealityDiff(simulation_id=simulation_id, action_id=observation.action_id, status=RealityDiffStatus.MATCHED, predicted_effect_ids=[e.effect_id for e in matched], actual_observation_summary="all predicted resources were mentioned in the real observation", severity="LOW", follow_up_required=False)

    if matched:
        return RealityDiff(
            simulation_id=simulation_id, action_id=observation.action_id, status=RealityDiffStatus.PARTIAL_MATCH,
            predicted_effect_ids=[e.effect_id for e in matched], differences=[f"missing expected effect on {e.resource}" for e in missing],
            actual_observation_summary="some but not all predicted effects were observed", severity="MEDIUM", follow_up_required=True,
        )

    return RealityDiff(
        simulation_id=simulation_id, action_id=observation.action_id, status=RealityDiffStatus.MISSING_EXPECTED_EFFECT,
        differences=[f"missing expected effect on {e.resource}" for e in missing],
        actual_observation_summary="none of the predicted effects were observed", severity="HIGH", follow_up_required=True,
    )


def failure_candidate_from_diff(diff: RealityDiff) -> FailureCandidateRecord | None:
    """
    spec §61-62: emits a CANDIDATE record only for a genuine mismatch --
    never for MATCHED -- and NEVER writes to durable Memory or training
    data itself (that remains normal Memory governance / explicitly
    Phase 12, neither of which this function touches).
    """
    if diff.status in (RealityDiffStatus.MATCHED,):
        return None
    return FailureCandidateRecord(
        kind=SimulationFailureCandidateKind.SIMULATION_FAILURE_CANDIDATE,
        simulation_id=diff.simulation_id, reality_diff_id=diff.diff_id,
        summary=f"{diff.status.value}: {diff.actual_observation_summary}",
    )
