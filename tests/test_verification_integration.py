"""Phase 15.8 -- stricter criterion-verification path tests."""
from __future__ import annotations

import pytest

from orca.mission import acceptance_criteria as ac_module
from orca.mission import requirements as requirements_module
from orca.mission.acceptance_criteria import CriterionStatus, VerificationMethod
from orca.mission.verification import VerificationOutcome, VerificationRecord
from orca.mission.verification_integration import (
    VerificationIntegrationError,
    verify_criterion_via_verification_record,
)


@pytest.fixture(autouse=True)
def _clean():
    requirements_module.reset_registry_for_tests()
    ac_module.reset_registry_for_tests()
    requirements_module.register(requirements_module.Requirement(
        id="REQ-TEST-VERIFY-001", source_section="test", statement="A thing must happen",
        acceptance_criteria=("some criterion",),
    ))
    ac_module.register_criterion(
        criterion_id="c1", requirement_id="REQ-TEST-VERIFY-001",
        description="A test observes the thing happening", verification_method=VerificationMethod.UNIT_TEST,
    )
    yield
    requirements_module.reset_registry_for_tests()
    ac_module.reset_registry_for_tests()


def _record(**overrides):
    defaults = dict(
        id="ver_1", mission_id="m1", requirement_id="REQ-TEST-VERIFY-001", criterion_id="c1",
        category="UNIT_TEST", verification_method="UNIT_TEST", verifier_id="UnitTestVerifier",
        started_at="2026-01-01T00:00:00Z", outcome=VerificationOutcome.PASS, revision="rev1",
        evidence_refs=("local:pytest",),
    )
    defaults.update(overrides)
    return VerificationRecord(**defaults)


def test_pass_record_verifies_criterion():
    updated = verify_criterion_via_verification_record("c1", _record())
    assert updated.status is CriterionStatus.VERIFIED
    assert updated.evidence_ref == "ver_1"


def test_non_pass_record_rejected():
    with pytest.raises(VerificationIntegrationError):
        verify_criterion_via_verification_record("c1", _record(outcome=VerificationOutcome.FAIL))


def test_record_scoped_to_different_criterion_rejected():
    ac_module.register_criterion(
        criterion_id="c2", requirement_id="REQ-TEST-VERIFY-001",
        description="A different observed criterion", verification_method=VerificationMethod.UNIT_TEST,
    )
    record_for_c2 = _record(criterion_id="c2")
    with pytest.raises(VerificationIntegrationError):
        verify_criterion_via_verification_record("c1", record_for_c2)


def test_record_with_mismatched_requirement_rejected():
    requirements_module.register(requirements_module.Requirement(
        id="REQ-TEST-OTHER-001", source_section="test", statement="A different thing",
        acceptance_criteria=("x",),
    ))
    record_wrong_req = _record(requirement_id="REQ-TEST-OTHER-001")
    with pytest.raises(VerificationIntegrationError):
        verify_criterion_via_verification_record("c1", record_wrong_req)


def test_string_evidence_ref_alone_is_not_this_path():
    # Confirms the OLD Phase 15.7 path still works unchanged (not
    # broken by this addition) -- a caller can still use
    # transition_criterion() directly with a bare string, but that is
    # explicitly the WEAKER path this module's docstring warns about.
    ac_module.transition_criterion("c1", CriterionStatus.IMPLEMENTED)
    updated = ac_module.transition_criterion("c1", CriterionStatus.VERIFIED, evidence_ref="trust me")
    assert updated.status is CriterionStatus.VERIFIED
    assert updated.evidence_ref == "trust me"  # legacy path -- Phase 15.7 behavior preserved verbatim
