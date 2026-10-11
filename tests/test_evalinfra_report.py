"""Reproducible reporting: deterministic JSON+Markdown from a verified log; every number labelled with arm, n, CI, endpoint status; no composite score."""
import copy
import json
from pathlib import Path

import pytest

from orca.eval.genesis_v2 import prereg as V2P
from orca.evalinfra import prereg_check as PC
from orca.evalinfra import report as RP
from orca.evalinfra import synthetic as SY
from orca.evalinfra.errors import PreregViolation

ROOT = Path(__file__).resolve().parents[1]
CATS = (3, 4, 10, 11, 12, 14, 15, 17)


@pytest.fixture(scope="module")
def exp(tmp_path_factory):
    d = tmp_path_factory.mktemp("rep")
    ex = SY.build_experiment(d / "log.jsonl", seed=61, categories=CATS, holdout_per_cat=30)
    ex["path"] = d / "log.jsonl"
    ex["report"] = RP.build_report(ex["path"], ex["prereg"], ex["plan"], allow_synthetic=True)
    return ex


def test_report_is_deterministic_byte_for_byte(exp, tmp_path):
    again = SY.build_experiment(tmp_path / "log.jsonl", seed=61, categories=CATS, holdout_per_cat=30)
    r2 = RP.build_report(tmp_path / "log.jsonl", again["prereg"], again["plan"], allow_synthetic=True)
    assert RP.report_json_text(r2) == RP.report_json_text(exp["report"])
    assert RP.render_markdown(r2) == RP.render_markdown(exp["report"])
    assert (tmp_path / "log.jsonl").read_bytes() == exp["path"].read_bytes()         # the whole result log is reproducible too


def test_every_endpoint_number_is_labelled_with_arms_n_ci_and_status(exp):
    rep = exp["report"]
    assert [e["id"] for e in rep["endpoints"]] == ["P1", "P2", "P3", "P4", "X1", "X2"]
    for e in rep["endpoints"]:
        assert e["status"] in ("PRIMARY", "EXPLORATORY") and e["treatment"] and e["control"] and e["category"] is not None
        assert e["result_status"] == "COMPUTED" and e["n"] == 30
        assert len(e["ci_percentile"]) == 2 and e["ci_confidence"] == 0.95 and e["n_resamples"] == 10_000
        assert "multiplicity" in e and e["metric"] == "pass_rate_binary"
        if e["status"] == "PRIMARY":
            assert e["multiplicity"]["status"] == "CONFIRMATORY" and e["multiplicity"]["family"] == "primary-family" and e["multiplicity"]["family_size"] == 4
            assert e["decision"] in ("SUPPORTED", "NOT_SUPPORTED") and e["threshold"] is not None
        else:
            assert e["multiplicity"]["status"] == "EXPLORATORY_UNADJUSTED" and e["multiplicity"]["adjusted_p"] is None and "decision" not in e
    for arm, cats in rep["descriptive_accuracy_by_arm_and_category"].items():
        for c in cats.values():
            assert c["arm"] == arm and c["n"] == 30 and c["status"] == "DESCRIPTIVE"
    for b in rep["category_breakdown"]:
        for c in b["categories"].values():
            assert c["n"] == 30 and c["status"] == "EXPLORATORY_UNADJUSTED" and len(c["ci_percentile"]) == 2 and c["arm_treatment"] == b["treatment"]
    for x in rep["nonregression"] + rep["zero_tolerance"]:
        assert x["n"] == 30


def test_categories_are_never_collapsed_into_a_single_score(exp):
    rep = exp["report"]
    text = RP.report_json_text(rep) + RP.render_markdown(rep)
    for forbidden in ("overall_score", "composite", "average_accuracy", "mean_accuracy_all", "pooled"):
        assert forbidden not in text
    per_cat = rep["descriptive_accuracy_by_arm_and_category"]["T2"]
    assert set(per_cat) == {str(c) for c in CATS}
    assert {r["category"] for r in rep["zero_tolerance"]} == {10, 14, 15, 17}
    gate = rep["promotion_gate"]
    assert isinstance(gate["all_preregistered_conditions_met"], bool) and "not a score" in gate["note"]


def test_reference_arm_without_data_is_not_evaluated_never_estimated(exp):
    rep = exp["report"]
    assert rep["arms"]["R"]["status"] == "NOT_EVALUATED" and "R" not in rep["descriptive_accuracy_by_arm_and_category"]
    md = RP.render_markdown(rep)
    assert "| R | NOT_EVALUATED |" in md


def test_synthetic_banner_everywhere(exp):
    rep = exp["report"]
    assert rep["synthetic"] is True and rep["banner"] == "SYNTHETIC - NOT EVIDENCE OF ANY MODEL CAPABILITY"
    md = RP.render_markdown(rep)
    assert md.startswith("# SYNTHETIC - NOT EVIDENCE OF ANY MODEL CAPABILITY") and md.rstrip().endswith("**SYNTHETIC - NOT EVIDENCE OF ANY MODEL CAPABILITY**")


def test_provenance_is_bound_into_the_report(exp):
    pv = exp["report"]["provenance"]
    assert pv["prereg_record_sha256"] == exp["prereg"]["record_sha256"] and pv["analysis_plan_sha256"] == exp["plan"]["plan_sha256"]
    assert pv["dataset_manifest_sha256"] == exp["manifest"]["manifest_sha256"] and set(pv["arm_config_hashes"]) == {"B0", "B1", "B2", "T1", "T2"}
    assert pv["log_head"] == {"seq": exp["report"]["provenance"]["log_head"]["seq"], "entry_hash": exp["log"].log.head()["entry_hash"]}


def test_pre_registered_decision_rule_is_applied_exactly(exp):
    for e in exp["report"]["endpoints"]:
        if e["status"] != "PRIMARY":
            continue
        ok = (e["difference"] >= e["threshold"] and e["ci_percentile"][0] > 0 and e["multiplicity"]["significant_after_correction"] and e["replicates_all_positive"])
        assert (e["decision"] == "SUPPORTED") == ok


def test_missing_arm_makes_dependent_endpoints_not_evaluated_and_keeps_family_size(tmp_path):
    ex = SY.build_experiment(tmp_path / "l.jsonl", seed=62, categories=CATS, holdout_per_cat=20, arms=("B1", "B2", "T1", "T2"))       # B0 never run
    rep = RP.build_report(tmp_path / "l.jsonl", ex["prereg"], ex["plan"], allow_synthetic=True)
    p1 = next(e for e in rep["endpoints"] if e["id"] == "P1")
    assert p1["result_status"] == "NOT_EVALUATED" and rep["primary_decisions"]["P1"] == "NOT_EVALUATED"
    p2 = next(e for e in rep["endpoints"] if e["id"] == "P2")
    assert p2["multiplicity"]["family_size"] == 4                                    # the declared family size is kept (P1 enters the correction as p = 1)
    from orca.evalinfra import stats_paired as SP
    raw = {e["id"]: e["mcnemar_p_two_sided"] for e in rep["endpoints"] if e["id"] in ("P2", "P3", "P4")}
    expected = SP.adjust_pvalues({"P1": 1.0, **raw}, "holm")                         # missing member counted as p = 1.0, never dropped or treated as significant
    for k in raw:
        assert next(e for e in rep["endpoints"] if e["id"] == k)["multiplicity"]["adjusted_p"] == pytest.approx(expected[k], abs=1e-6)
    assert rep["promotion_gate"]["primary_endpoints_all_supported"] is False
    assert any(b["status"] == "NOT_EVALUATED" for b in rep["category_breakdown"])


def test_incomplete_replicates_make_an_arm_not_evaluated(tmp_path):
    ex = SY.build_experiment(tmp_path / "l.jsonl", seed=63, categories=CATS, holdout_per_cat=12, arms=("B2", "T2"), replicates=3)
    # re-build a log in which T2 has only 2 of 3 replicates
    from orca.evalinfra.chain import ChainLog
    es = ChainLog(tmp_path / "l.jsonl").entries()
    out = ChainLog(tmp_path / "partial.jsonl")
    dropped = False
    for e in es:
        if e["kind"] == "RESULT" and e["payload"]["arm"] == "T2" and e["payload"]["replicate"] == 2:
            dropped = True
            continue
        out.append(e["kind"], e["payload"])
    assert dropped
    rep = RP.build_report(tmp_path / "partial.jsonl", ex["prereg"], ex["plan"], allow_synthetic=True)
    assert rep["arms"]["T2"]["status"] == "NOT_EVALUATED" and "incomplete replicates" in rep["arms"]["T2"]["reason"]


def test_refuses_when_prereg_or_plan_modified_or_not_synthetic_mode(exp):
    changed = copy.deepcopy(exp["prereg"])
    changed["bindings"]["floors"] = {"x": 1}
    changed["record_sha256"] = V2P.record_hash(changed)
    with pytest.raises(PreregViolation):
        RP.build_report(exp["path"], changed, exp["plan"], allow_synthetic=True)
    p = copy.deepcopy(exp["plan"])
    p["alpha"] = 0.2
    p["plan_sha256"] = PC.plan_hash(p)
    with pytest.raises(PreregViolation):
        RP.build_report(exp["path"], exp["prereg"], p, allow_synthetic=True)
    with pytest.raises(PreregViolation):
        RP.build_report(exp["path"], exp["prereg"], exp["plan"], allow_synthetic=False)


def test_refuses_a_tampered_log(exp, tmp_path):
    bad = tmp_path / "bad.jsonl"
    bad.write_text(exp["path"].read_text().replace('"score":1.0', '"score":0.0', 1))
    with pytest.raises(Exception) as e:
        RP.build_report(bad, exp["prereg"], exp["plan"], allow_synthetic=True)
    assert "ChainCorrupt" in type(e.value).__name__ or "LOG_VERIFICATION_FAILED" in str(e.value) or "HASH_MISMATCH" in str(e.value)


def test_non_binary_scores_refused_for_confirmatory_endpoints(tmp_path):
    from orca.evalinfra.leakage import LeakGuard
    from orca.evalinfra.results import RESULT_SCHEMA, EvalLog
    from orca.evalinfra.config_lock import config_hash
    cats = (3, 10, 11, 12, 14, 15, 17)
    items = SY.make_items(70, cats, {"SCREEN": 2, "QUALIFICATION_HOLDOUT": 4, "DEV": 2, "TRAIN": 2})
    manifest = SY.make_manifest(items)
    prereg = SY.make_prereg(manifest)
    plan = SY.make_plan(prereg, cats)
    log = EvalLog(tmp_path / "l.jsonl", leak_guard=LeakGuard(items=items))
    log.record_dataset(manifest)
    log.freeze_prereg(prereg, allow_synthetic=True)
    log.freeze_plan(plan)
    part = {p["split"]: p["partition_sha256"] for p in manifest["partitions"]}
    for arm in ("B0", "B1", "B2", "T1", "T2"):
        log.lock_config(SY.make_config(arm))
    for arm in ("B0", "B1", "B2", "T1", "T2"):
        cfg = SY.make_config(arm)
        for rep in range(3):
            rows = SY.draw_outcomes(items, "QUALIFICATION_HOLDOUT", arm, rep, 1)
            rows[0]["score"] = 0.5
            log.record_result({"schema_version": RESULT_SCHEMA, "run_id": f"{arm}{rep}", "arm": arm, "replicate": rep, "split": "QUALIFICATION_HOLDOUT", "synthetic": True,
                               "provenance": {"code_sha": cfg["code_sha"], "config_hash": config_hash(cfg), "dataset_commitment": part["QUALIFICATION_HOLDOUT"], "prereg_hash": prereg["record_sha256"]},
                               "rows": rows}, manifest=manifest)
    with pytest.raises(PreregViolation) as e:
        RP.build_report(tmp_path / "l.jsonl", prereg, plan, allow_synthetic=True)
    assert e.value.code == "METRIC_NOT_BINARY" or "METRIC_NOT_BINARY" in str(e.value)


def test_cli_report_writes_identical_files(exp, tmp_path):
    import subprocess
    import sys
    pj, pl = tmp_path / "prereg.json", tmp_path / "plan.json"
    pj.write_text(json.dumps(exp["prereg"], sort_keys=True))
    pl.write_text(json.dumps(exp["plan"], sort_keys=True))
    r = subprocess.run([sys.executable, "-m", "orca.evalinfra", "report", str(exp["path"]), "--prereg", str(pj), "--plan", str(pl), "--out-dir", str(tmp_path / "out"),
                        "--allow-synthetic"], capture_output=True, text=True, cwd=ROOT, timeout=300)
    assert r.returncode == 0, r.stderr
    assert (tmp_path / "out/report.json").read_text() == RP.report_json_text(exp["report"])
    assert (tmp_path / "out/report.md").read_text() == RP.render_markdown(exp["report"])
    refused = subprocess.run([sys.executable, "-m", "orca.evalinfra", "report", str(exp["path"]), "--prereg", str(pj), "--plan", str(pl), "--out-dir", str(tmp_path / "o2")],
                             capture_output=True, text=True, cwd=ROOT, timeout=300)
    assert refused.returncode == 1 and "REFUSED" in refused.stderr and not (tmp_path / "o2/report.json").exists()
