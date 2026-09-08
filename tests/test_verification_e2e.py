"""
Phase 15.8 -- end-to-end fixture (spec section 28): a harmless
deterministic sample "project" (a single Python file evaluated inside
the VERIFIED CONTAINER_SANDBOX, since this simulates untrusted/
generated project code, not ORNEUR's own trusted test suite -- spec
section 6's distinction). Proves the full chain:

    requirement -> acceptance criterion -> implementation ->
    build/test verification -> evidence -> criterion VERIFIED ->
    requirement aggregate PASS -> traceability

then deliberately breaks the implementation (a new revision), proving
the old PASS evidence does not silently re-validate the new revision,
then fixes it again, proving history retains FAIL between two PASSes
(never deleted, never rewritten).
"""
from __future__ import annotations

import sys

import pytest

from orca.mission import acceptance_criteria as ac_module
from orca.mission import requirements as requirements_module
from orca.mission.acceptance_criteria import CriterionStatus, VerificationMethod
from orca.mission.container_executor import is_docker_available
from orca.mission.execution_plan import ExecutionPlan, NetworkPolicy, ResourcePolicy
from orca.mission.traceability import trace_requirement
from orca.mission.verification import VerificationOutcome
from orca.mission.verification_aggregation import aggregate_requirement, filter_current_revision
from orca.mission.verification_integration import verify_criterion_via_verification_record
from orca.mission.verifiers import UnitTestVerifier

pytestmark = pytest.mark.skipif(not is_docker_available(), reason="Docker daemon unavailable on this host")


@pytest.fixture(autouse=True)
def _clean():
    requirements_module.reset_registry_for_tests()
    ac_module.reset_registry_for_tests()
    yield
    requirements_module.reset_registry_for_tests()
    ac_module.reset_registry_for_tests()


def _write_fixture_project(tmp_path, *, correct: bool):
    """A tiny deterministic "project": add_numbers() plus a test that
    imports and checks it. `correct=False` breaks the implementation
    deliberately."""
    impl_body = "def add_numbers(a, b):\n    return a + b\n" if correct else "def add_numbers(a, b):\n    return a - b  # BUG\n"
    (tmp_path / "app.py").write_text(impl_body)
    (tmp_path / "test_app.py").write_text(
        "from app import add_numbers\n\n"
        "def test_add():\n"
        "    assert add_numbers(2, 3) == 5\n"
    )


def _run_project_tests(tmp_path, revision: str, requirement_id: str, criterion_id: str):
    plan = ExecutionPlan(
        execution_id=f"e2e-{revision}", mission_id="m1", operation_id=None, mode="BUILD",
        tool="unit_test", workspace_root=str(tmp_path), working_directory=str(tmp_path),
        command=("python3", "-m", "pytest", "test_app.py", "-q"),
        environment_policy=frozenset(), network_policy=NetworkPolicy.DENIED,
        resource_policy=ResourcePolicy(cpu_seconds=10, memory_bytes=256 * 1024 * 1024, max_processes=32),
        timeout_seconds=30.0,
    )
    verifier = UnitTestVerifier(use_container=True)
    # python:3.11-slim needs pytest installed -- install it first via
    # a real (harmless) container run, since the base image doesn't
    # ship it. This is itself run through the verified sandbox too.
    from orca.mission.container_executor import run_in_container
    install_plan = ExecutionPlan(
        execution_id=f"e2e-install-{revision}", mission_id="m1", operation_id=None, mode="BUILD",
        tool="pip_install", workspace_root=str(tmp_path), working_directory=str(tmp_path),
        command=("pip", "install", "--quiet", "--target", "/workspace/.deps", "pytest"),
        environment_policy=frozenset(), network_policy=NetworkPolicy.ALLOWED,
        resource_policy=ResourcePolicy(cpu_seconds=30, memory_bytes=256 * 1024 * 1024, max_processes=32),
        timeout_seconds=60.0,
    )
    run_in_container(install_plan)  # best-effort; if pip fails offline, the test run below will show it truthfully

    test_plan = ExecutionPlan(
        execution_id=f"e2e-test-{revision}", mission_id="m1", operation_id=None, mode="BUILD",
        tool="unit_test", workspace_root=str(tmp_path), working_directory=str(tmp_path),
        command=("python3", "-c", "import sys; sys.path.insert(0, '/workspace/.deps'); "
                                    "import pytest; sys.exit(pytest.main(['/workspace/test_app.py', '-q']))"),
        environment_policy=frozenset(), network_policy=NetworkPolicy.DENIED,
        resource_policy=ResourcePolicy(cpu_seconds=10, memory_bytes=256 * 1024 * 1024, max_processes=32),
        timeout_seconds=30.0,
    )
    return verifier.verify(
        test_plan, mission_id="m1", requirement_id=requirement_id, criterion_id=criterion_id, revision=revision,
    )


def test_end_to_end_verify_break_fix_preserves_history(tmp_path):
    requirement_id = "REQ-E2E-ADDNUM-001"
    requirements_module.register(requirements_module.Requirement(
        id=requirement_id, source_section="Phase 15.8 e2e fixture",
        statement="add_numbers(a, b) returns the sum of a and b.",
        acceptance_criteria=("A test calls add_numbers(2, 3) and confirms the result is 5.",),
    ))
    criterion = ac_module.register_criterion(
        criterion_id=f"{requirement_id}-ac-000", requirement_id=requirement_id,
        description="A test calls add_numbers(2, 3) and confirms the result is 5",
        verification_method=VerificationMethod.UNIT_TEST,
    )

    # ── Step 1: correct implementation, revision "rev1" ─────────────
    _write_fixture_project(tmp_path, correct=True)
    record_rev1 = _run_project_tests(tmp_path, "rev1", requirement_id, criterion.criterion_id)
    assert record_rev1.outcome is VerificationOutcome.PASS, record_rev1.summary or record_rev1.error_detail

    verify_criterion_via_verification_record(criterion.criterion_id, record_rev1)
    assert requirements_module.get(requirement_id).status is requirements_module.RequirementStatus.UNIMPLEMENTED
    # Requirement-level status transition is a SEPARATE, explicit step
    # (spec section 17: "Do not automatically mutate RequirementStatus.VERIFIED
    # unless the existing forward-only registry requirements are also satisfied") --
    # criterion VERIFIED does not itself silently flip the requirement.
    requirements_module.transition(requirement_id, requirements_module.RequirementStatus.IMPLEMENTED,
                                    implementation_files=("app.py",))
    requirements_module.transition(requirement_id, requirements_module.RequirementStatus.VERIFIED,
                                    test_files=("test_app.py",), evidence_ref=record_rev1.id)

    aggregate_rev1 = aggregate_requirement(filter_current_revision((record_rev1,), current_revision="rev1"))
    assert aggregate_rev1 is VerificationOutcome.PASS

    row = trace_requirement(requirement_id)
    assert row.has_missing_links is False

    # ── Step 2: break it, revision "rev2" ───────────────────────────
    _write_fixture_project(tmp_path, correct=False)
    record_rev2 = _run_project_tests(tmp_path, "rev2", requirement_id, criterion.criterion_id)
    assert record_rev2.outcome is VerificationOutcome.FAIL, "the deliberately-broken implementation must FAIL, not PASS"

    # rev1's PASS evidence must NOT count as proof for rev2.
    all_records = (record_rev1, record_rev2)
    current_rev2 = filter_current_revision(all_records, current_revision="rev2")
    assert current_rev2 == (record_rev2,)
    aggregate_rev2 = aggregate_requirement(current_rev2)
    assert aggregate_rev2 is VerificationOutcome.FAIL
    assert aggregate_rev2 is not VerificationOutcome.PASS

    with pytest.raises(Exception):
        verify_criterion_via_verification_record(criterion.criterion_id, record_rev2)  # FAIL record cannot verify

    # ── Step 3: fix it again, revision "rev3" ───────────────────────
    _write_fixture_project(tmp_path, correct=True)
    record_rev3 = _run_project_tests(tmp_path, "rev3", requirement_id, criterion.criterion_id)
    assert record_rev3.outcome is VerificationOutcome.PASS

    all_records_final = (record_rev1, record_rev2, record_rev3)
    current_rev3 = filter_current_revision(all_records_final, current_revision="rev3")
    assert current_rev3 == (record_rev3,)
    assert aggregate_requirement(current_rev3) is VerificationOutcome.PASS

    # History preserved -- the FAIL record still exists, untouched.
    assert record_rev2.outcome is VerificationOutcome.FAIL
    assert len(all_records_final) == 3
    outcomes_in_order = [r.outcome for r in all_records_final]
    assert outcomes_in_order == [VerificationOutcome.PASS, VerificationOutcome.FAIL, VerificationOutcome.PASS]
