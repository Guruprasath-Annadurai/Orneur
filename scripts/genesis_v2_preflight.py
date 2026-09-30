#!/usr/bin/env python3
"""Role-separated setup preflight for Genesis Capability Eval V2. Reads only environment-variable PRESENCE; prints
no values. Exit 2 if not configured (or, for --role generator, if a security violation is found).

  python scripts/genesis_v2_preflight.py --role owner        # OWNER-CONTROLLED CONTEXT ONLY -- the only role that
                                                               # legitimately checks both vault-key halves together
                                                               # and cross-validates they form a matching keypair.
  python scripts/genesis_v2_preflight.py --role generator    # run FROM a generator's own deployment environment.
  python scripts/genesis_v2_preflight.py --role verifier     # run FROM a verifier/qualification-runner's own
                                                               # deployment environment.

Never run --role owner from a real generator or verifier deployment: it requires both key halves and defeats the
whole point of keeping them apart. Defaults to --role owner ONLY for backward compatibility with prior invocations
of this script; always pass --role explicitly for a real deployment check.
"""
import argparse
import json
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
from orca.eval.genesis_v2.store import generator_setup_preflight, owner_setup_preflight, verifier_setup_preflight  # noqa: E402

ROLE_FUNCS = {"owner": owner_setup_preflight, "generator": generator_setup_preflight, "verifier": verifier_setup_preflight}

if __name__ == "__main__":
    parser = argparse.ArgumentParser()
    parser.add_argument("--role", choices=sorted(ROLE_FUNCS), default="owner")
    args = parser.parse_args()
    rep = ROLE_FUNCS[args.role]()
    print(json.dumps(rep, indent=1))
    failed = bool(rep["missing"]) or bool(rep.get("violations"))
    sys.exit(0 if not failed else 2)
