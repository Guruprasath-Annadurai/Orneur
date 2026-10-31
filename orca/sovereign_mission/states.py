"""Mission lifecycle. Uncertain states do not transition to success."""

from __future__ import annotations

class StateError(Exception):
    def __init__(self, code: str):
        self.code = code
        super().__init__(code)


CREATED = "CREATED"
PLANNED = "PLANNED"
AWAITING_APPROVAL = "AWAITING_APPROVAL"
AUTHORIZED = "AUTHORIZED"
PAUSED = "PAUSED"
EXECUTING = "EXECUTING"
VERIFYING = "VERIFYING"
COMPLETED_VERIFIED = "COMPLETED_VERIFIED"
COMPLETED_UNVERIFIED = "COMPLETED_UNVERIFIED"
FAILED = "FAILED"
CANCELLED = "CANCELLED"
REVOKED = "REVOKED"
INTERRUPTED_UNKNOWN = "INTERRUPTED_UNKNOWN"
OUTCOME_UNKNOWN = "OUTCOME_UNKNOWN"

_ALLOWED: dict[str, frozenset[str]] = {
    CREATED: frozenset({PLANNED, CANCELLED}),
    PLANNED: frozenset({AWAITING_APPROVAL, CANCELLED}),
    AWAITING_APPROVAL: frozenset({AUTHORIZED, CANCELLED}),
    AUTHORIZED: frozenset({EXECUTING, PAUSED, CANCELLED, REVOKED}),
    PAUSED: frozenset({AUTHORIZED, CANCELLED, REVOKED}),
    EXECUTING: frozenset({VERIFYING, FAILED, CANCELLED, REVOKED, INTERRUPTED_UNKNOWN, OUTCOME_UNKNOWN}),
    VERIFYING: frozenset({COMPLETED_VERIFIED, COMPLETED_UNVERIFIED, FAILED, OUTCOME_UNKNOWN}),
    INTERRUPTED_UNKNOWN: frozenset({OUTCOME_UNKNOWN, FAILED}),
    OUTCOME_UNKNOWN: frozenset({FAILED}),
    COMPLETED_VERIFIED: frozenset(),
    COMPLETED_UNVERIFIED: frozenset(),
    FAILED: frozenset(),
    CANCELLED: frozenset(),
    REVOKED: frozenset(),
}


def transition(current: str, new: str, *, evidence_intact: bool = False) -> str:
    if new not in _ALLOWED.get(current, frozenset()):
        raise StateError("transition_refused")
    if new in {COMPLETED_VERIFIED, COMPLETED_UNVERIFIED}:
        if current != VERIFYING or not evidence_intact:
            raise StateError("verification_refused")
    if current in {INTERRUPTED_UNKNOWN, OUTCOME_UNKNOWN} and new in {COMPLETED_VERIFIED, COMPLETED_UNVERIFIED}:
        raise StateError("verification_refused")
    return new
