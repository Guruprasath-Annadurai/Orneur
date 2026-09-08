"""Phase 15.9 -- AntiGamingFinding model invariant tests."""
from __future__ import annotations

import pytest

from orca.mission.anti_gaming import (
    AntiGamingError,
    AntiGamingFinding,
    FindingCategory,
    Severity,
    blocking_findings,
    critical_findings,
    has_blocking_finding,
)


def _finding(**overrides):
    defaults = dict(
        finding_id="f1", mission_id="m1", revision="rev2", baseline_revision="rev1",
        category=FindingCategory.TEST_DELETED, severity=Severity.MEDIUM, file_path="tests/test_x.py",
        description="A test was deleted.", detector_id="detect_test_deletions",
        confidence_basis="AST comparison showed the function missing.",
    )
    defaults.update(overrides)
    return AntiGamingFinding(**defaults)


def test_empty_description_rejected():
    with pytest.raises(AntiGamingError):
        _finding(description="")


def test_empty_confidence_basis_rejected():
    with pytest.raises(AntiGamingError):
        _finding(confidence_basis="")


def test_critical_must_be_blocking():
    with pytest.raises(AntiGamingError):
        _finding(severity=Severity.CRITICAL, blocking=False)
    ok = _finding(severity=Severity.CRITICAL, blocking=True)
    assert ok.severity is Severity.CRITICAL


def test_has_blocking_finding():
    non_blocking = _finding(blocking=False)
    blocking = _finding(finding_id="f2", blocking=True, severity=Severity.CRITICAL)
    assert has_blocking_finding((non_blocking,)) is False
    assert has_blocking_finding((non_blocking, blocking)) is True


def test_blocking_findings_filters_correctly():
    a = _finding(finding_id="a", blocking=False)
    b = _finding(finding_id="b", blocking=True, severity=Severity.CRITICAL)
    result = blocking_findings((a, b))
    assert result == (b,)


def test_critical_findings_filters_correctly():
    a = _finding(finding_id="a", severity=Severity.LOW)
    b = _finding(finding_id="b", severity=Severity.CRITICAL, blocking=True)
    result = critical_findings((a, b))
    assert result == (b,)
