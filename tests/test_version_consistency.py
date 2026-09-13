"""
Version-string consistency invariant. Before this closure, three
independent version literals existed and had drifted:
pyproject.toml's `version = "1.0.0"` (deliberately bumped at commit
80964a3, "Tier 1 enterprise features"), orca/__version__.py's
`__version__ = "0.1.1"` (never updated in that bump -- this is what
`orneur --version` and the self-updater's fallback actually reported),
and orca/__init__.py's `__version__ = "0.1.0"` (unused by any real code
path, but still a third stale literal).

Evidence (git history of pyproject.toml) shows 1.0.0 was the deliberate,
intentional version; the other two were simply never updated in that
commit. This test prevents that drift from recurring by asserting all
three literals stay in sync -- pyproject.toml remains the canonical
source a human bumps; the other two must be updated in the same commit.
"""
from __future__ import annotations

import re
import tomllib
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parent.parent


def _pyproject_version() -> str:
    data = tomllib.loads((REPO_ROOT / "pyproject.toml").read_text(encoding="utf-8"))
    return data["project"]["version"]


def _literal_version(path: Path) -> str:
    text = path.read_text(encoding="utf-8")
    match = re.search(r'__version__\s*=\s*"([^"]+)"', text)
    assert match, f"{path} has no __version__ = \"...\" literal"
    return match.group(1)


def test_orca_version_module_matches_pyproject():
    assert _literal_version(REPO_ROOT / "orca/__version__.py") == _pyproject_version()


def test_orca_init_module_matches_pyproject():
    assert _literal_version(REPO_ROOT / "orca/__init__.py") == _pyproject_version()


def test_cli_version_flag_reports_the_canonical_version():
    from typer.testing import CliRunner

    from orca.cli import app

    runner = CliRunner()
    result = runner.invoke(app, ["--version"])
    assert result.exit_code == 0
    assert _pyproject_version() in result.stdout


def test_upgrade_module_fallback_version_matches_pyproject():
    from orca.upgrade import _current_version

    # _current_version() prefers importlib.metadata (the INSTALLED
    # distribution's version, which reflects pyproject.toml at install
    # time) and falls back to orca.__version__ only if that lookup fails
    # (e.g. running from an unbuilt source checkout). Either path must
    # agree with the source-of-truth pyproject.toml version checked out
    # right now.
    reported = _current_version()
    assert reported == _pyproject_version() or reported == _literal_version(REPO_ROOT / "orca/__version__.py")
