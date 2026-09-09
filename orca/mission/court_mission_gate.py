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

PHASE 15.9.1 CLOSURE (item 2): a real audit gap existed here -- this
function accepted ANY `CourtDecision` with `verdict is ACCEPT` and
never checked whether that decision was actually made FOR the mission
and revision currently being completed. A stale ACCEPT from an old
revision, or an ACCEPT genuinely produced for a DIFFERENT mission,
could previously be replayed to authorize an unrelated completion.
Fixed with an explicit, first-checked binding: `court_decision.revision
!= current_revision` and `court_decision.mission_id !=
current_mission_id` both BLOCK immediately, before the verification
gate is even consulted. This is DEFENSE IN DEPTH alongside
`arbiter_decide()`'s own internal binding (via `filter_current_context()`)
-- the decision itself now only ever accumulates `verification_refs`
for the correct mission/revision, and this gate independently checks
the decision's own declared mission/revision match the caller's
current context, so a caller cannot bypass the binding by constructing
or reusing a `CourtDecision` object out of context.

PHASE 15.9.2 CLOSURE (item 2): `current_mission_id` was still typed
`str | None`, so a caller could pass `None` (or an empty string) and
`filter_current_context()` would silently treat it as "no mission
scoping requested" -- exactly the unscoped-verification-query gap the
Court/COMPLETED_VERIFIED path must never allow, even though that same
`None` behavior is intentionally correct for generic Phase 15.8
utility callers of `filter_current_context()` itself (unchanged). This
mission-completion path now requires a genuine non-empty
`current_mission_id`, raising `CourtMissionGateError` immediately
otherwise, rather than silently falling through to an unscoped query.
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
    required_requirement_ids: tuple[str, ...], current_revision: str, current_mission_id: str,
) -> tuple[bool, str]:
    """Returns (can_proceed, reason). Only True when the Court
    verdict, the decision's own mission/revision binding, AND the
    verification gate ALL agree. A REJECT, NEED_MORE_EVIDENCE,
    ESCALATE, or HUMAN_APPROVAL_REQUIRED verdict always blocks
    (spec section 27). A stale-revision or cross-mission ACCEPT
    ALSO always blocks, checked BEFORE the verification gate
    (Phase 15.9.1 closure item 2) -- a `CourtDecision` for
    mission A/revision A can never authorize mission A/revision B
    or mission B/revision A.

    Raises `CourtMissionGateError` if `current_mission_id` is missing
    or empty (Phase 15.9.2 closure item 2) -- this mission-completion
    path must never silently fall through to an unscoped verification
    query."""
    if not current_mission_id:
        raise CourtMissionGateError(
            "can_proceed_to_completed_verified() requires a non-empty "
            "current_mission_id -- a missing/empty mission identity would "
            "disable cross-mission filtering for the mission-completion path "
            "(Phase 15.9.2 closure item 2)."
        )

    if court_decision.verdict is not CourtVerdict.ACCEPT:
        return False, f"Court verdict is {court_decision.verdict.value}, not ACCEPT."

    if court_decision.revision != current_revision:
        return False, (
            f"Court decision {court_decision.decision_id!r} was made for revision "
            f"{court_decision.revision!r}, not the current revision {current_revision!r} -- "
            f"a stale-revision ACCEPT cannot authorize completion."
        )

    if court_decision.mission_id != current_mission_id:
        return False, (
            f"Court decision {court_decision.decision_id!r} was made for mission "
            f"{court_decision.mission_id!r}, not the current mission {current_mission_id!r} -- "
            f"a cross-mission ACCEPT cannot authorize completion."
        )

    verification_ok, outcomes = can_complete_verified(
        records_by_requirement, required_requirement_ids=required_requirement_ids,
        current_revision=current_revision, mission_id=current_mission_id,
    )
    if not verification_ok:
        blocking = {rid: o.value for rid, o in outcomes.items() if o.value != "PASS"}
        return False, f"Verification gate not satisfied: {blocking!r}."

    return True, "Court ACCEPT (matching mission/revision) and verification gate both satisfied."
