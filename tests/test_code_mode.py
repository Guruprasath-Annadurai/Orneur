"""Phase 15.6 -- CodeMode capability policy, Prototype Debt, Launch gate."""
from __future__ import annotations

import pytest

from orca.mission.code_mode import (
    CapabilityAction,
    CodeMode,
    DebtResolutionStatus,
    DebtSeverity,
    LaunchCheckResult,
    PrototypeDebtError,
    blocking_debt_for_mission,
    evaluate_launch_gate,
    is_allowed_by_mode,
    launch_gate_passes,
    record_debt,
    requires_authority,
    reset_registry_for_tests,
    resolve_debt,
)


@pytest.fixture(autouse=True)
def _clean_registry():
    reset_registry_for_tests()
    yield
    reset_registry_for_tests()


# ── Mode capability policy ──────────────────────────────────────────

def test_assist_permits_read_and_tests_only():
    assert is_allowed_by_mode(CodeMode.ASSIST, CapabilityAction.READ_FILES)
    assert is_allowed_by_mode(CodeMode.ASSIST, CapabilityAction.RUN_TESTS)
    assert not is_allowed_by_mode(CodeMode.ASSIST, CapabilityAction.WRITE_FILES)
    assert not is_allowed_by_mode(CodeMode.ASSIST, CapabilityAction.DEPLOY)


def test_assist_does_not_permit_broad_autonomous_work():
    # ASSIST must not silently escalate into repository-wide execution.
    for action in (CapabilityAction.DELETE_FILES, CapabilityAction.DEPLOY,
                   CapabilityAction.PUBLISH, CapabilityAction.PERFORM_MIGRATIONS,
                   CapabilityAction.MODIFY_PRODUCTION_RESOURCES):
        assert not is_allowed_by_mode(CodeMode.ASSIST, action)


def test_prototype_permits_rapid_iteration_but_not_deploy():
    assert is_allowed_by_mode(CodeMode.PROTOTYPE, CapabilityAction.WRITE_FILES)
    assert is_allowed_by_mode(CodeMode.PROTOTYPE, CapabilityAction.RUN_ARBITRARY_COMMANDS)
    assert not is_allowed_by_mode(CodeMode.PROTOTYPE, CapabilityAction.DEPLOY)
    assert not is_allowed_by_mode(CodeMode.PROTOTYPE, CapabilityAction.PUBLISH)


def test_only_launch_permits_deploy_and_publish():
    assert is_allowed_by_mode(CodeMode.LAUNCH, CapabilityAction.DEPLOY)
    assert is_allowed_by_mode(CodeMode.LAUNCH, CapabilityAction.PUBLISH)
    for mode in (CodeMode.ASSIST, CodeMode.PROTOTYPE, CodeMode.BUILD):
        assert not is_allowed_by_mode(mode, CapabilityAction.PUBLISH)


def test_mode_never_bypasses_privileged_authority_requirement():
    # Mode permitting an attempt is not the same as the action being
    # unprivileged -- LAUNCH permits DEPLOY, but DEPLOY still requires
    # real Phase 15.5 authority.
    assert is_allowed_by_mode(CodeMode.LAUNCH, CapabilityAction.DEPLOY)
    assert requires_authority(CapabilityAction.DEPLOY)
    assert requires_authority(CapabilityAction.PERFORM_MIGRATIONS)
    assert requires_authority(CapabilityAction.ACCESS_SECRETS)
    assert not requires_authority(CapabilityAction.READ_FILES)


# ── Prototype Debt ──────────────────────────────────────────────────

def test_debt_requires_nonempty_description_and_reason():
    with pytest.raises(PrototypeDebtError):
        record_debt(id="d1", mission_id="m1", category="persistence", description="", reason="x")
    with pytest.raises(PrototypeDebtError):
        record_debt(id="d1", mission_id="m1", category="persistence", description="x", reason="")


def test_prototype_debt_survives_and_is_queryable():
    record_debt(
        id="d1", mission_id="m1", category="persistence",
        description="uses an in-memory dict instead of a real store",
        reason="fast product validation", severity=DebtSeverity.HIGH,
    )
    debts = blocking_debt_for_mission("m1", target_mode=CodeMode.LAUNCH)
    assert len(debts) == 1
    assert debts[0].id == "d1"


def test_prototype_success_is_not_production_readiness():
    # A PROTOTYPE mission running successfully must not itself satisfy
    # LAUNCH's evidence gate -- running != launch-ready.
    record_debt(id="d1", mission_id="m1", category="persistence",
                description="placeholder integration", reason="speed")
    results = evaluate_launch_gate({"build_evidence": True, "tests": True})
    assert not launch_gate_passes(results)  # most categories still UNVERIFIED


def test_blocking_debt_surfaces_before_launch_and_is_never_silently_erased():
    record_debt(id="d1", mission_id="m1", category="error_handling",
                description="reduced error handling", reason="prototype speed",
                blocking_for_build=False, blocking_for_launch=True)
    # Not blocking for BUILD...
    assert blocking_debt_for_mission("m1", target_mode=CodeMode.BUILD) == []
    # ...but blocks LAUNCH until resolved.
    assert len(blocking_debt_for_mission("m1", target_mode=CodeMode.LAUNCH)) == 1
    resolve_debt("d1", status=DebtResolutionStatus.RESOLVED)
    assert blocking_debt_for_mission("m1", target_mode=CodeMode.LAUNCH) == []
    # The record itself is never deleted -- only its status changes.
    from orca.mission.code_mode import debt_for_mission
    assert debt_for_mission("m1")[0].resolution_status == DebtResolutionStatus.RESOLVED


def test_resolve_debt_cannot_reopen():
    record_debt(id="d1", mission_id="m1", category="x", description="x", reason="x")
    with pytest.raises(PrototypeDebtError):
        resolve_debt("d1", status=DebtResolutionStatus.OPEN)


# ── Launch gate ──────────────────────────────────────────────────────

def test_missing_evidence_is_unverified_never_pass():
    results = evaluate_launch_gate({})
    assert all(r is LaunchCheckResult.UNVERIFIED for r in results.values())
    assert not launch_gate_passes(results)


def test_explicit_fail_is_fail_not_unverified():
    results = evaluate_launch_gate({"tests": False})
    assert results["tests"] is LaunchCheckResult.FAIL


def test_not_applicable_categories_do_not_block():
    from orca.mission.code_mode import REQUIRED_LAUNCH_CATEGORIES
    evidence = {c: True for c in REQUIRED_LAUNCH_CATEGORIES if c != "supply_chain"}
    results = evaluate_launch_gate(evidence, not_applicable=frozenset({"supply_chain"}))
    assert results["supply_chain"] is LaunchCheckResult.NOT_APPLICABLE
    assert launch_gate_passes(results)


def test_full_pass_requires_every_category():
    from orca.mission.code_mode import REQUIRED_LAUNCH_CATEGORIES
    evidence = {c: True for c in REQUIRED_LAUNCH_CATEGORIES}
    results = evaluate_launch_gate(evidence)
    assert launch_gate_passes(results)
    evidence["security"] = None  # simulate one category never actually gathered
    results2 = evaluate_launch_gate(evidence)
    assert not launch_gate_passes(results2)
