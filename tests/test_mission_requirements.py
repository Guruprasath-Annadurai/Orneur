"""
Phase 15.1 -- Requirement Compiler tests (orca/mission/requirements.py).

Proves the lifecycle enforcement is real, not just documented: a
requirement cannot reach IMPLEMENTED without an implementation
reference, cannot reach VERIFIED without both a test reference and an
evidence reference, and cannot skip states or move backward. Also
proves the Phase 15.1 seed data (orca/mission/requirements_seed.py)
is internally well-formed.
"""
from __future__ import annotations

import pytest

from orca.mission.requirements import (
    Requirement,
    RequirementError,
    RequirementStatus,
    all_requirements,
    get,
    register,
    reset_registry_for_tests,
    transition,
)


@pytest.fixture(autouse=True)
def _isolated_registry():
    reset_registry_for_tests()
    yield
    reset_registry_for_tests()


def _valid_req(req_id: str = "REQ-TEST-EXAMPLE-001") -> Requirement:
    return Requirement(
        id=req_id,
        source_section="test fixture",
        statement="Something must be true.",
        acceptance_criteria=("A test proves it.",),
    )


def test_valid_requirement_registers_and_defaults_unimplemented():
    req = register(_valid_req())
    assert req.status is RequirementStatus.UNIMPLEMENTED
    assert get("REQ-TEST-EXAMPLE-001") is req


def test_malformed_id_rejected():
    with pytest.raises(RequirementError):
        Requirement(id="not-a-valid-id", source_section="x", statement="x", acceptance_criteria=("x",))


def test_empty_statement_rejected():
    with pytest.raises(RequirementError):
        Requirement(id="REQ-TEST-EXAMPLE-002", source_section="x", statement="   ", acceptance_criteria=("x",))


def test_missing_acceptance_criteria_rejected():
    with pytest.raises(RequirementError):
        Requirement(id="REQ-TEST-EXAMPLE-003", source_section="x", statement="x", acceptance_criteria=())


def test_blank_acceptance_criterion_rejected():
    with pytest.raises(RequirementError):
        Requirement(id="REQ-TEST-EXAMPLE-004", source_section="x", statement="x", acceptance_criteria=("  ",))


def test_duplicate_id_rejected():
    register(_valid_req())
    with pytest.raises(RequirementError):
        register(_valid_req())


def test_unknown_id_lookup_raises():
    with pytest.raises(RequirementError):
        get("REQ-DOES-NOT-EXIST-999")


def test_cannot_reach_implemented_without_implementation_file():
    register(_valid_req())
    with pytest.raises(RequirementError):
        transition("REQ-TEST-EXAMPLE-001", RequirementStatus.IMPLEMENTED)


def test_implemented_requires_and_records_implementation_file():
    register(_valid_req())
    updated = transition(
        "REQ-TEST-EXAMPLE-001",
        RequirementStatus.IMPLEMENTED,
        implementation_files=("orca/mission/requirements.py",),
    )
    assert updated.status is RequirementStatus.IMPLEMENTED
    assert "orca/mission/requirements.py" in updated.implementation_files


def test_cannot_skip_unimplemented_straight_to_verified():
    register(_valid_req())
    with pytest.raises(RequirementError):
        transition(
            "REQ-TEST-EXAMPLE-001",
            RequirementStatus.VERIFIED,
            test_files=("tests/test_mission_requirements.py",),
            evidence_ref="some evidence",
        )


def test_verified_requires_test_file():
    register(_valid_req())
    transition("REQ-TEST-EXAMPLE-001", RequirementStatus.IMPLEMENTED, implementation_files=("f.py",))
    with pytest.raises(RequirementError):
        transition("REQ-TEST-EXAMPLE-001", RequirementStatus.VERIFIED, evidence_ref="some evidence")


def test_verified_requires_evidence_ref():
    register(_valid_req())
    transition("REQ-TEST-EXAMPLE-001", RequirementStatus.IMPLEMENTED, implementation_files=("f.py",))
    with pytest.raises(RequirementError):
        transition("REQ-TEST-EXAMPLE-001", RequirementStatus.VERIFIED, test_files=("t.py",))


def test_verified_succeeds_with_both_test_and_evidence():
    register(_valid_req())
    transition("REQ-TEST-EXAMPLE-001", RequirementStatus.IMPLEMENTED, implementation_files=("f.py",))
    updated = transition(
        "REQ-TEST-EXAMPLE-001",
        RequirementStatus.VERIFIED,
        test_files=("t.py",),
        evidence_ref="evidence doc section X",
    )
    assert updated.status is RequirementStatus.VERIFIED
    assert updated.evidence_ref == "evidence doc section X"


def test_verified_is_terminal_no_further_transitions():
    register(_valid_req())
    transition("REQ-TEST-EXAMPLE-001", RequirementStatus.IMPLEMENTED, implementation_files=("f.py",))
    transition("REQ-TEST-EXAMPLE-001", RequirementStatus.VERIFIED, test_files=("t.py",), evidence_ref="e")
    with pytest.raises(RequirementError):
        transition("REQ-TEST-EXAMPLE-001", RequirementStatus.IMPLEMENTED, implementation_files=("g.py",))


def test_cannot_reregister_same_id_after_transitions():
    """Requirement IDs are immutable history -- a re-specified
    requirement gets a new ID (e.g. -002), never overwrites -001."""
    register(_valid_req())
    transition("REQ-TEST-EXAMPLE-001", RequirementStatus.IMPLEMENTED, implementation_files=("f.py",))
    with pytest.raises(RequirementError):
        register(_valid_req())


class TestSeedRegistry:
    """Validates the actual Phase 15.1 requirement seed data is
    internally well-formed -- every entry passes the same real
    validation every other requirement does, no special-casing."""

    @pytest.fixture(autouse=True)
    def _seed(self):
        from orca.mission import requirements_seed
        requirements_seed._SEEDED = False  # force a fresh seed into this test's isolated registry
        requirements_seed.seed_registry()
        yield

    def test_seed_registers_multiple_requirements(self):
        reqs = all_requirements()
        assert len(reqs) >= 15, "expected a real, substantive Phase 15.1 requirement compilation"

    def test_seed_has_no_duplicate_ids(self):
        ids = [r.id for r in all_requirements()]
        assert len(ids) == len(set(ids))

    def test_seed_covers_multiple_spec_areas(self):
        areas = {r.id.split("-")[1] for r in all_requirements()}
        # at minimum: mission engine, window, autonomy, state, checkpoint,
        # operation idempotency, sandbox, authority, anti-gaming, no-fake,
        # production proof, relay, device trust, reconnect truthfulness
        assert len(areas) >= 10, f"expected broad spec coverage, got areas: {sorted(areas)}"

    def test_seed_neon_requirement_reflects_real_phase_15_0_evidence(self):
        # Phase 15.15's final requirement-registry audit inspected the
        # actual connection-routing code (orca/mission/db.py) and closed
        # this requirement's remaining two acceptance criteria with real
        # tests (see PHASE15_EVIDENCE.md's Phase 15.15 section) -- it is
        # no longer merely IMPLEMENTED.
        req = get("REQ-STATE-NEON-002")
        assert req.status is RequirementStatus.VERIFIED
        assert req.implementation_files  # non-empty -- points at the real evidence checkpoint
        assert req.test_files
        assert req.evidence_ref
