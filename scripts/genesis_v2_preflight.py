#!/usr/bin/env python3
"""Owner-setup preflight for Genesis Capability Eval V2. Reads only environment-variable PRESENCE; prints no values. Exit 2 if not configured."""
import json
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
from orca.eval.genesis_v2.store import owner_setup_preflight  # noqa: E402

if __name__ == "__main__":
    rep = owner_setup_preflight()
    print(json.dumps(rep, indent=1))
    sys.exit(0 if not rep["missing"] else 2)
