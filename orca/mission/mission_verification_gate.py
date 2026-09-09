"""
Phase 15.8 -- mission-completion verification gate (spec section 18).

Does NOT implement a second mission completion state machine.
`orca.mission.state_machine`/`mission_store.transition_mission()`
already enforce that `COMPLETED_VERIFIED` is only reachable from
VERIFYING/COURT_REVIEW and requires a non-empty `evidence_ref` (Phase
15.3). This module adds the layer ABOVE that: it decides whether the
REQUIRED verification set for a mission's requirements has actually
reached PASS before ever attempting that transition, using
`orca.mission.verification_aggregation.evaluate_requirement_
completion_for_mission()` -- the SAME centralized, non-vacuous,
authoritatively-scoped aggregation function
`orca.mission.cognitive_court.arbiter_decide()` uses (Phase 15.9.4
closure item 9) -- it never mutates the aggregation rule or bypasses
it for convenience.

PHASE 15.9.3 CLOSURE (items 1-2): an independent audit found this
module (and `arbiter_decide()`) trusted a `records_by_requirement`
dictionary KEY as if it were authority for a record's own identity,
and that a requirement with multiple required acceptance criteria
could PASS with evidence for only SOME of them. Both gaps were closed
by requirement-id binding and criterion-completeness checking.

PHASE 15.9.4 CLOSURE: tracing this hardened path further, an
independent audit found that the Phase 15.9.3 fix could still fall
back to "whatever verification records happen to exist" whenever the
Phase 15.7 in-process `AcceptanceCriterion` registry had nothing
registered for a requirement (and no explicit override was supplied)
-- a fail-OPEN condition, since a separately-started process that
never repopulates that in-memory registry would silently accept a
weaker verification scope than originally intended. This module now
REQUIRES every caller to supply an explicit, already-resolved
`RequiredVerificationScope` per required requirement
(`required_scopes_by_requirement`) -- there is no longer any code path
here that consults the in-process registry or falls back to whatever
records happen to be present. A requirement with no entry in
`required_scopes_by_requirement` raises `MissionVerificationGateError`
immediately, before any outcome is computed -- unknown expected scope
fails closed, it is never silently treated as "nothing is required."
`mission_id` is likewise now mandatory (previously optional for
generic Phase 15.8 backward compatibility) since this function
directly gates the `COMPLETED_VERIFIED` transition and is therefore
itself part of the mission-critical path, not a generic utility.
"""
from __future__ import annotations

from orca.mission.verification import VerificationOutcome, VerificationRecord
from orca.mission.verification_aggregation import (
    RequiredVerificationScope,
    evaluate_requirement_completion_for_mission,
)


class MissionVerificationGateError(Exception):
    pass


def can_complete_verified(
    records_by_requirement: dict[str, tuple[VerificationRecord, ...]],
    *,
    required_requirement_ids: tuple[str, ...],
    current_revision: str,
    mission_id: str,
    required_scopes_by_requirement: dict[str, RequiredVerificationScope],
) -> tuple[bool, dict[str, VerificationOutcome]]:
    """Returns (can_complete, per_requirement_outcome). `can_complete`
    is True only if EVERY required requirement's CURRENT-REVISION,
    CURRENT-MISSION, CURRENT-REQUIREMENT-IDENTITY (Phase 15.9.3
    closure item 1) verification history satisfies its OWN explicit
    `RequiredVerificationScope` from `required_scopes_by_requirement`
    (Phase 15.9.4 closure) -- a requirement missing from
    `records_by_requirement` entirely, or missing any key its scope
    requires, aggregates to UNVERIFIED (never vacuously PASS).

    Raises `MissionVerificationGateError` if `required_requirement_ids`
    is empty (Phase 15.9.2 closure item 1), if `mission_id` is empty
    (Phase 15.9.4 closure), or if ANY required requirement has no
    entry in `required_scopes_by_requirement` (Phase 15.9.4 closure
    item 4 -- unknown expected scope fails closed, it is never
    silently inferred from the Phase 15.7 registry or from whatever
    records happen to exist)."""
    if not required_requirement_ids:
        raise MissionVerificationGateError(
            "can_complete_verified() requires at least one required_requirement_id -- "
            "an empty required set would vacuously permit COMPLETED_VERIFIED."
        )
    if not mission_id:
        raise MissionVerificationGateError(
            "can_complete_verified() requires a non-empty mission_id -- this function "
            "directly gates COMPLETED_VERIFIED and is itself part of the mission-"
            "critical path (Phase 15.9.4 closure)."
        )
    missing_scopes = [rid for rid in required_requirement_ids if rid not in required_scopes_by_requirement]
    if missing_scopes:
        raise MissionVerificationGateError(
            f"can_complete_verified() has no explicit RequiredVerificationScope for: "
            f"{missing_scopes!r} -- an unknown expected verification scope must never "
            f"be silently inferred from the AcceptanceCriterion registry or from "
            f"whatever records happen to exist (Phase 15.9.4 closure)."
        )
    outcomes: dict[str, VerificationOutcome] = {}
    for req_id in required_requirement_ids:
        records = records_by_requirement.get(req_id, ())
        scope = required_scopes_by_requirement[req_id]
        outcome, _ = evaluate_requirement_completion_for_mission(
            records, requirement_id=req_id, current_revision=current_revision, mission_id=mission_id,
            required_scope=scope,
        )
        outcomes[req_id] = outcome
    can_complete = all(o is VerificationOutcome.PASS for o in outcomes.values())
    return can_complete, outcomes


def require_can_complete_verified(
    records_by_requirement: dict[str, tuple[VerificationRecord, ...]],
    *,
    required_requirement_ids: tuple[str, ...],
    current_revision: str,
    mission_id: str,
    required_scopes_by_requirement: dict[str, RequiredVerificationScope],
) -> None:
    """Raises MissionVerificationGateError with the exact per-requirement
    breakdown if COMPLETED_VERIFIED cannot yet be reached -- callers
    (e.g. a mission runner about to call
    orca.mission.mission_store.transition_mission(..., COMPLETED_VERIFIED))
    call this FIRST and only proceed if it does not raise."""
    can_complete, outcomes = can_complete_verified(
        records_by_requirement, required_requirement_ids=required_requirement_ids,
        current_revision=current_revision, mission_id=mission_id,
        required_scopes_by_requirement=required_scopes_by_requirement,
    )
    if not can_complete:
        blocking = {rid: o.value for rid, o in outcomes.items() if o is not VerificationOutcome.PASS}
        raise MissionVerificationGateError(
            f"Cannot reach COMPLETED_VERIFIED -- required requirements not all PASS for "
            f"revision {current_revision!r}, mission {mission_id!r}: {blocking!r}"
        )
