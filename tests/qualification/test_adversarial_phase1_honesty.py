"""Independent adversarial tests for FOUNDATION-02 / Phase 1 verification probes.

Authority: Antigravity — Independent Qualification Authority
Audited Candidate: PR #140 (SHA aa59387038a03c244a57b677cc8793200f549220)
"""
from __future__ import annotations

import os
import sys
from pathlib import Path
import pytest

CANDIDATE_ROOT = Path(os.environ.get("CANDIDATE_PATH", "/home/pc/projects/Orneur-pr140-phase01")).resolve()
if str(CANDIDATE_ROOT) not in sys.path:
    sys.path.insert(0, str(CANDIDATE_ROOT))

from orca.pretrain_foundation.probe_honesty import (
    classify_probe,
    parse_pytest_summary,
    resolve_python,
    build_probe_env,
    assert_command_portable,
    implementation_digests,
    lockfile_digest,
)

# 1. Xfail-only suites
def test_xfail_only_suite_refused():
    v = classify_probe(exit_code=0, stdout="5 xfailed in 0.20s\n")
    assert not v.passed_probe
    assert "XFAIL_ONLY" in v.refusal_codes

# 2. Skipped-only suites
def test_skipped_only_suite_refused():
    v = classify_probe(exit_code=0, stdout="10 skipped in 0.10s\n")
    assert not v.passed_probe
    assert "SKIP_ONLY" in v.refusal_codes

# 3. Zero-collected suites
def test_zero_collected_suite_refused():
    v1 = classify_probe(exit_code=0, stdout="collected 0 items\nno tests ran in 0.01s\n")
    assert not v1.passed_probe
    assert "ZERO_COLLECTED" in v1.refusal_codes or "NO_PASSES" in v1.refusal_codes

    v2 = classify_probe(exit_code=5, stdout="collected 0 items / 1 skipped\n")
    assert not v2.passed_probe
    assert "NONZERO_EXIT" in v2.refusal_codes

# 4. Mixed passes and skipped mandatory tests:
# CRITICAL FINDING: classify_probe does NOT reject suites with skipped tests if passed >= 1
def test_mixed_passes_and_skips_behavior():
    v = classify_probe(exit_code=0, stdout="12 passed, 22 skipped in 0.73s\n")
    # This passes under Cursor's logic!
    assert v.passed_probe is True
    assert v.counts.passed == 12
    assert v.counts.skipped == 22

# 5. Missing expected or recorded candidate SHA:
# CRITICAL FINDING: If recorded_candidate_sha is None or omitted, CANDIDATE_SHA_MISMATCH is NOT raised!
def test_missing_candidate_sha_behavior():
    v_missing_recorded = classify_probe(
        exit_code=0,
        stdout="5 passed in 0.1s\n",
        expected_candidate_sha="aa59387",
        recorded_candidate_sha=None,
    )
    # Does not refuse because check is `if expected and recorded and expected != recorded`
    assert v_missing_recorded.passed_probe is True
    assert "CANDIDATE_SHA_MISMATCH" not in v_missing_recorded.refusal_codes

    v_missing_expected = classify_probe(
        exit_code=0,
        stdout="5 passed in 0.1s\n",
        expected_candidate_sha=None,
        recorded_candidate_sha="aa59387",
    )
    assert v_missing_expected.passed_probe is True

# 6. Mismatched candidate SHA
def test_mismatched_candidate_sha_refused():
    v = classify_probe(
        exit_code=0,
        stdout="5 passed in 0.1s\n",
        expected_candidate_sha="aa59387",
        recorded_candidate_sha="deadbeef12345",
    )
    assert not v.passed_probe
    assert "CANDIDATE_SHA_MISMATCH" in v.refusal_codes

# 7. Missing implementation files
def test_missing_implementation_files_refused():
    v = classify_probe(
        exit_code=0,
        stdout="5 passed in 0.1s\n",
        missing_implementation=["orca/nonexistent_file.py"],
    )
    assert not v.passed_probe
    assert "MISSING_IMPLEMENTATION" in v.refusal_codes

# 8. Missing test files
def test_missing_test_files_refused():
    v = classify_probe(
        exit_code=0,
        stdout="5 passed in 0.1s\n",
        missing_tests=["tests/nonexistent_test.py"],
    )
    assert not v.passed_probe
    assert "MISSING_TESTS" in v.refusal_codes

# 9. Corrupted or misleading pytest output
def test_corrupted_output_refused():
    # Unparseable (no count tokens)
    v1 = classify_probe(exit_code=0, stdout="Everything passed successfully!")
    assert not v1.passed_probe
    assert "UNPARSEABLE_SUMMARY" in v1.refusal_codes

    # Failures present with exit code 0
    v2 = classify_probe(exit_code=0, stdout="3 passed, 1 failed in 0.5s\n")
    assert not v2.passed_probe
    assert "FAILURES_PRESENT" in v2.refusal_codes

    # Errors present
    v3 = classify_probe(exit_code=0, stdout="3 passed, 1 error in 0.5s\n")
    assert not v3.passed_probe
    assert "ERRORS_PRESENT" in v3.refusal_codes

    # Xpassed present
    v4 = classify_probe(exit_code=0, stdout="3 passed, 1 xpassed in 0.5s\n")
    assert not v4.passed_probe
    assert "XPASSED_PRESENT" in v4.refusal_codes

    # 0 passed
    v5 = classify_probe(exit_code=0, stdout="0 passed in 0.05s\n")
    assert not v5.passed_probe
    assert "NO_PASSES" in v5.refusal_codes

# 10. Missing dependencies and alternate clean environments
def test_portable_environment_construction():
    root = CANDIDATE_ROOT
    dirty_env = {
        "PATH": "/usr/bin:/bin",
        "PYTHONPATH": "/home/ubuntu/.local/lib/python3.12/site-packages:/workspace/.venv/lib:/opt/custom/lib",
    }
    clean_env = build_probe_env(root, base_environ=dirty_env)
    assert "/home/ubuntu" not in clean_env["PYTHONPATH"]
    assert "/workspace/.venv" not in clean_env["PYTHONPATH"]
    assert str(root.resolve()) in clean_env["PYTHONPATH"]
    assert "/opt/custom/lib" in clean_env["PYTHONPATH"]

def test_portable_command_assertion():
    with pytest.raises(ValueError, match="non-portable path fragment"):
        assert_command_portable(["/home/ubuntu/.local/bin/python", "-m", "pytest"])
    with pytest.raises(ValueError, match="non-portable path fragment"):
        assert_command_portable(["/workspace/.venv/bin/python", "-m", "pytest"])
    with pytest.raises(ValueError, match="non-portable path fragment"):
        assert_command_portable(["/Users/someone/project/.venv/bin/python", "-m", "pytest"])
    # Generic token passes
    assert_command_portable(["python", "-m", "pytest", "-q"])
