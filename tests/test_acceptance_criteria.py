"""Phase 15.7 -- Acceptance Criteria test matrix (spec section 22)."""
from __future__ import annotations

import pytest

from orca.mission import requirements as requirements_module
from orca.mission.acceptance_criteria import (
    CriterionError,
    CriterionStatus,
    VerificationMethod,
    criteria_for_requirement,
    register_criterion,
    requirement_all_criteria_verified,
    reset_registry_for_tests,
    transition_criterion,
)


@pytest.fixture(autouse=True)
def _clean():
    requirements_module.reset_registry_for_tests()
    reset_registry_for_tests()
    requirements_module.register(requirements_module.Requirement(
        id="REQ-TEST-EXAMPLE-001", source_section="test", statement="A thing must happen",
        acceptance_criteria=("some criterion",),
    ))
    yield
    requirements_module.reset_registry_for_tests()
    reset_registry_for_tests()


def test_criterion_linked_to_requirement():
    c = register_criterion(criterion_id="c1", requirement_id="REQ-TEST-EXAMPLE-001",
                            description="A test places an order and confirms status 200",
                            verification_method=VerificationMethod.INTEGRATION_TEST)
    assert c.requirement_id == "REQ-TEST-EXAMPLE-001"
    assert c in criteria_for_requirement("REQ-TEST-EXAMPLE-001")


def test_orphan_criterion_rejected():
    with pytest.raises(CriterionError):
        register_criterion(criterion_id="c1", requirement_id="REQ-DOES-NOTEXIST-001",
                            description="x", verification_method=VerificationMethod.UNIT_TEST)


def test_vague_description_rejected():
    with pytest.raises(CriterionError):
        register_criterion(criterion_id="c1", requirement_id="REQ-TEST-EXAMPLE-001",
                            description="works well", verification_method=VerificationMethod.MANUAL_REVIEW)


def test_missing_evidence_does_not_equal_pass():
    c = register_criterion(criterion_id="c1", requirement_id="REQ-TEST-EXAMPLE-001",
                            description="Order total matches sum of line items",
                            verification_method=VerificationMethod.UNIT_TEST)
    assert c.status is CriterionStatus.PENDING
    assert c.evidence_ref is None


def test_implementation_only_does_not_equal_verified():
    register_criterion(criterion_id="c1", requirement_id="REQ-TEST-EXAMPLE-001",
                        description="Order total matches sum of line items",
                        verification_method=VerificationMethod.UNIT_TEST)
    implemented = transition_criterion("c1", CriterionStatus.IMPLEMENTED)
    assert implemented.status is CriterionStatus.IMPLEMENTED
    assert implemented.status is not CriterionStatus.VERIFIED


def test_verified_requires_evidence():
    register_criterion(criterion_id="c1", requirement_id="REQ-TEST-EXAMPLE-001",
                        description="Order total matches sum of line items",
                        verification_method=VerificationMethod.UNIT_TEST)
    transition_criterion("c1", CriterionStatus.IMPLEMENTED)
    with pytest.raises(CriterionError):
        transition_criterion("c1", CriterionStatus.VERIFIED)
    verified = transition_criterion("c1", CriterionStatus.VERIFIED, evidence_ref="tests/test_orders.py::test_total")
    assert verified.status is CriterionStatus.VERIFIED


def test_multiple_criteria_under_one_requirement():
    register_criterion(criterion_id="c1", requirement_id="REQ-TEST-EXAMPLE-001",
                        description="criterion one is measurable", verification_method=VerificationMethod.UNIT_TEST)
    register_criterion(criterion_id="c2", requirement_id="REQ-TEST-EXAMPLE-001",
                        description="criterion two is measurable", verification_method=VerificationMethod.E2E_TEST)
    assert len(criteria_for_requirement("REQ-TEST-EXAMPLE-001")) == 2


def test_failed_criterion_prevents_requirement_level_verified_claim():
    register_criterion(criterion_id="c1", requirement_id="REQ-TEST-EXAMPLE-001",
                        description="criterion one is measurable", verification_method=VerificationMethod.UNIT_TEST)
    register_criterion(criterion_id="c2", requirement_id="REQ-TEST-EXAMPLE-001",
                        description="criterion two is measurable", verification_method=VerificationMethod.UNIT_TEST)
    transition_criterion("c1", CriterionStatus.IMPLEMENTED)
    transition_criterion("c1", CriterionStatus.VERIFIED, evidence_ref="ev1")
    transition_criterion("c2", CriterionStatus.FAILED)
    assert requirement_all_criteria_verified("REQ-TEST-EXAMPLE-001") is False


def test_zero_criteria_is_not_vacuously_verified():
    assert requirement_all_criteria_verified("REQ-TEST-EXAMPLE-001") is False


def test_all_verified_criteria_yields_true():
    register_criterion(criterion_id="c1", requirement_id="REQ-TEST-EXAMPLE-001",
                        description="criterion one is measurable", verification_method=VerificationMethod.UNIT_TEST)
    transition_criterion("c1", CriterionStatus.IMPLEMENTED)
    transition_criterion("c1", CriterionStatus.VERIFIED, evidence_ref="ev1")
    assert requirement_all_criteria_verified("REQ-TEST-EXAMPLE-001") is True


def test_failed_can_retry_via_pending():
    register_criterion(criterion_id="c1", requirement_id="REQ-TEST-EXAMPLE-001",
                        description="criterion one is measurable", verification_method=VerificationMethod.UNIT_TEST)
    transition_criterion("c1", CriterionStatus.FAILED)
    retried = transition_criterion("c1", CriterionStatus.PENDING)
    assert retried.status is CriterionStatus.PENDING
