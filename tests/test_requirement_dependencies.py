"""Phase 15.7 -- requirement dependency/conflict test matrix (spec section 21, 8-9)."""
from __future__ import annotations

import pytest

from orca.mission import requirements as requirements_module
from orca.mission.requirement_dependencies import (
    DependencyError,
    DependencyKind,
    add_dependency,
    detect_conflicts,
    dependencies_of,
    reset_registry_for_tests,
    unmet_blocking_dependencies,
)


def _req(id, statement="A thing must happen"):
    return requirements_module.register(requirements_module.Requirement(
        id=id, source_section="test", statement=statement, acceptance_criteria=("some criterion",),
    ))


@pytest.fixture(autouse=True)
def _clean():
    requirements_module.reset_registry_for_tests()
    reset_registry_for_tests()
    yield
    requirements_module.reset_registry_for_tests()
    reset_registry_for_tests()


def test_depends_on_edge_created():
    _req("REQ-A-X-001")
    _req("REQ-B-Y-001")
    add_dependency("REQ-A-X-001", DependencyKind.DEPENDS_ON, "REQ-B-Y-001")
    assert dependencies_of("REQ-A-X-001", DependencyKind.DEPENDS_ON)


def test_dependency_requires_registered_requirements():
    _req("REQ-A-X-001")
    with pytest.raises(DependencyError):
        add_dependency("REQ-A-X-001", DependencyKind.DEPENDS_ON, "REQ-GHOST-Y-001")


def test_self_dependency_rejected():
    _req("REQ-A-X-001")
    with pytest.raises(DependencyError):
        add_dependency("REQ-A-X-001", DependencyKind.DEPENDS_ON, "REQ-A-X-001")


def test_direct_cycle_rejected():
    _req("REQ-A-X-001")
    _req("REQ-B-Y-001")
    add_dependency("REQ-A-X-001", DependencyKind.DEPENDS_ON, "REQ-B-Y-001")
    with pytest.raises(DependencyError):
        add_dependency("REQ-B-Y-001", DependencyKind.DEPENDS_ON, "REQ-A-X-001")


def test_indirect_cycle_rejected():
    _req("REQ-A-X-001")
    _req("REQ-B-Y-001")
    _req("REQ-C-Z-001")
    add_dependency("REQ-A-X-001", DependencyKind.DEPENDS_ON, "REQ-B-Y-001")
    add_dependency("REQ-B-Y-001", DependencyKind.DEPENDS_ON, "REQ-C-Z-001")
    with pytest.raises(DependencyError):
        add_dependency("REQ-C-Z-001", DependencyKind.DEPENDS_ON, "REQ-A-X-001")


def test_idempotent_readd_does_not_error():
    _req("REQ-A-X-001")
    _req("REQ-B-Y-001")
    add_dependency("REQ-A-X-001", DependencyKind.DEPENDS_ON, "REQ-B-Y-001")
    add_dependency("REQ-A-X-001", DependencyKind.DEPENDS_ON, "REQ-B-Y-001")  # no error
    assert len(dependencies_of("REQ-A-X-001", DependencyKind.DEPENDS_ON)) == 1


def test_unmet_blocking_dependency_stays_visible():
    _req("REQ-A-X-001")
    _req("REQ-B-Y-001")
    add_dependency("REQ-A-X-001", DependencyKind.DEPENDS_ON, "REQ-B-Y-001")
    assert unmet_blocking_dependencies("REQ-A-X-001") == ("REQ-B-Y-001",)
    requirements_module.transition("REQ-B-Y-001", requirements_module.RequirementStatus.IMPLEMENTED,
                                    implementation_files=("f.py",))
    requirements_module.transition("REQ-B-Y-001", requirements_module.RequirementStatus.VERIFIED,
                                    test_files=("t.py",), evidence_ref="ev")
    assert unmet_blocking_dependencies("REQ-A-X-001") == ()


def test_conflict_detection_data_locality_vs_upload():
    _req("REQ-SEC-A-001", statement="All data must remain local to the device.")
    _req("REQ-INT-B-001", statement="Upload all data to a third-party analytics service.")
    conflicts = detect_conflicts(("REQ-SEC-A-001", "REQ-INT-B-001"))
    # This pair matches two contradiction phrases at once ("upload"
    # AND "third-party" both appear against "must remain local") --
    # both are genuine, independently-detected reasons, so >=1 is the
    # correct assertion, not exactly 1.
    assert len(conflicts) >= 1
    for c in conflicts:
        assert {c.requirement_a, c.requirement_b} == {"REQ-SEC-A-001", "REQ-INT-B-001"}


def test_no_conflict_for_unrelated_requirements():
    _req("REQ-A-X-001", statement="Users can create an account.")
    _req("REQ-B-Y-001", statement="The app supports dark mode.")
    assert detect_conflicts(("REQ-A-X-001", "REQ-B-Y-001")) == ()


def test_conflict_detection_never_auto_resolves():
    _req("REQ-SEC-A-001", statement="All data must remain local to the device.")
    _req("REQ-INT-B-001", statement="Upload all data to a third-party analytics service.")
    conflicts = detect_conflicts(("REQ-SEC-A-001", "REQ-INT-B-001"))
    # Both requirements remain exactly as registered -- no field was
    # mutated to "resolve" the conflict.
    assert requirements_module.get("REQ-SEC-A-001").statement == "All data must remain local to the device."
    assert requirements_module.get("REQ-INT-B-001").statement == "Upload all data to a third-party analytics service."
    assert len(conflicts) >= 1
