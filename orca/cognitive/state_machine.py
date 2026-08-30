"""
Cognitive Kernel execution state machine (Phase 3 spec §24). Transitions
are validated against an explicit allowed-graph -- an invalid transition
raises InvalidStateTransitionError rather than silently succeeding.
"""
from __future__ import annotations

import time

from orca.cognitive.contracts import CognitiveState, StateTransition
from orca.cognitive.errors import InvalidStateTransitionError

_ALLOWED: dict[CognitiveState, set[CognitiveState]] = {
    CognitiveState.RECEIVED: {CognitiveState.CLASSIFYING, CognitiveState.CANCELLED, CognitiveState.FAILED},
    CognitiveState.CLASSIFYING: {CognitiveState.PLANNED, CognitiveState.ABSTAINED, CognitiveState.FAILED, CognitiveState.CANCELLED},
    CognitiveState.PLANNED: {CognitiveState.EXECUTING, CognitiveState.ABSTAINED, CognitiveState.FAILED, CognitiveState.CANCELLED},
    CognitiveState.EXECUTING: {CognitiveState.WAITING, CognitiveState.VERIFYING, CognitiveState.COMPLETED, CognitiveState.ABSTAINED, CognitiveState.FAILED, CognitiveState.CANCELLED},
    CognitiveState.WAITING: {CognitiveState.EXECUTING, CognitiveState.ABSTAINED, CognitiveState.FAILED, CognitiveState.CANCELLED},
    CognitiveState.VERIFYING: {CognitiveState.COMPLETED, CognitiveState.ABSTAINED, CognitiveState.FAILED, CognitiveState.CANCELLED},
    CognitiveState.COMPLETED: set(),
    CognitiveState.ABSTAINED: set(),
    CognitiveState.FAILED: set(),
    CognitiveState.CANCELLED: set(),
}

TERMINAL_STATES = {CognitiveState.COMPLETED, CognitiveState.ABSTAINED, CognitiveState.FAILED, CognitiveState.CANCELLED}


class CognitiveStateMachine:
    def __init__(self, initial: CognitiveState = CognitiveState.RECEIVED):
        self._state = initial
        self.history: list[StateTransition] = []

    @property
    def state(self) -> CognitiveState:
        return self._state

    def is_terminal(self) -> bool:
        return self._state in TERMINAL_STATES

    def transition(self, to: CognitiveState) -> None:
        allowed = _ALLOWED.get(self._state, set())
        if to not in allowed:
            raise InvalidStateTransitionError(internal_detail=f"{self._state.value} -> {to.value} is not allowed")
        self.history.append(StateTransition(from_state=self._state, to_state=to, at_monotonic=time.monotonic()))
        self._state = to
