"""
ORNEUR packaging invariant. Builds the wheel from the current source tree
and asserts it actually contains the ORNEUR runtime, not just the legacy
`orca` package -- closing a real, reproduced pre-fix defect: before this
closure, `[tool.hatch.build.targets.wheel] packages = ["orca"]` meant the
built wheel never shipped `orneur/intelligence/ocl` at all, so
`import orneur.intelligence.ocl` would fail for anyone installing the
published distribution (it only ever worked via the repository's own
`pythonpath = ["."]` pytest setting, which hides a broken wheel).

Building a wheel is slow-ish (~5-10s including hatchling's isolated env
setup avoided here via direct hatchling build backend call) so this is
one test, not many -- it builds once per test session and asserts several
things about the same artifact.
"""
from __future__ import annotations

import subprocess
import sys
import tempfile
import zipfile
from pathlib import Path

import pytest

REPO_ROOT = Path(__file__).resolve().parent.parent

REQUIRED_WHEEL_PATHS = [
    "orca/",
    "orneur/",
    "orneur/intelligence/",
    "orneur/intelligence/ocl/",
    "orneur/intelligence/ocl/compiler.py",
    "orneur/intelligence/ocl/artifact.py",
    "orneur/intelligence/ocl/canonical.py",
]


@pytest.fixture(scope="module")
def built_wheel(tmp_path_factory):
    out_dir = tmp_path_factory.mktemp("orneur_wheel_build")
    result = subprocess.run(
        [sys.executable, "-m", "build", "--wheel", "--outdir", str(out_dir)],
        cwd=REPO_ROOT, capture_output=True, text=True, timeout=180,
    )
    assert result.returncode == 0, f"wheel build failed:\n{result.stdout}\n{result.stderr}"
    wheels = list(out_dir.glob("*.whl"))
    assert len(wheels) == 1, f"expected exactly one wheel, got {wheels}"
    return wheels[0]


def test_wheel_contains_both_orca_and_orneur_packages(built_wheel):
    with zipfile.ZipFile(built_wheel) as z:
        names = z.namelist()
    for required in REQUIRED_WHEEL_PATHS:
        assert any(n == required or n.startswith(required) for n in names), (
            f"wheel is missing required path {required!r} -- "
            f"see docs/orneur/brand/ORNEUR_PACKAGING_MIGRATION.md"
        )


def test_wheel_metadata_identifies_as_orneur(built_wheel):
    with zipfile.ZipFile(built_wheel) as z:
        names = z.namelist()
        metadata_path = next(n for n in names if n.endswith(".dist-info/METADATA"))
        metadata = z.read(metadata_path).decode("utf-8")

    assert "Name: orneur" in metadata
    assert "Orca Systems" not in metadata  # the unrelated third-party PyPI publisher
    assert "atheris.ai" not in metadata.lower()
    assert "github.com/Guruprasath-Annadurai/Orneur" in metadata


def test_wheel_console_scripts_include_orneur_primary_and_orca_alias(built_wheel):
    with zipfile.ZipFile(built_wheel) as z:
        names = z.namelist()
        entry_points_path = next(n for n in names if n.endswith(".dist-info/entry_points.txt"))
        entry_points = z.read(entry_points_path).decode("utf-8")

    assert "orneur = orca.cli:app" in entry_points
    assert "orca = orca.cli:app" in entry_points  # legacy compatibility alias, not removed


def test_isolated_install_can_import_ocl_and_run_cli(built_wheel):
    """Installs the built wheel into a FRESH virtualenv (not the repo's own
    .venv, and not relying on `pythonpath = ["."]`) and verifies the
    package actually works from the installed distribution -- proving
    packaging, not source-tree import behavior."""
    with tempfile.TemporaryDirectory() as tmp:
        venv_dir = Path(tmp) / "venv"
        subprocess.run([sys.executable, "-m", "venv", str(venv_dir)], check=True, timeout=60)
        venv_python = venv_dir / "bin" / "python"

        install = subprocess.run(
            [str(venv_python), "-m", "pip", "install", "--quiet", str(built_wheel)],
            capture_output=True, text=True, timeout=120,
        )
        assert install.returncode == 0, f"isolated install failed:\n{install.stdout}\n{install.stderr}"

        import_check = subprocess.run(
            [str(venv_python), "-c", "import orneur.intelligence.ocl; print('OK')"],
            capture_output=True, text=True, timeout=30,
        )
        assert import_check.returncode == 0, f"isolated import failed:\n{import_check.stdout}\n{import_check.stderr}"
        assert "OK" in import_check.stdout

        venv_orneur = venv_dir / "bin" / "orneur"
        help_check = subprocess.run(
            [str(venv_orneur), "--help"], capture_output=True, text=True, timeout=30,
        )
        assert help_check.returncode == 0, f"orneur --help failed:\n{help_check.stdout}\n{help_check.stderr}"
        assert "Orneur" in help_check.stdout

        venv_orca = venv_dir / "bin" / "orca"
        legacy_check = subprocess.run(
            [str(venv_orca), "--help"], capture_output=True, text=True, timeout=30,
        )
        assert legacy_check.returncode == 0, f"legacy orca --help failed:\n{legacy_check.stdout}\n{legacy_check.stderr}"
