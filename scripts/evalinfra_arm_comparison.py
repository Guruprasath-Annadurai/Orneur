#!/usr/bin/env python3
"""Four-arm research-comparison tooling. SYNTHETIC - NOT EVIDENCE OF ANY MODEL CAPABILITY.

No model is run (only deterministic in-process doubles), no network/GPU/provider is used, nothing is trained or selected.

    python scripts/evalinfra_arm_comparison.py validate DEFINITIONS.json     # exit 0 only if the comparison is acceptable (fail closed)
    python scripts/evalinfra_arm_comparison.py example OUT.json              # write a valid synthetic example definition
    python scripts/evalinfra_arm_comparison.py demo --out-dir DIR [--definitions F]   # validate, run doubles, write chain + arm-labelled report
    python scripts/evalinfra_arm_comparison.py check-prereg [DIR]            # validate the C1/C2/C3 draft templates
"""
from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from orca.evalinfra import arm_report as AP            # noqa: E402
from orca.evalinfra import arm_runner as AX            # noqa: E402
from orca.evalinfra import arms as AR                  # noqa: E402
from orca.evalinfra import prereg_templates as PT      # noqa: E402
from orca.evalinfra.errors import EvalInfraError      # noqa: E402


def _dump(path: Path, obj) -> None:
    path.write_text(json.dumps(obj, sort_keys=True, indent=2, ensure_ascii=False, allow_nan=False) + "\n")


def main(argv=None) -> int:
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    sub = ap.add_subparsers(dest="cmd", required=True)
    sub.add_parser("validate").add_argument("definitions")
    sub.add_parser("example").add_argument("out")
    d = sub.add_parser("demo")
    d.add_argument("--out-dir", required=True)
    d.add_argument("--definitions")
    d.add_argument("--holdout-per-cat", type=int, default=40)
    sub.add_parser("check-prereg").add_argument("dir", nargs="?")
    a = ap.parse_args(argv)
    print(AR.BANNER, file=sys.stderr)
    try:
        if a.cmd == "validate":
            print(json.dumps(AR.require_valid(json.loads(Path(a.definitions).read_text())), sort_keys=True, indent=2))
        elif a.cmd == "example":
            _dump(Path(a.out), AR.make_example_definitions())
        elif a.cmd == "check-prereg":
            probs = PT.validate_programme(PT.load_templates(a.dir))
            print(json.dumps({"ok": not probs, "problems": probs, "note": "draft templates: not frozen, not approved"}, indent=2))
            return 0 if not probs else 1
        else:
            out = Path(a.out_dir)
            out.mkdir(parents=True, exist_ok=True)
            defn = json.loads(Path(a.definitions).read_text()) if a.definitions else AR.make_example_definitions()
            log = out / "result_chain.jsonl"
            if log.exists():
                log.unlink()
            ex = AX.run_comparison(defn, log, holdout_per_cat=a.holdout_per_cat)
            rep = AP.build_arm_report(log, defn, ex["prereg"], ex["plan"])
            _dump(out / "arm_definitions.json", defn)
            _dump(out / "arm_report.json", rep)
            (out / "arm_report.md").write_text(AP.render_markdown(rep))
            print(f"wrote {out} (chain, definitions, arm_report.json/.md)")
    except EvalInfraError as e:
        print(f"REFUSED: {e}", file=sys.stderr)
        return 2
    return 0


if __name__ == "__main__":
    sys.exit(main())
