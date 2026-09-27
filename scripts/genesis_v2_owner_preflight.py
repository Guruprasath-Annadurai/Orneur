#!/usr/bin/env python3
"""Single deterministic owner-setup preflight for Genesis Capability Eval V2. Never generates a corpus, secret, or key.

  python scripts/genesis_v2_owner_preflight.py
"""
import json
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))
from orca.eval.genesis_v2 import owner_preflight as OP  # noqa: E402

if __name__ == "__main__":
    r = OP.run(ROOT)
    print(json.dumps(r, indent=1))
    print(r["result"])
    sys.exit(0 if r["result"] == "READY_FOR_PRIVATE_CORPUS_AUTHORIZATION" else 2)
