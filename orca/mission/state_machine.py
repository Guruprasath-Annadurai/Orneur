"""
Mission State Machine (Phase 15 spec section 6).

The 17 canonical mission states and their validated transitions.
Structurally enforces two hard invariants from the spec, not merely
documents them:

  1. COMPLETED_VERIFIED is reachable ONLY from a verification-oriented
     state (VERIFYING or COURT_REVIEW) -- never directly from RUNNING
     or any waiting/paused state. A mission cannot "complete verified"
     by skipping verification, mirroring how
     orca.mission.requirements.transition() already enforces this for
     individual requirements (Phase 15.1).
  2. Reaching COMPLETED_VERIFIED requires a non-empty evidence
     reference in the SAME call -- spec section 17's "no fake
     completion" applied structurally to the mission's own terminal
     state, not just to its constituent requirements.

COMPLETED_UNVERIFIED and COMPLETED_VERIFIED are DELIBERATELY both
terminal (no outgoing transitions) for this V1 state machine -- a
mission found to need further verification after landing in
COMPLETED_UNVERIFIED is represented by a NEW mission/verification
pass, not by mutating the old mission's history in place. This keeps
"was this specific mission run ever verified" an unambiguous,
never-rewritten fact.

AUDIT-C02-P0-03 ("cancellation truth"): CANCELLATION_REQUESTED is a
16th state, added because a cancel request against a mission that
MIGHT have a live worker process (RUNNING, any WAITING_* state, any
PAUSED_* state, BLOCKED) is not itself proof the worker has stopped.
Those states can no longer transition directly to CANCELLED -- only
to CANCELLATION_REQUESTED. DRAFT/PLANNING/READY still transition
directly to CANCELLED: no worker exists yet in those states, so there
is nothing to confirm terminated. This module itself does not perform
any reconciliation -- it only makes "request" and "confirmed"
genuinely distinct, persisted states; the actual worker-termination
check is the caller's responsibility (see
orca.serve.mission_api._require_reconciliation_principal() and the
cancel/confirm-cancelled endpoints for the current, honestly-scoped
implementation).

AUDIT-C02-P0-03 follow-up correction: the first version of this fix
let CANCELLATION_REQUESTED resolve to CANCELLED or FAILED on a bare
caller-supplied boolean -- including from the mission's own owner,
with no independent termination evidence at all. CANCELLATION_UNRESOLVED
is a 17th state, added for the genuinely distinct "a reconciliation
attempt happened but could not determine the worker's fate" outcome --
it must NEVER be silently folded into FAILED (which would misrepresent
an unresolved cancellation as a confirmed execution failure) or into
CANCELLED (which would misreport a possibly-still-running worker as
safely stopped). It is deliberately NOT terminal: a later, successful
reconciliation attempt can still resolve it to CANCELLATION_REQUESTED
(retry), CANCELLED, or FAILED."""
from __future__ import annotations

from enum import Enum


class MissionState(Enum):
    DRAFT = "DRAFT"
    PLANNING = "PLANNING"
    READY = "READY"
    RUNNING = "RUNNING"
    WAITING_TOOL = "WAITING_TOOL"
    WAITING_EXTERNAL_EVENT = "WAITING_EXTERNAL_EVENT"
    WAITING_APPROVAL = "WAITING_APPROVAL"
    VERIFYING = "VERIFYING"
    COURT_REVIEW = "COURT_REVIEW"
    PAUSED_USER = "PAUSED_USER"
    PAUSED_WINDOW_REACHED = "PAUSED_WINDOW_REACHED"
    BLOCKED = "BLOCKED"
    FAILED = "FAILED"
    COMPLETED_UNVERIFIED = "COMPLETED_UNVERIFIED"
    COMPLETED_VERIFIED = "COMPLETED_VERIFIED"
    CANCELLATION_REQUESTED = "CANCELLATION_REQUESTED"
    CANCELLATION_UNRESOLVED = "CANCELLATION_UNRESOLVED"
    CANCELLED = "CANCELLED"


TERMINAL_STATES: frozenset[MissionState] = frozenset({
    MissionState.FAILED,
    MissionState.COMPLETED_UNVERIFIED,
    MissionState.COMPLETED_VERIFIED,
    MissionState.CANCELLED,
})

_WAITING_STATES: frozenset[MissionState] = frozenset({
    MissionState.WAITING_TOOL,
    MissionState.WAITING_EXTERNAL_EVENT,
    MissionState.WAITING_APPROVAL,
})

S = MissionState

_ALLOWED_TRANSITIONS: dict[MissionState, frozenset[MissionState]] = {
    S.DRAFT: frozenset({S.PLANNING, S.CANCELLED}),
    S.PLANNING: frozenset({S.READY, S.BLOCKED, S.CANCELLED}),
    S.READY: frozenset({S.RUNNING, S.CANCELLED}),
    S.RUNNING: frozenset({
        S.WAITING_TOOL, S.WAITING_EXTERNAL_EVENT, S.WAITING_APPROVAL,
        S.VERIFYING, S.PAUSED_USER, S.PAUSED_WINDOW_REACHED,
        S.BLOCKED, S.FAILED, S.COMPLETED_UNVERIFIED, S.CANCELLATION_REQUESTED,
    }),
    S.WAITING_TOOL: frozenset({S.RUNNING, S.FAILED, S.PAUSED_WINDOW_REACHED, S.CANCELLATION_REQUESTED}),
    S.WAITING_EXTERNAL_EVENT: frozenset({S.RUNNING, S.FAILED, S.PAUSED_WINDOW_REACHED, S.CANCELLATION_REQUESTED}),
    S.WAITING_APPROVAL: frozenset({S.RUNNING, S.BLOCKED, S.PAUSED_WINDOW_REACHED, S.CANCELLATION_REQUESTED}),
    S.VERIFYING: frozenset({
        S.COURT_REVIEW, S.COMPLETED_VERIFIED, S.COMPLETED_UNVERIFIED,
        S.FAILED, S.BLOCKED, S.PAUSED_WINDOW_REACHED,
    }),
    # PAUSED_WINDOW_REACHED added here in Phase 15.14 (spec section 7
    # item 7): the six-hour autonomous window can genuinely expire
    # while a mission is in Court Review, and without this edge such a
    # mission could not be safely checkpointed/paused at its deadline
    # -- the minimum adjustment needed, not a broadened transition
    # table.
    S.COURT_REVIEW: frozenset({S.COMPLETED_VERIFIED, S.BLOCKED, S.WAITING_APPROVAL, S.FAILED, S.PAUSED_WINDOW_REACHED}),
    S.PAUSED_USER: frozenset({S.RUNNING, S.CANCELLATION_REQUESTED}),
    S.PAUSED_WINDOW_REACHED: frozenset({S.RUNNING, S.CANCELLATION_REQUESTED}),
    S.BLOCKED: frozenset({S.RUNNING, S.PLANNING, S.FAILED, S.CANCELLATION_REQUESTED}),
    # Includes a self-loop (CANCELLATION_REQUESTED -> itself): a
    # reconciliation attempt reporting STILL_RUNNING retires the old
    # cancellation episode and mints a fresh one, but the mission
    # legitimately remains CANCELLATION_REQUESTED throughout -- this
    # is "try again," not an error.
    S.CANCELLATION_REQUESTED: frozenset({S.CANCELLED, S.FAILED, S.CANCELLATION_UNRESOLVED, S.CANCELLATION_REQUESTED}),
    # Includes a self-loop (CANCELLATION_UNRESOLVED -> itself):
    # a repeated reconciliation attempt that STILL cannot determine
    # the worker's fate must be representable without raising --
    # "still don't know" is itself a legitimate, repeatable outcome,
    # not an error.
    S.CANCELLATION_UNRESOLVED: frozenset({S.CANCELLATION_REQUESTED, S.CANCELLED, S.FAILED, S.CANCELLATION_UNRESOLVED}),
    S.FAILED: frozenset(),
    S.COMPLETED_UNVERIFIED: frozenset(),
    S.COMPLETED_VERIFIED: frozenset(),
    S.CANCELLED: frozenset(),
}

# States from which COMPLETED_VERIFIED may be reached -- both already
# enforced by _ALLOWED_TRANSITIONS above, but kept as an explicit,
# separately-testable set so a future edit to the transition table
# can't accidentally widen this without a corresponding test failing.
_VERIFICATION_ORIGIN_STATES: frozenset[MissionState] = frozenset({S.VERIFYING, S.COURT_REVIEW})


class MissionStateError(Exception):
    """Raised on an invalid mission state transition."""


def is_terminal(state: MissionState) -> bool:
    return state in TERMINAL_STATES


def transition(
    current: MissionState,
    new: MissionState,
    *,
    evidence_ref: str | None = None,
) -> MissionState:
    """Validates and returns the new state. Raises MissionStateError on
    any invalid transition, including the two structurally-enforced
    invariants described in this module's docstring."""
    if new not in _ALLOWED_TRANSITIONS.get(current, frozenset()):
        allowed = sorted(s.value for s in _ALLOWED_TRANSITIONS.get(current, frozenset()))
        raise MissionStateError(
            f"Cannot transition {current.value} -> {new.value}. "
            f"Allowed from {current.value}: {allowed or 'none (terminal)'}."
        )

    if new is MissionState.COMPLETED_VERIFIED:
        if current not in _VERIFICATION_ORIGIN_STATES:
            # Belt-and-suspenders -- _ALLOWED_TRANSITIONS already
            # excludes this, but an explicit check here means this
            # invariant survives even if the transition table is
            # edited incorrectly in the future.
            raise MissionStateError(
                f"COMPLETED_VERIFIED is only reachable from "
                f"{sorted(s.value for s in _VERIFICATION_ORIGIN_STATES)}, not {current.value} -- "
                f"a mission cannot complete verified without passing through verification "
                f"(spec section 17)."
            )
        if not (evidence_ref or "").strip():
            raise MissionStateError(
                "COMPLETED_VERIFIED requires a non-empty evidence_ref -- "
                "spec section 17: 'no fake completion', section 18: Production Proof "
                "must never invent evidence."
            )

    return new
