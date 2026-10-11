"""Preregistration + analysis-plan validation, and the 'no analysis without a frozen, unmodified prereg' rule.

Two documents are validated and bound together:
  1. the V2 preregistration record (schema genesis-v2-preregistration/1) -- checked against the repository's schema descriptor
     (docs/orneur/phase-21/GENESIS_CAPABILITY_EVAL_V2_PREREGISTRATION_SCHEMA.json) AND the repo's own validator (orca.eval.genesis_v2.prereg);
  2. an ANALYSIS PLAN (schema orneur-evalinfra-analysis-plan/1) carrying what the blueprint (section 6.6 / 8) and register row QUAL-3 require declared
     BEFORE results: <= 4 primary endpoints each with a numeric threshold, exploratory endpoints labelled, multiplicity families, non-regression margins
     for EVERY category, zero-tolerance categories 10/14/15/17 (margin 0), >= 3 odd run replicates, >= 10,000 bootstrap resamples.

The binding to the result log is by hash chain (see orca.evalinfra.results): PREREG_FROZEN and ANALYSIS_PLAN_FROZEN entries must precede the first RESULT;
analysis recomputes both hashes from the documents it is handed and refuses if either differs from the chained value (i.e. a document modified after
results exist) or if the prereg is not FROZEN.
Nothing here freezes anything or changes the repository's real preregistration (which remains DRAFT_NOT_FROZEN).
"""
from __future__ import annotations

import json
from pathlib import Path

from orca.eval.genesis_v2 import prereg as V2P
from orca.eval.genesis_v2 import spec as V2
from orca.evalinfra.canon import is_hex64, is_int, is_num, obj_hash
from orca.evalinfra.errors import PreregViolation
from orca.evalinfra.stats_paired import ARMS, CORRECTIONS, MIN_RESAMPLES

PLAN_SCHEMA = "orneur-evalinfra-analysis-plan/1"
REQUIRED_ZERO_TOLERANCE = (10, 14, 15, 17)          # blueprint section 8 / GENESIS_PRETRAINING_QUALIFICATION.md "critical non-regression categories"
ANNOTATION_KEYS = frozenset({"document", "note"})         # informational keys present in the repository's own draft; covered by record_sha256, otherwise inert
MAX_PRIMARY = 4
MIN_REPLICATES = 3
PLAN_KEYS = frozenset({"schema_version", "prereg_record_sha256", "declared_at", "synthetic", "arms", "categories", "zero_tolerance_categories",
                       "analysis_split", "run_replicates", "bootstrap", "alpha", "correction", "families", "endpoints", "nonregression_margins", "promotion_comparison",
                       "breakdown_comparisons", "plan_sha256"})
BOOT_KEYS = frozenset({"resamples", "confidence", "base_seed"})
ENDPOINT_KEYS = frozenset({"id", "kind", "hypothesis", "treatment", "control", "category", "metric", "threshold"})
FAMILY_KEYS = frozenset({"name", "alpha", "endpoints"})
_TS = __import__("re").compile(r"^\d{4}-\d{2}-\d{2}T\d{2}:\d{2}:\d{2}Z$")


def plan_hash(plan: dict) -> str:
    return obj_hash({k: v for k, v in plan.items() if k != "plan_sha256"})


def _p(problems: list, cond: bool, msg: str) -> None:
    if not cond:
        problems.append(msg)


# ------------------------------------------------------------------------------------------------------------------------------ prereg doc
def validate_prereg_document(doc, *, schema_path=None, allow_synthetic: bool = False, require_frozen: bool = True) -> list:
    """Problems (empty list == valid). With require_frozen=True (the analysis gate) a DRAFT is a problem."""
    p: list = []
    if not isinstance(doc, dict):
        return ["prereg is not an object"]
    if schema_path is not None:
        try:
            sch = json.loads(Path(schema_path).read_text())
        except Exception as e:
            return [f"repository schema descriptor unreadable ({type(e).__name__}); fail closed"]
        _p(p, sch.get("schema_version") == V2P.SCHEMA_VERSION, "schema descriptor version differs from the validator's")
        req = set(sch["required_top_level"])
        _p(p, req <= set(doc) <= req | ANNOTATION_KEYS, f"top-level keys must be the schema's required keys {sorted(req)} plus at most the annotation keys {sorted(ANNOTATION_KEYS)}")
        b = doc.get("bindings")
        _p(p, isinstance(b, dict) and set(b) == set(sch["required_bindings"]), "bindings must be exactly the schema's required_bindings")
        _p(p, doc.get("status") in sch["status_values"], "status not in schema status_values")
        _p(p, doc.get("floors_status") in sch["floors_status_values"], "floors_status not in schema floors_status_values")
        bs = doc.get("binding_status")
        if isinstance(bs, dict):
            for k, v in bs.items():
                _p(p, v in sch["binding_status_values"], f"binding_status[{k}] not in schema binding_status_values")
    if require_frozen:
        p += V2P.validate_for_freeze(doc)
        _p(p, isinstance(doc.get("bindings"), dict) and doc["bindings"].get("private_corpus_aggregate_commitment") is not None,
           "the deferred private_corpus_aggregate_commitment must be bound before any analysis")
    else:
        p += V2P.validate_draft(doc)
    b = doc.get("bindings") if isinstance(doc.get("bindings"), dict) else {}
    ev, cv = b.get("eval_version"), b.get("corpus_version")
    if allow_synthetic:
        _p(p, isinstance(ev, str) and ev.startswith("SYNTHETIC"), "a synthetic prereg must carry an eval_version starting with SYNTHETIC")
    else:
        _p(p, ev == V2.EVAL_VERSION and cv == V2.CORPUS_VERSION, "eval/corpus version must be the V2 versions (use allow_synthetic only for synthetic fixtures)")
    return p


# ------------------------------------------------------------------------------------------------------------------------------ analysis plan
def validate_analysis_plan(plan, *, expected_prereg_sha256: str | None = None) -> list:
    p: list = []
    if not isinstance(plan, dict) or set(plan) != PLAN_KEYS:
        return [f"plan keys must be exactly {sorted(PLAN_KEYS)}"]
    _p(p, plan["schema_version"] == PLAN_SCHEMA, "schema_version")
    _p(p, is_hex64(plan["prereg_record_sha256"]), "prereg_record_sha256 must be a sha256 hex")
    if expected_prereg_sha256 is not None:
        _p(p, plan["prereg_record_sha256"] == expected_prereg_sha256, "plan is bound to a different prereg record")
    _p(p, isinstance(plan["declared_at"], str) and bool(_TS.match(plan["declared_at"])), "declared_at must be YYYY-MM-DDTHH:MM:SSZ")
    _p(p, isinstance(plan["synthetic"], bool), "synthetic must be a bool")
    arms = plan["arms"]
    _p(p, isinstance(arms, list) and len(arms) >= 2 and len(set(arms)) == len(arms) and set(arms) <= set(ARMS), f"arms must be >= 2 distinct members of {ARMS}")
    cats = plan["categories"]
    _p(p, isinstance(cats, list) and bool(cats) and len({repr(c) for c in cats}) == len(cats), "categories must be a non-empty list of unique ids")
    zt = plan["zero_tolerance_categories"]
    _p(p, isinstance(zt, list) and set(REQUIRED_ZERO_TOLERANCE) <= set(zt), f"zero_tolerance_categories must include {REQUIRED_ZERO_TOLERANCE}")
    if isinstance(zt, list) and isinstance(cats, list):
        _p(p, set(zt) <= set(cats), "every zero-tolerance category must be one of the plan's categories")
    _p(p, plan["analysis_split"] in ("SCREEN", "QUALIFICATION_HOLDOUT", "DEV", "TRAIN"), "analysis_split must be one of the four splits (fixed before results)")
    _p(p, is_int(plan["run_replicates"]) and plan["run_replicates"] >= MIN_REPLICATES and plan["run_replicates"] % 2 == 1,
       f"run_replicates must be an odd integer >= {MIN_REPLICATES} (odd so a per-item majority vote is defined)")
    bo = plan["bootstrap"]
    if isinstance(bo, dict) and set(bo) == BOOT_KEYS:
        _p(p, is_int(bo["resamples"]) and bo["resamples"] >= MIN_RESAMPLES, f"bootstrap resamples must be >= {MIN_RESAMPLES}")
        _p(p, is_num(bo["confidence"]) and 0.5 < bo["confidence"] < 1, "bootstrap confidence in (0.5, 1)")
        _p(p, is_int(bo["base_seed"]), "bootstrap base_seed must be an integer fixed in advance")
    else:
        p.append(f"bootstrap keys must be exactly {sorted(BOOT_KEYS)}")
    _p(p, is_num(plan["alpha"]) and 0 < plan["alpha"] < 1, "alpha in (0, 1)")
    _p(p, plan["correction"] in CORRECTIONS, f"correction must be one of {CORRECTIONS}")
    eps = plan["endpoints"]
    prim, ids = [], set()
    if not isinstance(eps, list) or not eps:
        p.append("endpoints must be a non-empty list")
        eps = []
    for e in eps:
        if not isinstance(e, dict) or set(e) != ENDPOINT_KEYS:
            p.append(f"endpoint keys must be exactly {sorted(ENDPOINT_KEYS)}")
            continue
        _p(p, isinstance(e["id"], str) and bool(e["id"]) and e["id"] not in ids, f"endpoint id duplicate/invalid: {e.get('id')!r}")
        ids.add(e["id"])
        _p(p, e["kind"] in ("PRIMARY", "EXPLORATORY"), f"{e['id']}: kind must be PRIMARY or EXPLORATORY (every endpoint is labelled)")
        _p(p, e["treatment"] in ARMS and e["control"] in ARMS and e["treatment"] != e["control"], f"{e['id']}: treatment/control must be distinct known arms")
        if isinstance(arms, list):
            _p(p, e["treatment"] in arms and e["control"] in arms, f"{e['id']}: arms must be in the plan's arms")
        _p(p, not isinstance(e["category"], (list, dict)) and e["category"] in cats, f"{e['id']}: exactly ONE plan category (no pooled endpoints)")
        _p(p, isinstance(e["metric"], str) and bool(e["metric"]), f"{e['id']}: metric required")
        _p(p, isinstance(e["hypothesis"], str) and bool(e["hypothesis"]), f"{e['id']}: hypothesis id required")
        if e["kind"] == "PRIMARY":
            prim.append(e)
            _p(p, is_num(e["threshold"]) and 0 < e["threshold"] <= 1, f"{e['id']}: a PRIMARY endpoint needs a numeric threshold in (0, 1] declared before results (QUAL-3)")
        else:
            _p(p, e["threshold"] is None or is_num(e["threshold"]), f"{e['id']}: threshold must be null or numeric")
    _p(p, 1 <= len(prim) <= MAX_PRIMARY, f"between 1 and {MAX_PRIMARY} PRIMARY endpoints are allowed (found {len(prim)})")
    _p(p, len({(e["treatment"], e["control"], repr(e["category"])) for e in prim}) == len(prim), "primary endpoints must be distinct comparisons")
    fam_of: dict = {}
    for f in plan["families"] if isinstance(plan["families"], list) else []:
        if not isinstance(f, dict) or set(f) != FAMILY_KEYS:
            p.append(f"family keys must be exactly {sorted(FAMILY_KEYS)}")
            continue
        _p(p, is_num(f["alpha"]) and 0 < f["alpha"] <= (plan["alpha"] if is_num(plan["alpha"]) else 1), f"family {f['name']!r}: alpha must be in (0, plan alpha]")
        for e in f["endpoints"] if isinstance(f["endpoints"], list) else []:
            _p(p, e not in fam_of, f"endpoint {e!r} is in two families")
            fam_of[e] = f["name"]
    if not isinstance(plan["families"], list) or not plan["families"]:
        p.append("families must be declared explicitly (the multiplicity family definition)")
    for e in prim:
        _p(p, e["id"] in fam_of, f"PRIMARY endpoint {e['id']} is not in any family")
    for e in eps:
        if isinstance(e, dict) and e.get("kind") == "EXPLORATORY":
            _p(p, e["id"] not in fam_of, f"EXPLORATORY endpoint {e['id']} must not be in a confirmatory family")
    _p(p, set(fam_of) <= {e["id"] for e in prim}, "families may contain only PRIMARY endpoints")
    nm = plan["nonregression_margins"]
    if isinstance(nm, dict) and isinstance(cats, list):
        _p(p, {str(k) for k in nm} == {str(c) for c in cats}, "nonregression_margins must cover EVERY plan category (QUAL-3: thresholds for critical and for unset categories)")
        for k, v in nm.items():
            _p(p, is_num(v) and 0 <= v <= 0.5, f"nonregression margin for {k} must be numeric in [0, 0.5]")
        for z in REQUIRED_ZERO_TOLERANCE:
            _p(p, nm.get(str(z)) == 0, f"zero-tolerance category {z} must have margin 0")
    else:
        p.append("nonregression_margins must be an object keyed by category")
    pc = plan["promotion_comparison"]
    _p(p, isinstance(pc, dict) and set(pc) == {"candidate", "control"} and pc.get("candidate") in ARMS and pc.get("control") in ARMS and pc["candidate"] != pc["control"],
       "promotion_comparison must name candidate/control arms")
    bc = plan["breakdown_comparisons"]
    _p(p, isinstance(bc, list) and all(isinstance(x, list) and len(x) == 2 and x[0] in ARMS and x[1] in ARMS for x in bc), "breakdown_comparisons must be [[treatment, control], ...]")
    _p(p, plan["plan_sha256"] == plan_hash(plan), "plan_sha256 mismatch (the plan was edited after hashing)")
    return p


# ------------------------------------------------------------------------------------------------------------------------------ chain binding
def assert_analysis_allowed(entries: list, prereg_doc: dict, plan_doc: dict, *, schema_path=None, allow_synthetic: bool = False) -> dict:
    """Raises PreregViolation unless: the prereg is FROZEN and valid; the plan is valid and bound to it; both were chained BEFORE the first result; and the
    documents handed in hash to exactly the chained values (i.e. neither was modified after results exist). Returns the chained hashes."""
    probs: list = []
    kinds = [e["kind"] for e in entries]
    pre = [e for e in entries if e["kind"] == "PREREG_FROZEN"]
    pln = [e for e in entries if e["kind"] == "ANALYSIS_PLAN_FROZEN"]
    res = [e for e in entries if e["kind"] == "RESULT"]
    _p(probs, len(pre) == 1, "exactly one PREREG_FROZEN entry is required (an unfrozen or missing prereg refuses analysis)")
    _p(probs, len(pln) == 1, "exactly one ANALYSIS_PLAN_FROZEN entry is required")
    _p(probs, bool(res), "no results are recorded")
    if len(pre) == 1 and len(pln) == 1:
        first_res = res[0]["seq"] if res else None
        if first_res is not None:
            _p(probs, pre[0]["seq"] < first_res and pln[0]["seq"] < first_res, "prereg and analysis plan must be chained BEFORE the first result")
            _p(probs, kinds.index("PREREG_FROZEN") < kinds.index("RESULT"), "result recorded before preregistration freeze")
        from orca.eval.genesis_v2 import prereg as _V2P
        cur_pre = _V2P.record_hash(prereg_doc) if isinstance(prereg_doc, dict) else None
        _p(probs, cur_pre == pre[0]["payload"]["record_sha256"], "the preregistration differs from the chained (frozen) version: modified after freeze/results")
        _p(probs, isinstance(plan_doc, dict) and plan_hash(plan_doc) == pln[0]["payload"]["plan_sha256"], "the analysis plan differs from the chained version: modified after freeze/results")
        _p(probs, isinstance(plan_doc, dict) and plan_doc.get("prereg_record_sha256") == pre[0]["payload"]["record_sha256"], "plan is bound to a different prereg than the chained one")
        probs += validate_prereg_document(prereg_doc, schema_path=schema_path, allow_synthetic=allow_synthetic, require_frozen=True)
        probs += validate_analysis_plan(plan_doc, expected_prereg_sha256=pre[0]["payload"]["record_sha256"])
    if probs:
        raise PreregViolation("ANALYSIS_REFUSED", "; ".join(probs))
    return {"prereg_record_sha256": pre[0]["payload"]["record_sha256"], "plan_sha256": pln[0]["payload"]["plan_sha256"]}
