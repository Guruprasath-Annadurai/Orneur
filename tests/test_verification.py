"""Phase 15.8 -- VerificationRecord/VerificationPlan core invariants."""
from __future__ import annotations

import pytest

from orca.mission.verification import (
    RequiredCheck,
    VerificationError,
    VerificationOutcome,
    VerificationPlan,
    VerificationRecord,
)


def _record(**overrides):
    defaults = dict(
        id="ver_1", mission_id="m1", requirement_id="REQ-X-Y-001", criterion_id=None,
        category="UNIT_TEST", verification_method="UNIT_TEST", verifier_id="TestVerifier",
        started_at="2026-01-01T00:00:00Z", outcome=VerificationOutcome.PASS, revision="rev1",
        evidence_refs=("some_command",),
    )
    defaults.update(overrides)
    return VerificationRecord(**defaults)


def test_not_applicable_requires_reason():
    with pytest.raises(VerificationError):
        _record(outcome=VerificationOutcome.NOT_APPLICABLE, evidence_refs=())


def test_not_applicable_with_reason_ok():
    r = _record(outcome=VerificationOutcome.NOT_APPLICABLE, not_applicable_reason="no UI in scope", evidence_refs=())
    assert r.outcome is VerificationOutcome.NOT_APPLICABLE


def test_error_requires_detail():
    with pytest.raises(VerificationError):
        _record(outcome=VerificationOutcome.ERROR, evidence_refs=())


def test_pass_requires_evidence_or_command_reference():
    with pytest.raises(VerificationError):
        _record(outcome=VerificationOutcome.PASS, evidence_refs=(), command_reference=None)
    ok = _record(outcome=VerificationOutcome.PASS, evidence_refs=(), command_reference="local:pytest")
    assert ok.outcome is VerificationOutcome.PASS


def test_fail_does_not_require_evidence():
    r = _record(outcome=VerificationOutcome.FAIL, evidence_refs=())
    assert r.outcome is VerificationOutcome.FAIL


def test_plan_requires_at_least_one_check():
    with pytest.raises(VerificationError):
        VerificationPlan(plan_id="p1", mission_id="m1", requirement_ids=("REQ-X-Y-001",), revision="rev1", checks=())


def test_plan_required_checks_property():
    plan = VerificationPlan(
        plan_id="p1", mission_id="m1", requirement_ids=("REQ-X-Y-001",), revision="rev1",
        checks=(
            RequiredCheck(category="BUILD", verification_method="BUILD_VERIFICATION", required=True),
            RequiredCheck(category="PERFORMANCE", verification_method="PERFORMANCE_TEST", required=False),
        ),
    )
    assert len(plan.required_checks) == 1
    assert plan.required_checks[0].category == "BUILD"
