#!/usr/bin/env python3
"""Verify requirements/train.txt is a structurally valid hash lock of the `train` extra (TRAIN-1).

  python scripts/trainprep/verify_train_lock.py [--lock requirements/train.txt] [--pyproject pyproject.toml]

Checks that every requirement is pinned with ==, carries at least one sha256 --hash, nothing redirects resolution (no URL/VCS/-e/index
options), and every `train`-extra package that applies on Python 3.11 is present. It downloads nothing and installs nothing: proving the
hashes against the index is `uv pip install --require-hashes -r requirements/train.txt`, which this script deliberately never runs.
Exit 0 ok / 1 problems. Prints one JSON document.
"""
from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path

REPO = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(REPO))

from orca.train.dryrun.lockcheck import check_lock_file, train_extra_requirements  # noqa: E402


def main(argv=None) -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--lock", default=str(REPO / "requirements" / "train.txt"))
    ap.add_argument("--pyproject", default=str(REPO / "pyproject.toml"))
    args = ap.parse_args(argv)
    required = train_extra_requirements(args.pyproject)
    rep = check_lock_file(args.lock, required_names=required)
    print(json.dumps({"ok": rep.ok, "lock": args.lock, "sha256": rep.sha256, "packages": rep.packages, "hashes": rep.hashes,
                      "required_from_train_extra": required, "problems": rep.problems}, indent=2))
    return 0 if rep.ok else 1


if __name__ == "__main__":
    raise SystemExit(main())
