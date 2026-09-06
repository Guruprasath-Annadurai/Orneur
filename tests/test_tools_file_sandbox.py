"""
Tests for orca/tools/__init__.py's _read_file/_write_file sandboxing —
added after an OWASP-style review found both tools accepted ANY absolute
path on the filesystem with zero restriction. Combined with the model's
known jailbreak susceptibility (0% block rate, see docs/SECURITY_AUDIT.md),
a jailbroken model could read secrets (~/.ssh, ~/.env, ~/.orca/auth.db) or
write anywhere the OS user running Orca has permission to.
"""
from __future__ import annotations

import pytest

from orca.tools import _read_file, _write_file, _resolve_in_workspace, WORKSPACE_DIR


@pytest.fixture(autouse=True)
def _isolated_workspace(tmp_path, monkeypatch):
    """Point WORKSPACE_DIR at an isolated temp dir so these tests never
    touch the real ~/.orca/workspace directory."""
    import orca.tools as tools_module
    monkeypatch.setattr(tools_module, "WORKSPACE_DIR", tmp_path)
    yield tmp_path


def test_write_then_read_inside_workspace_works_normally(tmp_path):
    result = _write_file("notes.txt", "hello world")
    assert "Written" in result
    assert (tmp_path / "notes.txt").read_text() == "hello world"

    read_back = _read_file("notes.txt")
    assert read_back == "hello world"


def test_write_creates_subdirectories_inside_workspace(tmp_path):
    _write_file("subdir/nested/notes.txt", "content")
    assert (tmp_path / "subdir" / "nested" / "notes.txt").read_text() == "content"


def test_read_rejects_absolute_path_outside_workspace():
    result = _read_file("/etc/passwd")
    assert "Access denied" in result


def test_write_rejects_absolute_path_outside_workspace(tmp_path):
    result = _write_file("/tmp/should-not-be-written-here.txt", "malicious content")
    assert "Access denied" in result


def test_read_rejects_home_directory_secrets():
    result = _read_file("~/.ssh/id_rsa")
    assert "Access denied" in result


def test_read_rejects_dotdot_traversal_escaping_workspace(tmp_path):
    # tmp_path IS the workspace; ../../../etc/passwd should escape it and be denied.
    result = _read_file("../../../../../../etc/passwd")
    assert "Access denied" in result


def test_write_rejects_dotdot_traversal_escaping_workspace(tmp_path):
    result = _write_file("../../../../../../tmp/escaped.txt", "malicious")
    assert "Access denied" in result


def test_read_file_not_found_inside_workspace_is_a_normal_message_not_denial(tmp_path):
    result = _read_file("does-not-exist.txt")
    assert "File not found" in result
    assert "Access denied" not in result


def test_resolve_in_workspace_returns_none_for_escaping_path(tmp_path):
    assert _resolve_in_workspace("/etc/passwd") is None
    assert _resolve_in_workspace("../outside.txt") is None


def test_resolve_in_workspace_returns_real_path_for_valid_relative_path(tmp_path):
    resolved = _resolve_in_workspace("a/b/c.txt")
    assert resolved is not None
    assert resolved == (tmp_path / "a" / "b" / "c.txt").resolve()
