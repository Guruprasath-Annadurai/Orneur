"""Runs the four comparison arms against deterministic in-process model DOUBLES over SYNTHETIC items and records per-item paired results into the existing
hash-chained evalinfra result log (EvalLog).

SYNTHETIC - NOT EVIDENCE OF ANY MODEL CAPABILITY. A ModelDouble is a seeded pseudo-random function whose success rates are chosen by the caller; it is not a
model, loads no weights, uses no GPU and no network. The runner refuses anything that is not a ModelDouble, so a real model cannot be plugged in here by
accident (real execution needs a separate, authorized runner; training stays NOT_AUTHORIZED).

Flow: validate arm definitions (fail closed) -> synthetic manifest -> frozen synthetic prereg + 4-arm analysis plan -> per-arm CONFIG_LOCK derived from the
definition -> for each arm and replicate: build the arm's request (vendor template / registered prompt / ORNEUR system), call the double, score by exact
match, record one paired RESULT covering exactly the same items for every arm.
"""
from __future__ import annotations

import random

from orca.evalinfra import arms as AR
from orca.evalinfra import prereg_check as PC
from orca.evalinfra import schema as SC
from orca.evalinfra import synthetic as SY
from orca.evalinfra.arms import ArmRefusal
from orca.evalinfra.config_lock import config_hash
from orca.evalinfra.leakage import LeakGuard
from orca.evalinfra.results import RESULT_SCHEMA, EvalLog

SPLIT = "QUALIFICATION_HOLDOUT"
CATEGORIES = (3, 4, 10, 11, 12, 14, 15, 17)
# SYNTHETIC success rates per (model role, scaffold) and category. Chosen to exercise the pipeline; they describe no real model.
DOUBLE_RATES = {
    ("base", "vendor_template_only"): SY.DEFAULT_RATES["B0"],
    ("base", "standard_prompt"): SY.DEFAULT_RATES["B1"],
    ("base", "orneur_system"): SY.DEFAULT_RATES["B2"],
    ("tuned", "orneur_system"): SY.DEFAULT_RATES["T2"],
}


class ModelDouble:
    """Deterministic stand-in for a model. Correctness for an item is `u_item < rate` (u shared across doubles => paired by construction), flipped with
    probability 0.08 per (model, scaffold, replicate, item). Holds the synthetic oracle (item -> answer), which a real model never would."""

    def __init__(self, model_id: str, revision: str, kind: str, oracle: dict, *, seed: int, rates: dict | None = None):
        if kind not in ("base", "tuned"):
            raise ArmRefusal("BAD_DOUBLE_KIND", kind)
        self.model_id, self.revision, self.kind = model_id, revision, kind
        self._oracle, self._seed = dict(oracle), seed
        self._rates = rates if rates is not None else DOUBLE_RATES
        self.calls = 0

    def respond(self, request: dict) -> dict:
        self.calls += 1
        key = (self.kind, request["scaffold"])
        if key not in self._rates:
            raise ArmRefusal("DOUBLE_HAS_NO_BEHAVIOUR", f"{self.model_id} cannot be run under scaffold {request['scaffold']!r}")
        iid, cat = request["item_id"], request["category"]
        u = random.Random(f"{self._seed}|difficulty|{iid}").random()
        noise = random.Random(f"{self._seed}|noise|{self.model_id}|{request['scaffold']}|{request['replicate']}|{iid}").random()
        ok = u < self._rates[key][cat]
        if noise < 0.08:
            ok = not ok
        text = self._oracle[iid] if ok else "wrong " + iid[-6:]
        used_tool = request["scaffold"] == "orneur_system" and bool(request["tool_set"])
        return {"text": text, "tool_calls": 1 if used_tool else 0, "retrieval_calls": 1 if request["retrieval"] else 0}


def make_doubles(defn: dict, items: list, *, seed: int, rates: dict | None = None) -> dict:
    """One double per distinct model identity in the (valid) definition."""
    AR.require_valid(defn)
    oracle = {i["item_id"]: i["ground_truth"]["answer"] for i in items}
    out = {}
    for a in defn["arms"]:
        m = a["model"]
        out.setdefault((m["id"], m["revision"]), ModelDouble(m["id"], m["revision"], m["kind"], oracle, seed=seed, rates=rates))
    return out


def build_request(defn: dict, arm_entry: dict, item: dict, replicate: int) -> dict:
    """What the arm's scaffold sends to the model (identifiers/hashes only; no network, no tools executed)."""
    sysb = arm_entry["system"]
    return {"scaffold": arm_entry["scaffold"], "item_id": item["item_id"], "category": item["category"], "replicate": replicate, "prompt": item["prompt"],
            "prompt_id": arm_entry["prompt_id"], "system_hash": AR.system_config_hash(arm_entry) if sysb else None,
            "tool_set": list(sysb["tool_set"]) if sysb else [], "retrieval": bool(sysb and sysb["retrieval"]["enabled"]),
            "decoding": arm_entry["decoding"], "budgets": arm_entry["budgets"]}


def score(answer: dict, item: dict, budgets: dict) -> float:
    """Exact-match score; an answer that overruns the declared output or tool budget scores 0 (the budget is part of the arm, not advice)."""
    if len(answer["text"].split()) > budgets["max_output_tokens"] or answer["tool_calls"] > budgets["max_tool_calls"] or answer["retrieval_calls"] > budgets["max_retrieval_calls"]:
        return 0.0
    return 1.0 if answer["text"] == item["ground_truth"]["answer"] else 0.0


def make_four_arm_plan(prereg: dict, categories, *, resamples: int, replicates: int, base_seed: int = 20261011) -> dict:
    plan = SY.make_plan(prereg, categories, resamples=resamples, base_seed=base_seed, replicates=replicates)
    cats = set(categories)
    eps = [{"id": "P1", "kind": "PRIMARY", "hypothesis": "H-system", "treatment": "B2", "control": "B1", "category": 10, "metric": "pass_rate_binary", "threshold": 0.10},
           {"id": "P2", "kind": "PRIMARY", "hypothesis": "H-train-in-product", "treatment": "T2", "control": "B2", "category": 11, "metric": "pass_rate_binary", "threshold": 0.10},
           {"id": "P3", "kind": "PRIMARY", "hypothesis": "H-train-in-product", "treatment": "T2", "control": "B2", "category": 12, "metric": "pass_rate_binary", "threshold": 0.10},
           {"id": "X1", "kind": "EXPLORATORY", "hypothesis": "H-prompt", "treatment": "B1", "control": "B0", "category": 3, "metric": "pass_rate_binary", "threshold": None},
           {"id": "X2", "kind": "EXPLORATORY", "hypothesis": "H-train-in-product", "treatment": "T2", "control": "B2", "category": 4, "metric": "pass_rate_binary", "threshold": None}]
    eps = [e for e in eps if e["category"] in cats]
    plan.update(arms=list(AR.ARM_IDS), endpoints=eps, families=[{"name": "primary-family", "alpha": 0.05, "endpoints": [e["id"] for e in eps if e["kind"] == "PRIMARY"]}],
                promotion_comparison={"candidate": "T2", "control": "B2"}, breakdown_comparisons=[["B1", "B0"], ["B2", "B1"], ["T2", "B2"]])
    plan["plan_sha256"] = PC.plan_hash(plan)
    return plan


def run_comparison(defn: dict, log_path, *, doubles: dict | None = None, seed: int = 7, categories=CATEGORIES, holdout_per_cat: int = 40, resamples: int = 10_000,
                   replicates: int = 3, skip_arms=()) -> dict:
    """Validate (fail closed), then execute the four arms against doubles and record into a FRESH hash-chained log. `skip_arms` exists so a test can prove a
    log with a missing arm is refused by the report; it is never used by the demo."""
    AR.require_valid(defn)
    items = SY.make_items(seed, categories, {"SCREEN": 8, "QUALIFICATION_HOLDOUT": holdout_per_cat, "DEV": 4, "TRAIN": 8})
    doubles = doubles if doubles is not None else make_doubles(defn, items, seed=seed)
    for d in doubles.values():
        if not isinstance(d, ModelDouble):
            raise ArmRefusal("ONLY_MODEL_DOUBLES", "this runner executes ModelDouble instances only; real models are out of scope and NOT authorized")
    manifest = SY.make_manifest(items)
    prereg = SY.make_prereg(manifest)
    plan = make_four_arm_plan(prereg, categories, resamples=resamples, replicates=replicates)
    log = EvalLog(log_path, leak_guard=LeakGuard(items=[i for i in items if i["split"] in SC.PRIVATE_SPLITS]))
    log.record_dataset(manifest)
    log.freeze_prereg(prereg, allow_synthetic=True)
    log.freeze_plan(plan)
    cfgs = {a: AR.to_lock_config(defn, a) for a in AR.ARM_IDS}
    for a in AR.ARM_IDS:
        log.lock_config(cfgs[a])
    part = {p["split"]: p["partition_sha256"] for p in manifest["partitions"]}[SPLIT]
    by = {e["arm"]: e for e in defn["arms"]}
    holdout = sorted((i for i in items if i["split"] == SPLIT), key=lambda i: i["item_id"])
    for a in AR.ARM_IDS:
        if a in skip_arms:
            continue
        e = by[a]
        dbl = doubles.get((e["model"]["id"], e["model"]["revision"]))
        if dbl is None:
            raise ArmRefusal("NO_DOUBLE_FOR_ARM", a)
        for rep in range(replicates):
            rows = [{"item_id": it["item_id"], "category": it["category"], "score": score(dbl.respond(build_request(defn, e, it, rep)), it, e["budgets"])} for it in holdout]
            log.record_result({"schema_version": RESULT_SCHEMA, "run_id": f"synthetic-{a}-r{rep}", "arm": a, "replicate": rep, "split": SPLIT, "synthetic": True,
                               "provenance": {"code_sha": cfgs[a]["code_sha"], "config_hash": config_hash(cfgs[a]), "dataset_commitment": part, "prereg_hash": prereg["record_sha256"]},
                               "rows": rows}, manifest=manifest)
    return {"items": items, "manifest": manifest, "prereg": prereg, "plan": plan, "configs": cfgs, "doubles": doubles, "log": log, "definition": defn}
