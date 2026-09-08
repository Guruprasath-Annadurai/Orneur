"""Phase 15.7 -- traceability report tests (spec section 13)."""
from __future__ import annotations

import pytest

from orca.mission import acceptance_criteria as ac_module
from orca.mission import requirements as requirements_module
from orca.mission.acceptance_criteria import CriterionStatus, VerificationMethod
from orca.mission.traceability import trace_requirement, trace_requirements


@pytest.fixture(autouse=True)
def _clean():
    requirements_module.reset_registry_for_tests()
    ac_module.reset_registry_for_tests()
    requirements_module.register(requirements_module.Requirement(
        id="REQ-TEST-TRACE-001", source_section="test", statement="A thing must happen",
        acceptance_criteria=("some criterion",),
    ))
    yield
    requirements_module.reset_registry_for_tests()
    ac_module.reset_registry_for_tests()


def test_missing_links_visible_for_fresh_requirement():
    row = trace_requirement("REQ-TEST-TRACE-001")
    assert row.status == "UNIMPLEMENTED"
    assert row.implementation_files == ()
    assert row.test_files == ()
    assert row.evidence_ref is None
    assert row.acceptance_criteria == ()
    assert row.has_missing_links is True


def test_fully_linked_requirement_has_no_missing_links():
    ac_module.register_criterion(criterion_id="c1", requirement_id="REQ-TEST-TRACE-001",
                                  description="criterion is measurable", verification_method=VerificationMethod.UNIT_TEST)
    ac_module.transition_criterion("c1", CriterionStatus.IMPLEMENTED)
    ac_module.transition_criterion("c1", CriterionStatus.VERIFIED, evidence_ref="ev1")
    requirements_module.transition("REQ-TEST-TRACE-001", requirements_module.RequirementStatus.IMPLEMENTED,
                                    implementation_files=("f.py",))
    requirements_module.transition("REQ-TEST-TRACE-001", requirements_module.RequirementStatus.VERIFIED,
                                    test_files=("t.py",), evidence_ref="ev2")
    row = trace_requirement("REQ-TEST-TRACE-001")
    assert row.has_missing_links is False


def test_partial_link_still_shows_missing():
    ac_module.register_criterion(criterion_id="c1", requirement_id="REQ-TEST-TRACE-001",
                                  description="criterion is measurable", verification_method=VerificationMethod.UNIT_TEST)
    # criterion never verified -- requirement stays unimplemented too
    row = trace_requirement("REQ-TEST-TRACE-001")
    assert row.has_missing_links is True
    assert len(row.acceptance_criteria) == 1


def test_trace_requirements_batch():
    requirements_module.register(requirements_module.Requirement(
        id="REQ-TEST-TRACE-002", source_section="test", statement="Another thing",
        acceptance_criteria=("x",),
    ))
    rows = trace_requirements(("REQ-TEST-TRACE-001", "REQ-TEST-TRACE-002"))
    assert len(rows) == 2
    assert {r.requirement_id for r in rows} == {"REQ-TEST-TRACE-001", "REQ-TEST-TRACE-002"}


def test_trace_missing_requirement_raises():
    from orca.mission.requirements import RequirementError
    with pytest.raises(RequirementError):
        trace_requirement("REQ-GHOST-X-001")
