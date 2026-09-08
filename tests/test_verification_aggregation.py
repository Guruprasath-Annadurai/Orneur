"""Phase 15.8 -- aggregation, stale detection, check-ordering tests."""
from __future__ import annotations

import pytest

from orca.mission.verification import VerificationOutcome, VerificationRecord
from orca.mission.verification_aggregation import (
    CheckOrderingEdge,
    CheckOrderingError,
    aggregate_outcomes,
    aggregate_requirement,
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
