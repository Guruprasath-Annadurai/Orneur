"""
Phase 15.9 -- Court/mission gate integration tests (spec sections 14,
27-28), including Phase 15.9.1 closure item 2's revision/mission-
binding adversarial scenarios A-C, Phase 15.9.2 closure item 2's
unscoped-mission-identity rejection scenarios C-D, and Phase 15.9.4
closure's mandatory explicit RequiredVerificationScope.
"""
from __future__ import annotations

import pytest

from orca.mission.cognitive_court import CourtDecision, CourtRole, CourtVerdict, RiskLevel
from orca.mission.court_mission_gate import CourtMissionGateError, can_proceed_to_completed_verified
from orca.mission.verification import VerificationOutcome, VerificationRecord
from orca.mission.verification_aggregation import RequiredVerificationScope

_UNIT_TEST_SCOPE = RequiredVerificationScope(requirement_level_categories=frozenset({"UNIT_TEST"}))


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
        required_scopes_by_requirement={"REQ-A-X-001": _UNIT_TEST_SCOPE},
    )
    assert ok is False
    assert "REJECT" in reason


def test_need_more_evidence_blocks():
    ok, _ = can_proceed_to_completed_verified(
        court_decision=_decision(CourtVerdict.NEED_MORE_EVIDENCE),
        records_by_requirement={}, required_requirement_ids=("REQ-A-X-001",), current_revision="rev1",
        current_mission_id="m1", required_scopes_by_requirement={"REQ-A-X-001": _UNIT_TEST_SCOPE},
    )
    assert ok is False


def test_escalate_blocks():
    ok, _ = can_proceed_to_completed_verified(
        court_decision=_decision(CourtVerdict.ESCALATE),
        records_by_requirement={}, required_requirement_ids=("REQ-A-X-001",), current_revision="rev1",
        current_mission_id="m1", required_scopes_by_requirement={"REQ-A-X-001": _UNIT_TEST_SCOPE},
    )
    assert ok is False


def test_human_approval_required_blocks():
    ok, _ = can_proceed_to_completed_verified(
        court_decision=_decision(CourtVerdict.HUMAN_APPROVAL_REQUIRED),
        records_by_requirement={}, required_requirement_ids=("REQ-A-X-001",), current_revision="rev1",
        current_mission_id="m1", required_scopes_by_requirement={"REQ-A-X-001": _UNIT_TEST_SCOPE},
    )
    assert ok is False


def test_accept_verdict_still_requires_verification_gate():
    ok, reason = can_proceed_to_completed_verified(
        court_decision=_decision(CourtVerdict.ACCEPT),
        records_by_requirement={}, required_requirement_ids=("REQ-A-X-001",), current_revision="rev1",
        current_mission_id="m1", required_scopes_by_requirement={"REQ-A-X-001": _UNIT_TEST_SCOPE},
    )
    assert ok is False
    assert "Verification gate" in reason


def test_accept_verdict_and_passing_verification_both_required_to_proceed():
    ok, reason = can_proceed_to_completed_verified(
        court_decision=_decision(CourtVerdict.ACCEPT),
        records_by_requirement={"REQ-A-X-001": (_pass_record("REQ-A-X-001"),)},
        required_requirement_ids=("REQ-A-X-001",), current_revision="rev1", current_mission_id="m1",
        required_scopes_by_requirement={"REQ-A-X-001": _UNIT_TEST_SCOPE},
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
        required_scopes_by_requirement={"REQ-A-X-001": _UNIT_TEST_SCOPE},
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
        required_scopes_by_requirement={"REQ-A-X-001": _UNIT_TEST_SCOPE},
    )
    assert ok is False
    assert "mission" in reason.lower()


def test_scenario_c_matching_mission_and_revision_may_proceed():
    matching_decision = _decision(CourtVerdict.ACCEPT, mission_id="m1", revision="rev1")
    ok, reason = can_proceed_to_completed_verified(
        court_decision=matching_decision,
        records_by_requirement={"REQ-A-X-001": (_pass_record("REQ-A-X-001", mission_id="m1", revision="rev1"),)},
        required_requirement_ids=("REQ-A-X-001",), current_revision="rev1", current_mission_id="m1",
        required_scopes_by_requirement={"REQ-A-X-001": _UNIT_TEST_SCOPE},
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
        required_scopes_by_requirement={"REQ-A-X-001": _UNIT_TEST_SCOPE},
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
            required_scopes_by_requirement={"REQ-A-X-001": _UNIT_TEST_SCOPE},
        )


def test_closure_15_9_2_d_current_mission_id_empty_string_raises_typed_error():
    matching_decision = _decision(CourtVerdict.ACCEPT, mission_id="m1", revision="rev1")
    with pytest.raises(CourtMissionGateError):
        can_proceed_to_completed_verified(
            court_decision=matching_decision,
            records_by_requirement={"REQ-A-X-001": (_pass_record("REQ-A-X-001", mission_id="m1", revision="rev1"),)},
            required_requirement_ids=("REQ-A-X-001",), current_revision="rev1", current_mission_id="",
            required_scopes_by_requirement={"REQ-A-X-001": _UNIT_TEST_SCOPE},
        )


def test_closure_15_9_2_matching_nonempty_mission_and_revision_still_succeeds():
    matching_decision = _decision(CourtVerdict.ACCEPT, mission_id="m9", revision="rev9")
    ok, reason = can_proceed_to_completed_verified(
        court_decision=matching_decision,
        records_by_requirement={"REQ-A-X-001": (_pass_record("REQ-A-X-001", mission_id="m9", revision="rev9"),)},
        required_requirement_ids=("REQ-A-X-001",), current_revision="rev9", current_mission_id="m9",
        required_scopes_by_requirement={"REQ-A-X-001": _UNIT_TEST_SCOPE},
    )
    assert ok is True
    assert "satisfied" in reason.lower()


# ── Phase 15.9.3 closure item 1/4: requirement-id dict-key spoofing ──

def test_closure_15_9_3_a_dict_key_spoofing_cannot_complete():
    # required_requirement_ids=("REQ-B",) but the record supplied
    # under that dict key genuinely claims requirement_id="REQ-A" --
    # this must be caught even though the Court's own ACCEPT decision
    # and mission/revision binding are otherwise perfectly valid.
    matching_decision = _decision(CourtVerdict.ACCEPT, mission_id="m1", revision="rev1")
    spoofed_record = _pass_record("REQ-A", mission_id="m1", revision="rev1")
    ok, reason = can_proceed_to_completed_verified(
        court_decision=matching_decision,
        records_by_requirement={"REQ-B": (spoofed_record,)},
        required_requirement_ids=("REQ-B",), current_revision="rev1", current_mission_id="m1",
        required_scopes_by_requirement={"REQ-B": _UNIT_TEST_SCOPE},
    )
    assert ok is False
    assert "Verification gate" in reason


def test_closure_15_9_3_b_correct_dict_key_and_requirement_id_still_succeeds():
    matching_decision = _decision(CourtVerdict.ACCEPT, mission_id="m1", revision="rev1")
    real_record = _pass_record("REQ-B", mission_id="m1", revision="rev1")
    ok, reason = can_proceed_to_completed_verified(
        court_decision=matching_decision,
        records_by_requirement={"REQ-B": (real_record,)},
        required_requirement_ids=("REQ-B",), current_revision="rev1", current_mission_id="m1",
        required_scopes_by_requirement={"REQ-B": _UNIT_TEST_SCOPE},
    )
    assert ok is True
    assert "satisfied" in reason.lower()


# ── Phase 15.9.4 closure: authoritative scope must be explicit ──────

def test_closure_15_9_4_a_no_scope_supplied_cannot_complete_even_with_pass_record():
    matching_decision = _decision(CourtVerdict.ACCEPT, mission_id="m1", revision="rev1")
    with pytest.raises(Exception):
        can_proceed_to_completed_verified(
            court_decision=matching_decision,
            records_by_requirement={"REQ-A-X-001": (_pass_record("REQ-A-X-001"),)},
            required_requirement_ids=("REQ-A-X-001",), current_revision="rev1", current_mission_id="m1",
            required_scopes_by_requirement={},
        )


def test_closure_15_9_4_b_registry_populated_but_scope_omitted_still_rejects():
    # Even if a caller populated the Phase 15.7 AcceptanceCriterion
    # registry in this same process, can_proceed_to_completed_verified()
    # never consults it -- omitting the explicit scope must still fail
    # closed (the registry cannot secretly change this decision API).
    from orca.mission import acceptance_criteria as ac_module
    from orca.mission import requirements as requirements_module
    from orca.mission.acceptance_criteria import VerificationMethod

    requirements_module.reset_registry_for_tests()
    ac_module.reset_registry_for_tests()
    try:
        requirements_module.register(requirements_module.Requirement(
            id="REQ-A-X-001", source_section="test", statement="A thing must happen",
            acceptance_criteria=("some criterion",),
        ))
        ac_module.register_criterion(
            criterion_id="c1", requirement_id="REQ-A-X-001", description="A criterion",
            verification_method=VerificationMethod.UNIT_TEST,
        )
        matching_decision = _decision(CourtVerdict.ACCEPT, mission_id="m1", revision="rev1")
        with pytest.raises(Exception):
            can_proceed_to_completed_verified(
                court_decision=matching_decision,
                records_by_requirement={"REQ-A-X-001": (_pass_record("REQ-A-X-001"),)},
                required_requirement_ids=("REQ-A-X-001",), current_revision="rev1", current_mission_id="m1",
                required_scopes_by_requirement={},
            )
    finally:
        requirements_module.reset_registry_for_tests()
        ac_module.reset_registry_for_tests()


def test_closure_15_9_4_j_matching_mission_revision_requirement_and_complete_scope_still_succeeds():
    matching_decision = _decision(CourtVerdict.ACCEPT, mission_id="m1", revision="rev1")
    real_record = _pass_record("REQ-A-X-001", mission_id="m1", revision="rev1")
    ok, reason = can_proceed_to_completed_verified(
        court_decision=matching_decision,
        records_by_requirement={"REQ-A-X-001": (real_record,)},
        required_requirement_ids=("REQ-A-X-001",), current_revision="rev1", current_mission_id="m1",
        required_scopes_by_requirement={"REQ-A-X-001": _UNIT_TEST_SCOPE},
    )
    assert ok is True
    assert "satisfied" in reason.lower()
