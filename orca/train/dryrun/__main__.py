"""Launcher for `python -m orca.train.dryrun`.

The synthetic run happens in a CHILD interpreter started with a scrubbed environment (no API keys, no proxy variables, a throw-away
ORNEUR_HOME, no user site, no PYTHON* variables), so the dry-run cannot see credentials or write into the operator's real ~/.orca.
Nothing about the child's behaviour depends on an environment switch: the marker below only selects "am I the child".
"""
from __future__ import annotations

import os
import subprocess
import sys
import tempfile
from pathlib import Path

_CHILD = "ORNEUR_DRYRUN_CHILD"


def main(argv=None) -> int:
    argv = list(sys.argv[1:] if argv is None else argv)
    if os.environ.get(_CHILD) == "1":
        from orca.train.dryrun.cli import run_cli
        return run_cli(argv)
    repo = Path(__file__).resolve().parents[3]
    with tempfile.TemporaryDirectory(prefix="orneur-dryrun-home-") as home:
        env = {"PATH": os.defpath, "LANG": "C.UTF-8", "PYTHONHASHSEED": "0", "ORNEUR_HOME": home, _CHILD: "1", "HOME": home,
               "CUDA_VISIBLE_DEVICES": "", "HF_HUB_OFFLINE": "1", "TRANSFORMERS_OFFLINE": "1", "WANDB_MODE": "disabled"}
        proc = subprocess.run([sys.executable, "-E", "-s", "-m", "orca.train.dryrun", *argv], cwd=str(repo), env=env, check=False)
    return proc.returncode


if __name__ == "__main__":
    raise SystemExit(main())
