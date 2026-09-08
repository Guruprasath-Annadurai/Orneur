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
from orca.mission.verification_aggregation import aggregate_requirement, filter_current_revision


class MissionVerificationGateError(Exception):
    pass


def can_complete_verified(
    records_by_requirement: dict[str, tuple[VerificationRecord, ...]],
    *,
    required_requirement_ids: tuple[str, ...],
    current_revision: str,
) -> tuple[bool, dict[str, VerificationOutcome]]:
    """Returns (can_complete, per_requirement_outcome). `can_complete`
    is True only if EVERY required requirement's CURRENT-REVISION
    verification history aggregates to PASS. A requirement missing
    from `records_by_requirement` entirely aggregates to UNVERIFIED
    (never vacuously PASS) via the same rule
    `aggregate_requirement(())` already enforces."""
    if not required_requirement_ids:
        raise MissionVerificationGateError(
            "can_complete_verified() requires at least one required_requirement_id -- "
            "an empty required set would vacuously permit COMPLETED_VERIFIED."
        )
    outcomes: dict[str, VerificationOutcome] = {}
    for req_id in required_requirement_ids:
        records = records_by_requirement.get(req_id, ())
        current = filter_current_revision(records, current_revision=current_revision)
        outcomes[req_id] = aggregate_requirement(current)
    can_complete = all(o is VerificationOutcome.PASS for o in outcomes.values())
    return can_complete, outcomes


def require_can_complete_verified(
    records_by_requirement: dict[str, tuple[VerificationRecord, ...]],
    *,
    required_requirement_ids: tuple[str, ...],
    current_revision: str,
) -> None:
    """Raises MissionVerificationGateError with the exact per-requirement
    breakdown if COMPLETED_VERIFIED cannot yet be reached -- callers
    (e.g. a mission runner about to call
    orca.mission.mission_store.transition_mission(..., COMPLETED_VERIFIED))
    call this FIRST and only proceed if it does not raise."""
    can_complete, outcomes = can_complete_verified(
        records_by_requirement, required_requirement_ids=required_requirement_ids,
        current_revision=current_revision,
    )
    if not can_complete:
        blocking = {rid: o.value for rid, o in outcomes.items() if o is not VerificationOutcome.PASS}
        raise MissionVerificationGateError(
            f"Cannot reach COMPLETED_VERIFIED -- required requirements not all PASS for "
            f"revision {current_revision!r}: {blocking!r}"
        )
