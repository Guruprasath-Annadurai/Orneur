"""
Phase 15.8 -- concrete verifier tests, including failure injection
(spec section 29): none of these scenarios may produce PASS.
"""
from __future__ import annotations

import sys

import pytest

from orca.mission.execution_plan import ExecutionPlan, NetworkPolicy, ResourcePolicy
from orca.mission.verification import VerificationOutcome
from orca.mission.verifiers import (
    AccessibilityVerifier,
    BuildVerifier,
    ExternalConfirmationVerifier,
    ManualReviewVerifier,
    PerformanceVerifier,
    StaticAnalysisVerifier,
    UnitTestVerifier,
    parse_pytest_output,
)


def _plan(tmp_path, command, **overrides) -> ExecutionPlan:
    defaults = dict(
        execution_id="e1", mission_id="m1", operation_id=None, mode="BUILD",
        tool="verifier", workspace_root=str(tmp_path), working_directory=str(tmp_path),
        command=tuple(command), environment_policy=frozenset(),
        network_policy=NetworkPolicy.DENIED,
        resource_policy=ResourcePolicy(cpu_seconds=5, memory_bytes=128 * 1024 * 1024, max_processes=None),
        timeout_seconds=10.0,
    )
    defaults.update(overrides)
    return ExecutionPlan(**defaults)


# ── BuildVerifier ────────────────────────────────────────────────────

def test_build_success_yields_pass(tmp_path):
    bv = BuildVerifier(use_container=False)
    rec = bv.verify(_plan(tmp_path, [sys.executable, "-c", "print('built')"]),
                     mission_id="m1", requirement_id="REQ-X-Y-001", criterion_id=None, revision="rev1")
    assert rec.outcome is VerificationOutcome.PASS


def test_build_failure_yields_fail(tmp_path):
    bv = BuildVerifier(use_container=False)
    rec = bv.verify(_plan(tmp_path, [sys.executable, "-c", "import sys; sys.exit(1)"]),
                     mission_id="m1", requirement_id="REQ-X-Y-001", criterion_id=None, revision="rev1")
    assert rec.outcome is VerificationOutcome.FAIL
    assert rec.outcome is not VerificationOutcome.PASS


def test_build_timeout_never_pass(tmp_path):
    bv = BuildVerifier(use_container=False)
    rec = bv.verify(_plan(tmp_path, [sys.executable, "-c", "import time; time.sleep(30)"], timeout_seconds=0.5),
                     mission_id="m1", requirement_id="REQ-X-Y-001", criterion_id=None, revision="rev1")
    assert rec.outcome is VerificationOutcome.TIMED_OUT
    assert rec.outcome is not VerificationOutcome.PASS


def test_verifier_command_missing_never_yields_pass(tmp_path):
    # orca.mission.sandbox_executor.run_command() (Phase 15.6,
    # unmodified) reports a failed-to-start process as FAILED --
    # which maps to VerificationOutcome.FAIL here. Either FAIL or
    # ERROR is a defensible classification for "the command could not
    # even start"; the one invariant that actually matters is that it
    # is never PASS.
    bv = BuildVerifier(use_container=False)
    rec = bv.verify(_plan(tmp_path, ["/nonexistent/command/xyz"]),
                     mission_id="m1", requirement_id="REQ-X-Y-001", criterion_id=None, revision="rev1")
    assert rec.outcome in (VerificationOutcome.FAIL, VerificationOutcome.ERROR)
    assert rec.outcome is not VerificationOutcome.PASS


# ── UnitTestVerifier / pytest output parsing ────────────────────────────

def test_pytest_summary_parsing_basic():
    r = parse_pytest_output("3 passed, 1 skipped in 0.12s\ncollected 4 items", "")
    assert r.passed == 3 and r.skipped == 1 and r.collected == 4


def test_pytest_summary_parsing_failures():
    r = parse_pytest_output("2 failed, 1 error in 0.5s", "")
    assert r.failed == 2 and r.errors == 1


def test_pytest_summary_unparseable_stays_none():
    r = parse_pytest_output("some totally unrelated output", "")
    assert r.passed is None and r.failed is None and r.collected is None


def test_unit_test_pass(tmp_path):
    tv = UnitTestVerifier(use_container=False)
    script = "print('collected 1 items')\nprint('1 passed in 0.01s')"
    rec = tv.verify(_plan(tmp_path, [sys.executable, "-c", script]),
                     mission_id="m1", requirement_id="REQ-X-Y-001", criterion_id="c1", revision="rev1")
    assert rec.outcome is VerificationOutcome.PASS


def test_unit_test_zero_collected_is_unverified_not_pass(tmp_path):
    tv = UnitTestVerifier(use_container=False)
    script = "print('collected 0 items')\nprint('no tests ran in 0.01s')"
    rec = tv.verify(_plan(tmp_path, [sys.executable, "-c", script]),
                     mission_id="m1", requirement_id="REQ-X-Y-001", criterion_id="c1", revision="rev1")
    assert rec.outcome is VerificationOutcome.UNVERIFIED
    assert rec.outcome is not VerificationOutcome.PASS


def test_unit_test_nonzero_exit_with_failures_is_fail(tmp_path):
    tv = UnitTestVerifier(use_container=False)
    script = "print('collected 2 items')\nprint('1 passed, 1 failed in 0.01s')\nimport sys; sys.exit(1)"
    rec = tv.verify(_plan(tmp_path, [sys.executable, "-c", script]),
                     mission_id="m1", requirement_id="REQ-X-Y-001", criterion_id="c1", revision="rev1")
    assert rec.outcome is VerificationOutcome.FAIL


def test_unit_test_unparseable_output_is_unverified_not_pass(tmp_path):
    tv = UnitTestVerifier(use_container=False)
    rec = tv.verify(_plan(tmp_path, [sys.executable, "-c", "print('nothing recognizable here')"]),
                     mission_id="m1", requirement_id="REQ-X-Y-001", criterion_id="c1", revision="rev1")
    assert rec.outcome is VerificationOutcome.UNVERIFIED
    assert rec.outcome is not VerificationOutcome.PASS


def test_unit_test_cancellation_never_pass(tmp_path):
    from orca.godmode.cancellation import CancellationSignal

    class _AlwaysCancelled:
        def is_cancelled(self) -> bool:
            return True

    tv = UnitTestVerifier(use_container=False)
    # run_command signature takes cancellation via run_command(plan, cancellation=...) --
    # UnitTestVerifier._run() doesn't expose it directly, so this test
    # exercises the underlying sandbox_executor path instead, matching
    # the disclosed integration boundary (see module docstring).
    from orca.mission.sandbox_executor import run_command
    result = run_command(_plan(tmp_path, [sys.executable, "-c", "import time; time.sleep(30)"], timeout_seconds=10.0),
                          cancellation=_AlwaysCancelled())
    assert result.status.value == "CANCELLED"
    assert result.status.value != "SUCCEEDED"


# ── Interface-only verifiers: UNVERIFIED by default, never self-PASS ─

def test_static_analysis_unavailable_tool_is_unverified():
    v = StaticAnalysisVerifier()
    rec = v.verify(mission_id="m1", requirement_id="REQ-X-Y-001", criterion_id=None, revision="rev1", tool_available=False)
    assert rec.outcome is VerificationOutcome.UNVERIFIED


def test_static_analysis_real_result_required_for_pass():
    v = StaticAnalysisVerifier()
    rec = v.verify(mission_id="m1", requirement_id="REQ-X-Y-001", criterion_id=None, revision="rev1",
                    tool_available=True, tool_name="ruff", passed=True, summary="0 issues")
    assert rec.outcome is VerificationOutcome.PASS
    rec2 = v.verify(mission_id="m1", requirement_id="REQ-X-Y-001", criterion_id=None, revision="rev1",
                     tool_available=True)
    assert rec2.outcome is VerificationOutcome.UNVERIFIED


def test_performance_no_measurement_is_unverified_not_pass():
    v = PerformanceVerifier()
    rec = v.verify(mission_id="m1", requirement_id="REQ-X-Y-001", criterion_id=None, revision="rev1")
    assert rec.outcome is VerificationOutcome.UNVERIFIED


def test_performance_real_measurement_evaluated_against_threshold():
    v = PerformanceVerifier()
    rec = v.verify(mission_id="m1", requirement_id="REQ-X-Y-001", criterion_id=None, revision="rev1",
                    metric="p95_latency_ms", threshold=200, measured_value=150, environment="staging")
    assert rec.outcome is VerificationOutcome.PASS
    rec2 = v.verify(mission_id="m1", requirement_id="REQ-X-Y-001", criterion_id=None, revision="rev1",
                     metric="p95_latency_ms", threshold=200, measured_value=350, environment="staging")
    assert rec2.outcome is VerificationOutcome.FAIL


def test_accessibility_no_ui_is_not_applicable_with_reason():
    v = AccessibilityVerifier()
    rec = v.verify(mission_id="m1", requirement_id="REQ-X-Y-001", criterion_id=None, revision="rev1", has_ui=False)
    assert rec.outcome is VerificationOutcome.NOT_APPLICABLE
    assert rec.not_applicable_reason


def test_accessibility_ui_exists_but_unchecked_is_unverified_not_pass():
    v = AccessibilityVerifier()
    rec = v.verify(mission_id="m1", requirement_id="REQ-X-Y-001", criterion_id=None, revision="rev1", has_ui=True)
    assert rec.outcome is VerificationOutcome.UNVERIFIED


def test_manual_review_no_reviewer_is_unverified_not_pass():
    v = ManualReviewVerifier()
    rec = v.verify(mission_id="m1", requirement_id="REQ-X-Y-001", criterion_id=None, revision="rev1")
    assert rec.outcome is VerificationOutcome.UNVERIFIED


def test_manual_review_real_reviewer_and_evidence_required_for_pass():
    v = ManualReviewVerifier()
    rec = v.verify(mission_id="m1", requirement_id="REQ-X-Y-001", criterion_id=None, revision="rev1",
                    reviewer="user_bob", passed=True, evidence_ref="review-doc-123")
    assert rec.outcome is VerificationOutcome.PASS


def test_external_confirmation_absent_is_unverified_not_pass():
    v = ExternalConfirmationVerifier()
    rec = v.verify(mission_id="m1", requirement_id="REQ-X-Y-001", criterion_id=None, revision="rev1")
    assert rec.outcome is VerificationOutcome.UNVERIFIED


def test_external_confirmation_with_real_ref_is_pass():
    v = ExternalConfirmationVerifier()
    rec = v.verify(mission_id="m1", requirement_id="REQ-X-Y-001", criterion_id=None, revision="rev1",
                    confirmation_ref="app-store-listing-url")
    assert rec.outcome is VerificationOutcome.PASS
