"""
FailureRegressionSuite (spec §36-37, §82).

Every accepted (VERIFIED) failure becomes a regression case: input,
expected behavior, source lineage, target subsystem/model -- run before
and after training. This is the independent failure-to-eval path that must
work even when no training ever occurs (spec §82's required E2E).

This module does not itself re-implement Truth/Court/Simulation execution
-- `run_case` takes a caller-supplied `executor` callable (typically a thin
wrapper around the real subsystem, e.g. TruthFabric.assess_evidence or
CognitiveCourt.run) so the suite stays a thin, honest orchestration layer
over EXISTING real execution paths rather than a second, parallel one.
"""
from __future__ import annotations

from dataclasses import dataclass, field
from typing import Callable

from orca.learning.contracts import CurriculumCandidate, FailureType, RootCauseClass, SecurityClass


@dataclass
class RegressionCase:
    case_id: str
    failure_ids: list[str]
    input_summary: str
    expected_behavior: str
    target_subsystem: str
    is_security_regression: bool = False


@dataclass
class RegressionRunResult:
    case_id: str
    passed: bool
    actual_summary: str = ""
    notes: str = ""


def build_regression_case(candidate: CurriculumCandidate, target_subsystem: str) -> RegressionCase:
    return RegressionCase(
        case_id=f"regr-{candidate.candidate_id}",
        failure_ids=list(candidate.failure_ids),
        input_summary=candidate.input_summary,
        expected_behavior=candidate.expected_behavior,
        target_subsystem=target_subsystem,
        # Spec §37: security failures become SECURITY_REGRESSION, preserved
        # in security tests/evals, never ordinary capability training.
        is_security_regression=candidate.security_class == SecurityClass.SECURITY_SENSITIVE,
    )


@dataclass
class FailureRegressionSuite:
    cases: list[RegressionCase] = field(default_factory=list)

    def add(self, case: RegressionCase) -> None:
        self.cases.append(case)

    def run(self, executor: Callable[[RegressionCase], RegressionRunResult]) -> list[RegressionRunResult]:
        return [executor(case) for case in self.cases]

    def security_cases(self) -> list[RegressionCase]:
        return [c for c in self.cases if c.is_security_regression]

    def capability_cases(self) -> list[RegressionCase]:
        return [c for c in self.cases if not c.is_security_regression]
