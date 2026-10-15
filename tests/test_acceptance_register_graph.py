"""The master acceptance graph stays acyclic and matches the frozen C-ids."""

import subprocess
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]


def test_acceptance_register_graph_matches_sources():
    proc = subprocess.run(
        [
            sys.executable,
            "scripts/acceptance/validate_register_graph.py",
            "--check",
            "--self-test",
        ],
        cwd=ROOT,
        capture_output=True,
        text=True,
        check=False,
    )
    assert proc.returncode == 0, proc.stderr + proc.stdout
    assert "numerator=0" in proc.stdout
