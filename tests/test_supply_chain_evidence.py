"""Phase 15.10 -- supply-chain / licensing evidence tests (spec sections 14-15)."""
from __future__ import annotations

from pathlib import Path

from orca.mission.supply_chain_evidence import (
    CONTAINER_SANDBOX_MUTABLE_IMAGE_TAG,
    evaluate_licensing,
    evaluate_supply_chain,
    no_ui_accessibility,
)
from orca.mission.verification import VerificationOutcome

_REPO_ROOT = Path(__file__).resolve().parent.parent


def test_supply_chain_never_claims_pass_without_a_scanner():
    result = evaluate_supply_chain(_REPO_ROOT)
    assert result.status is not VerificationOutcome.PASS


def test_supply_chain_reports_real_lockfile_dependency_count():
    result = evaluate_supply_chain(_REPO_ROOT)
    assert "uv.lock" in result.summary
    assert "package(s) resolved" in result.summary


def test_supply_chain_discloses_mutable_container_image_tag():
    result = evaluate_supply_chain(_REPO_ROOT)
    assert CONTAINER_SANDBOX_MUTABLE_IMAGE_TAG in result.summary


def test_supply_chain_missing_lockfile_is_unverified():
    result = evaluate_supply_chain(Path("/nonexistent/does/not/exist"))
    assert result.status is VerificationOutcome.UNVERIFIED
    assert "no uv.lock found" in result.summary


def test_licensing_never_claims_legally_safe_or_commercially_cleared():
    result = evaluate_licensing(_REPO_ROOT)
    assert "legally safe" not in result.summary.lower()
    assert "commercially cleared" not in result.summary.lower()
    assert result.status is not VerificationOutcome.PASS


def test_licensing_reports_real_source_license_when_declared():
    result = evaluate_licensing(_REPO_ROOT)
    assert "MIT" in result.summary


def test_licensing_discloses_missing_license_file():
    result = evaluate_licensing(_REPO_ROOT)
    assert "top-level LICENSE file present: False" in result.summary


def test_no_ui_accessibility_is_not_applicable_with_real_reason():
    result = no_ui_accessibility()
    assert result.status is VerificationOutcome.NOT_APPLICABLE
    assert result.not_applicable_reason
