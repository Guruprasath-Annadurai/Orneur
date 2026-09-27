#!/usr/bin/env python3
"""Owner preflight: prove the private vault is isolated from the public repository. Exit 0 = PASS, 2 = FAIL. Creates nothing; prints no secret.

  python scripts/genesis_v2_vault_verify.py --vault /ABSOLUTE/PATH/TO/VAULT        (placeholder: your own path, chosen by you)
"""
import argparse
import json
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))
from orca.eval.genesis_v2.vault_verify import verify_vault_isolation  # noqa: E402

if __name__ == "__main__":
    ap = argparse.ArgumentParser()
    ap.add_argument("--vault", required=True)
    a = ap.parse_args()
    r = verify_vault_isolation(Path(a.vault), ROOT)
    print(json.dumps(r, indent=1))
    print("VAULT ISOLATION PASS" if r["pass"] else "VAULT ISOLATION FAIL")
    sys.exit(0 if r["pass"] else 2)
