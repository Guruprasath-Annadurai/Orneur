"""
Phase 15.8 -- concrete Verifier implementations (spec sections 5-15).

Command-based verifiers (BuildVerifier, UnitTestVerifier) execute through
Phase 15.6/15.6.1's governed execution paths -- never a bare, ungoverned
`subprocess.run()`. For UNTRUSTED/generated project code (the
end-to-end fixture, spec section 28), the VERIFIED `CONTAINER_SANDBOX`
path is used, never a silent fallback to `LOCAL_SUBPROCESS`. For
ORNEUR's OWN trusted test suites (SecurityVerifier, AuthorityVerifier
running this repository's own pytest files), `LOCAL_SUBPROCESS` is
used deliberately and disclosed -- this is trusted first-party test
execution, not arbitrary/generated code, which is the exact
distinction spec section 6 draws ("For untrusted/generated project
commands, prefer CONTAINER_SANDBOX").

Interface-only verifiers (StaticAnalysisVerifier, PerformanceVerifier,
AccessibilityVerifier, ManualReviewVerifier, ExternalConfirmationVerifier)
produce UNVERIFIED unless the caller supplies a real, external
observation -- none of them can self-declare PASS from confidence
(spec section 27: "A model cannot fabricate either").
"""
from __future__ import annotations

import re
import uuid
from dataclasses import dataclass
from datetime import datetime, timezone

from orca.mission.container_executor import run_in_container
from orca.mission.execution_plan import ExecutionPlan
from orca.mission.sandbox_executor import ExecutionOutcome, run_command
from orca.mission.verification import VerificationOutcome, VerificationRecord

VERIFIER_VERSION = "15.8.0"


def _now_iso() -> str:
    return datetime.now(timezone.utc).isoformat()


def _vid() -> str:
    return f"ver_{uuid.uuid4().hex[:16]}"


_EXEC_OUTCOME_TO_VERIFICATION_OUTCOME: dict[ExecutionOutcome, VerificationOutcome] = {
    ExecutionOutcome.SUCCEEDED: VerificationOutcome.PASS,
    ExecutionOutcome.FAILED: VerificationOutcome.FAIL,
    ExecutionOutcome.TIMED_OUT: VerificationOutcome.TIMED_OUT,
    ExecutionOutcome.CANCELLED: VerificationOutcome.CANCELLED,
    ExecutionOutcome.SANDBOX_UNAVAILABLE: VerificationOutcome.ERROR,
}


@dataclass
class CommandVerifier:
    """Shared execution logic for BuildVerifier/UnitTestVerifier. `use_container`
    selects the execution path explicitly -- there is no implicit
    fallback between the two."""
    category: str
    verification_method: str
    use_container: bool = True

    def _run(self, plan: ExecutionPlan):
        if self.use_container:
            return run_in_container(plan)
        return run_command(plan)

    def verify(
        self, plan: ExecutionPlan, *, mission_id: str | None, requirement_id: str | None,
        criterion_id: str | None, revision: str,
    ) -> VerificationRecord:
        started_at = _now_iso()
        result = self._run(plan)
        exec_outcome = _EXEC_OUTCOME_TO_VERIFICATION_OUTCOME.get(result.status, VerificationOutcome.ERROR)

        common = dict(
            id=_vid(), mission_id=mission_id, requirement_id=requirement_id, criterion_id=criterion_id,
            category=self.category, verification_method=self.verification_method,
            verifier_id=type(self).__name__, verifier_version=VERIFIER_VERSION,
            started_at=started_at, finished_at=result.finished_at, revision=revision,
            command_reference=f"{result.execution_path}:{' '.join(plan.command)}",
            environment_identity=result.execution_path,
        )

        if exec_outcome is VerificationOutcome.ERROR:
            return VerificationRecord(
                **common, outcome=VerificationOutcome.ERROR,
                error_detail=f"execution status {result.status.value}: {result.stderr[:500]}",
            )
        if exec_outcome is VerificationOutcome.PASS:
            return VerificationRecord(
                **common, outcome=VerificationOutcome.PASS,
                summary=f"exit_code=0, stdout={len(result.stdout)}B", evidence_refs=(common["command_reference"],),
            )
        return VerificationRecord(
            **common, outcome=exec_outcome,
            summary=f"exit_code={result.exit_code}",
            error_detail=result.stderr[:1000] if exec_outcome in (VerificationOutcome.FAIL,) else None,
        )


@dataclass
class BuildVerifier(CommandVerifier):
    category: str = "BUILD"
    verification_method: str = "BUILD_VERIFICATION"


_PYTEST_SUMMARY_RE = re.compile(
    r"(?:(?P<passed>\d+) passed)?"
    r"(?:,?\s*(?P<failed>\d+) failed)?"
    r"(?:,?\s*(?P<skipped>\d+) skipped)?"
    r"(?:,?\s*(?P<errors>\d+) error)?"
)
_COLLECTED_RE = re.compile(r"collected (\d+) item")
_NO_TESTS_RAN_RE = re.compile(r"no tests ran")


@dataclass
class TestVerifierResult:
    passed: int | None
    failed: int | None
    skipped: int | None
    errors: int | None
    collected: int | None


def parse_pytest_output(stdout: str, stderr: str) -> TestVerifierResult:
    """Parses pytest's own `-q` summary line. If the summary cannot be
    parsed reliably, every metric stays None (unavailable), never
    fabricated -- spec section 8's explicit instruction."""
    combined = stdout + "\n" + stderr
    collected_match = _COLLECTED_RE.search(combined)
    collected = int(collected_match.group(1)) if collected_match else None

    # pytest's final summary line looks like "3 passed, 1 failed in 0.12s"
    # -- search from the end for the most specific match.
    summary_line = None
    for line in reversed(combined.splitlines()):
        if re.search(r"\d+ (passed|failed|error|skipped)", line):
            summary_line = line
            break
    if summary_line is None:
        return TestVerifierResult(None, None, None, None, collected)

    m = _PYTEST_SUMMARY_RE.search(summary_line)
    if not m:
        return TestVerifierResult(None, None, None, None, collected)

    def _int_or_none(v: str | None) -> int | None:
        return int(v) if v is not None else None

    return TestVerifierResult(
        passed=_int_or_none(m.group("passed")), failed=_int_or_none(m.group("failed")),
        skipped=_int_or_none(m.group("skipped")), errors=_int_or_none(m.group("errors")),
        collected=collected,
    )


@dataclass
class UnitTestVerifier(CommandVerifier):
    """Runs a test command and classifies the result from PARSED,
    bounded output -- never assumes success from exit code alone
    without checking for the "0 collected" trap (spec section 8:
    "0 collected unexpectedly must not silently become PASS")."""
    category: str = "UNIT_TEST"
    verification_method: str = "UNIT_TEST"

    def verify(
        self, plan: ExecutionPlan, *, mission_id: str | None, requirement_id: str | None,
        criterion_id: str | None, revision: str, expect_zero_collected: bool = False,
    ) -> VerificationRecord:
        started_at = _now_iso()
        result = self._run(plan)
        exec_outcome = _EXEC_OUTCOME_TO_VERIFICATION_OUTCOME.get(result.status, VerificationOutcome.ERROR)
        parsed = parse_pytest_output(result.stdout, result.stderr)

        common = dict(
            id=_vid(), mission_id=mission_id, requirement_id=requirement_id, criterion_id=criterion_id,
            category=self.category, verification_method=self.verification_method,
            verifier_id=type(self).__name__, verifier_version=VERIFIER_VERSION,
            started_at=started_at, finished_at=result.finished_at, revision=revision,
            command_reference=f"{result.execution_path}:{' '.join(plan.command)}",
            environment_identity=result.execution_path,
        )

        if exec_outcome is VerificationOutcome.ERROR:
            return VerificationRecord(
                **common, outcome=VerificationOutcome.ERROR,
                error_detail=f"execution status {result.status.value}: {result.stderr[:500]}",
            )
        if exec_outcome in (VerificationOutcome.TIMED_OUT, VerificationOutcome.CANCELLED):
            return VerificationRecord(**common, outcome=exec_outcome, summary="test run did not complete")

        # exit code alone is not trusted -- an unexpectedly-empty
        # collection is FAIL (or UNVERIFIED, per policy), never PASS.
        if parsed.collected == 0 and not expect_zero_collected:
            return VerificationRecord(
                **common, outcome=VerificationOutcome.UNVERIFIED,
                summary="0 tests collected -- cannot confirm PASS from an empty/failed collection",
            )

        if exec_outcome is VerificationOutcome.FAIL or (parsed.failed or 0) > 0 or (parsed.errors or 0) > 0:
            return VerificationRecord(
                **common, outcome=VerificationOutcome.FAIL,
                summary=f"passed={parsed.passed} failed={parsed.failed} errors={parsed.errors} skipped={parsed.skipped}",
                error_detail=result.stdout[-1000:] if result.stdout else result.stderr[:1000],
            )

        if parsed.passed is None and parsed.collected is None:
            # exit 0 but the summary itself could not be parsed at all
            return VerificationRecord(
                **common, outcome=VerificationOutcome.UNVERIFIED,
                summary="test output could not be parsed -- exit code alone is not sufficient evidence",
                limitations="pytest summary line not recognized by parse_pytest_output()",
            )

        return VerificationRecord(
            **common, outcome=VerificationOutcome.PASS,
            summary=f"passed={parsed.passed} skipped={parsed.skipped} collected={parsed.collected}",
            evidence_refs=(common["command_reference"],),
        )


@dataclass
class SecurityVerifier(UnitTestVerifier):
    """Runs a NAMED, EXACT set of existing ORNEUR security test files
    (never a vague 'security suite PASS' claim -- spec section 10) via
    LOCAL_SUBPROCESS: this is ORNEUR's own trusted first-party test
    code, not untrusted/generated content, so the CONTAINER_SANDBOX
    preference (spec section 6) does not apply here."""
    category: str = "SECURITY"
    verification_method: str = "SECURITY_TEST"
    use_container: bool = False


@dataclass
class AuthorityVerifier(UnitTestVerifier):
    """Runs existing Phase 15.5 authority test files (test_authority_bridge.py,
    test_operation_store_live_neon.py, etc.) -- reuses, does not
    reimplement, the authority engine's own test evidence."""
    category: str = "AUTHORITY"
    verification_method: str = "SECURITY_TEST"
    use_container: bool = False


# ── Interface-only verifiers (spec sections 12-15) ──────────────────
# Each produces UNVERIFIED by default. None can self-declare PASS --
# a real external observation must be supplied by the caller.

class InterfaceVerifierError(Exception):
    pass


@dataclass
class StaticAnalysisVerifier:
    category: str = "STATIC_ANALYSIS"
    verification_method: str = "STATIC_ANALYSIS"

    def verify(
        self, *, mission_id: str | None, requirement_id: str | None, criterion_id: str | None,
        revision: str, tool_available: bool, tool_name: str | None = None,
        passed: bool | None = None, summary: str | None = None,
    ) -> VerificationRecord:
        common = dict(
            id=_vid(), mission_id=mission_id, requirement_id=requirement_id, criterion_id=criterion_id,
            category=self.category, verification_method=self.verification_method,
            verifier_id=type(self).__name__, verifier_version=VERIFIER_VERSION,
            started_at=_now_iso(), finished_at=_now_iso(), revision=revision,
        )
        if not tool_available:
            return VerificationRecord(
                **common, outcome=VerificationOutcome.UNVERIFIED,
                summary=f"static analysis tool unavailable ({tool_name or 'unspecified'}) -- UNVERIFIED, not PASS",
            )
        if passed is None:
            return VerificationRecord(
                **common, outcome=VerificationOutcome.UNVERIFIED,
                summary="tool available but no real result supplied",
            )
        outcome = VerificationOutcome.PASS if passed else VerificationOutcome.FAIL
        return VerificationRecord(
            **common, outcome=outcome, summary=summary or f"{tool_name} result",
            evidence_refs=(f"{tool_name}:{'pass' if passed else 'fail'}",) if outcome is VerificationOutcome.PASS else (),
            error_detail=summary if outcome is VerificationOutcome.FAIL else None,
        )


@dataclass
class PerformanceVerifier:
    category: str = "PERFORMANCE"
    verification_method: str = "PERFORMANCE_TEST"

    def verify(
        self, *, mission_id: str | None, requirement_id: str | None, criterion_id: str | None,
        revision: str, metric: str | None = None, threshold: float | None = None,
        measured_value: float | None = None, environment: str | None = None,
    ) -> VerificationRecord:
        common = dict(
            id=_vid(), mission_id=mission_id, requirement_id=requirement_id, criterion_id=criterion_id,
            category=self.category, verification_method=self.verification_method,
            verifier_id=type(self).__name__, verifier_version=VERIFIER_VERSION,
            started_at=_now_iso(), finished_at=_now_iso(), revision=revision,
        )
        if metric is None or threshold is None or measured_value is None:
            return VerificationRecord(
                **common, outcome=VerificationOutcome.UNVERIFIED,
                summary="no benchmark measurement supplied -- 'felt fast' is never evidence",
            )
        passed = measured_value < threshold
        return VerificationRecord(
            **common, outcome=VerificationOutcome.PASS if passed else VerificationOutcome.FAIL,
            summary=f"{metric}={measured_value} (threshold {threshold}) in {environment or 'unspecified environment'}",
            evidence_refs=(f"{metric}:{measured_value}",) if passed else (),
            error_detail=None if passed else f"{metric}={measured_value} exceeded threshold {threshold}",
        )


@dataclass
class AccessibilityVerifier:
    category: str = "ACCESSIBILITY"
    verification_method: str = "INSPECTION"

    def verify(
        self, *, mission_id: str | None, requirement_id: str | None, criterion_id: str | None,
        revision: str, has_ui: bool, checked: bool = False, passed: bool | None = None,
        summary: str | None = None,
    ) -> VerificationRecord:
        common = dict(
            id=_vid(), mission_id=mission_id, requirement_id=requirement_id, criterion_id=criterion_id,
            category=self.category, verification_method=self.verification_method,
            verifier_id=type(self).__name__, verifier_version=VERIFIER_VERSION,
            started_at=_now_iso(), finished_at=_now_iso(), revision=revision,
        )
        if not has_ui:
            return VerificationRecord(
                **common, outcome=VerificationOutcome.NOT_APPLICABLE,
                not_applicable_reason="no UI exists in this mission's scope",
            )
        if not checked or passed is None:
            return VerificationRecord(
                **common, outcome=VerificationOutcome.UNVERIFIED,
                summary="UI exists but accessibility was not checked -- never defaults to PASS",
            )
        return VerificationRecord(
            **common, outcome=VerificationOutcome.PASS if passed else VerificationOutcome.FAIL,
            summary=summary or "accessibility check result",
            evidence_refs=(summary or "accessibility check",) if passed else (),
            error_detail=summary if not passed else None,
        )


@dataclass
class ManualReviewVerifier:
    category: str = "MANUAL_REVIEW"
    verification_method: str = "MANUAL_REVIEW"

    def verify(
        self, *, mission_id: str | None, requirement_id: str | None, criterion_id: str | None,
        revision: str, reviewer: str | None = None, passed: bool | None = None,
        evidence_ref: str | None = None,
    ) -> VerificationRecord:
        common = dict(
            id=_vid(), mission_id=mission_id, requirement_id=requirement_id, criterion_id=criterion_id,
            category=self.category, verification_method=self.verification_method,
            verifier_id=type(self).__name__, verifier_version=VERIFIER_VERSION,
            started_at=_now_iso(), finished_at=_now_iso(), revision=revision,
        )
        if not reviewer or passed is None or not (evidence_ref or "").strip():
            return VerificationRecord(
                **common, outcome=VerificationOutcome.UNVERIFIED,
                summary="no real reviewer/evidence supplied -- a model cannot fabricate manual review",
            )
        return VerificationRecord(
            **common, outcome=VerificationOutcome.PASS if passed else VerificationOutcome.FAIL,
            summary=f"reviewed by {reviewer}", evidence_refs=(evidence_ref,) if passed else (),
            error_detail=None if passed else f"reviewer {reviewer} did not approve",
        )


@dataclass
class ExternalConfirmationVerifier:
    category: str = "EXTERNAL_CONFIRMATION"
    verification_method: str = "EXTERNAL_CONFIRMATION"

    def verify(
        self, *, mission_id: str | None, requirement_id: str | None, criterion_id: str | None,
        revision: str, confirmation_ref: str | None = None,
    ) -> VerificationRecord:
        common = dict(
            id=_vid(), mission_id=mission_id, requirement_id=requirement_id, criterion_id=criterion_id,
            category=self.category, verification_method=self.verification_method,
            verifier_id=type(self).__name__, verifier_version=VERIFIER_VERSION,
            started_at=_now_iso(), finished_at=_now_iso(), revision=revision,
        )
        if not (confirmation_ref or "").strip():
            return VerificationRecord(
                **common, outcome=VerificationOutcome.UNVERIFIED,
                summary="no external confirmation reference supplied -- absent confirmation is never PASS",
            )
        return VerificationRecord(
            **common, outcome=VerificationOutcome.PASS,
            summary=f"externally confirmed: {confirmation_ref}", evidence_refs=(confirmation_ref,),
        )
