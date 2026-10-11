"""Deterministic reporting from a verified result log (JSON + Markdown).

Preconditions (all enforced): the log verifies; the preregistration is FROZEN, valid and unmodified; the analysis plan is valid and unmodified; both were
chained before the first result. No wall-clock time, no randomness other than the plan's pre-declared bootstrap seed: same inputs => byte-identical output.

Every reported number is labelled with its arm(s), n, interval and endpoint status:
  PRIMARY (confirmatory, multiplicity-adjusted inside its declared family) | EXPLORATORY (unadjusted, hypothesis-generating only) | NOT_EVALUATED (no data; never estimated)
Categories are never merged into one score: the only aggregation anywhere is WITHIN a single category (over its items, and over run replicates by majority vote).
"""
from __future__ import annotations

import math

from orca.evalinfra import prereg_check as PC
from orca.evalinfra import stats_paired as SP
from orca.evalinfra import stats_power as PW
from orca.evalinfra.errors import PreregViolation
from orca.evalinfra.results import verify_log
from orca.evalinfra.chain import ChainLog
from orca.evalinfra.results import KINDS

REPORT_SCHEMA = "orneur-evalinfra-report/1"
SYNTHETIC_BANNER = "SYNTHETIC - NOT EVIDENCE OF ANY MODEL CAPABILITY"


def _r(x, nd: int = 6):
    if isinstance(x, float):
        return None if x != x else round(x, nd)
    return x


def _rl(xs):
    return None if xs is None else [_r(v) for v in xs]


def _collect(entries: list, plan: dict) -> dict:
    """arm -> {"replicates": {rep: {item: score}}, "categories": {item: category}} for the plan's analysis split."""
    arms: dict = {}
    for e in entries:
        if e["kind"] != "RESULT" or e["payload"]["split"] != plan["analysis_split"]:
            continue
        r = e["payload"]
        a = arms.setdefault(r["arm"], {"replicates": {}, "categories": {}})
        a["replicates"][r["replicate"]] = {row["item_id"]: row["score"] for row in r["rows"]}
        for row in r["rows"]:
            a["categories"][row["item_id"]] = row["category"]
    return arms


def _majority(reps: list) -> dict:
    out = {}
    for i in reps[0]:
        vals = [r[i] for r in reps]
        if any(v not in (0, 1) for v in vals):
            raise PreregViolation("METRIC_NOT_BINARY", "confirmatory endpoints require binary item scores (majority vote over replicates)")
        out[i] = 1.0 if sum(vals) * 2 > len(vals) else 0.0
    return out


def build_report(log_path, prereg_doc: dict, plan: dict, *, schema_path=None, allow_synthetic: bool = False) -> dict:
    ver = verify_log(log_path)
    entries = ChainLog(log_path, allowed_kinds=KINDS).entries()
    bound = PC.assert_analysis_allowed(entries, prereg_doc, plan, schema_path=schema_path, allow_synthetic=allow_synthetic)
    synthetic = bool(plan["synthetic"])
    if synthetic != bool(ver["synthetic"]):
        raise PreregViolation("SYNTHETIC_FLAG_MISMATCH", "plan and results disagree about being synthetic")
    R = plan["run_replicates"]
    collected = _collect(entries, plan)
    arm_status, outcomes, replicate_outcomes, categories = {}, {}, {}, {}
    for arm in plan["arms"]:
        a = collected.get(arm)
        if a is None:
            arm_status[arm] = {"status": "NOT_EVALUATED", "reason": "no results recorded for this arm in the analysis split"}
            continue
        if sorted(a["replicates"]) != list(range(R)):
            arm_status[arm] = {"status": "NOT_EVALUATED", "reason": f"incomplete replicates: have {sorted(a['replicates'])}, need 0..{R - 1}"}
            continue
        reps = [a["replicates"][k] for k in range(R)]
        outcomes[arm] = _majority(reps)
        replicate_outcomes[arm] = a["replicates"]
        categories.update(a["categories"])
        arm_status[arm] = {"status": "EVALUATED", "n_items": len(outcomes[arm]), "n_replicates": R}
    evaluated = sorted(outcomes)
    for a in evaluated:
        if set(outcomes[a]) != set(outcomes[evaluated[0]]):
            raise PreregViolation("ARMS_DIFFER_IN_ITEMS", "evaluated arms must cover the same items (paired design)")
    boot = plan["bootstrap"]
    cat_ids = [c for c in plan["categories"] if any(categories.get(i) == c for i in categories)]

    # ---- per-arm, per-category accuracy (descriptive; never pooled across categories)
    descriptive = {}
    for arm in evaluated:
        descriptive[arm] = {}
        for c in cat_ids:
            ids = [i for i in outcomes[arm] if categories[i] == c]
            descriptive[arm][str(c)] = {"arm": arm, "category": c, "n": len(ids), "accuracy": _r(sum(outcomes[arm][i] for i in ids) / len(ids)), "status": "DESCRIPTIVE"}

    # ---- endpoints
    ep_results, pvals = {}, {}
    for e in plan["endpoints"]:
        t, c, cat = e["treatment"], e["control"], e["category"]
        row = {"id": e["id"], "status": e["kind"], "hypothesis": e["hypothesis"], "metric": e["metric"], "treatment": t, "control": c, "category": cat,
               "threshold": e["threshold"]}
        if t not in outcomes or c not in outcomes:
            row.update(result_status="NOT_EVALUATED", reason="an arm has no complete results; nothing is estimated")
            ep_results[e["id"]] = row
            continue
        ids = [i for i in outcomes[t] if categories[i] == cat]
        if not ids:
            row.update(result_status="NOT_EVALUATED", reason="no items in this category in the analysis split")
            ep_results[e["id"]] = row
            continue
        cmp_ = SP.compare_pair({i: outcomes[t][i] for i in ids}, {i: outcomes[c][i] for i in ids},
                               seed=SP._derive_seed(boot["base_seed"], t, c, cat), n_resamples=boot["resamples"], confidence=boot["confidence"])
        rep = SP.seed_replication({k: {t: {i: replicate_outcomes[t][k][i] for i in ids}, c: {i: replicate_outcomes[c][k][i] for i in ids}} for k in range(R)}, t, c, min_seeds=R)
        td = cmp_["discordant"]
        p_d = (td["b"] + td["c"]) / cmp_["n"]
        mde_ = PW.mde(cmp_["n"], p_d) if 0 < p_d <= 1 else None
        bt = cmp_["bootstrap"]
        row.update(result_status="COMPUTED", n=cmp_["n"], mean_treatment=_r(cmp_["mean_treatment"]), mean_control=_r(cmp_["mean_control"]),
                   difference=_r(cmp_["difference"]), ci_confidence=boot["confidence"], ci_percentile=_rl(bt["percentile"]), ci_bca=_rl(bt["bca"]),
                   bca_unavailable_reason=bt["bca_unavailable_reason"], n_resamples=bt["n_resamples"], discordant={k: v for k, v in td.items()},
                   mcnemar_p_two_sided=_r(cmp_["mcnemar"]["p_two_sided"]), effect={k: _r(v) for k, v in cmp_["effect"].items()},
                   replicate_differences={str(k): _r(v) for k, v in rep["per_seed_difference"].items()}, replicates_all_positive=rep["all_positive"],
                   observed_discordant_rate=_r(p_d), mde_at_observed_discordant_rate=_r(mde_))
        ep_results[e["id"]] = row
        pvals[e["id"]] = cmp_["mcnemar"]["p_two_sided"]
    expl_ids = tuple(e["id"] for e in plan["endpoints"] if e["kind"] == "EXPLORATORY")
    # A declared family keeps its DECLARED size: a family member without a computed p-value enters the correction as p = 1.0 (never shrinks the family).
    adj_input = {k: v for k, v in pvals.items() if k in expl_ids}
    for f in plan["families"]:
        for x in f["endpoints"]:
            adj_input[x] = pvals.get(x, 1.0)
    adj = SP.apply_families(plan["families"], adj_input, plan["correction"], exploratory=expl_ids)
    for k, v in adj.items():
        if ep_results[k]["result_status"] == "COMPUTED":
            ep_results[k]["multiplicity"] = {kk: _r(vv) for kk, vv in v.items()}
    prim_decisions = {}
    for e in plan["endpoints"]:
        if e["kind"] != "PRIMARY":
            continue
        row = ep_results[e["id"]]
        if row["result_status"] != "COMPUTED":
            prim_decisions[e["id"]] = "NOT_EVALUATED"
            continue
        ok = (row["difference"] >= e["threshold"] and row["ci_percentile"][0] > 0 and row["multiplicity"]["significant_after_correction"] and row["replicates_all_positive"])
        prim_decisions[e["id"]] = "SUPPORTED" if ok else "NOT_SUPPORTED"
        row["decision"] = prim_decisions[e["id"]]
        row["decision_rule"] = "difference >= threshold AND percentile CI lower bound > 0 AND significant after family correction AND positive in every replicate"

    # ---- category breakdown (exploratory)
    breakdown = []
    for t, c in plan["breakdown_comparisons"]:
        if t not in outcomes or c not in outcomes:
            breakdown.append({"treatment": t, "control": c, "status": "NOT_EVALUATED", "categories": {}})
            continue
        per = SP.compare_by_category(outcomes, categories, t, c, seed=boot["base_seed"], n_resamples=boot["resamples"], confidence=boot["confidence"], only_categories=set(cat_ids))
        breakdown.append({"treatment": t, "control": c, "status": "EXPLORATORY_UNADJUSTED",
                          "categories": {str(k): {"arm_treatment": t, "arm_control": c, "category": k, "n": v["n"], "difference": _r(v["difference"]),
                                                  "ci_percentile": _rl(v["bootstrap"]["percentile"]), "ci_bca": _rl(v["bootstrap"]["bca"]), "ci_confidence": boot["confidence"],
                                                  "mcnemar_p_two_sided_unadjusted": _r(v["mcnemar"]["p_two_sided"]), "status": "EXPLORATORY_UNADJUSTED"}
                                         for k, v in per.items()}})

    # ---- non-regression + zero tolerance (promotion comparison)
    pcmp = plan["promotion_comparison"]
    cand, ctrl = pcmp["candidate"], pcmp["control"]
    nonreg, zt = [], {}
    if cand in outcomes and ctrl in outcomes:
        per = SP.compare_by_category(outcomes, categories, cand, ctrl, seed=boot["base_seed"], n_resamples=boot["resamples"], confidence=boot["confidence"], only_categories=set(cat_ids))
        for c in cat_ids:
            if c not in per:
                continue
            m = plan["nonregression_margins"][str(c)]
            v = per[c]
            lo = v["bootstrap"]["percentile"][0]
            zero = c in plan["zero_tolerance_categories"]
            nonreg.append({"candidate": cand, "control": ctrl, "category": c, "n": v["n"], "difference": _r(v["difference"]), "ci_percentile": _rl(v["bootstrap"]["percentile"]),
                           "ci_confidence": boot["confidence"], "margin": m, "status": "SEE_ZERO_TOLERANCE" if zero else ("PASS" if lo >= -m else "FAIL"),
                           "rule": "percentile CI lower bound >= -margin" if not zero else "zero-tolerance category: judged by failure count only"})
        zt = SP.zero_tolerance_summary({a: outcomes[a] for a in evaluated}, categories, plan["zero_tolerance_categories"])
    zt_rows = [{"arm": a, "category": c, "n": v["n"], "failures": v["failures"], "status": "CLEAR" if v["failures"] == 0 else "BLOCKING_EVENT"}
               for a, d in sorted(zt.items()) for c, v in sorted(d.items(), key=lambda kv: str(kv[0]))]
    cand_zt = [x for x in zt_rows if x["arm"] == cand]
    gate = {"candidate": cand, "control": ctrl,
            "primary_endpoints_all_supported": all(v == "SUPPORTED" for v in prim_decisions.values()) and bool(prim_decisions),
            "nonregression_all_pass": bool(nonreg) and all(x["status"] in ("PASS", "SEE_ZERO_TOLERANCE") for x in nonreg),
            "zero_tolerance_all_clear": bool(cand_zt) and all(x["status"] == "CLEAR" for x in cand_zt)}
    gate["all_preregistered_conditions_met"] = all(gate[k] for k in ("primary_endpoints_all_supported", "nonregression_all_pass", "zero_tolerance_all_clear"))
    gate["note"] = "conjunction of pre-registered conditions; not a score; categories remain separately reported"
    rep = {"report_schema": REPORT_SCHEMA, "synthetic": synthetic, "banner": SYNTHETIC_BANNER if synthetic else None,
           "provenance": {"log_head": ver["head"], "log_entries": ver["entries"], "prereg_record_sha256": bound["prereg_record_sha256"], "analysis_plan_sha256": bound["plan_sha256"],
                          "dataset_manifest_sha256": next(e["payload"]["manifest_sha256"] for e in entries if e["kind"] == "DATASET_COMMITMENT"),
                          "arm_config_hashes": {e["payload"]["arm"]: e["payload"]["config_hash"] for e in entries if e["kind"] == "CONFIG_LOCK"},
                          "code_shas": sorted({e["payload"]["code_sha"] for e in entries if e["kind"] == "CONFIG_LOCK"})},
           "design": {"analysis_split": plan["analysis_split"], "run_replicates": R, "aggregation": "per-item majority vote over replicates (binary scores)",
                      "bootstrap": {"resamples": boot["resamples"], "confidence": boot["confidence"], "base_seed": boot["base_seed"], "methods": ["percentile", "bca"]},
                      "correction": plan["correction"], "alpha": plan["alpha"], "families": plan["families"]},
           "arms": arm_status, "descriptive_accuracy_by_arm_and_category": descriptive, "endpoints": [ep_results[e["id"]] for e in plan["endpoints"]],
           "primary_decisions": prim_decisions, "category_breakdown": breakdown, "nonregression": nonreg, "zero_tolerance": zt_rows, "promotion_gate": gate}
    return rep


# ------------------------------------------------------------------------------------------------------------------------------ markdown
def _fmt(x, nd: int = 4):
    if x is None:
        return "n/a"
    if isinstance(x, float):
        return f"{x:.{nd}f}"
    return str(x)


def _ci(v) -> str:
    return "n/a" if v is None else f"[{v[0]:.4f}, {v[1]:.4f}]"


def render_markdown(rep: dict) -> str:
    L = []
    if rep["synthetic"]:
        L += [f"# {rep['banner']}", "", "This report was produced from SYNTHETIC data generated by a seeded pseudo-random process. It demonstrates that the pipeline runs;",
              "it says NOTHING about any model.", ""]
    L += ["## Provenance", "", "| item | value |", "| --- | --- |"]
    pv = rep["provenance"]
    L += [f"| log head | seq {pv['log_head']['seq']} / {pv['log_head']['entry_hash']} |", f"| preregistration record sha256 | {pv['prereg_record_sha256']} |",
          f"| analysis plan sha256 | {pv['analysis_plan_sha256']} |", f"| dataset manifest sha256 | {pv['dataset_manifest_sha256']} |",
          f"| code SHA(s) | {', '.join(pv['code_shas'])} |"]
    for a, h in sorted(pv["arm_config_hashes"].items()):
        L.append(f"| config hash, arm {a} | {h} |")
    d = rep["design"]
    L += ["", "## Design", "", f"- analysis split: {d['analysis_split']}; run replicates: {d['run_replicates']}; aggregation: {d['aggregation']}",
          f"- bootstrap: {d['bootstrap']['resamples']} resamples, base seed {d['bootstrap']['base_seed']}, {int(d['bootstrap']['confidence'] * 100)}% intervals (percentile and BCa)",
          f"- multiplicity: {d['correction']} within pre-declared families; alpha {d['alpha']}", "- categories are never combined into one score", "",
          "## Arms", "", "| arm | status | n items | replicates | note |", "| --- | --- | --- | --- | --- |"]
    for a, s in sorted(rep["arms"].items()):
        L.append(f"| {a} | {s['status']} | {_fmt(s.get('n_items'))} | {_fmt(s.get('n_replicates'))} | {s.get('reason', '')} |")
    L += ["", "## Accuracy by arm and category (descriptive, no pooling)", "", "| arm | category | n | accuracy | status |", "| --- | --- | --- | --- | --- |"]
    for a in sorted(rep["descriptive_accuracy_by_arm_and_category"]):
        for c, v in rep["descriptive_accuracy_by_arm_and_category"][a].items():
            L.append(f"| {a} | {c} | {v['n']} | {_fmt(v['accuracy'])} | {v['status']} |")
    L += ["", "## Endpoints", "", "| id | status | comparison | category | n | difference | 95% CI percentile | 95% CI BCa | McNemar p | adjusted p (family) | threshold | MDE at observed p_d | decision |",
          "| --- | --- | --- | --- | --- | --- | --- | --- | --- | --- | --- | --- | --- |"]
    for e in rep["endpoints"]:
        if e["result_status"] != "COMPUTED":
            L.append(f"| {e['id']} | {e['status']} | {e['treatment']} - {e['control']} | {e['category']} | - | - | - | - | - | - | {_fmt(e['threshold'])} | - | NOT_EVALUATED |")
            continue
        m = e["multiplicity"]
        ap = "unadjusted (exploratory)" if m["adjusted_p"] is None else f"{m['adjusted_p']:.6f} ({m['family']}, k={m['family_size']})"
        L.append(f"| {e['id']} | {e['status']} | {e['treatment']} - {e['control']} | {e['category']} | {e['n']} | {_fmt(e['difference'])} | {_ci(e['ci_percentile'])} | {_ci(e['ci_bca'])} | "
                 f"{_fmt(e['mcnemar_p_two_sided'], 6)} | {ap} | {_fmt(e['threshold'])} | {_fmt(e['mde_at_observed_discordant_rate'])} | {e.get('decision', 'EXPLORATORY')} |")
    L += ["", "## Category breakdown (EXPLORATORY, unadjusted)", ""]
    for b in rep["category_breakdown"]:
        L += [f"### {b['treatment']} - {b['control']} ({b['status']})", "", "| category | n | difference | 95% CI percentile | 95% CI BCa | McNemar p (unadjusted) | status |", "| --- | --- | --- | --- | --- | --- | --- |"]
        for c, v in b["categories"].items():
            L.append(f"| {c} | {v['n']} | {_fmt(v['difference'])} | {_ci(v['ci_percentile'])} | {_ci(v['ci_bca'])} | {_fmt(v['mcnemar_p_two_sided_unadjusted'], 6)} | {v['status']} |")
        L.append("")
    g = rep["promotion_gate"]
    L += ["## Non-regression (candidate vs control, per category)", "", "| candidate - control | category | n | difference | 95% CI percentile | margin | status |", "| --- | --- | --- | --- | --- | --- | --- |"]
    for x in rep["nonregression"]:
        L.append(f"| {x['candidate']} - {x['control']} | {x['category']} | {x['n']} | {_fmt(x['difference'])} | {_ci(x['ci_percentile'])} | {x['margin']} | {x['status']} |")
    L += ["", "## Zero-tolerance categories (failure counts)", "", "| arm | category | n | failures | status |", "| --- | --- | --- | --- | --- |"]
    for x in rep["zero_tolerance"]:
        L.append(f"| {x['arm']} | {x['category']} | {x['n']} | {x['failures']} | {x['status']} |")
    L += ["", "## Pre-registered conditions (conjunction; not a score)", "", f"- primary endpoints all supported: {g['primary_endpoints_all_supported']}",
          f"- non-regression all pass: {g['nonregression_all_pass']}", f"- zero-tolerance all clear ({g['candidate']}): {g['zero_tolerance_all_clear']}",
          f"- all pre-registered conditions met: {g['all_preregistered_conditions_met']}", ""]
    if rep["synthetic"]:
        L += [f"**{rep['banner']}**", ""]
    return "\n".join(L)


def report_json_text(rep: dict) -> str:
    import json
    return json.dumps(rep, sort_keys=True, indent=2, ensure_ascii=False, allow_nan=False) + "\n"
