"""Four-arm comparison report: system effect (arm 3 - arm 2), training-inside-product effect (arm 4 - arm 3, PRIMARY) and standardized-prompt effect
(arm 2 - arm 1), each computed per category with paired statistics and ALWAYS labelled with its treatment and control arm.

SYNTHETIC - NOT EVIDENCE OF ANY MODEL CAPABILITY when the inputs are synthetic (the only mode this infrastructure supports today).

Fail-closed preconditions (ArmRefusal otherwise): the arm definitions validate (B2/T2 identical system, arm-2 prompt registered and budget-matched);
the chained CONFIG_LOCKs equal the locks re-derived from the definitions; B2 and T2 locks differ only in model identity; all four arms have complete
results; and the underlying evalinfra report (chain verification, frozen prereg, unmodified plan) succeeds. No number is ever produced without its arm labels:
`aggregate_scores` refuses unlabelled rows, and there is no cross-category or cross-arm pooled score anywhere.
"""
from __future__ import annotations

from orca.evalinfra import arms as AR
from orca.evalinfra import report as RP
from orca.evalinfra import stats_paired as SP
from orca.evalinfra.arms import ArmRefusal
from orca.evalinfra.canon import canonical
from orca.evalinfra.chain import ChainLog
from orca.evalinfra.config_lock import config_hash
from orca.evalinfra.results import KINDS

ARM_REPORT_SCHEMA = "orneur-evalinfra-arm-report/1"


def aggregate_scores(rows) -> dict:
    """Mean score per (arm, category). Refuses rows without a known arm label, rows without a category, and an input that lacks any of the four arms."""
    if not isinstance(rows, list) or not rows:
        raise ArmRefusal("UNLABELLED_AGGREGATE", "no rows")
    acc: dict = {}
    for r in rows:
        if not isinstance(r, dict) or r.get("arm") not in AR.ARM_IDS or "category" not in r or "score" not in r:
            raise ArmRefusal("UNLABELLED_AGGREGATE", "every row needs an arm label (one of B0/B1/B2/T2), a category and a score; aggregates without arm labels are refused")
        acc.setdefault((r["arm"], r["category"]), []).append(r["score"])
    present = {a for a, _ in acc}
    if present != set(AR.ARM_IDS):
        raise ArmRefusal("MISSING_ARM", f"aggregate refused: arms present {sorted(present)}, all four required")
    return {f"{a}|{c}": {"arm": a, "category": c, "n": len(v), "mean": sum(v) / len(v)} for (a, c), v in sorted(acc.items(), key=lambda kv: (kv[0][0], str(kv[0][1])))}


def assert_arm_labelled(report: dict) -> None:
    """Every effect row must name two distinct known arms; a report with an unlabelled number is refused."""
    rows = report.get("effects")
    if not isinstance(rows, list) or not rows:
        raise ArmRefusal("UNLABELLED_AGGREGATE", "report has no labelled effects")
    for r in rows:
        if r.get("treatment_arm") not in AR.ARM_IDS or r.get("control_arm") not in AR.ARM_IDS or r["treatment_arm"] == r["control_arm"] or "category" not in r:
            raise ArmRefusal("UNLABELLED_AGGREGATE", f"effect row without proper arm labels: {sorted(r)}")


def _check_locks(entries: list, defn: dict) -> dict:
    locks = {e["payload"]["arm"]: e["payload"] for e in entries if e["kind"] == "CONFIG_LOCK"}
    for a in AR.ARM_IDS:
        if a not in locks:
            raise ArmRefusal("MISSING_ARM", f"no CONFIG_LOCK for arm {a}")
        if locks[a]["config_hash"] != config_hash(AR.to_lock_config(defn, a)):
            raise ArmRefusal("LOCK_DIFFERS_FROM_DEFINITION", f"arm {a}: the chained lock differs from the configuration derived from the arm definitions")
    strip = lambda c: {k: v for k, v in c.items() if k not in ("arm", "model")}      # noqa: E731
    if canonical(strip(locks["B2"]["config"])) != canonical(strip(locks["T2"]["config"])):
        raise ArmRefusal("SYSTEM_CONFIG_MISMATCH", "chained B2 and T2 locks differ in more than model identity")
    return locks


def build_arm_report(log_path, defn: dict, prereg_doc: dict, plan: dict, *, allow_synthetic: bool = True) -> dict:
    info = AR.require_valid(defn)
    if not allow_synthetic or defn["synthetic"] is not True:
        raise ArmRefusal("NON_SYNTHETIC_UNSUPPORTED", "this infrastructure is synthetic-only; real comparisons need a separate authorized runner")
    if sorted(plan["arms"]) != sorted(AR.ARM_IDS):
        raise ArmRefusal("MISSING_ARM", f"the analysis plan must list exactly the four arms {AR.ARM_IDS}")
    entries = ChainLog(log_path, allowed_kinds=KINDS).entries()
    _check_locks(entries, defn)
    collected = RP._collect(entries, plan)
    for a in AR.ARM_IDS:
        if a not in collected or sorted(collected[a]["replicates"]) != list(range(plan["run_replicates"])):
            raise ArmRefusal("MISSING_ARM", f"arm {a} has no complete results in the analysis split; a comparison with a missing arm is refused")
    base = RP.build_report(log_path, prereg_doc, plan, allow_synthetic=allow_synthetic)
    outcomes = {a: RP._majority([collected[a]["replicates"][k] for k in range(plan["run_replicates"])]) for a in AR.ARM_IDS}
    categories: dict = {}
    for a in AR.ARM_IDS:
        categories.update(collected[a]["categories"])
    boot = plan["bootstrap"]
    prim = {(e["treatment"], e["control"], e["category"]): e["id"] for e in plan["endpoints"] if e["kind"] == "PRIMARY"}
    effects = []
    for name, t, c, definition in AR.EFFECTS:
        per = SP.compare_by_category(outcomes, categories, t, c, seed=boot["base_seed"], n_resamples=boot["resamples"], confidence=boot["confidence"],
                                     only_categories=set(plan["categories"]))
        for cat, v in per.items():
            pid = prim.get((t, c, cat))
            effects.append({"effect": name, "definition": definition, "treatment_arm": t, "treatment_arm_number": AR.ARM_NUMBER[t], "control_arm": c,
                            "control_arm_number": AR.ARM_NUMBER[c], "category": cat, "n": v["n"], "difference": RP._r(v["difference"]),
                            "ci_percentile": RP._rl(v["bootstrap"]["percentile"]), "ci_bca": RP._rl(v["bootstrap"]["bca"]), "ci_confidence": boot["confidence"],
                            "mcnemar_p_two_sided_unadjusted": RP._r(v["mcnemar"]["p_two_sided"]),
                            "status": f"SEE_PRIMARY_ENDPOINT:{pid}" if pid else "EXPLORATORY_UNADJUSTED",
                            "is_primary_comparison": (t, c) == ("T2", "B2")})
    effects.sort(key=lambda r: ([n for n, *_ in AR.EFFECTS].index(r["effect"]), str(r["category"])))
    rep = {"report_schema": ARM_REPORT_SCHEMA, "synthetic": True, "banner": AR.BANNER,
           "arm_definition": {"comparison_id": defn["comparison_id"], "definition_sha256": info["definition_sha256"], "system_config_hash": info["system_config_hash"],
                              "arm_numbers": AR.ARM_NUMBER, "primary_comparison": info["primary_comparison"],
                              "verdict": "B2 and T2 share a byte-identical system configuration and differ only in model identity; arm-2 prompt registered and budget-matched"},
           "provenance": base["provenance"], "design": base["design"], "arms": base["arms"],
           "descriptive_accuracy_by_arm_and_category": base["descriptive_accuracy_by_arm_and_category"],
           "effects": effects, "plan_endpoints": base["endpoints"], "primary_decisions": base["primary_decisions"], "zero_tolerance": base["zero_tolerance"],
           "promotion_gate": base["promotion_gate"],
           "limitations": ["Outcomes come from seeded ModelDoubles with hard-coded success rates; no model was run.", "Categories are never pooled and no arm-unlabelled aggregate exists.",
                           "A SUPPORTED/NOT_SUPPORTED label here describes a synthetic pipeline check only."]}
    assert_arm_labelled(rep)
    return rep


def render_markdown(rep: dict) -> str:
    assert_arm_labelled(rep)
    L = [f"# {rep['banner']}", "", f"Comparison `{rep['arm_definition']['comparison_id']}`; system_config_hash `{rep['arm_definition']['system_config_hash'][:16]}`.", "",
         "Arm numbering: 1=B0 base alone; 2=B1 base+standard prompt; 3=B2 base+ORNEUR system; 4=T2 tuned+IDENTICAL ORNEUR system (primary: arm 4 - arm 3).", "",
         "| effect | treatment | control | category | n | difference | 95% CI (percentile) | status |", "|---|---|---|---|---|---|---|---|"]
    for r in rep["effects"]:
        ci = r["ci_percentile"]
        L.append(f"| {r['effect']} ({r['definition']}) | {r['treatment_arm']} | {r['control_arm']} | {r['category']} | {r['n']} | {r['difference']} | [{ci[0]}, {ci[1]}] | {r['status']} |")
    L += ["", "Limitations:"] + [f"- {x}" for x in rep["limitations"]]
    return "\n".join(L) + "\n"
