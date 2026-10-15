"""Preregistration + analysis-plan validation and the 'no analysis without a frozen, unmodified prereg' rule (hash chain)."""
import copy
import json
from pathlib import Path

import pytest

from orca.eval.genesis_v2 import prereg as V2P
from orca.evalinfra import prereg_check as PC
from orca.evalinfra import synthetic as SY
from orca.evalinfra.errors import PreregViolation
from orca.evalinfra.leakage import LeakGuard
from orca.evalinfra.results import EvalLog

ROOT = Path(__file__).resolve().parents[1]
SCHEMA = ROOT / "docs/orneur/phase-21/GENESIS_CAPABILITY_EVAL_V2_PREREGISTRATION_SCHEMA.json"
DRAFT = ROOT / "docs/orneur/phase-21/GENESIS_CAPABILITY_EVAL_V2_PREREGISTRATION_DRAFT.json"
CATS = (3, 10, 11, 12, 14, 15, 17)


@pytest.fixture(scope="module")
def parts():
    items = SY.make_items(31, CATS, {"SCREEN": 2, "QUALIFICATION_HOLDOUT": 4, "DEV": 2, "TRAIN": 2})
    manifest = SY.make_manifest(items)
    prereg = SY.make_prereg(manifest)
    return items, manifest, prereg, SY.make_plan(prereg, CATS)


def plan_problems(plan, prereg):
    plan = copy.deepcopy(plan)
    plan["plan_sha256"] = PC.plan_hash(plan)                                  # re-hash so ONLY the deliberate edit is judged
    return PC.validate_analysis_plan(plan, expected_prereg_sha256=prereg["record_sha256"])


# ------------------------------------------------------------------------------------------------ prereg document vs the repository schema
def test_repository_draft_is_a_valid_draft_but_never_eligible_for_analysis():
    draft = json.loads(DRAFT.read_text())
    assert draft["status"] == "DRAFT_NOT_FROZEN" and draft["frozen"] is False
    assert PC.validate_prereg_document(draft, schema_path=SCHEMA, require_frozen=False) == []
    probs = PC.validate_prereg_document(draft, schema_path=SCHEMA, require_frozen=True)
    assert probs and any("not bound" in p or "not FROZEN" in p for p in probs)            # unfrozen => refused for analysis
    assert any("private_corpus_aggregate_commitment" in p for p in probs)


def test_synthetic_frozen_prereg_passes_only_in_synthetic_mode(parts):
    _, _, prereg, _ = parts
    assert PC.validate_prereg_document(prereg, schema_path=SCHEMA, allow_synthetic=True) == []
    probs = PC.validate_prereg_document(prereg, schema_path=SCHEMA, allow_synthetic=False)
    assert any("V2 versions" in p for p in probs)


def test_prereg_schema_deviations_refused(parts):
    _, _, prereg, _ = parts
    def check(mutate):
        d = copy.deepcopy(prereg)
        mutate(d)
        d["record_sha256"] = V2P.record_hash(d)
        return PC.validate_prereg_document(d, schema_path=SCHEMA, allow_synthetic=True)
    assert check(lambda d: d.update(extra_top_level=1))
    assert check(lambda d: d["bindings"].pop("floors"))
    assert check(lambda d: d["bindings"].update(floors=None))
    assert check(lambda d: d.update(status="DRAFT_NOT_FROZEN"))
    assert check(lambda d: d.update(floors_status="PROPOSED_NOT_LOCKED"))
    assert check(lambda d: d.update(frozen_at=None))
    assert check(lambda d: d["binding_status"].update(floors="MAYBE"))
    d = copy.deepcopy(prereg)
    d["bindings"]["floors"] = {"changed": True}                                # record hash no longer matches
    assert any("record_sha256" in p for p in PC.validate_prereg_document(d, schema_path=SCHEMA, allow_synthetic=True))
    assert PC.validate_prereg_document(prereg, schema_path=ROOT / "nope.json", allow_synthetic=True)[0].startswith("repository schema descriptor unreadable")
    assert PC.validate_prereg_document("x") == ["prereg is not an object"]


# ------------------------------------------------------------------------------------------------ analysis plan rules
def test_valid_plan_passes(parts):
    _, _, prereg, plan = parts
    assert PC.validate_analysis_plan(plan, expected_prereg_sha256=prereg["record_sha256"]) == []


@pytest.mark.parametrize("name,mutate,expect", [
    ("more than four primaries", lambda p: p["endpoints"].extend({**p["endpoints"][0], "id": f"Z{i}", "category": c, "treatment": "T1", "control": "B1"} for i, c in enumerate((14, 15, 17))), "PRIMARY endpoints are allowed"),
    ("no primary", lambda p: [e.update(kind="EXPLORATORY") for e in p["endpoints"]], "between 1 and 4 PRIMARY"),
    ("primary without threshold", lambda p: p["endpoints"][0].update(threshold=None), "needs a numeric threshold"),
    ("threshold above 1", lambda p: p["endpoints"][0].update(threshold=1.5), "needs a numeric threshold"),
    ("unlabeled endpoint kind", lambda p: p["endpoints"][0].update(kind="MAYBE"), "kind must be PRIMARY or EXPLORATORY"),
    ("pooled categories", lambda p: p["endpoints"][0].update(category=[3, 10]), "ONE plan category"),
    ("category not in plan", lambda p: p["endpoints"][0].update(category=99), "ONE plan category"),
    ("same arm both sides", lambda p: p["endpoints"][0].update(control="B2"), "distinct known arms"),
    ("arm not in plan", lambda p: p.update(arms=["B0", "B1", "B2", "T1"]), "arms must be in the plan"),
    ("zero tolerance 15 missing", lambda p: p.update(zero_tolerance_categories=[10, 14, 17]), "must include (10, 14, 15, 17)"),
    ("zero tolerance margin nonzero", lambda p: p["nonregression_margins"].update({"14": 0.05}), "zero-tolerance category 14 must have margin 0"),
    ("margin missing for a category", lambda p: p["nonregression_margins"].pop("3"), "cover EVERY plan category"),
    ("margin out of range", lambda p: p["nonregression_margins"].update({"3": 0.9}), "margin for 3"),
    ("fewer than 3 replicates", lambda p: p.update(run_replicates=2), "odd integer >= 3"),
    ("even replicate count", lambda p: p.update(run_replicates=4), "odd integer >= 3"),
    ("too few resamples", lambda p: p["bootstrap"].update(resamples=9999), "resamples must be >= 10000"),
    ("no fixed bootstrap seed", lambda p: p["bootstrap"].update(base_seed=None), "base_seed"),
    ("unknown correction", lambda p: p.update(correction="sidak"), "correction must be one of"),
    ("no families", lambda p: p.update(families=[]), "families must be declared"),
    ("primary outside any family", lambda p: p["families"][0].update(endpoints=["P1", "P2", "P3"]), "not in any family"),
    ("exploratory inside a family", lambda p: p["families"][0]["endpoints"].append("X2"), "must not be in a confirmatory family"),
    ("endpoint in two families", lambda p: p["families"].append({"name": "again", "alpha": 0.05, "endpoints": ["P1"]}), "in two families"),
    ("family alpha above plan alpha", lambda p: p["families"][0].update(alpha=0.2), "alpha must be in"),
    ("no promotion comparison", lambda p: p.update(promotion_comparison={"candidate": "T2"}), "promotion_comparison"),
    ("bad analysis split", lambda p: p.update(analysis_split="PILOT_TRAIN"), "analysis_split"),
    ("unknown key", lambda p: p.update(sneaky=1), "plan keys must be exactly"),
])
def test_plan_rule_violations_refused(parts, name, mutate, expect):
    _, _, prereg, plan = parts
    p = copy.deepcopy(plan)
    mutate(p)
    probs = plan_problems(p, prereg)
    assert any(expect in x for x in probs), (name, probs)


def test_plan_hash_edit_detected_and_wrong_prereg_binding_detected(parts):
    _, _, prereg, plan = parts
    p = copy.deepcopy(plan)
    p["alpha"] = 0.10
    assert any("plan_sha256 mismatch" in x for x in PC.validate_analysis_plan(p))
    assert any("different prereg" in x for x in PC.validate_analysis_plan(plan, expected_prereg_sha256="0" * 64))


# ------------------------------------------------------------------------------------------------ chain binding
def build(tmp_path, parts, *, freeze=True, plan=True, results=True):
    items, manifest, prereg, pl = parts
    log = EvalLog(tmp_path / "log.jsonl", leak_guard=LeakGuard(items=items))
    log.record_dataset(manifest)
    if freeze:
        log.freeze_prereg(prereg, allow_synthetic=True)
    if plan:
        log.freeze_plan(pl)
    return log


def test_unfrozen_or_invalid_prereg_cannot_be_chained_so_no_result_can_exist(tmp_path, parts):
    items, manifest, prereg, plan = parts
    log = EvalLog(tmp_path / "log.jsonl", leak_guard=LeakGuard(items=items))
    log.record_dataset(manifest)
    draft = json.loads(DRAFT.read_text())
    with pytest.raises(PreregViolation) as e:
        log.freeze_prereg(draft, schema_path=SCHEMA, allow_synthetic=True)
    assert e.value.code == "PREREG_NOT_FROZEN_OR_INVALID"
    d = copy.deepcopy(prereg)
    d["status"], d["frozen"] = "DRAFT_NOT_FROZEN", False
    d["record_sha256"] = V2P.record_hash(d)
    with pytest.raises(PreregViolation):
        log.freeze_prereg(d, allow_synthetic=True)
    with pytest.raises(PreregViolation) as e:
        log.freeze_plan(plan)                                                    # plan before prereg
    assert e.value.code == "PREREG_REQUIRED_FIRST"
    from tests.test_evalinfra_config_lock import CL  # noqa: F401  (import check only)
    cfg = SY.make_config("T2")
    log.lock_config(cfg)
    from orca.evalinfra.results import RESULT_SCHEMA
    r = {"schema_version": RESULT_SCHEMA, "run_id": "r", "arm": "T2", "replicate": 0, "split": "QUALIFICATION_HOLDOUT", "synthetic": True,
         "provenance": {"code_sha": cfg["code_sha"], "config_hash": CL.config_hash(cfg), "dataset_commitment": "0" * 64, "prereg_hash": "0" * 64},
         "rows": SY.draw_outcomes(items, "QUALIFICATION_HOLDOUT", "T2", 0, 1)}
    with pytest.raises(PreregViolation) as e:
        log.record_result(r, manifest=manifest)
    assert e.value.code == "PREREG_PLAN_DATASET_REQUIRED"


def test_a_plan_bound_to_another_prereg_cannot_be_frozen(tmp_path, parts):
    log = build(tmp_path, parts, plan=False)
    other = copy.deepcopy(parts[3])
    other["prereg_record_sha256"] = "1" * 64
    other["plan_sha256"] = PC.plan_hash(other)
    with pytest.raises(PreregViolation) as e:
        log.freeze_plan(other)
    assert e.value.code == "PLAN_INVALID"


@pytest.fixture(scope="module")
def finished(tmp_path_factory, parts):
    d = tmp_path_factory.mktemp("fin")
    ex = SY.build_experiment(d / "log.jsonl", seed=31, categories=CATS, holdout_per_cat=6, arms=("B0", "B2", "T2"))
    return ex, d / "log.jsonl"


def test_analysis_allowed_when_frozen_unmodified_and_ordered(finished):
    ex, path = finished
    entries = ex["log"].log.entries()
    got = PC.assert_analysis_allowed(entries, ex["prereg"], ex["plan"], schema_path=SCHEMA, allow_synthetic=True)
    assert got["prereg_record_sha256"] == ex["prereg"]["record_sha256"] and got["plan_sha256"] == ex["plan"]["plan_sha256"]


def test_analysis_refused_when_prereg_modified_after_results_exist(finished):
    ex, _ = finished
    entries = ex["log"].log.entries()
    changed = copy.deepcopy(ex["prereg"])
    changed["bindings"]["floors"] = {"synthetic": True, "binding": "floors", "relaxed": True}
    changed["record_sha256"] = V2P.record_hash(changed)                        # even with a self-consistent new hash
    with pytest.raises(PreregViolation) as e:
        PC.assert_analysis_allowed(entries, changed, ex["plan"], allow_synthetic=True)
    assert "modified after freeze" in str(e.value)
    sneaky = copy.deepcopy(ex["prereg"])
    sneaky["bindings"]["floors"] = {"synthetic": True, "binding": "floors", "relaxed": True}   # edited WITHOUT re-hashing
    with pytest.raises(PreregViolation):
        PC.assert_analysis_allowed(entries, sneaky, ex["plan"], allow_synthetic=True)


def test_analysis_refused_when_plan_modified_after_results_exist(finished):
    ex, _ = finished
    entries = ex["log"].log.entries()
    changed = copy.deepcopy(ex["plan"])
    changed["endpoints"][0]["threshold"] = 0.01                                 # lower the bar after seeing results
    changed["plan_sha256"] = PC.plan_hash(changed)
    with pytest.raises(PreregViolation) as e:
        PC.assert_analysis_allowed(entries, ex["prereg"], changed, allow_synthetic=True)
    assert "analysis plan differs from the chained version" in str(e.value)


def test_analysis_refused_without_results_or_with_missing_freeze_entries(tmp_path, parts, finished):
    log = build(tmp_path, parts)
    with pytest.raises(PreregViolation) as e:
        PC.assert_analysis_allowed(log.log.entries(), parts[2], parts[3], allow_synthetic=True)
    assert "no results" in str(e.value)
    ex, _ = finished
    entries = [x for x in ex["log"].log.entries() if x["kind"] != "PREREG_FROZEN"]
    with pytest.raises(PreregViolation) as e:
        PC.assert_analysis_allowed(entries, ex["prereg"], ex["plan"], allow_synthetic=True)
    assert "exactly one PREREG_FROZEN" in str(e.value)


def test_analysis_refused_when_a_result_precedes_the_freeze(finished):
    ex, _ = finished
    entries = ex["log"].log.entries()
    res = next(x for x in entries if x["kind"] == "RESULT")
    reordered = [res] + [x for x in entries if x is not res]
    with pytest.raises(PreregViolation) as e:
        PC.assert_analysis_allowed(reordered, ex["prereg"], ex["plan"], allow_synthetic=True)
    assert "BEFORE the first result" in str(e.value) or "before preregistration" in str(e.value)


def test_non_synthetic_mode_refuses_synthetic_material(finished):
    ex, _ = finished
    with pytest.raises(PreregViolation):
        PC.assert_analysis_allowed(ex["log"].log.entries(), ex["prereg"], ex["plan"], allow_synthetic=False)
