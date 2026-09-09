"""
Phase 15.9 -- Court/mission gate integration tests (spec sections 14,
27-28), including Phase 15.9.1 closure item 2's revision/mission-
binding adversarial scenarios A-C, and Phase 15.9.2 closure item 2's
unscoped-mission-identity rejection scenarios C-D.
"""
from __future__ import annotations

import pytest

from orca.mission.cognitive_court import CourtDecision, CourtRole, CourtVerdict, RiskLevel
from orca.mission.court_mission_gate import CourtMissionGateError, can_proceed_to_completed_verified
from orca.mission.verification import VerificationOutcome, VerificationRecord


def _decision(verdict: CourtVerdict, *, mission_id: str = "m1", revision: str = "rev1") -> CourtDecision:
    return CourtDecision(
        decision_id="d1", mission_id=mission_id, revision=revision, risk_level=RiskLevel.STANDARD,
        roles_invoked=(CourtRole.ARBITER,), findings_considered=(), verification_refs=(),
        reasoning_summary="test decision", verdict=verdict,
    )


def _pass_record(requirement_id: str, *, mission_id: str = "m1", revision: str = "rev1") -> VerificationRecord:
    return VerificationRecord(
        id=f"ver_{requirement_id}_{mission_id}_{revision}", mission_id=mission_id, requirement_id=requirement_id,
        criterion_id=None, category="UNIT_TEST", verification_method="UNIT_TEST", verifier_id="UnitTestVerifier",
        started_at="2026-01-01T00:00:00Z", outcome=VerificationOutcome.PASS, revision=revision,
        evidence_refs=("x",),
    )


def test_reject_verdict_blocks_regardless_of_verification():
    ok, reason = can_proceed_to_completed_verified(
        court_decision=_decision(CourtVerdict.REJECT),
        records_by_requirement={"REQ-A-X-001": (_pass_record("REQ-A-X-001"),)},
        required_requirement_ids=("REQ-A-X-001",), current_revision="rev1", current_mission_id="m1",
    )
    assert ok is False
    assert "REJECT" in reason


def test_need_more_evidence_blocks():
    ok, _ = can_proceed_to_completed_verified(
        court_decision=_decision(CourtVerdict.NEED_MORE_EVIDENCE),
        records_by_requirement={}, required_requirement_ids=("REQ-A-X-001",), current_revision="rev1",
        current_mission_id="m1",
    )
    assert ok is False


def test_escalate_blocks():
    ok, _ = can_proceed_to_completed_verified(
        court_decision=_decision(CourtVerdict.ESCALATE),
        records_by_requirement={}, required_requirement_ids=("REQ-A-X-001",), current_revision="rev1",
        current_mission_id="m1",
    )
    assert ok is False


def test_human_approval_required_blocks():
    ok, _ = can_proceed_to_completed_verified(
        court_decision=_decision(CourtVerdict.HUMAN_APPROVAL_REQUIRED),
        records_by_requirement={}, required_requirement_ids=("REQ-A-X-001",), current_revision="rev1",
        current_mission_id="m1",
    )
    assert ok is False


def test_accept_verdict_still_requires_verification_gate():
    ok, reason = can_proceed_to_completed_verified(
        court_decision=_decision(CourtVerdict.ACCEPT),
        records_by_requirement={}, required_requirement_ids=("REQ-A-X-001",), current_revision="rev1",
        current_mission_id="m1",
    )
    assert ok is False
    assert "Verification gate" in reason


def test_accept_verdict_and_passing_verification_both_required_to_proceed():
    ok, reason = can_proceed_to_completed_verified(
        court_decision=_decision(CourtVerdict.ACCEPT),
        records_by_requirement={"REQ-A-X-001": (_pass_record("REQ-A-X-001"),)},
        required_requirement_ids=("REQ-A-X-001",), current_revision="rev1", current_mission_id="m1",
    )
    assert ok is True


# ── Phase 15.9.1 closure item 2: revision/mission binding ───────────

def test_scenario_a_stale_accept_from_rev1_cannot_authorize_rev2():
    # The Court ACCEPT was made about revision "rev1". Even with
    # perfectly valid PASS evidence for revision "rev2", the STALE
    # decision must not authorize completion of rev2.
    stale_decision = _decision(CourtVerdict.ACCEPT, mission_id="m1", revision="rev1")
    ok, reason = can_proceed_to_completed_verified(
        court_decision=stale_decision,
        records_by_requirement={"REQ-A-X-001": (_pass_record("REQ-A-X-001", mission_id="m1", revision="rev2"),)},
        required_requirement_ids=("REQ-A-X-001",), current_revision="rev2", current_mission_id="m1",
    )
    assert ok is False
    assert "revision" in reason.lower()


def test_scenario_b_accept_for_mission_1_cannot_complete_mission_2():
    # The Court ACCEPT was made about mission "m1". Valid PASS
    # evidence exists for mission "m2" at the same revision, but the
    # decision itself is bound to m1 and must not authorize m2.
    decision_for_m1 = _decision(CourtVerdict.ACCEPT, mission_id="m1", revision="rev1")
    ok, reason = can_proceed_to_completed_verified(
        court_decision=decision_for_m1,
        records_by_requirement={"REQ-A-X-001": (_pass_record("REQ-A-X-001", mission_id="m2", revision="rev1"),)},
        required_requirement_ids=("REQ-A-X-001",), current_revision="rev1", current_mission_id="m2",
    )
    assert ok is False
    assert "mission" in reason.lower()


def test_scenario_c_matching_mission_and_revision_may_proceed():
    matching_decision = _decision(CourtVerdict.ACCEPT, mission_id="m1", revision="rev1")
    ok, reason = can_proceed_to_completed_verified(
        court_decision=matching_decision,
        records_by_requirement={"REQ-A-X-001": (_pass_record("REQ-A-X-001", mission_id="m1", revision="rev1"),)},
        required_requirement_ids=("REQ-A-X-001",), current_revision="rev1", current_mission_id="m1",
    )
    assert ok is True
    assert "satisfied" in reason.lower()


def test_cross_mission_evidence_alone_does_not_leak_into_correct_mission_completion():
    # Evidence exists for BOTH m1 (correct) and m2 (wrong) for the
    # same requirement id -- only the m1 record may count.
    matching_decision = _decision(CourtVerdict.ACCEPT, mission_id="m1", revision="rev1")
    ok, _ = can_proceed_to_completed_verified(
        court_decision=matching_decision,
        records_by_requirement={"REQ-A-X-001": (
            _pass_record("REQ-A-X-001", mission_id="m2", revision="rev1"),
        )},
        required_requirement_ids=("REQ-A-X-001",), current_revision="rev1", current_mission_id="m1",
    )
    # The only record present is for m2 -- it must not count for m1.
    assert ok is False


# ── Phase 15.9.2 closure item 2: completion gate must never be unscoped ─

def test_closure_15_9_2_c_current_mission_id_none_raises_typed_error():
    matching_decision = _decision(CourtVerdict.ACCEPT, mission_id="m1", revision="rev1")
    with pytest.raises(CourtMissionGateError):
        can_proceed_to_completed_verified(
            court_decision=matching_decision,
            records_by_requirement={"REQ-A-X-001": (_pass_record("REQ-A-X-001", mission_id="m1", revision="rev1"),)},
            required_requirement_ids=("REQ-A-X-001",), current_revision="rev1", current_mission_id=None,
        )


def test_closure_15_9_2_d_current_mission_id_empty_string_raises_typed_error():
    matching_decision = _decision(CourtVerdict.ACCEPT, mission_id="m1", revision="rev1")
    with pytest.raises(CourtMissionGateError):
        can_proceed_to_completed_verified(
            court_decision=matching_decision,
            records_by_requirement={"REQ-A-X-001": (_pass_record("REQ-A-X-001", mission_id="m1", revision="rev1"),)},
            required_requirement_ids=("REQ-A-X-001",), current_revision="rev1", current_mission_id="",
        )


def test_closure_15_9_2_matching_nonempty_mission_and_revision_still_succeeds():
    matching_decision = _decision(CourtVerdict.ACCEPT, mission_id="m9", revision="rev9")
    ok, reason = can_proceed_to_completed_verified(
        court_decision=matching_decision,
        records_by_requirement={"REQ-A-X-001": (_pass_record("REQ-A-X-001", mission_id="m9", revision="rev9"),)},
        required_requirement_ids=("REQ-A-X-001",), current_revision="rev9", current_mission_id="m9",
    )
    assert ok is True
    assert "satisfied" in reason.lower()
