"""Phase 15.8 -- mission COMPLETED_VERIFIED gate tests (spec section 18, 29)."""
from __future__ import annotations

import pytest

from orca.mission.mission_verification_gate import (
    MissionVerificationGateError,
    can_complete_verified,
    require_can_complete_verified,
)
from orca.mission.verification import VerificationOutcome, VerificationRecord


def _rec(outcome, requirement_id="REQ-A-X-001", revision="rev1", started_at="2026-01-01T00:00:00Z"):
    return VerificationRecord(
        id=f"ver_{requirement_id}_{started_at}", mission_id="m1", requirement_id=requirement_id,
        criterion_id="c1", category="UNIT_TEST", verification_method="UNIT_TEST",
        verifier_id="UnitTestVerifier", started_at=started_at, outcome=outcome, revision=revision,
        evidence_refs=("x",) if outcome == VerificationOutcome.PASS else (),
    )


def test_empty_required_set_raises():
    with pytest.raises(MissionVerificationGateError):
        can_complete_verified({}, required_requirement_ids=(), current_revision="rev1")


def test_missing_requirement_blocks_completion():
    can_complete, outcomes = can_complete_verified(
        {}, required_requirement_ids=("REQ-A-X-001",), current_revision="rev1",
    )
    assert can_complete is False
    assert outcomes["REQ-A-X-001"] is VerificationOutcome.UNVERIFIED


def test_all_pass_permits_completion():
    records = {"REQ-A-X-001": (_rec(VerificationOutcome.PASS),), "REQ-B-Y-001": (_rec(VerificationOutcome.PASS, requirement_id="REQ-B-Y-001"),)}
    can_complete, outcomes = can_complete_verified(
        records, required_requirement_ids=("REQ-A-X-001", "REQ-B-Y-001"), current_revision="rev1",
    )
    assert can_complete is True
    assert all(o is VerificationOutcome.PASS for o in outcomes.values())


def test_one_failing_requirement_blocks_completion():
    records = {"REQ-A-X-001": (_rec(VerificationOutcome.PASS),), "REQ-B-Y-001": (_rec(VerificationOutcome.FAIL, requirement_id="REQ-B-Y-001"),)}
    can_complete, outcomes = can_complete_verified(
        records, required_requirement_ids=("REQ-A-X-001", "REQ-B-Y-001"), current_revision="rev1",
    )
    assert can_complete is False
    assert outcomes["REQ-B-Y-001"] is VerificationOutcome.FAIL


def test_stale_revision_evidence_blocks_completion():
    # Evidence exists but for an OLD revision -- must not count.
    records = {"REQ-A-X-001": (_rec(VerificationOutcome.PASS, revision="rev0"),)}
    can_complete, outcomes = can_complete_verified(
        records, required_requirement_ids=("REQ-A-X-001",), current_revision="rev1",
    )
    assert can_complete is False
    assert outcomes["REQ-A-X-001"] is VerificationOutcome.UNVERIFIED


def test_require_can_complete_verified_raises_with_breakdown():
    records = {"REQ-A-X-001": (_rec(VerificationOutcome.FAIL),)}
    with pytest.raises(MissionVerificationGateError) as exc_info:
        require_can_complete_verified(records, required_requirement_ids=("REQ-A-X-001",), current_revision="rev1")
    assert "REQ-A-X-001" in str(exc_info.value)


def test_require_can_complete_verified_passes_silently_when_all_pass():
    records = {"REQ-A-X-001": (_rec(VerificationOutcome.PASS),)}
    require_can_complete_verified(records, required_requirement_ids=("REQ-A-X-001",), current_revision="rev1")  # no raise
