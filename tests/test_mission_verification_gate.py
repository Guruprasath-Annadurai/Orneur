"""Phase 15.8 -- mission COMPLETED_VERIFIED gate tests (spec section 18, 29),
including Phase 15.9.4 closure's mandatory explicit RequiredVerificationScope."""
from __future__ import annotations

import pytest

from orca.mission.mission_verification_gate import (
    MissionVerificationGateError,
    can_complete_verified,
    require_can_complete_verified,
)
from orca.mission.verification import VerificationOutcome, VerificationRecord
from orca.mission.verification_aggregation import RequiredVerificationScope

_C1_SCOPE = RequiredVerificationScope(criterion_ids=frozenset({"c1"}))


def _rec(outcome, requirement_id="REQ-A-X-001", revision="rev1", started_at="2026-01-01T00:00:00Z"):
    return VerificationRecord(
        id=f"ver_{requirement_id}_{started_at}", mission_id="m1", requirement_id=requirement_id,
        criterion_id="c1", category="UNIT_TEST", verification_method="UNIT_TEST",
        verifier_id="UnitTestVerifier", started_at=started_at, outcome=outcome, revision=revision,
        evidence_refs=("x",) if outcome == VerificationOutcome.PASS else (),
    )


def test_empty_required_set_raises():
    with pytest.raises(MissionVerificationGateError):
        can_complete_verified(
            {}, required_requirement_ids=(), current_revision="rev1", mission_id="m1",
            required_scopes_by_requirement={},
        )


def test_missing_requirement_blocks_completion():
    can_complete, outcomes = can_complete_verified(
        {}, required_requirement_ids=("REQ-A-X-001",), current_revision="rev1", mission_id="m1",
        required_scopes_by_requirement={"REQ-A-X-001": _C1_SCOPE},
    )
    assert can_complete is False
    assert outcomes["REQ-A-X-001"] is VerificationOutcome.UNVERIFIED


def test_all_pass_permits_completion():
    records = {"REQ-A-X-001": (_rec(VerificationOutcome.PASS),), "REQ-B-Y-001": (_rec(VerificationOutcome.PASS, requirement_id="REQ-B-Y-001"),)}
    can_complete, outcomes = can_complete_verified(
        records, required_requirement_ids=("REQ-A-X-001", "REQ-B-Y-001"), current_revision="rev1",
        mission_id="m1",
        required_scopes_by_requirement={"REQ-A-X-001": _C1_SCOPE, "REQ-B-Y-001": _C1_SCOPE},
    )
    assert can_complete is True
    assert all(o is VerificationOutcome.PASS for o in outcomes.values())


def test_one_failing_requirement_blocks_completion():
    records = {"REQ-A-X-001": (_rec(VerificationOutcome.PASS),), "REQ-B-Y-001": (_rec(VerificationOutcome.FAIL, requirement_id="REQ-B-Y-001"),)}
    can_complete, outcomes = can_complete_verified(
        records, required_requirement_ids=("REQ-A-X-001", "REQ-B-Y-001"), current_revision="rev1",
        mission_id="m1",
        required_scopes_by_requirement={"REQ-A-X-001": _C1_SCOPE, "REQ-B-Y-001": _C1_SCOPE},
    )
    assert can_complete is False
    assert outcomes["REQ-B-Y-001"] is VerificationOutcome.FAIL


def test_stale_revision_evidence_blocks_completion():
    # Evidence exists but for an OLD revision -- must not count.
    records = {"REQ-A-X-001": (_rec(VerificationOutcome.PASS, revision="rev0"),)}
    can_complete, outcomes = can_complete_verified(
        records, required_requirement_ids=("REQ-A-X-001",), current_revision="rev1", mission_id="m1",
        required_scopes_by_requirement={"REQ-A-X-001": _C1_SCOPE},
    )
    assert can_complete is False
    assert outcomes["REQ-A-X-001"] is VerificationOutcome.UNVERIFIED


def test_require_can_complete_verified_raises_with_breakdown():
    records = {"REQ-A-X-001": (_rec(VerificationOutcome.FAIL),)}
    with pytest.raises(MissionVerificationGateError) as exc_info:
        require_can_complete_verified(
            records, required_requirement_ids=("REQ-A-X-001",), current_revision="rev1", mission_id="m1",
            required_scopes_by_requirement={"REQ-A-X-001": _C1_SCOPE},
        )
    assert "REQ-A-X-001" in str(exc_info.value)


def test_require_can_complete_verified_passes_silently_when_all_pass():
    records = {"REQ-A-X-001": (_rec(VerificationOutcome.PASS),)}
    require_can_complete_verified(
        records, required_requirement_ids=("REQ-A-X-001",), current_revision="rev1", mission_id="m1",
        required_scopes_by_requirement={"REQ-A-X-001": _C1_SCOPE},
    )  # no raise


# ── Phase 15.9.3 closure item 1/4: requirement-id dict-key spoofing ──

def test_closure_15_9_3_a_dict_key_spoofing_cannot_pass():
    # required_requirement_ids=("REQ-B",) but the record supplied
    # under that key genuinely claims requirement_id="REQ-A".
    spoofed_record = _rec(VerificationOutcome.PASS, requirement_id="REQ-A")
    can_complete, outcomes = can_complete_verified(
        {"REQ-B": (spoofed_record,)}, required_requirement_ids=("REQ-B",), current_revision="rev1",
        mission_id="m1", required_scopes_by_requirement={"REQ-B": _C1_SCOPE},
    )
    assert can_complete is False
    assert outcomes["REQ-B"] is VerificationOutcome.UNVERIFIED


def test_closure_15_9_3_b_correct_dict_key_and_requirement_id_still_completes():
    real_record = _rec(VerificationOutcome.PASS, requirement_id="REQ-B")
    can_complete, outcomes = can_complete_verified(
        {"REQ-B": (real_record,)}, required_requirement_ids=("REQ-B",), current_revision="rev1",
        mission_id="m1", required_scopes_by_requirement={"REQ-B": _C1_SCOPE},
    )
    assert can_complete is True
    assert outcomes["REQ-B"] is VerificationOutcome.PASS


def test_closure_15_9_3_c_mixed_wrong_pass_ignored_correct_fail_dominates():
    correct_fail = _rec(VerificationOutcome.FAIL, requirement_id="REQ-B")
    wrong_pass = _rec(VerificationOutcome.PASS, requirement_id="REQ-A", started_at="2026-01-02T00:00:00Z")
    can_complete, outcomes = can_complete_verified(
        {"REQ-B": (correct_fail, wrong_pass)}, required_requirement_ids=("REQ-B",), current_revision="rev1",
        mission_id="m1", required_scopes_by_requirement={"REQ-B": _C1_SCOPE},
    )
    assert can_complete is False
    assert outcomes["REQ-B"] is VerificationOutcome.FAIL


# ── Phase 15.9.4 closure: authoritative scope must be explicit ──────

def test_closure_15_9_4_a_no_scope_supplied_raises_even_with_pass_record():
    pass_record = _rec(VerificationOutcome.PASS, requirement_id="REQ-A-X-001")
    with pytest.raises(MissionVerificationGateError):
        can_complete_verified(
            {"REQ-A-X-001": (pass_record,)}, required_requirement_ids=("REQ-A-X-001",),
            current_revision="rev1", mission_id="m1", required_scopes_by_requirement={},
        )


def test_closure_15_9_4_b_missing_mission_id_raises():
    pass_record = _rec(VerificationOutcome.PASS, requirement_id="REQ-A-X-001")
    with pytest.raises(MissionVerificationGateError):
        can_complete_verified(
            {"REQ-A-X-001": (pass_record,)}, required_requirement_ids=("REQ-A-X-001",),
            current_revision="rev1", mission_id="",
            required_scopes_by_requirement={"REQ-A-X-001": _C1_SCOPE},
        )


def test_closure_15_9_4_c_explicit_scope_after_simulated_registry_loss_still_completes():
    # Simulates a process restart: no AcceptanceCriterion registry
    # state exists at all here (this test never registers any), yet
    # completion still works correctly because the scope is supplied
    # explicitly -- the decision does not depend on in-process state.
    c1 = _rec(VerificationOutcome.PASS, requirement_id="REQ-CRIT-001")
    c2 = VerificationRecord(
        id="ver_c2", mission_id="m1", requirement_id="REQ-CRIT-001", criterion_id="c2",
        category="UNIT_TEST", verification_method="UNIT_TEST", verifier_id="UnitTestVerifier",
        started_at="2026-01-01T00:00:00Z", outcome=VerificationOutcome.PASS, revision="rev1",
        evidence_refs=("x",),
    )
    scope = RequiredVerificationScope(criterion_ids=frozenset({"c1", "c2"}))
    can_complete, outcomes = can_complete_verified(
        {"REQ-CRIT-001": (c1, c2)}, required_requirement_ids=("REQ-CRIT-001",), current_revision="rev1",
        mission_id="m1", required_scopes_by_requirement={"REQ-CRIT-001": scope},
    )
    assert can_complete is True
    assert outcomes["REQ-CRIT-001"] is VerificationOutcome.PASS


def test_closure_15_9_4_d_explicit_scope_c1_only_is_unverified():
    c1 = _rec(VerificationOutcome.PASS, requirement_id="REQ-CRIT-001")
    scope = RequiredVerificationScope(criterion_ids=frozenset({"c1", "c2"}))
    can_complete, outcomes = can_complete_verified(
        {"REQ-CRIT-001": (c1,)}, required_requirement_ids=("REQ-CRIT-001",), current_revision="rev1",
        mission_id="m1", required_scopes_by_requirement={"REQ-CRIT-001": scope},
    )
    assert can_complete is False
    assert outcomes["REQ-CRIT-001"] is VerificationOutcome.UNVERIFIED


def test_closure_15_9_4_e_requirement_level_category_scope_partial_is_unverified():
    unit_pass = VerificationRecord(
        id="ver_unit", mission_id="m1", requirement_id="REQ-CAT-001", criterion_id=None,
        category="UNIT_TEST", verification_method="UNIT_TEST", verifier_id="UnitTestVerifier",
        started_at="2026-01-01T00:00:00Z", outcome=VerificationOutcome.PASS, revision="rev1",
        evidence_refs=("x",),
    )
    scope = RequiredVerificationScope(requirement_level_categories=frozenset({"UNIT_TEST", "SECURITY_TEST"}))
    can_complete, outcomes = can_complete_verified(
        {"REQ-CAT-001": (unit_pass,)}, required_requirement_ids=("REQ-CAT-001",), current_revision="rev1",
        mission_id="m1", required_scopes_by_requirement={"REQ-CAT-001": scope},
    )
    assert can_complete is False
    assert outcomes["REQ-CAT-001"] is VerificationOutcome.UNVERIFIED


def test_closure_15_9_4_f_requirement_level_category_scope_complete_passes():
    unit_pass = VerificationRecord(
        id="ver_unit", mission_id="m1", requirement_id="REQ-CAT-001", criterion_id=None,
        category="UNIT_TEST", verification_method="UNIT_TEST", verifier_id="UnitTestVerifier",
        started_at="2026-01-01T00:00:00Z", outcome=VerificationOutcome.PASS, revision="rev1",
        evidence_refs=("x",),
    )
    security_pass = VerificationRecord(
        id="ver_security", mission_id="m1", requirement_id="REQ-CAT-001", criterion_id=None,
        category="SECURITY_TEST", verification_method="SECURITY_TEST", verifier_id="SecurityVerifier",
        started_at="2026-01-01T00:00:00Z", outcome=VerificationOutcome.PASS, revision="rev1",
        evidence_refs=("x",),
    )
    scope = RequiredVerificationScope(requirement_level_categories=frozenset({"UNIT_TEST", "SECURITY_TEST"}))
    can_complete, outcomes = can_complete_verified(
        {"REQ-CAT-001": (unit_pass, security_pass)}, required_requirement_ids=("REQ-CAT-001",),
        current_revision="rev1", mission_id="m1", required_scopes_by_requirement={"REQ-CAT-001": scope},
    )
    assert can_complete is True
    assert outcomes["REQ-CAT-001"] is VerificationOutcome.PASS


def test_closure_15_9_4_g_unexpected_extra_category_does_not_substitute_for_missing_required():
    unit_pass = VerificationRecord(
        id="ver_unit", mission_id="m1", requirement_id="REQ-CAT-001", criterion_id=None,
        category="UNIT_TEST", verification_method="UNIT_TEST", verifier_id="UnitTestVerifier",
        started_at="2026-01-01T00:00:00Z", outcome=VerificationOutcome.PASS, revision="rev1",
        evidence_refs=("x",),
    )
    extra_pass = VerificationRecord(
        id="ver_extra", mission_id="m1", requirement_id="REQ-CAT-001", criterion_id=None,
        category="PERFORMANCE_TEST", verification_method="PERFORMANCE_TEST", verifier_id="PerfVerifier",
        started_at="2026-01-01T00:00:00Z", outcome=VerificationOutcome.PASS, revision="rev1",
        evidence_refs=("x",),
    )
    scope = RequiredVerificationScope(requirement_level_categories=frozenset({"UNIT_TEST", "SECURITY_TEST"}))
    can_complete, outcomes = can_complete_verified(
        {"REQ-CAT-001": (unit_pass, extra_pass)}, required_requirement_ids=("REQ-CAT-001",),
        current_revision="rev1", mission_id="m1", required_scopes_by_requirement={"REQ-CAT-001": scope},
    )
    assert can_complete is False
    assert outcomes["REQ-CAT-001"] is VerificationOutcome.UNVERIFIED


def test_closure_15_9_4_process_restart_simulation_decision_independent_of_registry_state():
    # Explicit process-boundary simulation (spec item 8): populate the
    # Phase 15.7 AcceptanceCriterion registry in "process A", then
    # reset it as if a new process started ("process B"), and confirm
    # the SAME VerificationRecords produce the SAME, correct outcome in
    # both states -- because the decision only ever depends on the
    # explicitly-supplied RequiredVerificationScope, never on whether
    # the registry happens to be populated.
    from orca.mission import acceptance_criteria as ac_module
    from orca.mission import requirements as requirements_module
    from orca.mission.acceptance_criteria import VerificationMethod

    c1 = _rec(VerificationOutcome.PASS, requirement_id="REQ-RESTART-X-001")
    c2 = VerificationRecord(
        id="ver_restart_c2", mission_id="m1", requirement_id="REQ-RESTART-X-001", criterion_id="c2",
        category="UNIT_TEST", verification_method="UNIT_TEST", verifier_id="UnitTestVerifier",
        started_at="2026-01-01T00:00:00Z", outcome=VerificationOutcome.PASS, revision="rev1",
        evidence_refs=("x",),
    )
    explicit_scope = RequiredVerificationScope(criterion_ids=frozenset({"c1", "c2"}))

    requirements_module.reset_registry_for_tests()
    ac_module.reset_registry_for_tests()
    try:
        # Process A: registry populated with matching criteria.
        requirements_module.register(requirements_module.Requirement(
            id="REQ-RESTART-X-001", source_section="test", statement="Two criteria",
            acceptance_criteria=("first", "second"),
        ))
        ac_module.register_criterion(
            criterion_id="c1", requirement_id="REQ-RESTART-X-001", description="First",
            verification_method=VerificationMethod.UNIT_TEST,
        )
        ac_module.register_criterion(
            criterion_id="c2", requirement_id="REQ-RESTART-X-001", description="Second",
            verification_method=VerificationMethod.UNIT_TEST,
        )
        can_complete_a, outcomes_a = can_complete_verified(
            {"REQ-RESTART-X-001": (c1, c2)}, required_requirement_ids=("REQ-RESTART-X-001",),
            current_revision="rev1", mission_id="m1",
            required_scopes_by_requirement={"REQ-RESTART-X-001": explicit_scope},
        )

        # Process B: simulated restart -- registry cleared entirely.
        requirements_module.reset_registry_for_tests()
        ac_module.reset_registry_for_tests()
        can_complete_b, outcomes_b = can_complete_verified(
            {"REQ-RESTART-X-001": (c1, c2)}, required_requirement_ids=("REQ-RESTART-X-001",),
            current_revision="rev1", mission_id="m1",
            required_scopes_by_requirement={"REQ-RESTART-X-001": explicit_scope},
        )

        assert can_complete_a is True
        assert can_complete_b is True
        assert outcomes_a == outcomes_b
    finally:
        requirements_module.reset_registry_for_tests()
        ac_module.reset_registry_for_tests()
