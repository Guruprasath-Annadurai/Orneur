#!/usr/bin/env python3
"""End-to-end SYNTHETIC demonstration of the evalinfra pipeline.

SYNTHETIC - NOT EVIDENCE OF ANY MODEL CAPABILITY. No model is run, nothing is downloaded, no network or provider is contacted, no secret is read or created.
All 'outcomes' are draws from a seeded pseudo-random generator whose per-arm success probabilities are hard-coded in orca/evalinfra/synthetic.py.

Pipeline exercised: synthetic items -> split-separation + leakage checks -> public manifest (commitments only) -> frozen synthetic prereg + analysis plan ->
locked per-arm configurations -> recorded results (hash chain) -> verification -> deterministic JSON+Markdown report -> power tables -> budget refusal.

    python scripts/evalinfra_synthetic_demo.py --out-dir docs/orneur/status/evalinfra/demo
"""
from __future__ import annotations

import argparse
import json
import sys
import tempfile
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from orca.evalinfra import budget as BU                 # noqa: E402
from orca.evalinfra import report as RP                 # noqa: E402
from orca.evalinfra import splits as SPL                # noqa: E402
from orca.evalinfra import stats_power as PW            # noqa: E402
from orca.evalinfra import synthetic as SY              # noqa: E402
from orca.evalinfra.errors import BudgetExceeded       # noqa: E402
from orca.evalinfra.leakage import LeakGuard           # noqa: E402
from orca.evalinfra.results import verify_log          # noqa: E402

BANNER = "SYNTHETIC - NOT EVIDENCE OF ANY MODEL CAPABILITY"
CATEGORIES = (3, 4, 10, 11, 12, 14, 15, 17)
SEED = 20261011


def _dump(path: Path, obj) -> None:
    path.write_text(json.dumps(obj, sort_keys=True, indent=2, ensure_ascii=False, allow_nan=False) + "\n")


def run(out_dir: Path, *, holdout_per_cat: int = 60, resamples: int = 10_000) -> dict:
    out_dir = Path(out_dir)
    out_dir.mkdir(parents=True, exist_ok=True)
    log_path = out_dir / "result_chain.jsonl"
    if log_path.exists():
        log_path.unlink()
    ex = SY.build_experiment(log_path, seed=SEED, categories=CATEGORIES, holdout_per_cat=holdout_per_cat, resamples=resamples)

    # 1. split separation + leakage self-checks on the synthetic corpus (negative controls prove the checks can fail)
    sep = SPL.check_split_separation(ex["items"], canaries={"TRAIN": ["CANARY-TRAIN-synthetic-0001-aaaa"], "QUALIFICATION_HOLDOUT": ["CANARY-HOLDOUT-synthetic-0002-bbbb"]})
    leaky = [dict(i) for i in ex["items"]]
    victim = next(i for i in leaky if i["split"] == "QUALIFICATION_HOLDOUT")
    victim["prompt"] = victim["prompt"] + " CANARY-TRAIN-synthetic-0001-aaaa"
    neg = SPL.check_split_separation(leaky, canaries={"TRAIN": ["CANARY-TRAIN-synthetic-0001-aaaa"]})
    guard = LeakGuard(items=ex["items"], canaries=["CANARY-HOLDOUT-synthetic-0002-bbbb"])
    leak_clean = guard.scan({"rows": [{"item_id": "syn-x", "score": 1.0}]})
    leak_dirty = guard.scan({"debug": "CANARY-HOLDOUT-synthetic-0002-bbbb", "prompt": "x"})
    checks = {"banner": BANNER, "split_separation_on_synthetic_corpus": {"status": sep.status, "pairs_checked": sep.checked_pairs, "findings": len(sep.findings)},
              "negative_control_canary_in_wrong_split": {"status": neg.status, "finding_kinds": sorted({f["check"] for f in neg.findings})},
              "leak_guard_on_clean_artifact": {"findings": len(leak_clean)}, "leak_guard_negative_control": {"finding_kinds": sorted({f["kind"] for f in leak_dirty})}}

    # 2. power tables (blueprint section 6.6)
    power = {"banner": BANNER, "alpha": 0.05, "power": 0.8, "required_n_ceil": {str(d): {str(p): n for p, n in row.items()} for d, row in PW.sample_size_table().items()},
             "required_n_nearest_as_in_blueprint": {str(d): {str(p): n for p, n in row.items()} for d, row in PW.sample_size_table(rounding="nearest").items()},
             "mde_points_at_p_d_0.20": {str(n): round(v * 100, 1) for n, v in PW.mde_table().items()},
             "bonferroni_8_comparisons_n_for_5pts_p_d_0.20": PW.required_n(0.05, 0.20, alpha=PW.bonferroni_alpha(0.05, 8)),
             "mde_points_of_this_demo_per_category_n": (None if PW.mde(holdout_per_cat, 0.20) is None else round(PW.mde(holdout_per_cat, 0.20) * 100, 1))}

    # 3. budget: default cap 0 refuses everything; a synthetic cap then refuses an over-cap operation BEFORE it runs
    with tempfile.TemporaryDirectory() as td:
        led = BU.BudgetLedger(Path(td) / "budget.jsonl")
        events = []

        def attempt(op, cost, **kw):
            try:
                led.reserve(op, cost, **kw)
                events.append({"op": op, "cost_usd": cost, "result": "RESERVED"})
            except BudgetExceeded as e:
                events.append({"op": op, "cost_usd": cost, "result": "REFUSED", "code": e.code})
        attempt("op-default-cap", 0)
        led.configure(10, 0.2, authorization_ref="SYNTHETIC-DEMO-AUTHORIZATION-REF")
        attempt("op-1", 5)
        attempt("op-2", 3)
        attempt("op-3-would-exceed-ordinary-cap", 0.5)
        attempt("op-4-contingency", 1.5, use_contingency=True, reason="synthetic demonstration of a contingency draw")
        attempt("op-5-would-exceed-hard-cap", 0.6, use_contingency=True, reason="synthetic demonstration of a refused draw")
        budget = {"banner": BANNER, "events": events, "final_state": led.state()}

    # 4. artifacts
    _dump(out_dir / "manifest.json", ex["manifest"])
    _dump(out_dir / "prereg.json", ex["prereg"])
    _dump(out_dir / "analysis_plan.json", ex["plan"])
    _dump(out_dir / "arm_configs.json", ex["configs"])
    _dump(out_dir / "isolation_and_leakage_checks.json", checks)
    _dump(out_dir / "power_tables.json", power)
    _dump(out_dir / "budget_demo.json", budget)
    summary = verify_log(log_path)
    _dump(out_dir / "verification.json", {"banner": BANNER, "verify_result": summary})
    rep = RP.build_report(log_path, ex["prereg"], ex["plan"], allow_synthetic=True)
    (out_dir / "report.json").write_text(RP.report_json_text(rep))
    (out_dir / "report.md").write_text(RP.render_markdown(rep))
    (out_dir / "SYNTHETIC_NOT_EVIDENCE.md").write_text(
        f"# {BANNER}\n\n"
        "Everything in this directory was generated by `scripts/evalinfra_synthetic_demo.py` from a seeded pseudo-random generator. No model was run, no data from any real\n"
        "benchmark was used, no network or provider was contacted, no secret exists here, and the 'preregistration' in `prereg.json` is a SYNTHETIC fixture (its `eval_version`\n"
        "is `SYNTHETIC-DEMO/0`); it is NOT the repository's V2 preregistration, which remains DRAFT_NOT_FROZEN.\n\n"
        "The per-arm success probabilities were typed into `orca/evalinfra/synthetic.py` (DEFAULT_RATES). A 'SUPPORTED' decision in `report.md` therefore only shows that the\n"
        "pipeline can recover an effect that was planted by construction; it says nothing about B0/B1/B2/T1/T2 or any real model.\n\n"
        "Regenerate: `python scripts/evalinfra_synthetic_demo.py --out-dir docs/orneur/status/evalinfra/demo` (output is byte-for-byte reproducible; a test enforces this).\n"
        f"Verify the chain: `python -m orca.evalinfra verify {out_dir.name}/result_chain.jsonl`.\n")
    return {"report": rep, "verify": summary}


def main(argv=None) -> int:
    ap = argparse.ArgumentParser(description=__doc__.split("\n\n")[0])
    ap.add_argument("--out-dir", required=True)
    ap.add_argument("--holdout-per-category", type=int, default=60)
    a = ap.parse_args(argv)
    res = run(Path(a.out_dir), holdout_per_cat=a.holdout_per_category)
    print(BANNER)
    print(f"wrote demo artifacts to {a.out_dir}; chain entries: {res['verify']['entries']}, results: {res['verify']['results']}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
