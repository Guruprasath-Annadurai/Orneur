"""
Phase 15.14 -- UNIT tests for orca.mission.mission_window (no mission
Neon database required): the pure `evaluate_mission_window()` status
classification, using an injected clock -- never real elapsed time.

Live-Neon-dependent behavior (real window start/expiry/resume against
real Postgres, real atomic checkpoint+pause, real concurrent expiry
races, real Relay reconnect interaction, real operation-idempotency
interaction) is covered in tests/test_mission_window_live_neon.py
(LIVE_NEON_TEMP_BRANCH).
"""
from __future__ import annotations

from datetime import datetime, timedelta, timezone

import pytest

from orca.mission.mission_window import (
    DEFAULT_AUTONOMOUS_WINDOW_SECONDS,
    MissionWindowDecision,
    MissionWindowStatus,
    evaluate_mission_window,
)
from orca.mission.state_machine import MissionState


def _mission(**overrides) -> dict:
    base = {
        "autonomy_level": "L3",
        "state": MissionState.RUNNING.value,
        "window_started_at": None,
        "window_deadline_at": None,
    }
    base.update(overrides)
    return base


def test_default_window_is_six_hours():
    assert DEFAULT_AUTONOMOUS_WINDOW_SECONDS == 6 * 60 * 60


@pytest.mark.parametrize("level", ["L0", "L1", "L2"])
def test_non_autonomous_levels_are_not_applicable(level):
    mission = _mission(autonomy_level=level, window_started_at="2026-01-01T00:00:00+00:00", window_deadline_at="2026-01-01T06:00:00+00:00")
    now = datetime(2026, 1, 1, 3, tzinfo=timezone.utc)
    assert evaluate_mission_window(mission, now=now) is MissionWindowStatus.NOT_APPLICABLE


@pytest.mark.parametrize("level", ["L3", "L4"])
def test_autonomous_levels_are_applicable(level):
    mission = _mission(autonomy_level=level, window_started_at=None, window_deadline_at=None)
    now = datetime(2026, 1, 1, tzinfo=timezone.utc)
    assert evaluate_mission_window(mission, now=now) is MissionWindowStatus.NOT_STARTED


def test_no_timestamps_is_not_started():
    mission = _mission(window_started_at=None, window_deadline_at=None)
    now = datetime(2026, 1, 1, tzinfo=timezone.utc)
    assert evaluate_mission_window(mission, now=now) is MissionWindowStatus.NOT_STARTED


def test_only_started_populated_is_invalid():
    mission = _mission(window_started_at="2026-01-01T00:00:00+00:00", window_deadline_at=None)
    now = datetime(2026, 1, 1, tzinfo=timezone.utc)
    assert evaluate_mission_window(mission, now=now) is MissionWindowStatus.INVALID


def test_only_deadline_populated_is_invalid():
    mission = _mission(window_started_at=None, window_deadline_at="2026-01-01T06:00:00+00:00")
    now = datetime(2026, 1, 1, tzinfo=timezone.utc)
    assert evaluate_mission_window(mission, now=now) is MissionWindowStatus.INVALID


def test_deadline_before_start_is_invalid():
    mission = _mission(window_started_at="2026-01-01T06:00:00+00:00", window_deadline_at="2026-01-01T00:00:00+00:00")
    now = datetime(2026, 1, 1, 3, tzinfo=timezone.utc)
    assert evaluate_mission_window(mission, now=now) is MissionWindowStatus.INVALID


def test_malformed_timestamp_is_invalid():
    mission = _mission(window_started_at="not-a-timestamp", window_deadline_at="2026-01-01T06:00:00+00:00")
    now = datetime(2026, 1, 1, 3, tzinfo=timezone.utc)
    assert evaluate_mission_window(mission, now=now) is MissionWindowStatus.INVALID


def test_before_deadline_is_active():
    started = datetime(2026, 1, 1, tzinfo=timezone.utc)
    deadline = started + timedelta(seconds=DEFAULT_AUTONOMOUS_WINDOW_SECONDS)
    mission = _mission(window_started_at=started.isoformat(), window_deadline_at=deadline.isoformat())
    now = deadline - timedelta(milliseconds=1)
    assert evaluate_mission_window(mission, now=now) is MissionWindowStatus.ACTIVE


def test_exact_boundary_is_expired():
    started = datetime(2026, 1, 1, tzinfo=timezone.utc)
    deadline = started + timedelta(seconds=DEFAULT_AUTONOMOUS_WINDOW_SECONDS)
    mission = _mission(window_started_at=started.isoformat(), window_deadline_at=deadline.isoformat())
    assert evaluate_mission_window(mission, now=deadline) is MissionWindowStatus.EXPIRED


def test_past_deadline_is_expired():
    started = datetime(2026, 1, 1, tzinfo=timezone.utc)
    deadline = started + timedelta(seconds=DEFAULT_AUTONOMOUS_WINDOW_SECONDS)
    mission = _mission(window_started_at=started.isoformat(), window_deadline_at=deadline.isoformat())
    now = deadline + timedelta(milliseconds=1)
    assert evaluate_mission_window(mission, now=now) is MissionWindowStatus.EXPIRED


@pytest.mark.parametrize("state", [
    MissionState.FAILED, MissionState.COMPLETED_UNVERIFIED, MissionState.COMPLETED_VERIFIED, MissionState.CANCELLED,
])
def test_terminal_state_is_terminal_regardless_of_timestamps(state):
    started = datetime(2026, 1, 1, tzinfo=timezone.utc)
    deadline = started + timedelta(seconds=DEFAULT_AUTONOMOUS_WINDOW_SECONDS)
    mission = _mission(state=state.value, window_started_at=started.isoformat(), window_deadline_at=deadline.isoformat())
    now = started  # well before deadline -- terminal still wins
    assert evaluate_mission_window(mission, now=now) is MissionWindowStatus.TERMINAL


def test_paused_window_reached_is_paused():
    started = datetime(2026, 1, 1, tzinfo=timezone.utc)
    deadline = started + timedelta(seconds=DEFAULT_AUTONOMOUS_WINDOW_SECONDS)
    mission = _mission(
        state=MissionState.PAUSED_WINDOW_REACHED.value,
        window_started_at=started.isoformat(), window_deadline_at=deadline.isoformat(),
    )
    assert evaluate_mission_window(mission, now=started) is MissionWindowStatus.PAUSED


@pytest.mark.parametrize("state", [
    MissionState.WAITING_TOOL, MissionState.WAITING_EXTERNAL_EVENT, MissionState.WAITING_APPROVAL,
    MissionState.VERIFYING, MissionState.COURT_REVIEW,
])
def test_waiting_states_still_count_toward_expiry(state):
    started = datetime(2026, 1, 1, tzinfo=timezone.utc)
    deadline = started + timedelta(seconds=DEFAULT_AUTONOMOUS_WINDOW_SECONDS)
    mission = _mission(state=state.value, window_started_at=started.isoformat(), window_deadline_at=deadline.isoformat())
    now = deadline + timedelta(seconds=1)
    assert evaluate_mission_window(mission, now=now) is MissionWindowStatus.EXPIRED


def test_decision_enum_has_exactly_two_values():
    assert {d.value for d in MissionWindowDecision} == {"ALLOW_NEW_WORK", "DENY_NOT_ELIGIBLE"}


def test_status_enum_has_exactly_eight_values():
    assert {s.value for s in MissionWindowStatus} == {
        "NOT_STARTED", "ACTIVE", "EXPIRED", "PAUSED", "BLOCKED", "TERMINAL", "NOT_APPLICABLE", "INVALID",
    }


# ── Phase 15.14.1 item 3/4: mission-state governance is STRONGER ────
# than a still-in-range deadline -- NOT_STARTED, PAUSED_USER, and
# BLOCKED must never be reported as eligible-for-work regardless of
# window timestamps.

def test_not_started_l3_is_not_started_not_active():
    mission = _mission(window_started_at=None, window_deadline_at=None)
    now = datetime(2026, 1, 1, tzinfo=timezone.utc)
    assert evaluate_mission_window(mission, now=now) is MissionWindowStatus.NOT_STARTED


def test_paused_user_is_paused_even_with_deadline_in_future():
    started = datetime(2026, 1, 1, tzinfo=timezone.utc)
    deadline = started + timedelta(seconds=DEFAULT_AUTONOMOUS_WINDOW_SECONDS)
    mission = _mission(
        state=MissionState.PAUSED_USER.value,
        window_started_at=started.isoformat(), window_deadline_at=deadline.isoformat(),
    )
    now = started + timedelta(hours=1)  # well inside the window
    assert evaluate_mission_window(mission, now=now) is MissionWindowStatus.PAUSED


def test_blocked_is_blocked_even_with_deadline_in_future():
    started = datetime(2026, 1, 1, tzinfo=timezone.utc)
    deadline = started + timedelta(seconds=DEFAULT_AUTONOMOUS_WINDOW_SECONDS)
    mission = _mission(
        state=MissionState.BLOCKED.value,
        window_started_at=started.isoformat(), window_deadline_at=deadline.isoformat(),
    )
    now = started + timedelta(hours=1)
    assert evaluate_mission_window(mission, now=now) is MissionWindowStatus.BLOCKED


def test_require_new_autonomous_work_allowed_eligibility_set_is_active_and_not_applicable_only():
    """Pure sanity check on the shared eligibility set -- ACTIVE and
    NOT_APPLICABLE are the ONLY statuses that admit new work; every
    other status (including NOT_STARTED, PAUSED, BLOCKED) denies."""
    from orca.mission.mission_window import _WORK_ADMITTING_STATUSES
    assert _WORK_ADMITTING_STATUSES == {MissionWindowStatus.NOT_APPLICABLE, MissionWindowStatus.ACTIVE}


# ── Canonical requirement registry (spec section 20) ─────────────────

def _seed_canonical_registry():
    from orca.mission import requirements as requirements_module
    from orca.mission import requirements_seed
    requirements_module.reset_registry_for_tests()
    requirements_seed._SEEDED = False
    requirements_seed.seed_registry()
    return requirements_module


def test_canonical_req_window_default_001_is_verified():
    from orca.mission.requirements import RequirementStatus
    requirements_module = _seed_canonical_registry()
    try:
        req = requirements_module.get("REQ-WINDOW-DEFAULT-001")
        assert req.status is RequirementStatus.VERIFIED
        assert "orca/mission/mission_window.py" in req.implementation_files
        assert req.evidence_ref is not None and req.evidence_ref.strip() != ""
    finally:
        requirements_module.reset_registry_for_tests()


def test_canonical_req_window_expiry_002_is_verified():
    from orca.mission.requirements import RequirementStatus
    requirements_module = _seed_canonical_registry()
    try:
        req = requirements_module.get("REQ-WINDOW-EXPIRY-002")
        assert req.status is RequirementStatus.VERIFIED
        assert "orca/mission/mission_window.py" in req.implementation_files
        assert req.evidence_ref is not None and req.evidence_ref.strip() != ""
    finally:
        requirements_module.reset_registry_for_tests()


def test_canonical_req_ckpt_restore_002_is_now_verified():
    from orca.mission.requirements import RequirementStatus
    requirements_module = _seed_canonical_registry()
    try:
        req = requirements_module.get("REQ-CKPT-RESTORE-002")
        assert req.status is RequirementStatus.VERIFIED
        assert "tests/test_mission_window_live_neon.py" in req.test_files
        assert req.evidence_ref is not None and req.evidence_ref.strip() != ""
    finally:
        requirements_module.reset_registry_for_tests()
