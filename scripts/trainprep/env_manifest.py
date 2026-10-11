#!/usr/bin/env python3
"""Emit (or verify) the deterministic reproducible-environment manifest.

  python scripts/trainprep/env_manifest.py --code-sha <40hex> --dataset-bundle-sha256 <64hex> --seed 1234 [--seed-name data_seed=99]
  python scripts/trainprep/env_manifest.py --verify manifest.json

The code SHA and dataset bundle hash are INJECTED (never discovered here). The container digest is reported as null / NOT_BUILT because no
image has been built. Output is canonical JSON: same inputs -> same bytes.
"""
from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path

REPO = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(REPO))

from orca.train.dryrun.envmanifest import build_env_manifest, env_manifest_bytes, verify_env_manifest  # noqa: E402


def main(argv=None) -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--code-sha")
    ap.add_argument("--dataset-bundle-sha256")
    ap.add_argument("--seed", type=int, default=None)
    ap.add_argument("--seed-name", action="append", default=[], help="extra name=int seeds")
    ap.add_argument("--lock", default=str(REPO / "requirements" / "train.txt"))
    ap.add_argument("--verify")
    args = ap.parse_args(argv)
    if args.verify:
        problems = verify_env_manifest(json.loads(Path(args.verify).read_text()))
        print(json.dumps({"ok": not problems, "problems": problems}))
        return 1 if problems else 0
    if not (args.code_sha and args.dataset_bundle_sha256 and args.seed is not None):
        ap.error("--code-sha, --dataset-bundle-sha256 and --seed are required (they are injected, never guessed)")
    seeds = {"seed": args.seed, **{k: int(v) for k, v in (s.split("=", 1) for s in args.seed_name)}}
    sys.stdout.buffer.write(env_manifest_bytes(build_env_manifest(code_sha=args.code_sha, dataset_bundle_sha256=args.dataset_bundle_sha256,
                                                                  seeds=seeds, lock_path=args.lock)))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
