"""
Phase 15.8 -- mission-completion verification gate (spec section 18).

Does NOT implement a second mission completion state machine.
`orca.mission.state_machine`/`mission_store.transition_mission()`
already enforce that `COMPLETED_VERIFIED` is only reachable from
VERIFYING/COURT_REVIEW and requires a non-empty `evidence_ref` (Phase
15.3). This module adds the layer ABOVE that: it decides whether the
REQUIRED verification set for a mission's requirements has actually
reached PASS before ever attempting that transition, using
`orca.mission.verification_aggregation.aggregate_requirement()` --
the same non-vacuous aggregation rule used everywhere else in this
package. It never mutates the aggregation rule or bypasses it for
convenience.
"""
from __future__ import annotations

from orca.mission.verification import VerificationOutcome, VerificationRecord
from orca.mission.verification_aggregation import aggregate_requirement, filter_current_context


class MissionVerificationGateError(Exception):
    pass


def can_complete_verified(
    records_by_requirement: dict[str, tuple[VerificationRecord, ...]],
    *,
    required_requirement_ids: tuple[str, ...],
    current_revision: str,
    mission_id: str | None = None,
) -> tuple[bool, dict[str, VerificationOutcome]]:
    """Returns (can_complete, per_requirement_outcome). `can_complete`
    is True only if EVERY required requirement's CURRENT-REVISION,
    CURRENT-MISSION (when `mission_id` is supplied) verification
    history aggregates to PASS. A requirement missing from
    `records_by_requirement` entirely aggregates to UNVERIFIED (never
    vacuously PASS) via the same rule `aggregate_requirement(())`
    already enforces. `mission_id` is optional (default None, no
    mission-scoping enforced) for backward compatibility with Phase
    15.8 callers that only ever operate within one mission's own
    connection scope; the Court integration in
    `orca.mission.court_mission_gate` always supplies it explicitly
    (Phase 15.9.1 closure item 2)."""
    if not required_requirement_ids:
        raise MissionVerificationGateError(
            "can_complete_verified() requires at least one required_requirement_id -- "
            "an empty required set would vacuously permit COMPLETED_VERIFIED."
        )
    outcomes: dict[str, VerificationOutcome] = {}
    for req_id in required_requirement_ids:
        records = records_by_requirement.get(req_id, ())
        current = filter_current_context(records, current_revision=current_revision, mission_id=mission_id)
        outcomes[req_id] = aggregate_requirement(current)
    can_complete = all(o is VerificationOutcome.PASS for o in outcomes.values())
    return can_complete, outcomes


def require_can_complete_verified(
    records_by_requirement: dict[str, tuple[VerificationRecord, ...]],
    *,
    required_requirement_ids: tuple[str, ...],
    current_revision: str,
    mission_id: str | None = None,
) -> None:
    """Raises MissionVerificationGateError with the exact per-requirement
    breakdown if COMPLETED_VERIFIED cannot yet be reached -- callers
    (e.g. a mission runner about to call
    orca.mission.mission_store.transition_mission(..., COMPLETED_VERIFIED))
    call this FIRST and only proceed if it does not raise."""
    can_complete, outcomes = can_complete_verified(
        records_by_requirement, required_requirement_ids=required_requirement_ids,
        current_revision=current_revision, mission_id=mission_id,
    )
    if not can_complete:
        blocking = {rid: o.value for rid, o in outcomes.items() if o is not VerificationOutcome.PASS}
        raise MissionVerificationGateError(
            f"Cannot reach COMPLETED_VERIFIED -- required requirements not all PASS for "
            f"revision {current_revision!r}"
            + (f", mission {mission_id!r}" if mission_id else "") + f": {blocking!r}"
        )
