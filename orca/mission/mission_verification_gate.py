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
completion()` -- the SAME centralized, non-vacuous aggregation
function `orca.mission.cognitive_court.arbiter_decide()` uses (Phase
15.9.3 closure item 8) -- it never mutates the aggregation rule or
bypasses it for convenience.

PHASE 15.9.3 CLOSURE (items 1-2): an independent audit found this
module (and `arbiter_decide()`) trusted a `records_by_requirement`
dictionary KEY as if it were authority for a record's own identity --
a `VerificationRecord` whose own `requirement_id` field disagreed with
the dict key it was filed under still silently counted as proof, and a
requirement with multiple required acceptance criteria could PASS with
evidence for only SOME of them, since the old `aggregate_requirement()`
only ever aggregated whichever keys happened to be present. Both gaps
are now closed by `evaluate_requirement_completion()`, which
independently re-checks `record.requirement_id` against the expected
`requirement_id` (never trusting dict placement) and, when the Phase
15.7 `AcceptanceCriterion` registry has criteria registered for a
requirement (or a caller supplies an explicit override), requires
EVERY one of them to have current-context PASS evidence -- a missing
required criterion is UNVERIFIED, never silently absent from the
aggregate.
"""
from __future__ import annotations

from orca.mission.verification import VerificationOutcome, VerificationRecord
from orca.mission.verification_aggregation import evaluate_requirement_completion


class MissionVerificationGateError(Exception):
    pass


def can_complete_verified(
    records_by_requirement: dict[str, tuple[VerificationRecord, ...]],
    *,
    required_requirement_ids: tuple[str, ...],
    current_revision: str,
    mission_id: str | None = None,
    required_criteria_by_requirement: dict[str, frozenset[str]] | None = None,
) -> tuple[bool, dict[str, VerificationOutcome]]:
    """Returns (can_complete, per_requirement_outcome). `can_complete`
    is True only if EVERY required requirement's CURRENT-REVISION,
    CURRENT-MISSION (when `mission_id` is supplied), CURRENT-
    REQUIREMENT-IDENTITY (Phase 15.9.3 closure item 1 -- a record
    dict-keyed under a requirement it does not itself claim to be for
    never counts) verification history aggregates to PASS, AND every
    required acceptance criterion for that requirement (Phase 15.9.3
    closure item 2, from the `AcceptanceCriterion` registry or from
    `required_criteria_by_requirement` when supplied) has current-
    context PASS evidence of its own. A requirement missing from
    `records_by_requirement` entirely aggregates to UNVERIFIED (never
    vacuously PASS). `mission_id` is optional (default None, no
    mission-scoping enforced) for backward compatibility with Phase
    15.8 callers that only ever operate within one mission's own
    connection scope; the Court integration in
    `orca.mission.court_mission_gate` always supplies it explicitly
    (Phase 15.9.1 closure item 2). `required_criteria_by_requirement`
    is optional per-requirement -- when a requirement has no entry
    there AND no registered `AcceptanceCriterion`, this falls back to
    the original whatever-exists-in-records aggregation (a legitimate
    requirement-level-check pattern, closure item 3)."""
    if not required_requirement_ids:
        raise MissionVerificationGateError(
            "can_complete_verified() requires at least one required_requirement_id -- "
            "an empty required set would vacuously permit COMPLETED_VERIFIED."
        )
    outcomes: dict[str, VerificationOutcome] = {}
    for req_id in required_requirement_ids:
        records = records_by_requirement.get(req_id, ())
        explicit_keys = (required_criteria_by_requirement or {}).get(req_id)
        outcome, _ = evaluate_requirement_completion(
            records, requirement_id=req_id, current_revision=current_revision, mission_id=mission_id,
            required_criterion_ids=explicit_keys,
        )
        outcomes[req_id] = outcome
    can_complete = all(o is VerificationOutcome.PASS for o in outcomes.values())
    return can_complete, outcomes


def require_can_complete_verified(
    records_by_requirement: dict[str, tuple[VerificationRecord, ...]],
    *,
    required_requirement_ids: tuple[str, ...],
    current_revision: str,
    mission_id: str | None = None,
    required_criteria_by_requirement: dict[str, frozenset[str]] | None = None,
) -> None:
    """Raises MissionVerificationGateError with the exact per-requirement
    breakdown if COMPLETED_VERIFIED cannot yet be reached -- callers
    (e.g. a mission runner about to call
    orca.mission.mission_store.transition_mission(..., COMPLETED_VERIFIED))
    call this FIRST and only proceed if it does not raise."""
    can_complete, outcomes = can_complete_verified(
        records_by_requirement, required_requirement_ids=required_requirement_ids,
        current_revision=current_revision, mission_id=mission_id,
        required_criteria_by_requirement=required_criteria_by_requirement,
    )
    if not can_complete:
        blocking = {rid: o.value for rid, o in outcomes.items() if o is not VerificationOutcome.PASS}
        raise MissionVerificationGateError(
            f"Cannot reach COMPLETED_VERIFIED -- required requirements not all PASS for "
            f"revision {current_revision!r}"
            + (f", mission {mission_id!r}" if mission_id else "") + f": {blocking!r}"
        )
