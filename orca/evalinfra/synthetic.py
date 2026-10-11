"""SYNTHETIC fixtures only: fake items, fake manifests, fake preregistration/plan, fake configurations and fake outcomes drawn from a seeded generator.

NOTHING HERE IS EVIDENCE OF ANY MODEL CAPABILITY. No model is run; the 'outcomes' are pseudo-random draws whose per-arm success probabilities are
chosen by the caller. Item text is random pseudo-words (it contains no real benchmark content, and none of it is derived from any V1 prompt/answer/seed/instance).
Every artifact built here is labelled synthetic (eval_version starts with SYNTHETIC, `synthetic: true`), and the validators refuse to mix it with real material.
"""
from __future__ import annotations

import hashlib
import random

from orca.eval.genesis_v2 import prereg as V2P
from orca.eval.genesis_v2 import similarity as S
from orca.evalinfra import prereg_check as PC
from orca.evalinfra import schema as SC
from orca.evalinfra.config_lock import SCHEMA_VERSION as CONFIG_SCHEMA
from orca.evalinfra.leakage import LeakGuard
from orca.evalinfra.results import RESULT_SCHEMA, EvalLog

EVAL_VERSION = "SYNTHETIC-DEMO/0"
FROZEN_AT = "2026-10-11T00:00:00Z"
DECLARED_AT = "2026-10-11T00:00:01Z"
FUNC = sorted(S.FUNCTION_WORDS)
SYLL = ["ka", "to", "mi", "re", "lu", "po", "vo", "ne", "sa", "di", "xu", "fe", "ga", "zi", "bo", "ru", "ty", "ha", "qe", "wo"]
CATEGORY_NAMES = {3: "Quantitative reasoning", 4: "Coding", 10: "Verification and fabricated-completion resistance", 11: "Tool planning", 12: "Uncertainty and epistemic behavior",
                  14: "Human-sovereignty and authority boundaries", 15: "Security and adversarial behavior", 17: "Presence Mode and verified task-state"}
SCORER_FOR = {3: "exact_match", 4: "unit_test", 10: "pattern_match", 11: "schema_match", 12: "pattern_match", 14: "pattern_match", 15: "pattern_match", 17: "pattern_match"}
ZERO_TOL = (10, 14, 15, 17)


def _pw(rng) -> str:
    return "".join(rng.choice(SYLL) for _ in range(rng.randint(2, 4)))


def _sentence(rng, n: int) -> str:
    return " ".join(rng.choice(FUNC) if rng.random() < 0.35 else _pw(rng) for _ in range(n)).capitalize() + "."


def make_items(seed: int, categories, counts: dict) -> list:
    """counts: {split: items per category}. Returns private in-memory item dicts (prompt + hidden answer): SYNTHETIC, never public."""
    items = []
    for split in SC.SPLITS:
        for cat in categories:
            rng = random.Random(f"{seed}|{split}|{cat}")
            for i in range(counts.get(split, 0)):
                iid = "syn-" + hashlib.sha256(f"{seed}|{split}|{cat}|{i}".encode()).hexdigest()[:24]
                prompt = " ".join(_sentence(rng, rng.randint(14, 22)) for _ in range(3))
                items.append({"item_id": iid, "split": split, "category": cat, "cluster": f"{split}-{cat}-{i // 5}", "prompt": prompt,
                              "ground_truth": {"answer": "ans " + " ".join(_pw(rng) for _ in range(6))}})
    return items


def make_manifest(items: list, *, eval_id: str = "synthetic-demo-eval", salt_label: str = "evalinfra-synthetic") -> dict:
    cats = sorted({i["category"] for i in items})
    scorers = sorted({SCORER_FOR[c] for c in cats})
    pub = [{"id": it["item_id"], "category": it["category"], "split": it["split"], "scorer": SCORER_FOR[it["category"]],
            "commitment": SC.synthetic_commitment(salt_label, it["item_id"], {"p": it["prompt"], "a": it["ground_truth"]})} for it in items]
    return SC.build_manifest(
        eval_id=eval_id, eval_version=EVAL_VERSION, synthetic=True, taxonomy="genesis-spec32-17cat-synthetic-subset",
        categories=[{"id": c, "name": CATEGORY_NAMES[c], "scorer": SCORER_FOR[c], "role": "GATING", "zero_tolerance": c in ZERO_TOL} for c in cats],
        scorers=[{"id": s, "type": s, "version": "1"} for s in scorers], items=pub)


def make_prereg(manifest: dict) -> dict:
    names = list(V2P.BINDINGS)
    b = {k: {"synthetic": True, "binding": k} for k in names}
    b["eval_version"], b["corpus_version"] = EVAL_VERSION, EVAL_VERSION
    b["private_corpus_aggregate_commitment"] = manifest["manifest_sha256"]
    bs = {k: "BOUND" for k in names}
    bs["private_corpus_aggregate_commitment"] = "DEFERRED"        # see INVENTORY.md: the repo validator requires this status even once the binding is filled
    d = {"schema_version": V2P.SCHEMA_VERSION, "status": "FROZEN", "frozen": True, "bindings": b, "binding_status": bs, "floors_status": "LOCKED",
         "first_candidate_run_at": None, "candidate_results": [], "frozen_at": FROZEN_AT, "record_sha256": ""}
    d["record_sha256"] = V2P.record_hash(d)
    return d


def make_plan(prereg: dict, categories, *, resamples: int = 10_000, base_seed: int = 20261011, replicates: int = 3) -> dict:
    cats = list(categories)
    eps = [{"id": "P1", "kind": "PRIMARY", "hypothesis": "H1", "treatment": "B2", "control": "B0", "category": 10, "metric": "pass_rate_binary", "threshold": 0.10},
           {"id": "P2", "kind": "PRIMARY", "hypothesis": "H5", "treatment": "T2", "control": "B2", "category": 11, "metric": "pass_rate_binary", "threshold": 0.10},
           {"id": "P3", "kind": "PRIMARY", "hypothesis": "H2", "treatment": "T2", "control": "B2", "category": 12, "metric": "pass_rate_binary", "threshold": 0.10},
           {"id": "P4", "kind": "PRIMARY", "hypothesis": "H3", "treatment": "T1", "control": "B1", "category": 3, "metric": "pass_rate_binary", "threshold": 0.10},
           {"id": "X1", "kind": "EXPLORATORY", "hypothesis": "H3", "treatment": "T2", "control": "B2", "category": 4, "metric": "pass_rate_binary", "threshold": None},
           {"id": "X2", "kind": "EXPLORATORY", "hypothesis": "H1", "treatment": "B2", "control": "B1", "category": 11, "metric": "pass_rate_binary", "threshold": None}]
    eps = [e for e in eps if e["category"] in cats]
    prim = [e["id"] for e in eps if e["kind"] == "PRIMARY"]
    plan = {"schema_version": PC.PLAN_SCHEMA, "prereg_record_sha256": prereg["record_sha256"], "declared_at": DECLARED_AT, "synthetic": True,
            "arms": ["B0", "B1", "B2", "T1", "T2", "R"], "categories": cats, "zero_tolerance_categories": list(ZERO_TOL), "analysis_split": "QUALIFICATION_HOLDOUT",
            "run_replicates": replicates, "bootstrap": {"resamples": resamples, "confidence": 0.95, "base_seed": base_seed}, "alpha": 0.05, "correction": "holm",
            "families": [{"name": "primary-family", "alpha": 0.05, "endpoints": prim}], "endpoints": eps,
            "nonregression_margins": {str(c): (0 if c in ZERO_TOL else 0.10) for c in cats},
            "promotion_comparison": {"candidate": "T2", "control": "B2"}, "breakdown_comparisons": [["T2", "B2"], ["B2", "B0"]], "plan_sha256": ""}
    plan["plan_sha256"] = PC.plan_hash(plan)
    return plan


def make_config(arm: str, *, synthetic: bool = True, **over) -> dict:
    h = lambda s: hashlib.sha256(s.encode()).hexdigest()           # noqa: E731
    base = {"B0": "base", "B1": "base", "B2": "base", "T1": "tuned", "T2": "tuned", "R": "reference"}[arm]
    c = {"schema_version": CONFIG_SCHEMA, "arm": arm, "synthetic": synthetic, "model": {"id": f"synthetic/{base}-model", "revision": hashlib.sha1(f"rev-{base}".encode()).hexdigest()},
         "tokenizer": {"id": "synthetic/tokenizer", "revision": hashlib.sha1(b"tok").hexdigest()}, "chat_template_sha256": h("template"),
         "decoding": {"do_sample": False, "temperature": 0, "top_p": 1.0, "top_k": 0, "max_new_tokens": 512}, "system_prompt_sha256": h(f"system-{arm}"),
         "tool_rag_kernel_config_sha256": h(f"stack-{arm}"), "code_sha": hashlib.sha1(b"synthetic-code").hexdigest()}
    c.update(over)
    return c


# arm -> success probability by category (SYNTHETIC numbers chosen to exercise the pipeline, not to resemble any model)
DEFAULT_RATES = {
    "B0": {3: .50, 4: .45, 10: .45, 11: .50, 12: .40, 14: .85, 15: .85, 17: .85},
    "B1": {3: .55, 4: .48, 10: .50, 11: .55, 12: .45, 14: .90, 15: .90, 17: .90},
    "B2": {3: .60, 4: .55, 10: .75, 11: .60, 12: .55, 14: .97, 15: .97, 17: .97},
    "T1": {3: .72, 4: .50, 10: .55, 11: .58, 12: .50, 14: .92, 15: .92, 17: .92},
    "T2": {3: .74, 4: .56, 10: .78, 11: .78, 12: .75, 14: 1.0, 15: 1.0, 17: 1.0},
}


def draw_outcomes(items: list, split: str, arm: str, replicate: int, seed: int, rates: dict = DEFAULT_RATES) -> list:
    """Paired by construction: every arm shares each item's latent difficulty u_i; an arm is correct iff u_i < rate, flipped with prob 0.08 per (arm, replicate)."""
    rows = []
    for it in sorted((i for i in items if i["split"] == split), key=lambda i: i["item_id"]):
        u = random.Random(f"{seed}|difficulty|{it['item_id']}").random()
        noise = random.Random(f"{seed}|noise|{arm}|{replicate}|{it['item_id']}").random()
        ok = u < rates[arm][it["category"]]
        if noise < 0.08:
            ok = not ok
        rows.append({"item_id": it["item_id"], "category": it["category"], "score": 1.0 if ok else 0.0})
    return rows


def build_experiment(log_path, *, seed: int = 7, categories=(3, 4, 10, 11, 12, 14, 15, 17), holdout_per_cat: int = 40, resamples: int = 10_000,
                     arms=("B0", "B1", "B2", "T1", "T2"), replicates: int = 3) -> dict:
    """End-to-end SYNTHETIC experiment recorded into a fresh hash-chained log. Returns all artifacts needed to analyse it."""
    items = make_items(seed, categories, {"SCREEN": 8, "QUALIFICATION_HOLDOUT": holdout_per_cat, "DEV": 4, "TRAIN": 8})
    manifest = make_manifest(items)
    prereg = make_prereg(manifest)
    plan = make_plan(prereg, categories, resamples=resamples, replicates=replicates)
    guard = LeakGuard(items=[i for i in items if i["split"] in SC.PRIVATE_SPLITS])
    log = EvalLog(log_path, leak_guard=guard)
    log.record_dataset(manifest)
    log.freeze_prereg(prereg, allow_synthetic=True)
    log.freeze_plan(plan)
    cfgs = {a: make_config(a) for a in arms}
    from orca.evalinfra.config_lock import config_hash
    for a in arms:
        log.lock_config(cfgs[a])
    part = {p["split"]: p["partition_sha256"] for p in manifest["partitions"]}
    for a in arms:
        for rep in range(replicates):
            log.record_result({"schema_version": RESULT_SCHEMA, "run_id": f"synthetic-{a}-r{rep}", "arm": a, "replicate": rep, "split": "QUALIFICATION_HOLDOUT", "synthetic": True,
                               "provenance": {"code_sha": cfgs[a]["code_sha"], "config_hash": config_hash(cfgs[a]), "dataset_commitment": part["QUALIFICATION_HOLDOUT"],
                                              "prereg_hash": prereg["record_sha256"]},
                               "rows": draw_outcomes(items, "QUALIFICATION_HOLDOUT", a, rep, seed)}, manifest=manifest)
    return {"items": items, "manifest": manifest, "prereg": prereg, "plan": plan, "configs": cfgs, "log": log, "guard": guard}
