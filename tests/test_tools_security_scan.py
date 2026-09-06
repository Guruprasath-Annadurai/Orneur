"""
Tests for orca/tools/security.py's run_security_scan — the real static
security scan tool backing Novus's "run a security check" capability
(bandit for Python + a portable hardcoded-secret pattern scan).
"""
from __future__ import annotations

import pytest

from orca.tools.security import run_security_scan


@pytest.fixture(autouse=True)
def _isolated_workspace(tmp_path, monkeypatch):
    import orca.tools as tools_module
    monkeypatch.setattr(tools_module, "WORKSPACE_DIR", tmp_path)
    yield tmp_path


def test_rejects_path_outside_workspace():
    result = run_security_scan("/etc/passwd")
    assert isinstance(result, str)
    assert "Access denied" in result


def test_missing_path_reports_not_found(tmp_path):
    result = run_security_scan("does_not_exist.py")
    assert isinstance(result, str)
    assert "not found" in result.lower()


def test_clean_python_file_has_no_findings(tmp_path):
    (tmp_path / "clean.py").write_text("def add(a, b):\n    return a + b\n")
    result = run_security_scan("clean.py")
    formatted = result.format()
    assert "no findings" in formatted.lower()
    assert result.files_scanned == 1


def test_bandit_flags_a_real_python_security_issue(tmp_path):
    # eval() on unsanitized input is a real, well-known bandit finding
    # (B307) -- a genuine test that bandit actually ran, not a fixture
    # that only exercises the happy path.
    (tmp_path / "risky.py").write_text(
        "def run(user_input):\n    return eval(user_input)\n"
    )
    result = run_security_scan("risky.py")
    assert not isinstance(result, str), f"expected ScanResult, got error: {result}"
    assert result.bandit_ran, f"bandit did not run: {result.bandit_error}"
    assert len(result.findings) >= 1
    formatted = result.format()
    assert "risky.py" in formatted


def test_hardcoded_aws_key_detected_in_non_python_file(tmp_path):
    # Secret-pattern scan must work for ANY file, not just Python -- this
    # is the honest cross-language part of the tool's real scope.
    (tmp_path / "config.swift").write_text(
        'let awsKey = "AKIAABCDEFGHIJKLMNOP"\n'
    )
    result = run_security_scan("config.swift")
    assert not isinstance(result, str)
    labels = [f.label for f in result.findings]
    assert "AWS access key" in labels


def test_hardcoded_private_key_detected(tmp_path):
    (tmp_path / "id_rsa.txt").write_text("-----BEGIN RSA PRIVATE KEY-----\nMIIEow...\n")
    result = run_security_scan("id_rsa.txt")
    assert not isinstance(result, str)
    labels = [f.label for f in result.findings]
    assert "Private key header" in labels


def test_scanning_a_directory_covers_multiple_files(tmp_path):
    (tmp_path / "a.py").write_text("x = 1\n")
    (tmp_path / "b.js").write_text('const key = "sk-abcdefghijklmnopqrstuvwx12345";\n')
    result = run_security_scan(".")
    assert not isinstance(result, str)
    assert result.files_scanned >= 2


def test_no_python_files_skips_bandit_but_still_scans_secrets(tmp_path):
    (tmp_path / "notes.md") .write_text("just some notes, nothing secret\n")
    result = run_security_scan("notes.md")
    assert not isinstance(result, str)
    assert result.bandit_ran is False
    assert result.bandit_error is None  # bandit wasn't needed, not an error
