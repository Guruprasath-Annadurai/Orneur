"""
Phase 15.9 -- typed Anti-Test-Gaming finding model (spec sections 1-2).

    A GREEN TEST SUITE IS NOT TRUSTWORTHY IF THE CHANGE MADE THE TEST
    SUITE EASIER TO PASS.

This module defines the finding vocabulary and the deterministic
blocking policy. Detection logic (baseline/candidate diff analysis,
AST-based weakening detection, collection comparison) lives in
`orca.mission.git_diff_analysis` and `orca.mission.gaming_detectors`
-- this module only defines WHAT a finding looks like and WHICH
categories are always CRITICAL, never how one is discovered.

A detector that cannot determine intent reports a finding/risk, never
invents malicious intent -- `confidence_basis` records exactly what
evidence backs a finding (e.g. "assert count decreased from 3 to 1 in
the same function name, same file, at revision B" -- a fact, not an
accusation).
"""
from __future__ import annotations

from dataclasses import dataclass, field
from datetime import datetime, timezone
from enum import Enum


def _now_iso() -> str:
    return datetime.now(timezone.utc).isoformat()


class FindingCategory(str, Enum):
    TEST_DELETED = "TEST_DELETED"
    TEST_DISABLED = "TEST_DISABLED"
    TEST_SKIPPED = "TEST_SKIPPED"
    ASSERTION_REMOVED = "ASSERTION_REMOVED"
    ASSERTION_WEAKENED = "ASSERTION_WEAKENED"
    EXPECTED_BEHAVIOR_CHANGED = "EXPECTED_BEHAVIOR_CHANGED"
    ERROR_SUPPRESSED = "ERROR_SUPPRESSED"
    VALIDATION_DISABLED = "VALIDATION_DISABLED"
    SECURITY_CHECK_WEAKENED = "SECURITY_CHECK_WEAKENED"
    AUTH_CHECK_WEAKENED = "AUTH_CHECK_WEAKENED"
    MOCK_REPLACES_REQUIRED_BEHAVIOR = "MOCK_REPLACES_REQUIRED_BEHAVIOR"
    HARDCODED_TEST_OUTPUT = "HARDCODED_TEST_OUTPUT"
    COLLECTION_REDUCED = "COLLECTION_REDUCED"
    PARAMETRIZATION_REDUCED = "PARAMETRIZATION_REDUCED"
    VERIFICATION_SCOPE_REDUCED = "VERIFICATION_SCOPE_REDUCED"


class Severity(str, Enum):
    INFO = "INFO"
    LOW = "LOW"
    MEDIUM = "MEDIUM"
    HIGH = "HIGH"
    CRITICAL = "CRITICAL"


#: Categories that are ALWAYS CRITICAL and blocking when they touch a
#: security-relevant path (spec section 2's own examples) -- the
#: elevation to CRITICAL itself is decided by the detector (which
#: knows the file path), this set just enumerates which categories
#: are EVER eligible for that elevation.
SECURITY_ELEVATABLE_CATEGORIES = frozenset({
    FindingCategory.TEST_DELETED,
    FindingCategory.TEST_DISABLED,
    FindingCategory.TEST_SKIPPED,
    FindingCategory.ASSERTION_REMOVED,
    FindingCategory.ASSERTION_WEAKENED,
    FindingCategory.EXPECTED_BEHAVIOR_CHANGED,
    FindingCategory.SECURITY_CHECK_WEAKENED,
    FindingCategory.AUTH_CHECK_WEAKENED,
    FindingCategory.MOCK_REPLACES_REQUIRED_BEHAVIOR,
    FindingCategory.VALIDATION_DISABLED,
})


class AntiGamingError(Exception):
    pass


@dataclass(frozen=True)
class AntiGamingFinding:
    finding_id: str
    mission_id: str | None
    revision: str
    baseline_revision: str
    category: FindingCategory
    severity: Severity
    file_path: str
    description: str
    detector_id: str
    confidence_basis: str
    created_at: str = field(default_factory=_now_iso)
    line_reference: str | None = None
    evidence_refs: tuple[str, ...] = field(default_factory=tuple)
    requirement_ids: tuple[str, ...] = field(default_factory=tuple)
    test_ids: tuple[str, ...] = field(default_factory=tuple)
    security_relevance: bool = False
    blocking: bool = False
    detector_version: str = "15.9.0"

    def __post_init__(self) -> None:
        if not self.description.strip():
            raise AntiGamingError(f"{self.finding_id}: description must not be empty.")
        if not self.confidence_basis.strip():
            raise AntiGamingError(
                f"{self.finding_id}: confidence_basis must not be empty -- a finding must state "
                f"what real evidence backs it, never assert intent from confidence alone."
            )
        if self.severity is Severity.CRITICAL and not self.blocking:
            raise AntiGamingError(
                f"{self.finding_id}: a CRITICAL finding must be blocking=True -- "
                f"per spec section 2, critical verification/security weakening must block."
            )


def has_blocking_finding(findings: tuple[AntiGamingFinding, ...]) -> bool:
    return any(f.blocking for f in findings)


def blocking_findings(findings: tuple[AntiGamingFinding, ...]) -> tuple[AntiGamingFinding, ...]:
    return tuple(f for f in findings if f.blocking)


def critical_findings(findings: tuple[AntiGamingFinding, ...]) -> tuple[AntiGamingFinding, ...]:
    return tuple(f for f in findings if f.severity is Severity.CRITICAL)
