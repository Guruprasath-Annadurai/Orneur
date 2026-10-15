"""Four-arm runner + arm-labelled report over model doubles. SYNTHETIC - NOT EVIDENCE OF ANY MODEL CAPABILITY."""
import copy
import socket

import pytest

from orca.evalinfra import arm_report as AP
from orca.evalinfra import arm_runner as AX
from orca.evalinfra import arms as AR
from orca.evalinfra.arms import ArmRefusal
from orca.evalinfra.results import verify_log

HOLDOUT = 20


def D():
    return copy.deepcopy(AR.make_example_definitions())


@pytest.fixture(scope="module")
def run(tmp_path_factory):
    d = D()
    p = tmp_path_factory.mktemp("arms") / "chain.jsonl"
    ex = AX.run_comparison(d, p, holdout_per_cat=HOLDOUT)
    return d, p, ex, AP.build_arm_report(p, d, ex["prereg"], ex["plan"])


def test_results_are_paired_chained_and_verify(run):
    d, p, ex, rep = run
    v = verify_log(p)
    assert v["ok"] and v["synthetic"] and v["arms_locked"] == ["B0", "B1", "B2", "T2"] and v["results"] == 12
    assert rep["synthetic"] is True and rep["banner"] == AR.BANNER
    n = HOLDOUT * len(AX.CATEGORIES)
    for a in AR.ARM_IDS:
        assert rep["arms"][a] == {"status": "EVALUATED", "n_items": n, "n_replicates": 3}


def test_effects_are_labelled_and_match_manual_differences(run):
    _, p, ex, rep = run
    AP.assert_arm_labelled(rep)
    names = {(r["effect"], r["treatment_arm"], r["control_arm"]) for r in rep["effects"]}
    assert names == {("system_effect", "B2", "B1"), ("training_inside_product_effect", "T2", "B2"), ("standardized_prompt_effect", "B1", "B0")}
    prim = [r for r in rep["effects"] if r["is_primary_comparison"]]
    assert prim and all(r["treatment_arm"] == "T2" and r["control_arm"] == "B2" and r["treatment_arm_number"] == 4 and r["control_arm_number"] == 3 for r in prim)
    # recompute system effect (3-2) for one category straight from the chained rows
    from orca.evalinfra import report as RP
    from orca.evalinfra.chain import ChainLog
    from orca.evalinfra.results import KINDS
    col = RP._collect(ChainLog(p, allowed_kinds=KINDS).entries(), ex["plan"])
    maj = {a: RP._majority([col[a]["replicates"][k] for k in range(3)]) for a in AR.ARM_IDS}
    cat = 10
    ids = [i for i in maj["B2"] if col["B2"]["categories"][i] == cat]
    manual = sum(maj["B2"][i] - maj["B1"][i] for i in ids) / len(ids)
    row = next(r for r in rep["effects"] if r["effect"] == "system_effect" and r["category"] == cat)
    assert row["difference"] == pytest.approx(manual, abs=1e-6) and row["n"] == len(ids)


def test_no_pooled_cross_category_or_unlabelled_number(run):
    _, _, _, rep = run
    assert all("category" in r and "treatment_arm" in r and "control_arm" in r for r in rep["effects"])
    assert not any(k in rep for k in ("overall", "overall_score", "mean_score", "pooled"))
    md = AP.render_markdown(rep)
    assert md.startswith("# " + AR.BANNER)


def test_report_is_deterministic(run, tmp_path):
    d, p, ex, rep = run
    ex2 = AX.run_comparison(D(), tmp_path / "again.jsonl", holdout_per_cat=HOLDOUT)
    assert ex2["log"].log.head() == ex["log"].log.head()
    assert AP.build_arm_report(tmp_path / "again.jsonl", D(), ex2["prereg"], ex2["plan"]) == rep


def test_no_network_is_touched(tmp_path, monkeypatch):
    def boom(*a, **k):
        raise AssertionError("network access attempted")
    monkeypatch.setattr(socket, "socket", boom)
    monkeypatch.setattr(socket, "create_connection", boom)
    AX.run_comparison(D(), tmp_path / "c.jsonl", holdout_per_cat=2, replicates=3)


def test_runner_refuses_mismatched_system_before_running_anything(tmp_path):
    """failing-before: a mismatched B2/T2 system must be refused and leave NO log behind."""
    d = D()
    next(a for a in d["arms"] if a["arm"] == "T2")["system"]["prompts"]["system"] = "f" * 64
    with pytest.raises(ArmRefusal) as e:
        AX.run_comparison(d, tmp_path / "x.jsonl", holdout_per_cat=2)
    assert e.value.code == "COMPARISON_REFUSED" and not (tmp_path / "x.jsonl").exists()


def test_runner_refuses_non_double_models(tmp_path):
    class RealLooking:
        def respond(self, r):
            raise AssertionError("must never be called")
    d = D()
    doubles = {(a["model"]["id"], a["model"]["revision"]): RealLooking() for a in d["arms"]}
    with pytest.raises(ArmRefusal) as e:
        AX.run_comparison(d, tmp_path / "x.jsonl", doubles=doubles, holdout_per_cat=2)
    assert e.value.code == "ONLY_MODEL_DOUBLES"


def test_report_refuses_log_with_missing_arm(tmp_path):
    """failing-before: an arm without results (here arm 2) must refuse the whole comparison; nothing is estimated for the others."""
    d = D()
    ex = AX.run_comparison(d, tmp_path / "m.jsonl", holdout_per_cat=2, skip_arms=("B1",))
    with pytest.raises(ArmRefusal) as e:
        AP.build_arm_report(tmp_path / "m.jsonl", d, ex["prereg"], ex["plan"])
    assert e.value.code == "MISSING_ARM" and "B1" in e.value.detail


def test_report_refuses_definition_that_differs_from_locked_configs(run, tmp_path):
    d, p, ex, _ = run
    d2 = D()
    for a in d2["arms"]:                                       # a consistent but DIFFERENT budget on every arm is still a different configuration
        a["budgets"]["max_wall_clock_s"] = 31
        if a["system"]:
            a["system"]["budgets"]["max_wall_clock_s"] = 31
    assert AR.problems(d2) == []
    with pytest.raises(ArmRefusal) as e:
        AP.build_arm_report(p, d2, ex["prereg"], ex["plan"])
    assert e.value.code == "LOCK_DIFFERS_FROM_DEFINITION"


def test_report_refuses_invalid_definition_even_with_a_valid_log(run):
    d, p, ex, _ = run
    bad = D()
    next(a for a in bad["arms"] if a["arm"] == "T2")["system"]["retrieval"]["top_k"] = 9
    with pytest.raises(ArmRefusal):
        AP.build_arm_report(p, bad, ex["prereg"], ex["plan"])


def test_report_refuses_plan_without_all_four_arms(run):
    d, p, ex, _ = run
    plan = {**ex["plan"], "arms": ["B0", "B2", "T2"]}
    with pytest.raises(ArmRefusal) as e:
        AP.build_arm_report(p, d, ex["prereg"], plan)
    assert e.value.code == "MISSING_ARM"


def test_aggregate_without_arm_labels_is_refused():
    good = [{"arm": a, "category": 3, "score": s} for a in AR.ARM_IDS for s in (0.0, 1.0)]
    agg = AP.aggregate_scores(good)
    assert agg["T2|3"] == {"arm": "T2", "category": 3, "n": 2, "mean": 0.5}
    for bad in ([{"category": 3, "score": 1.0}], [{"arm": "ORNEUR", "category": 3, "score": 1.0}], [{"arm": "B2", "score": 1.0}], [], None,
                [r for r in good if r["arm"] != "B1"]):
        with pytest.raises(ArmRefusal):
            AP.aggregate_scores(bad)


def test_report_with_stripped_labels_is_refused(run):
    _, _, _, rep = run
    bad = copy.deepcopy(rep)
    del bad["effects"][0]["control_arm"]
    with pytest.raises(ArmRefusal) as e:
        AP.assert_arm_labelled(bad)
    assert e.value.code == "UNLABELLED_AGGREGATE"
    with pytest.raises(ArmRefusal):
        AP.render_markdown(bad)
    with pytest.raises(ArmRefusal):
        AP.assert_arm_labelled({"effects": []})


def test_doubles_are_unselected_placeholders_not_real_models(run):
    d, _, ex, _ = run
    assert all(a["model"]["id"].startswith("synthetic/") for a in d["arms"])
    assert all(isinstance(x, AX.ModelDouble) for x in ex["doubles"].values())
