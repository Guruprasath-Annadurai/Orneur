"""Phase 15.8 -- aggregation, stale detection, check-ordering tests."""
from __future__ import annotations

import pytest

from orca.mission import acceptance_criteria as ac_module
from orca.mission import requirements as requirements_module
from orca.mission.acceptance_criteria import VerificationMethod
from orca.mission.verification import VerificationOutcome, VerificationRecord
from orca.mission.verification_aggregation import (
    CheckOrderingEdge,
    CheckOrderingError,
    aggregate_outcomes,
    aggregate_requirement,
    evaluate_requirement_completion,
    expected_keys_for_requirement,
    filter_current_requirement_context,
    filter_current_revision,
    is_evidence_stale,
    validate_check_ordering,
)


def _rec(outcome, criterion_id="c1", started_at="2026-01-01T00:00:00Z", revision="rev1", **overrides):
    defaults = dict(
        id=f"ver_{started_at}_{criterion_id}", mission_id="m1", requirement_id="REQ-X-Y-001",
        criterion_id=criterion_id, category="UNIT_TEST", verification_method="UNIT_TEST",
        verifier_id="TestVerifier", started_at=started_at, outcome=outcome, revision=revision,
        evidence_refs=("x",) if outcome == VerificationOutcome.PASS else (),
        not_applicable_reason="n/a" if outcome == VerificationOutcome.NOT_APPLICABLE else None,
        error_detail="e" if outcome == VerificationOutcome.ERROR else None,
    )
    defaults.update(overrides)
    return VerificationRecord(**defaults)


# ── aggregate_outcomes: non-vacuous truth table ──────────────────────

def test_empty_outcomes_is_unverified_never_vacuous_pass():
    assert aggregate_outcomes(()) is VerificationOutcome.UNVERIFIED


def test_any_fail_dominates():
    result = aggregate_outcomes((VerificationOutcome.PASS, VerificationOutcome.FAIL))
    assert result is VerificationOutcome.FAIL


def test_any_unverified_blocks_pass():
    result = aggregate_outcomes((VerificationOutcome.PASS, VerificationOutcome.UNVERIFIED))
    assert result is VerificationOutcome.UNVERIFIED


def test_error_and_cancelled_and_timed_out_all_block_pass():
    for bad in (VerificationOutcome.ERROR, VerificationOutcome.CANCELLED, VerificationOutcome.TIMED_OUT):
        assert aggregate_outcomes((VerificationOutcome.PASS, bad)) is VerificationOutcome.UNVERIFIED


def test_all_pass_yields_pass():
    assert aggregate_outcomes((VerificationOutcome.PASS, VerificationOutcome.PASS)) is VerificationOutcome.PASS


def test_pass_with_not_applicable_yields_pass():
    result = aggregate_outcomes((VerificationOutcome.PASS, VerificationOutcome.NOT_APPLICABLE))
    assert result is VerificationOutcome.PASS


def test_all_not_applicable_is_unverified_not_vacuous_pass():
    result = aggregate_outcomes((VerificationOutcome.NOT_APPLICABLE, VerificationOutcome.NOT_APPLICABLE))
    assert result is VerificationOutcome.UNVERIFIED


# ── aggregate_requirement: latest-per-key, history preserved ────────

def test_aggregate_requirement_zero_records_unverified():
    assert aggregate_requirement(()) is VerificationOutcome.UNVERIFIED


def test_aggregate_requirement_uses_latest_per_criterion():
    old_fail = _rec(VerificationOutcome.FAIL, criterion_id="c1", started_at="2026-01-01T00:00:00Z")
    new_pass = _rec(VerificationOutcome.PASS, criterion_id="c1", started_at="2026-01-02T00:00:00Z")
    result = aggregate_requirement((old_fail, new_pass))
    assert result is VerificationOutcome.PASS  # latest wins, but old_fail is NOT deleted (see store tests)


def test_aggregate_requirement_multiple_criteria_all_must_pass():
    c1_pass = _rec(VerificationOutcome.PASS, criterion_id="c1")
    c2_fail = _rec(VerificationOutcome.FAIL, criterion_id="c2")
    assert aggregate_requirement((c1_pass, c2_fail)) is VerificationOutcome.FAIL


# ── stale evidence ───────────────────────────────────────────────────

def test_stale_evidence_detected_for_different_revision():
    rec = _rec(VerificationOutcome.PASS, revision="rev1")
    assert is_evidence_stale(rec, current_revision="rev2") is True
    assert is_evidence_stale(rec, current_revision="rev1") is False


def test_filter_current_revision_excludes_stale_but_does_not_error():
    rev1_pass = _rec(VerificationOutcome.PASS, criterion_id="c1", revision="rev1")
    rev2_fail = _rec(VerificationOutcome.FAIL, criterion_id="c1", revision="rev2", started_at="2026-01-02T00:00:00Z")
    current = filter_current_revision((rev1_pass, rev2_fail), current_revision="rev2")
    assert current == (rev2_fail,)
    # revision A's PASS does not count as revision B's proof:
    assert aggregate_requirement(current) is VerificationOutcome.FAIL


def test_revision_a_pass_does_not_verify_revision_b():
    rev1_pass = _rec(VerificationOutcome.PASS, criterion_id="c1", revision="rev1")
    # No record at all for rev2 yet -- must be UNVERIFIED, not silently PASS.
    current = filter_current_revision((rev1_pass,), current_revision="rev2")
    assert current == ()
    assert aggregate_requirement(current) is VerificationOutcome.UNVERIFIED


# ── check ordering / cycle detection ─────────────────────────────────

def test_check_ordering_accepts_dag():
    validate_check_ordering((
        CheckOrderingEdge(before="BUILD", after="UNIT_TEST"),
        CheckOrderingEdge(before="UNIT_TEST", after="INTEGRATION_TEST"),
    ))  # no error


def test_check_ordering_rejects_direct_cycle():
    with pytest.raises(CheckOrderingError):
        validate_check_ordering((
            CheckOrderingEdge(before="BUILD", after="UNIT_TEST"),
            CheckOrderingEdge(before="UNIT_TEST", after="BUILD"),
        ))


def test_check_ordering_rejects_indirect_cycle():
    with pytest.raises(CheckOrderingError):
        validate_check_ordering((
            CheckOrderingEdge(before="A", after="B"),
            CheckOrderingEdge(before="B", after="C"),
            CheckOrderingEdge(before="C", after="A"),
        ))


# ── Phase 15.9.3 closure item 1: requirement-id binding ──────────────
# A VerificationRecord may contribute to requirement X ONLY when its
# OWN record.requirement_id == X -- a caller filing it under
# records_by_requirement[X] is never itself authority for that.

def test_filter_current_requirement_context_rejects_record_for_different_requirement():
    record_for_req_a = _rec(VerificationOutcome.PASS, requirement_id="REQ-A")
    current = filter_current_requirement_context(
        (record_for_req_a,), current_revision="rev1", requirement_id="REQ-B",
    )
    assert current == ()


def test_filter_current_requirement_context_keeps_matching_requirement():
    record_for_req_a = _rec(VerificationOutcome.PASS, requirement_id="REQ-A")
    current = filter_current_requirement_context(
        (record_for_req_a,), current_revision="rev1", requirement_id="REQ-A",
    )
    assert current == (record_for_req_a,)


def test_dictionary_key_spoofing_does_not_substitute_for_real_requirement_id():
    # The record's OWN requirement_id is "REQ-A" -- filing it under a
    # "REQ-B" dict key must not make it count as REQ-B's evidence.
    spoofed_record = _rec(VerificationOutcome.PASS, requirement_id="REQ-A")
    outcome, contributing = evaluate_requirement_completion(
        (spoofed_record,), requirement_id="REQ-B", current_revision="rev1", mission_id="m1",
    )
    assert outcome is VerificationOutcome.UNVERIFIED
    assert contributing == ()


def test_correctly_scoped_record_still_supports_completion():
    real_record = _rec(VerificationOutcome.PASS, requirement_id="REQ-A")
    outcome, contributing = evaluate_requirement_completion(
        (real_record,), requirement_id="REQ-A", current_revision="rev1", mission_id="m1",
    )
    assert outcome is VerificationOutcome.PASS
    assert contributing == (real_record,)


def test_mixed_records_wrong_pass_ignored_correct_fail_dominates():
    # One correctly-scoped FAIL for REQ-B's own criterion "c1", plus
    # one PASS whose real requirement_id is REQ-A (wrongly filed under
    # REQ-B) -- the wrong PASS must be ignored and the real FAIL must
    # dominate the aggregate.
    correct_fail = _rec(VerificationOutcome.FAIL, requirement_id="REQ-B", criterion_id="c1")
    wrong_pass = _rec(VerificationOutcome.PASS, requirement_id="REQ-A", criterion_id="c2",
                       started_at="2026-01-02T00:00:00Z")
    outcome, contributing = evaluate_requirement_completion(
        (correct_fail, wrong_pass), requirement_id="REQ-B", current_revision="rev1", mission_id="m1",
    )
    assert outcome is VerificationOutcome.FAIL
    assert contributing == ()


# ── Phase 15.9.3 closure item 2: required-criterion completeness ────

@pytest.fixture(autouse=True)
def _clean_criteria_registries():
    requirements_module.reset_registry_for_tests()
    ac_module.reset_registry_for_tests()
    yield
    requirements_module.reset_registry_for_tests()
    ac_module.reset_registry_for_tests()


def _register_req_with_two_criteria(req_id="REQ-CRIT-X-001", c1="c1", c2="c2"):
    requirements_module.register(requirements_module.Requirement(
        id=req_id, source_section="test", statement="Two criteria must both be verified",
        acceptance_criteria=("first", "second"),
    ))
    ac_module.register_criterion(
        criterion_id=c1, requirement_id=req_id, description="First criterion",
        verification_method=VerificationMethod.UNIT_TEST,
    )
    ac_module.register_criterion(
        criterion_id=c2, requirement_id=req_id, description="Second criterion",
        verification_method=VerificationMethod.UNIT_TEST,
    )


def test_expected_keys_for_requirement_none_when_no_criteria_registered():
    assert expected_keys_for_requirement("REQ-NEVER-REGISTERED") is None


def test_expected_keys_for_requirement_returns_registered_criterion_ids():
    _register_req_with_two_criteria()
    assert expected_keys_for_requirement("REQ-CRIT-X-001") == frozenset({"c1", "c2"})


def test_scenario_1_only_c1_evidence_is_unverified_not_pass():
    # C2 has no VerificationRecord at all -- missing required criterion
    # evidence is UNVERIFIED, never PASS, and `contributing` is empty
    # even though C1 individually passed (it is only ever populated
    # when the AGGREGATE outcome is itself PASS).
    _register_req_with_two_criteria()
    c1_pass = _rec(VerificationOutcome.PASS, requirement_id="REQ-CRIT-X-001", criterion_id="c1")
    outcome, contributing = evaluate_requirement_completion(
        (c1_pass,), requirement_id="REQ-CRIT-X-001", current_revision="rev1", mission_id="m1",
    )
    assert outcome is VerificationOutcome.UNVERIFIED
    assert contributing == ()


def test_scenario_2_c1_pass_c2_pass_yields_pass():
    _register_req_with_two_criteria()
    c1_pass = _rec(VerificationOutcome.PASS, requirement_id="REQ-CRIT-X-001", criterion_id="c1")
    c2_pass = _rec(VerificationOutcome.PASS, requirement_id="REQ-CRIT-X-001", criterion_id="c2")
    outcome, contributing = evaluate_requirement_completion(
        (c1_pass, c2_pass), requirement_id="REQ-CRIT-X-001", current_revision="rev1", mission_id="m1",
    )
    assert outcome is VerificationOutcome.PASS
    assert set(contributing) == {c1_pass, c2_pass}


def test_scenario_3_c1_pass_c2_fail_yields_fail():
    _register_req_with_two_criteria()
    c1_pass = _rec(VerificationOutcome.PASS, requirement_id="REQ-CRIT-X-001", criterion_id="c1")
    c2_fail = _rec(VerificationOutcome.FAIL, requirement_id="REQ-CRIT-X-001", criterion_id="c2")
    outcome, _ = evaluate_requirement_completion(
        (c1_pass, c2_fail), requirement_id="REQ-CRIT-X-001", current_revision="rev1", mission_id="m1",
    )
    assert outcome is VerificationOutcome.FAIL


def test_scenario_4_c2_stale_pass_yields_unverified_for_current_revision():
    _register_req_with_two_criteria()
    c1_pass = _rec(VerificationOutcome.PASS, requirement_id="REQ-CRIT-X-001", criterion_id="c1", revision="rev2")
    c2_stale_pass = _rec(VerificationOutcome.PASS, requirement_id="REQ-CRIT-X-001", criterion_id="c2", revision="rev1")
    outcome, _ = evaluate_requirement_completion(
        (c1_pass, c2_stale_pass), requirement_id="REQ-CRIT-X-001", current_revision="rev2", mission_id="m1",
    )
    assert outcome is VerificationOutcome.UNVERIFIED


def test_scenario_5_c2_pass_from_other_mission_does_not_count():
    _register_req_with_two_criteria()
    c1_pass = _rec(VerificationOutcome.PASS, requirement_id="REQ-CRIT-X-001", criterion_id="c1", mission_id="mA")
    c2_pass_other_mission = _rec(VerificationOutcome.PASS, requirement_id="REQ-CRIT-X-001", criterion_id="c2",
                                  mission_id="mB")
    outcome, _ = evaluate_requirement_completion(
        (c1_pass, c2_pass_other_mission), requirement_id="REQ-CRIT-X-001", current_revision="rev1", mission_id="mA",
    )
    assert outcome is VerificationOutcome.UNVERIFIED


def test_scenario_6_unrelated_c3_pass_does_not_substitute_for_missing_c2():
    _register_req_with_two_criteria()
    c1_pass = _rec(VerificationOutcome.PASS, requirement_id="REQ-CRIT-X-001", criterion_id="c1")
    c3_pass_unrelated = _rec(VerificationOutcome.PASS, requirement_id="REQ-CRIT-X-001", criterion_id="c3")
    outcome, contributing = evaluate_requirement_completion(
        (c1_pass, c3_pass_unrelated), requirement_id="REQ-CRIT-X-001", current_revision="rev1", mission_id="m1",
    )
    assert outcome is VerificationOutcome.UNVERIFIED
    # c3 is not a required key -- it must never appear as a contributor.
    assert c3_pass_unrelated not in contributing


def test_scenario_7_record_criterion_id_matches_but_requirement_id_is_wrong():
    _register_req_with_two_criteria()
    _register_req_with_two_criteria(req_id="REQ-OTHER-X-001", c1="c1-other", c2="c2-other")
    c1_pass = _rec(VerificationOutcome.PASS, requirement_id="REQ-CRIT-X-001", criterion_id="c1")
    # Same criterion_id string "c2" but genuinely belongs to a DIFFERENT requirement.
    wrong_requirement_c2 = _rec(VerificationOutcome.PASS, requirement_id="REQ-OTHER-X-001", criterion_id="c2")
    outcome, contributing = evaluate_requirement_completion(
        (c1_pass, wrong_requirement_c2), requirement_id="REQ-CRIT-X-001", current_revision="rev1", mission_id="m1",
    )
    assert outcome is VerificationOutcome.UNVERIFIED
    assert wrong_requirement_c2 not in contributing


def test_explicit_required_criterion_ids_override_takes_precedence():
    # No AcceptanceCriterion registered at all -- caller supplies an
    # explicit override instead, which must still be enforced strictly.
    c1_pass = _rec(VerificationOutcome.PASS, requirement_id="REQ-NO-REGISTRY", criterion_id="c1")
    outcome, _ = evaluate_requirement_completion(
        (c1_pass,), requirement_id="REQ-NO-REGISTRY", current_revision="rev1", mission_id="m1",
        required_criterion_ids=frozenset({"c1", "c2"}),
    )
    assert outcome is VerificationOutcome.UNVERIFIED


def test_no_registry_and_no_override_falls_back_to_legacy_whatever_exists():
    # A genuine requirement-level check pattern (criterion_id=None,
    # grouped by category) with no AcceptanceCriterion registered at
    # all must behave exactly as Phase 15.8's original aggregate_
    # requirement() -- not break just because this closure exists.
    category_only_pass = _rec(VerificationOutcome.PASS, requirement_id="REQ-LEGACY", criterion_id=None)
    outcome, contributing = evaluate_requirement_completion(
        (category_only_pass,), requirement_id="REQ-LEGACY", current_revision="rev1", mission_id="m1",
    )
    assert outcome is VerificationOutcome.PASS
    assert contributing == (category_only_pass,)
