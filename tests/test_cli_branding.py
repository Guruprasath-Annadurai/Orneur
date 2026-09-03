"""
Regression coverage for orca/cli.py's Orneur rebrand (commit cc732b0),
which had zero test coverage before this file -- a real, pre-existing
gap (orca/cli.py had no tests of any kind prior to this) surfaced during
Phase 12.1's baseline-lineage audit rather than introduced by the rename
itself.
"""
from __future__ import annotations

from typer.testing import CliRunner

from orca.cli import app

runner = CliRunner()


def test_typer_app_name_is_orneur():
    assert app.info.name == "orneur"


def test_version_flag_reports_orneur():
    result = runner.invoke(app, ["--version"])
    assert result.exit_code == 0
    assert result.stdout.strip().startswith("orneur ")


def test_help_still_works():
    result = runner.invoke(app, ["--help"])
    assert result.exit_code == 0
