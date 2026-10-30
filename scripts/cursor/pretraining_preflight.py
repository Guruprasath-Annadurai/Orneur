#!/usr/bin/env python3
"""Local preflight for the pre-training foundation. Does not accept requirements.

Prints the git SHA, the acceptance-register validator line, and the
model-family statuses. Exit 0 means those commands ran. It does not mean
training is authorized.
"""
from __future__ import annotations

import argparse
import json
import subprocess
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from orca.genesis.model.family_registry import default_registry  # noqa: E402
from orca.pretrain_foundation.compute_scenarios import frontier_pretraining_available  # noqa: E402


def _git_sha() -> str:
    out = subprocess.check_output(["git", "rev-parse", "HEAD"], cwd=ROOT, text=True)
    return out.strip()


def _register_line() -> str:
    out = subprocess.check_output(
        [sys.executable, "scripts/acceptance/validate_register_graph.py", "--check"],
        cwd=ROOT,
        text=True,
    )
    return out.strip()


def main() -> int:
    parser = argparse.ArgumentParser(description="Pre-training foundation preflight")
    parser.add_argument("--json", action="store_true", dest="as_json")
    args = parser.parse_args()
    registry = {
        family: {"status": record.status, "notes": record.notes}
        for family, record in default_registry().items()
    }
    payload = {
        "git_sha": _git_sha(),
        "acceptance_register": _register_line(),
        "model_families": registry,
        "frontier_pretraining_available": frontier_pretraining_available(),
        "training_authorized": False,
        "requirements_accepted_by_this_tool": False,
    }
    if args.as_json:
        print(json.dumps(payload, indent=2, sort_keys=True))
    else:
        print(f"git_sha={payload['git_sha']}")
        print(payload["acceptance_register"])
        for family, row in registry.items():
            print(f"{family} status={row['status']}")
        print("training_authorized=false")
        print("requirements_accepted_by_this_tool=false")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
