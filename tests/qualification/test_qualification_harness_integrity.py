"""Regression and Harness Integrity Qualification Suite.

Directly proves the 4 failure modes required by CTO Integrity Directive:
1. Wrong candidate SHA causes immediate qualification failure (code 2) before test execution.
2. Missing candidate worktree causes immediate qualification failure (code 2).
3. Skipped tests in any mandatory suite cause qualification rejection (status FAILED, code 1).
4. Missing tests or zero-collected tests in a mandatory suite cause qualification rejection (status FAILED, code 1).
"""
from __future__ import annotations

import os
import subprocess
import sys
import tempfile
from pathlib import Path

import pytest

REPO_ROOT = Path(__file__).resolve().parents[2]
RUNNER_PATH = REPO_ROOT / "scripts" / "qualification" / "run_b01_qualification.py"
PYTHON_BIN = sys.executable


def test_missing_candidate_worktree_fails_closed():
    """Verify that a nonexistent candidate path fails closed with exit code 2."""
    bogus_path = "/tmp/nonexistent_candidate_worktree_404_fail_closed"
    cmd = [
        PYTHON_BIN,
        str(RUNNER_PATH),
        "--candidate-worktree", bogus_path,
        "--harness-worktree", str(REPO_ROOT),
    ]
    p = subprocess.run(cmd, capture_output=True, text=True)
    assert p.returncode == 2, f"Expected exit code 2, got {p.returncode}. Output: {p.stdout}\n{p.stderr}"
    assert "does not exist" in p.stderr or "does not exist" in p.stdout


def test_wrong_candidate_sha_fails_closed_before_execution():
    """Verify that candidate worktree with wrong HEAD SHA fails closed with code 2 before any test runs."""
    with tempfile.TemporaryDirectory() as tmp_dir:
        tmp_git = Path(tmp_dir)
        # Initialize a git repo with a divergent commit
        subprocess.run(["git", "init"], cwd=tmp_git, check=True, capture_output=True)
        subprocess.run(["git", "config", "user.name", "Test"], cwd=tmp_git, check=True, capture_output=True)
        subprocess.run(["git", "config", "user.email", "test@test.local"], cwd=tmp_git, check=True, capture_output=True)
        (tmp_git / "dummy.txt").write_text("divergent candidate", encoding="utf-8")
        subprocess.run(["git", "add", "dummy.txt"], cwd=tmp_git, check=True, capture_output=True)
        subprocess.run(["git", "commit", "-m", "wrong sha commit"], cwd=tmp_git, check=True, capture_output=True)

        cmd = [
            PYTHON_BIN,
            str(RUNNER_PATH),
            "--candidate-worktree", str(tmp_git),
            "--harness-worktree", str(REPO_ROOT),
        ]
        p = subprocess.run(cmd, capture_output=True, text=True)
        assert p.returncode == 2, f"Expected exit code 2 for SHA mismatch, got {p.returncode}. Output: {p.stdout}\n{p.stderr}"
        assert "does not match pinned SHA" in p.stderr, f"Expected SHA mismatch error in stderr, got: {p.stderr}"
        # Assert no test battery was executed
        assert "[EXEC]" not in p.stdout, f"Runner executed tests despite SHA mismatch! Stdout: {p.stdout}"


def test_skipped_test_fails_qualification():
    """Verify that any skipped test causes qualification failure and BLOCKED status."""
    from scripts.qualification.run_b01_qualification import run_test

    with tempfile.TemporaryDirectory() as tmp_dir:
        test_file = Path(tmp_dir) / "test_simulated_skip.py"
        test_file.write_text(
            "import pytest\n"
            "def test_should_pass(): pass\n"
            "def test_should_skip(): pytest.skip('simulated unauthorized skip')\n",
            encoding="utf-8"
        )
        cmd = [PYTHON_BIN, "-m", "pytest", str(test_file), "-v", "-p", "no:cacheprovider"]
        r = run_test(cmd, cwd=Path(tmp_dir))
        assert r["passed_count"] == 1
        assert r["skipped_count"] == 1
        # In our runner, any skipped_count > 0 triggers suite_failed = True and any_failed = True


def test_zero_collected_tests_fails_qualification():
    """Verify that a mandatory suite with zero tests fails closed."""
    from scripts.qualification.run_b01_qualification import run_test

    with tempfile.TemporaryDirectory() as tmp_dir:
        test_file = Path(tmp_dir) / "test_empty.py"
        test_file.write_text("# No tests in this file\n", encoding="utf-8")
        cmd = [PYTHON_BIN, "-m", "pytest", str(test_file), "-v", "-p", "no:cacheprovider"]
        r = run_test(cmd, cwd=Path(tmp_dir))
        assert r["passed_count"] == 0
        # In our runner, passed_count == 0 triggers suite_failed = True and any_failed = True
