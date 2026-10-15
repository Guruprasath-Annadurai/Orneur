"""The reconciled test.yml preview stays complete and parses as real YAML."""

import subprocess
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]


def test_reconciled_preview_matches_expected_shape():
    proc = subprocess.run(
        [sys.executable, "scripts/ci/validate_reconciled_workflow_preview.py"],
        cwd=ROOT,
        capture_output=True,
        text=True,
        check=False,
    )
    assert proc.returncode == 0, proc.stderr + proc.stdout
    assert "9 jobs" in proc.stdout
