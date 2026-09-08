"""Phase 15.9 -- Court/mission gate integration tests (spec sections 14, 27-28)."""
from __future__ import annotations

from orca.mission.cognitive_court import CourtDecision, CourtRole, CourtVerdict, RiskLevel
from orca.mission.court_mission_gate import can_proceed_to_completed_verified
from orca.mission.verification import VerificationOutcome, VerificationRecord


def _decision(verdict: CourtVerdict) -> CourtDecision:
    return CourtDecision(
        decision_id="d1", mission_id="m1", revision="rev1", risk_level=RiskLevel.STANDARD,
        roles_invoked=(CourtRole.ARBITER,), findings_considered=(), verification_refs=(),
        reasoning_summary="test decision", verdict=verdict,
    )


def _pass_record(requirement_id: str) -> VerificationRecord:
    return VerificationRecord(
        id="ver_1", mission_id="m1", requirement_id=requirement_id, criterion_id=None,
        category="UNIT_TEST", verification_method="UNIT_TEST", verifier_id="UnitTestVerifier",
        started_at="2026-01-01T00:00:00Z", outcome=VerificationOutcome.PASS, revision="rev1",
        evidence_refs=("x",),
    )


def test_reject_verdict_blocks_regardless_of_verification():
    ok, reason = can_proceed_to_completed_verified(
        court_decision=_decision(CourtVerdict.REJECT),
        records_by_requirement={"REQ-A-X-001": (_pass_record("REQ-A-X-001"),)},
        required_requirement_ids=("REQ-A-X-001",), current_revision="rev1",
    )
    assert ok is False
    assert "REJECT" in reason


def test_need_more_evidence_blocks():
    ok, _ = can_proceed_to_completed_verified(
        court_decision=_decision(CourtVerdict.NEED_MORE_EVIDENCE),
        records_by_requirement={}, required_requirement_ids=("REQ-A-X-001",), current_revision="rev1",
    )
    assert ok is False


def test_escalate_blocks():
    ok, _ = can_proceed_to_completed_verified(
        court_decision=_decision(CourtVerdict.ESCALATE),
        records_by_requirement={}, required_requirement_ids=("REQ-A-X-001",), current_revision="rev1",
    )
    assert ok is False


def test_human_approval_required_blocks():
    ok, _ = can_proceed_to_completed_verified(
        court_decision=_decision(CourtVerdict.HUMAN_APPROVAL_REQUIRED),
        records_by_requirement={}, required_requirement_ids=("REQ-A-X-001",), current_revision="rev1",
    )
    assert ok is False


def test_accept_verdict_still_requires_verification_gate():
    ok, reason = can_proceed_to_completed_verified(
        court_decision=_decision(CourtVerdict.ACCEPT),
        records_by_requirement={}, required_requirement_ids=("REQ-A-X-001",), current_revision="rev1",
    )
    assert ok is False
    assert "Verification gate" in reason


def test_accept_verdict_and_passing_verification_both_required_to_proceed():
    ok, reason = can_proceed_to_completed_verified(
        court_decision=_decision(CourtVerdict.ACCEPT),
        records_by_requirement={"REQ-A-X-001": (_pass_record("REQ-A-X-001"),)},
        required_requirement_ids=("REQ-A-X-001",), current_revision="rev1",
    )
    assert ok is True
