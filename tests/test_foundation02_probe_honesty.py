"""Adversarial honesty tests for FOUNDATION-02 verification probes.

Deliberately corrupt outcomes, remove dependencies, alter SHAs, and simulate
skip-/xfail-only and mixed pass/skip suites. The evidence engine must not
manufacture PASS.
"""
from __future__ import annotations

import os
import sys
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

from orca.pretrain_foundation.probe_honesty import (
    assert_command_portable,
    build_probe_env,
    classify_probe,
    is_complete_candidate_sha,
    parse_pytest_summary,
    resolve_python,
)

# Complete 40-hex identities used by acceptance-producing probe scenarios.
SHA_A = "4d9fcda896e9ac12581f67fd65aaf3bc23aad7e4"
SHA_B = "deadbeefdeadbeefdeadbeefdeadbeefdeadbeef"


def test_parse_distinguishes_passed_from_xfailed():
    counts = parse_pytest_summary("23 passed, 1 xfailed in 0.88s", "")
    assert counts.parseable is True
    assert counts.passed == 23
    assert counts.xfailed == 1
    assert counts.failed is None


def test_honest_suite_with_residual_xfail_still_verifies():
    """G4-style: real passes + documented strict xfail residual may verify."""
    verdict = classify_probe(
        exit_code=0,
        stdout="23 passed, 1 xfailed in 0.88s\n",
        expected_candidate_sha=SHA_A,
        recorded_candidate_sha=SHA_A,
    )
    assert verdict.passed_probe is True
    assert verdict.counts.passed == 23
    assert verdict.counts.xfailed == 1
    assert "xfailed=" in verdict.reason


def test_adversarial_xfail_only_must_not_pass():
    verdict = classify_probe(exit_code=0, stdout="5 xfailed in 0.10s\n")
    assert verdict.passed_probe is False
    assert "XFAIL_ONLY" in verdict.refusal_codes


def test_adversarial_skip_only_must_not_pass():
    verdict = classify_probe(exit_code=0, stdout="10 skipped in 0.05s\n")
    assert verdict.passed_probe is False
    assert "SKIP_ONLY" in verdict.refusal_codes
    assert "SKIPS_PRESENT" in verdict.refusal_codes


def test_adversarial_complete_module_skip_must_not_pass():
    """Complete module skip (all collected items skipped) refuses VERIFIED."""
    verdict = classify_probe(
        exit_code=0,
        stdout="collected 8 items\n8 skipped in 0.02s\n",
        expected_candidate_sha=SHA_A,
        recorded_candidate_sha=SHA_A,
    )
    assert verdict.passed_probe is False
    assert "SKIP_ONLY" in verdict.refusal_codes
    assert "SKIPS_PRESENT" in verdict.refusal_codes


def test_adversarial_mixed_passes_and_skips_must_not_pass():
    """Mandatory mixed pass/skip suites must refuse (Antigravity P1)."""
    verdict = classify_probe(
        exit_code=0,
        stdout="12 passed, 22 skipped in 0.73s\n",
        expected_candidate_sha=SHA_A,
        recorded_candidate_sha=SHA_A,
    )
    assert verdict.passed_probe is False
    assert "SKIPS_PRESENT" in verdict.refusal_codes
    assert verdict.counts.passed == 12
    assert verdict.counts.skipped == 22


def test_adversarial_partial_skip_with_xfail_must_not_pass():
    verdict = classify_probe(
        exit_code=0,
        stdout="5 passed, 2 skipped, 1 xfailed in 0.40s\n",
        expected_candidate_sha=SHA_A,
        recorded_candidate_sha=SHA_A,
    )
    assert verdict.passed_probe is False
    assert "SKIPS_PRESENT" in verdict.refusal_codes


def test_adversarial_zero_collected_must_not_pass():
    verdict = classify_probe(
        exit_code=0,
        stdout="collected 0 items\nno tests ran in 0.01s\n",
    )
    assert verdict.passed_probe is False
    assert "ZERO_COLLECTED" in verdict.refusal_codes or "NO_PASSES" in verdict.refusal_codes


def test_adversarial_exit_zero_with_failures_must_not_pass():
    # Corrupted / inconsistent result: claim exit 0 while summary shows failures.
    verdict = classify_probe(exit_code=0, stdout="2 failed, 1 passed in 0.2s\n")
    assert verdict.passed_probe is False
    assert "FAILURES_PRESENT" in verdict.refusal_codes


def test_adversarial_nonzero_exit_must_not_pass():
    verdict = classify_probe(exit_code=1, stdout="1 failed, 2 passed in 0.2s\n")
    assert verdict.passed_probe is False
    assert "NONZERO_EXIT" in verdict.refusal_codes


def test_adversarial_unparseable_summary_must_not_pass():
    verdict = classify_probe(exit_code=0, stdout="all good, trust me\n")
    assert verdict.passed_probe is False
    assert "UNPARSEABLE_SUMMARY" in verdict.refusal_codes


def test_adversarial_missing_dependency_must_not_pass():
    verdict = classify_probe(
        exit_code=0,
        stdout="3 passed in 0.1s\n",
        missing_implementation=["orca/missing.py"],
        expected_candidate_sha=SHA_A,
        recorded_candidate_sha=SHA_A,
    )
    assert verdict.passed_probe is False
    assert "MISSING_IMPLEMENTATION" in verdict.refusal_codes


def test_adversarial_missing_tests_must_not_pass():
    verdict = classify_probe(
        exit_code=0,
        stdout="3 passed in 0.1s\n",
        missing_tests=["tests/missing.py"],
        expected_candidate_sha=SHA_A,
        recorded_candidate_sha=SHA_A,
    )
    assert verdict.passed_probe is False
    assert "MISSING_TESTS" in verdict.refusal_codes


def test_adversarial_altered_sha_must_not_pass():
    verdict = classify_probe(
        exit_code=0,
        stdout="12 passed in 0.4s\n",
        expected_candidate_sha=SHA_A,
        recorded_candidate_sha=SHA_B,
    )
    assert verdict.passed_probe is False
    assert "CANDIDATE_SHA_MISMATCH" in verdict.refusal_codes


def test_adversarial_missing_recorded_sha_must_not_pass():
    """Antigravity P2: omitted recorded SHA must refuse, not silent-pass."""
    verdict = classify_probe(
        exit_code=0,
        stdout="10 passed in 0.2s\n",
        expected_candidate_sha=SHA_A,
        recorded_candidate_sha=None,
    )
    assert verdict.passed_probe is False
    assert "CANDIDATE_SHA_MISSING" in verdict.refusal_codes


def test_adversarial_missing_expected_sha_must_not_pass():
    verdict = classify_probe(
        exit_code=0,
        stdout="10 passed in 0.2s\n",
        expected_candidate_sha=None,
        recorded_candidate_sha=SHA_A,
    )
    assert verdict.passed_probe is False
    assert "CANDIDATE_SHA_MISSING" in verdict.refusal_codes


def test_adversarial_empty_sha_must_not_pass():
    verdict = classify_probe(
        exit_code=0,
        stdout="10 passed in 0.2s\n",
        expected_candidate_sha="",
        recorded_candidate_sha="   ",
    )
    assert verdict.passed_probe is False
    assert "CANDIDATE_SHA_MISSING" in verdict.refusal_codes


def test_adversarial_malformed_sha_must_not_pass():
    """Short / non-hex identities are not complete commit SHAs."""
    assert is_complete_candidate_sha("98069d8") is False
    verdict = classify_probe(
        exit_code=0,
        stdout="10 passed in 0.2s\n",
        expected_candidate_sha="98069d8",
        recorded_candidate_sha="98069d8",
    )
    assert verdict.passed_probe is False
    assert "CANDIDATE_SHA_MALFORMED" in verdict.refusal_codes


def test_adversarial_corrupt_pass_count_zero_must_not_pass():
    verdict = classify_probe(exit_code=0, stdout="0 passed in 0.01s\n")
    assert verdict.passed_probe is False
    assert "NO_PASSES" in verdict.refusal_codes


def test_resolve_python_never_hardcodes_workspace_absolute():
    py = resolve_python(ROOT)
    assert py == sys.executable or py.endswith(str(Path(".venv") / "bin" / "python")) or py.endswith(
        str(Path(".venv") / "Scripts" / "python.exe")
    )
    # Must not be the literal cloud absolute path preference from the broken builder.
    assert py != "/workspace/.venv/bin/python" or (ROOT / ".venv" / "bin" / "python").exists()


def test_probe_env_wipes_inherited_pythonpath_and_addopts():
    dirty = {
        **os.environ,
        "PYTHONPATH": "/home/ubuntu/.local/lib/python3.12/site-packages:/usr/lib/python3/dist-packages:/opt/ok",
        "PYTEST_ADDOPTS": "-q --maxfail=1",
    }
    env = build_probe_env(ROOT, base_environ=dirty)
    assert env["PYTHONPATH"] == str(ROOT.resolve())
    assert "/home/ubuntu/" not in env["PYTHONPATH"]
    assert "/opt/ok" not in env["PYTHONPATH"]
    assert "PYTEST_ADDOPTS" not in env


def test_portable_command_rejects_home_ubuntu_fragment():
    with pytest.raises(ValueError, match="non-portable"):
        assert_command_portable(
            ["/home/ubuntu/.local/bin/python", "-m", "pytest", "tests/x.py"]
        )


def test_portable_command_accepts_generic_python_token():
    assert_command_portable(["python", "-m", "pytest", "-q", "tests/x.py"])
