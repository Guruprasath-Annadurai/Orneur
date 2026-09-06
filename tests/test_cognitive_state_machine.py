"""
Cognitive state machine transitions must be validated -- an invalid
transition raises rather than silently succeeding (Phase 3 spec §24).
"""
from __future__ import annotations

import pytest

from orca.cognitive.contracts import CognitiveState
from orca.cognitive.errors import InvalidStateTransitionError
from orca.cognitive.state_machine import CognitiveStateMachine


def test_starts_received():
    sm = CognitiveStateMachine()
    assert sm.state == CognitiveState.RECEIVED
    assert not sm.is_terminal()


def test_valid_happy_path():
    sm = CognitiveStateMachine()
    sm.transition(CognitiveState.CLASSIFYING)
    sm.transition(CognitiveState.PLANNED)
    sm.transition(CognitiveState.EXECUTING)
    sm.transition(CognitiveState.COMPLETED)
    assert sm.state == CognitiveState.COMPLETED
    assert sm.is_terminal()
    assert len(sm.history) == 4


def test_invalid_transition_rejected():
    sm = CognitiveStateMachine()
    with pytest.raises(InvalidStateTransitionError):
        sm.transition(CognitiveState.COMPLETED)  # RECEIVED -> COMPLETED is not allowed
    assert sm.state == CognitiveState.RECEIVED  # unchanged on rejection


def test_terminal_state_accepts_no_further_transitions():
    sm = CognitiveStateMachine(initial=CognitiveState.COMPLETED)
    with pytest.raises(InvalidStateTransitionError):
        sm.transition(CognitiveState.EXECUTING)


def test_waiting_can_return_to_executing():
    sm = CognitiveStateMachine()
    sm.transition(CognitiveState.CLASSIFYING)
    sm.transition(CognitiveState.PLANNED)
    sm.transition(CognitiveState.EXECUTING)
    sm.transition(CognitiveState.WAITING)
    sm.transition(CognitiveState.EXECUTING)
    sm.transition(CognitiveState.VERIFYING)
    sm.transition(CognitiveState.COMPLETED)
    assert sm.state == CognitiveState.COMPLETED


def test_cancellation_allowed_from_most_non_terminal_states():
    for state in (CognitiveState.RECEIVED, CognitiveState.CLASSIFYING):
        sm = CognitiveStateMachine(initial=state)
        sm.transition(CognitiveState.CANCELLED)
        assert sm.state == CognitiveState.CANCELLED


def test_abstained_reachable_from_planned():
    sm = CognitiveStateMachine()
    sm.transition(CognitiveState.CLASSIFYING)
    sm.transition(CognitiveState.PLANNED)
    sm.transition(CognitiveState.ABSTAINED)
    assert sm.state == CognitiveState.ABSTAINED
    assert sm.is_terminal()
