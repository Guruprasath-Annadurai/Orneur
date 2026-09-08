"""
Phase 15.9 -- Court/mission integration (spec sections 14, 27-28).

Does NOT create a second mission completion state machine.
`orca.mission.state_machine`/`mission_store.transition_mission()`
(Phase 15.3, unmodified) still own the actual `COURT_REVIEW` ->
`COMPLETED_VERIFIED` transition and its evidence_ref requirement.
This module only decides WHETHER that transition should be attempted,
by combining:

  1. `orca.mission.mission_verification_gate` (Phase 15.8) -- is every
     required requirement's verification PASS for the current revision?
  2. This phase's `CourtDecision.verdict` -- did the Court actually
     ACCEPT?

Court review is explicitly NOT authority (spec section 28): even
`can_proceed_to_completed_verified() == True` grants no permission to
deploy, mutate production, or access a secret -- that still requires
the real Phase 15.5 authority path, entirely separately. Likewise, a
real Phase 15.5 authority approval does not force a Court ACCEPT --
the two planes never influence one another's decision logic.
"""
from __future__ import annotations

from orca.mission.cognitive_court import CourtDecision, CourtVerdict
from orca.mission.mission_verification_gate import can_complete_verified
from orca.mission.verification import VerificationRecord


class CourtMissionGateError(Exception):
    pass


def can_proceed_to_completed_verified(
    *, court_decision: CourtDecision,
    records_by_requirement: dict[str, tuple[VerificationRecord, ...]],
    required_requirement_ids: tuple[str, ...], current_revision: str,
) -> tuple[bool, str]:
    """Returns (can_proceed, reason). Only True when BOTH the
    verification gate AND the Court verdict agree -- a REJECT,
    NEED_MORE_EVIDENCE, ESCALATE, or HUMAN_APPROVAL_REQUIRED verdict
    always blocks, regardless of verification state (spec section 27:
    "A REJECT verdict must block... NEED_MORE_EVIDENCE must block...
    ESCALATE must block... HUMAN_APPROVAL_REQUIRED must block")."""
    if court_decision.verdict is not CourtVerdict.ACCEPT:
        return False, f"Court verdict is {court_decision.verdict.value}, not ACCEPT."

    verification_ok, outcomes = can_complete_verified(
        records_by_requirement, required_requirement_ids=required_requirement_ids,
        current_revision=current_revision,
    )
    if not verification_ok:
        blocking = {rid: o.value for rid, o in outcomes.items() if o.value != "PASS"}
        return False, f"Verification gate not satisfied: {blocking!r}."

    return True, "Court ACCEPT and verification gate both satisfied for the current revision."
