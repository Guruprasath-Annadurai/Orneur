"""
Phase 15.3 -- Mission State Machine tests.

Exercises exactly what spec section 30's Phase 15.3 test plan asks
for: valid transitions, invalid transitions, terminal states, pause,
resume, blocked, failed, and the verified/unverified completion
distinction -- plus the two structural invariants
orca.mission.state_machine enforces (COMPLETED_VERIFIED only reachable
via VERIFYING/COURT_REVIEW, and only with an evidence reference).
"""
from __future__ import annotations

import pytest

from orca.mission.state_machine import (
    TERMINAL_STATES,
    MissionState,
    MissionStateError,
    is_terminal,
    transition,
)

S = MissionState


class TestValidTransitions:
    def test_draft_to_planning(self):
        assert transition(S.DRAFT, S.PLANNING) is S.PLANNING

    def test_planning_to_ready(self):
        assert transition(S.PLANNING, S.READY) is S.READY

    def test_ready_to_running(self):
        assert transition(S.READY, S.RUNNING) is S.RUNNING

    def test_running_to_each_waiting_state(self):
        for waiting in (S.WAITING_TOOL, S.WAITING_EXTERNAL_EVENT, S.WAITING_APPROVAL):
            assert transition(S.RUNNING, waiting) is waiting

    def test_waiting_tool_back_to_running(self):
        assert transition(S.WAITING_TOOL, S.RUNNING) is S.RUNNING

    def test_running_to_verifying(self):
        assert transition(S.RUNNING, S.VERIFYING) is S.VERIFYING

    def test_verifying_to_court_review(self):
        assert transition(S.VERIFYING, S.COURT_REVIEW) is S.COURT_REVIEW

    def test_court_review_to_completed_verified_with_evidence(self):
        assert transition(S.COURT_REVIEW, S.COMPLETED_VERIFIED, evidence_ref="proof-123") is S.COMPLETED_VERIFIED


class TestInvalidTransitions:
    def test_draft_cannot_jump_to_running(self):
        with pytest.raises(MissionStateError):
            transition(S.DRAFT, S.RUNNING)

    def test_completed_verified_has_no_outgoing_transitions(self):
        with pytest.raises(MissionStateError):
            transition(S.COMPLETED_VERIFIED, S.RUNNING)

    def test_planning_cannot_go_directly_to_verifying(self):
        with pytest.raises(MissionStateError):
            transition(S.PLANNING, S.VERIFYING)

    def test_cancelled_is_a_dead_end(self):
        with pytest.raises(MissionStateError):
            transition(S.CANCELLED, S.RUNNING)


class TestTerminalStates:
    def test_terminal_states_are_exactly_four(self):
        assert TERMINAL_STATES == frozenset({
            S.FAILED, S.COMPLETED_UNVERIFIED, S.COMPLETED_VERIFIED, S.CANCELLED,
        })

    @pytest.mark.parametrize("state", sorted(TERMINAL_STATES, key=lambda s: s.value))
    def test_every_terminal_state_has_no_allowed_transitions(self, state):
        assert is_terminal(state)
        for candidate in MissionState:
            with pytest.raises(MissionStateError):
                transition(state, candidate)

    def test_non_terminal_state_is_not_terminal(self):
        assert not is_terminal(S.RUNNING)


class TestPauseResume:
    def test_running_to_paused_user_and_back(self):
        assert transition(S.RUNNING, S.PAUSED_USER) is S.PAUSED_USER
        assert transition(S.PAUSED_USER, S.RUNNING) is S.RUNNING

    def test_running_to_paused_window_reached_and_back(self):
        assert transition(S.RUNNING, S.PAUSED_WINDOW_REACHED) is S.PAUSED_WINDOW_REACHED
        assert transition(S.PAUSED_WINDOW_REACHED, S.RUNNING) is S.RUNNING

    def test_paused_states_can_be_cancelled(self):
        assert transition(S.PAUSED_USER, S.CANCELLED) is S.CANCELLED
        assert transition(S.PAUSED_WINDOW_REACHED, S.CANCELLED) is S.CANCELLED


class TestBlocked:
    def test_running_to_blocked_and_back(self):
        assert transition(S.RUNNING, S.BLOCKED) is S.BLOCKED
        assert transition(S.BLOCKED, S.RUNNING) is S.RUNNING

    def test_blocked_can_return_to_planning(self):
        assert transition(S.BLOCKED, S.PLANNING) is S.PLANNING

    def test_blocked_can_fail(self):
        assert transition(S.BLOCKED, S.FAILED) is S.FAILED


class TestFailed:
    def test_running_can_fail_directly(self):
        assert transition(S.RUNNING, S.FAILED) is S.FAILED

    def test_waiting_states_can_fail(self):
        for waiting in (S.WAITING_TOOL, S.WAITING_EXTERNAL_EVENT):
            assert transition(waiting, S.FAILED) is S.FAILED

    def test_failed_is_terminal(self):
        with pytest.raises(MissionStateError):
            transition(S.FAILED, S.RUNNING)


class TestVerifiedVsUnverifiedCompletion:
    """The spec's hard invariant: COMPLETED_UNVERIFIED and
    COMPLETED_VERIFIED must remain distinct and COMPLETED_UNVERIFIED
    can never masquerade as COMPLETED_VERIFIED (spec section 17)."""

    def test_running_can_reach_completed_unverified_directly(self):
        """Work can finish without formal verification (e.g. a
        low-risk ASSIST-mode task) -- that's honestly UNVERIFIED, not
        an error."""
        assert transition(S.RUNNING, S.COMPLETED_UNVERIFIED) is S.COMPLETED_UNVERIFIED

    def test_verifying_can_reach_completed_unverified(self):
        """Verification was attempted but came back inconclusive/
        incomplete -- still honestly UNVERIFIED."""
        assert transition(S.VERIFYING, S.COMPLETED_UNVERIFIED) is S.COMPLETED_UNVERIFIED

    def test_running_cannot_reach_completed_verified_directly(self):
        """The core structural guarantee: verification cannot be
        skipped. RUNNING -> COMPLETED_VERIFIED must be rejected even
        though RUNNING -> COMPLETED_UNVERIFIED is allowed."""
        with pytest.raises(MissionStateError):
            transition(S.RUNNING, S.COMPLETED_VERIFIED, evidence_ref="not-good-enough")

    def test_waiting_states_cannot_reach_completed_verified(self):
        for waiting in (S.WAITING_TOOL, S.WAITING_EXTERNAL_EVENT, S.WAITING_APPROVAL):
            with pytest.raises(MissionStateError):
                transition(waiting, S.COMPLETED_VERIFIED, evidence_ref="x")

    def test_verifying_to_completed_verified_requires_evidence(self):
        with pytest.raises(MissionStateError):
            transition(S.VERIFYING, S.COMPLETED_VERIFIED)  # no evidence_ref

    def test_verifying_to_completed_verified_rejects_blank_evidence(self):
        with pytest.raises(MissionStateError):
            transition(S.VERIFYING, S.COMPLETED_VERIFIED, evidence_ref="   ")

    def test_verifying_to_completed_verified_succeeds_with_evidence(self):
        assert transition(S.VERIFYING, S.COMPLETED_VERIFIED, evidence_ref="workflow run 34226783102") is S.COMPLETED_VERIFIED

    def test_court_review_to_completed_verified_requires_evidence(self):
        with pytest.raises(MissionStateError):
            transition(S.COURT_REVIEW, S.COMPLETED_VERIFIED)

    def test_completed_unverified_and_completed_verified_are_distinct_and_both_terminal(self):
        assert S.COMPLETED_UNVERIFIED != S.COMPLETED_VERIFIED
        assert is_terminal(S.COMPLETED_UNVERIFIED)
        assert is_terminal(S.COMPLETED_VERIFIED)
        # Neither can transition into the other -- completion status,
        # once recorded, is not silently upgraded/downgraded in place.
        with pytest.raises(MissionStateError):
            transition(S.COMPLETED_UNVERIFIED, S.COMPLETED_VERIFIED, evidence_ref="x")
        with pytest.raises(MissionStateError):
            transition(S.COMPLETED_VERIFIED, S.COMPLETED_UNVERIFIED)


class TestAllStatesReachTerminalOrAreTerminal:
    """Sanity check on the whole transition graph: every non-terminal
    state has at least one outgoing transition (no accidental dead
    ends that aren't one of the 4 real terminal states)."""

    @pytest.mark.parametrize("state", [s for s in MissionState if s not in TERMINAL_STATES])
    def test_non_terminal_state_has_outgoing_transitions(self, state):
        from orca.mission.state_machine import _ALLOWED_TRANSITIONS
        assert len(_ALLOWED_TRANSITIONS[state]) > 0, f"{state.value} has no outgoing transitions but isn't terminal"
