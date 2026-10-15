#!/usr/bin/env python3
"""Generate or check docs/orneur/status/trainprep/OFFHOST_NOTEBOOK_INVENTORY.json (read-only scan; executes nothing).

  python scripts/trainprep/offhost_inventory.py --write   # regenerate the committed inventory
  python scripts/trainprep/offhost_inventory.py --check   # exit 1 if the repo and the inventory disagree (what CI runs)
"""
from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path

REPO = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(REPO))

from orca.train.dryrun import inventory as inv  # noqa: E402


def main(argv=None) -> int:
    ap = argparse.ArgumentParser()
    g = ap.add_mutually_exclusive_group(required=True)
    g.add_argument("--write", action="store_true")
    g.add_argument("--check", action="store_true")
    args = ap.parse_args(argv)
    target = REPO / inv.INVENTORY_REL
    if args.write:
        target.parent.mkdir(parents=True, exist_ok=True)
        target.write_bytes(inv.inventory_bytes(inv.build_inventory(REPO)))
        print(f"wrote {inv.INVENTORY_REL}")
        return 0
    problems = inv.compare(REPO, json.loads(target.read_text()))
    print(json.dumps({"ok": not problems, "problems": problems}, indent=2))
    return 1 if problems else 0


if __name__ == "__main__":
    raise SystemExit(main())
