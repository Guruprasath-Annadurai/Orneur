"""
Regression tests for the path-traversal / prefix-confusion vulnerability in
orca/mcp/fs_server.py's _safe_path(). The original implementation used
`str(path).startswith(str(allowed_root))`, a substring check that a sibling
directory whose name happens to start with the same characters as the
allowed root can defeat -- e.g. allowed root "/safe/data" would also accept
"/safe/database-secret" because the STRING "/safe/database-secret" starts
with the STRING "/safe/data", even though the directory is not inside it.

Fixed via proper path-ancestry resolution (Path.resolve() + relative_to),
matching the pattern already proven correct in orca/tools/__init__.py's
_resolve_in_workspace().
"""
from __future__ import annotations

import os
from pathlib import Path

import pytest

from orca.mcp import fs_server


@pytest.fixture
def isolated_root(tmp_path, monkeypatch):
    """Point fs_server's allowed roots at a throwaway directory tree."""
    allowed = tmp_path / "safe" / "data"
    allowed.mkdir(parents=True)
    (allowed / "inside.txt").write_text("ok")

    # A sibling directory whose name is a superstring of the allowed root's
    # own string -- the exact shape of the prefix-confusion bug.
    sibling = tmp_path / "safe" / "database-secret"
    sibling.mkdir(parents=True)
    (sibling / "secret.txt").write_text("should not be reachable")

    monkeypatch.setattr(fs_server, "_allowed_roots", [allowed])
    return allowed, sibling


def test_valid_path_inside_allowed_root_succeeds(isolated_root):
    allowed, _ = isolated_root
    resolved = fs_server._safe_path(str(allowed / "inside.txt"))
    assert resolved == (allowed / "inside.txt").resolve()


def test_dotdot_traversal_is_rejected(isolated_root):
    allowed, _ = isolated_root
    with pytest.raises(PermissionError):
        fs_server._safe_path(str(allowed / ".." / ".." / "etc" / "passwd"))


def test_absolute_path_escape_is_rejected(isolated_root):
    with pytest.raises(PermissionError):
        fs_server._safe_path("/etc/passwd")


def test_sibling_prefix_confusion_is_rejected(isolated_root):
    """
    THE bug: allowed root ".../safe/data" must not admit ".../safe/database-secret"
    just because the strings share a prefix. This is the exact class of bug
    named in the security audit (allowed root /safe/data, malicious target
    /safe/database-secret).
    """
    _, sibling = isolated_root
    with pytest.raises(PermissionError):
        fs_server._safe_path(str(sibling / "secret.txt"))


def test_symlink_escape_is_rejected(isolated_root, tmp_path):
    allowed, _ = isolated_root
    outside = tmp_path / "outside"
    outside.mkdir()
    (outside / "real_secret.txt").write_text("nope")

    link = allowed / "escape_link"
    try:
        os.symlink(outside, link)
    except (OSError, NotImplementedError):
        pytest.skip("symlinks not supported in this environment")

    with pytest.raises(PermissionError):
        fs_server._safe_path(str(link / "real_secret.txt"))
