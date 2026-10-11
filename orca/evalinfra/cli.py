"""Command line: python -m orca.evalinfra <verify|report|prereg-check|sample-size|mde> ...  (no network, no model, no secrets)."""
from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path

from orca.evalinfra import prereg_check as PC
from orca.evalinfra import report as RP
from orca.evalinfra import stats_power as PW
from orca.evalinfra.errors import EvalInfraError
from orca.evalinfra.results import verify_log

DEFAULT_SCHEMA = "docs/orneur/phase-21/GENESIS_CAPABILITY_EVAL_V2_PREREGISTRATION_SCHEMA.json"


def _load(path):
    return json.loads(Path(path).read_text())


def main(argv=None) -> int:
    ap = argparse.ArgumentParser(prog="python -m orca.evalinfra")
    sub = ap.add_subparsers(dest="cmd", required=True)
    v = sub.add_parser("verify", help="verify a result log (hash chain + provenance rules)")
    v.add_argument("log")
    v.add_argument("--head-seq", type=int)
    v.add_argument("--head-hash")
    r = sub.add_parser("report", help="deterministic JSON+Markdown report from a verified log")
    r.add_argument("log")
    r.add_argument("--prereg", required=True)
    r.add_argument("--plan", required=True)
    r.add_argument("--out-dir", required=True)
    r.add_argument("--schema", default=None)
    r.add_argument("--allow-synthetic", action="store_true")
    c = sub.add_parser("prereg-check", help="validate a prereg + analysis plan (no chain)")
    c.add_argument("--prereg", required=True)
    c.add_argument("--plan", required=True)
    c.add_argument("--schema", default=None)
    c.add_argument("--allow-synthetic", action="store_true")
    c.add_argument("--draft", action="store_true", help="validate the prereg as a DRAFT (not frozen) -- analysis would still be refused")
    n = sub.add_parser("sample-size")
    n.add_argument("--delta", type=float, required=True)
    n.add_argument("--pd", type=float, required=True)
    n.add_argument("--alpha", type=float, default=0.05)
    n.add_argument("--power", type=float, default=0.80)
    m = sub.add_parser("mde")
    m.add_argument("--n", type=int, required=True)
    m.add_argument("--pd", type=float, required=True)
    m.add_argument("--alpha", type=float, default=0.05)
    m.add_argument("--power", type=float, default=0.80)
    a = ap.parse_args(argv)
    try:
        if a.cmd == "verify":
            head = None if a.head_seq is None else {"seq": a.head_seq, "entry_hash": a.head_hash}
            s = verify_log(a.log, expected_head=head)
            if s["synthetic"]:
                print(RP.SYNTHETIC_BANNER, file=sys.stderr)
            print(json.dumps(s, sort_keys=True, indent=2))
            return 0
        if a.cmd == "report":
            rep = RP.build_report(a.log, _load(a.prereg), _load(a.plan), schema_path=a.schema, allow_synthetic=a.allow_synthetic)
            out = Path(a.out_dir)
            out.mkdir(parents=True, exist_ok=True)
            (out / "report.json").write_text(RP.report_json_text(rep))
            (out / "report.md").write_text(RP.render_markdown(rep))
            print(f"wrote {out / 'report.json'} and {out / 'report.md'}")
            return 0
        if a.cmd == "prereg-check":
            pre, plan = _load(a.prereg), _load(a.plan)
            probs = PC.validate_prereg_document(pre, schema_path=a.schema or DEFAULT_SCHEMA, allow_synthetic=a.allow_synthetic, require_frozen=not a.draft)
            from orca.eval.genesis_v2 import prereg as V2P
            probs += PC.validate_analysis_plan(plan, expected_prereg_sha256=V2P.record_hash(pre))
            print(json.dumps({"valid": not probs, "problems": probs}, indent=2))
            return 0 if not probs else 1
        if a.cmd == "sample-size":
            print(PW.required_n(a.delta, a.pd, a.alpha, a.power))
            return 0
        if a.cmd == "mde":
            print(PW.mde(a.n, a.pd, a.alpha, a.power))
            return 0
    except EvalInfraError as e:
        print(f"REFUSED: {e}", file=sys.stderr)
        return 1
    return 2


if __name__ == "__main__":
    raise SystemExit(main())
