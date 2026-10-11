"""Paired comparison statistics: McNemar exact, paired bootstrap (percentile + BCa), effect sizes, category breakdown, multiplicity families."""
import math
import random

import pytest

from orca.evalinfra import stats_paired as SP
from orca.evalinfra.errors import SchemaViolation


# ------------------------------------------------------------------------------------------------ McNemar
def test_mcnemar_exact_matches_hand_computed_values():
    r = SP.mcnemar_exact(10, 2)                      # n=12, k=2: 2*(1+12+66)/4096
    assert r["p_two_sided"] == pytest.approx(158 / 4096, abs=1e-15)
    assert SP.mcnemar_exact(2, 10)["p_two_sided"] == r["p_two_sided"]           # symmetric
    assert SP.mcnemar_exact(5, 5)["p_two_sided"] == 1.0
    assert SP.mcnemar_exact(0, 0)["p_two_sided"] == 1.0 and SP.mcnemar_exact(0, 0)["n_discordant"] == 0
    assert SP.mcnemar_exact(8, 0)["p_two_sided"] == pytest.approx(2 / 256)
    assert SP.mcnemar_exact(1, 0)["p_two_sided"] == 1.0                          # capped at 1
    assert SP.mcnemar_exact(10, 2)["p_mid"] < SP.mcnemar_exact(10, 2)["p_two_sided"]


def test_mcnemar_exact_is_exact_for_large_counts_and_matches_scipy_style_reference():
    # reference computed independently with math.comb in rational arithmetic: n=400, b=230, c=170
    from fractions import Fraction
    n, k = 400, 170
    ref = float(min(Fraction(1), Fraction(2 * sum(math.comb(n, i) for i in range(k + 1)), 2 ** n)))
    assert SP.mcnemar_exact(230, 170)["p_two_sided"] == ref
    assert ref == pytest.approx(0.0027, abs=0.0006)          # continuity-uncorrected normal approximation: z = (230-200)/10 = 3.0


def test_mcnemar_rejects_negative_counts():
    with pytest.raises(SchemaViolation):
        SP.mcnemar_exact(-1, 3)


def test_discordant_counts_orientation():
    x, y = [1, 1, 0, 0, 1], [0, 1, 1, 0, 0]
    assert SP.discordant_counts([float(v) for v in x], [float(v) for v in y]) == {"n11": 1, "b": 2, "c": 1, "n00": 1}


# ------------------------------------------------------------------------------------------------ alignment
def test_unpaired_or_non_numeric_outcomes_refused():
    with pytest.raises(SchemaViolation) as e:
        SP.align({"a": 1.0, "b": 0.0}, {"a": 1.0})
    assert e.value.code == "UNPAIRED_ITEMS"
    with pytest.raises(SchemaViolation):
        SP.align({"a": float("nan")}, {"a": 1.0})
    with pytest.raises(SchemaViolation):
        SP.align({"a": True}, {"a": 1.0})


# ------------------------------------------------------------------------------------------------ bootstrap
DIFFS = [1.0] * 30 + [-1.0] * 10 + [0.0] * 60


def test_bootstrap_is_deterministic_and_seed_sensitive():
    a = SP.paired_bootstrap(DIFFS, seed=1)
    b = SP.paired_bootstrap(DIFFS, seed=1)
    c = SP.paired_bootstrap(DIFFS, seed=2)
    assert a == b
    assert a["boot_se"] != c["boot_se"] and a["point"] == c["point"] == pytest.approx(0.2)
    cont = [random.Random(i).random() - 0.4 for i in range(80)]            # continuous differences: different seeds give different intervals
    assert SP.paired_bootstrap(cont, seed=1)["percentile"] != SP.paired_bootstrap(cont, seed=2)["percentile"]


def test_bootstrap_refuses_fewer_than_10000_resamples_and_bad_inputs():
    for bad in (9999, 1000, 0, -5, 10_000.0):
        with pytest.raises(SchemaViolation) as e:
            SP.paired_bootstrap(DIFFS, seed=1, n_resamples=bad)
        assert e.value.code == "TOO_FEW_RESAMPLES"
    with pytest.raises(SchemaViolation):
        SP.paired_bootstrap([1.0], seed=1)
    with pytest.raises(SchemaViolation):
        SP.paired_bootstrap(DIFFS, seed=True)
    with pytest.raises(SchemaViolation):
        SP.paired_bootstrap(DIFFS, seed=1, confidence=1.0)


def test_bootstrap_interval_is_calibrated_against_the_analytic_se():
    r = SP.paired_bootstrap(DIFFS, seed=3)
    n = len(DIFFS)
    mean = sum(DIFFS) / n
    se = math.sqrt(sum((d - mean) ** 2 for d in DIFFS) / (n - 1) / n)
    assert r["boot_se"] == pytest.approx(se, rel=0.05)
    lo, hi = r["percentile"]
    assert lo == pytest.approx(mean - 1.96 * se, abs=0.02) and hi == pytest.approx(mean + 1.96 * se, abs=0.02)
    assert r["n_resamples"] == 10_000 and r["bca"] is not None


def test_bca_differs_from_percentile_for_skewed_data_and_is_close_for_symmetric():
    sym = SP.paired_bootstrap([1.0] * 20 + [-1.0] * 20 + [0.0] * 20, seed=4)
    assert sym["bca"][0] == pytest.approx(sym["percentile"][0], abs=0.05) and sym["bca"][1] == pytest.approx(sym["percentile"][1], abs=0.05)
    rng = random.Random(9)
    skew = [0.0] * 55 + [1.0] * 5 + [rng.random() * 0.2 for _ in range(10)]
    r = SP.paired_bootstrap(skew, seed=4)
    assert r["bca"] != r["percentile"] and r["bca"][0] <= r["point"] <= r["bca"][1]
    assert "bca_z0" in r and "bca_acceleration" in r


def test_bca_reports_unavailability_instead_of_inventing_a_value():
    r = SP.paired_bootstrap([0.5] * 20, seed=1)                  # zero-variance: every resample equals the point estimate -> a point-mass interval, honestly
    assert r["percentile"] == [0.5, 0.5] and r["bca"] == [0.5, 0.5]
    r2 = SP.paired_bootstrap([1.0, 0.0], seed=1)
    assert r2["bca"] is None and "fewer than 3" in r2["bca_unavailable_reason"]


def test_cluster_bootstrap_widens_the_interval_when_items_are_correlated():
    diffs = [1.0] * 20 + [0.0] * 20 + [-1.0] * 4 + [0.0] * 16
    clusters = [i // 10 for i in range(len(diffs))]               # whole clusters move together
    plain = SP.paired_bootstrap(diffs, seed=5)
    clus = SP.paired_bootstrap(diffs, seed=5, clusters=clusters)
    assert (clus["percentile"][1] - clus["percentile"][0]) > (plain["percentile"][1] - plain["percentile"][0])
    assert clus["n_units"] == 6 and plain["n_units"] == 60
    with pytest.raises(SchemaViolation):
        SP.paired_bootstrap(diffs, seed=5, clusters=[1, 2])


# ------------------------------------------------------------------------------------------------ effect sizes
def test_effect_sizes_known_values():
    diffs = [1.0, 1.0, 1.0, 0.0, 0.0, -1.0]
    e = SP.effect_sizes(diffs)
    assert e["mean_difference"] == pytest.approx(2 / 6)
    sd = math.sqrt(sum((d - 1 / 3) ** 2 for d in diffs) / 5)
    assert e["cohens_dz"] == pytest.approx((1 / 3) / sd)
    assert e["hedges_gz"] == pytest.approx(e["cohens_dz"] * (1 - 3 / (4 * 5 - 1)))
    x, y = [1.0, 1.0, 1.0, 0.0, 0.0, 0.0], [0.0, 0.0, 1.0, 0.0, 1.0, 0.0]
    e = SP.effect_sizes([p - q for p, q in zip(x, y)], x, y)
    assert e["odds_ratio_discordant"] == pytest.approx((2 + 0.5) / (1 + 0.5)) and e["cohens_g"] == pytest.approx(2 / 3 - 0.5)
    assert SP.effect_sizes([0.0, 0.0, 0.0])["cohens_dz"] is None             # zero variance: undefined, not infinity


# ------------------------------------------------------------------------------------------------ comparison + categories
def _data(seed=1, n=40):
    rng = random.Random(seed)
    cats = {f"i{k:03d}": ("A" if k < n else "B") for k in range(2 * n)}
    ctrl = {i: float(rng.random() < 0.5) for i in cats}
    trt = {i: (1.0 if (ctrl[i] == 1.0 or (cats[i] == "A" and rng.random() < 0.6)) else 0.0) for i in cats}
    return {"T2": trt, "B2": ctrl}, cats


def test_compare_pair_reports_n_difference_ci_and_mcnemar():
    out, cats = _data()
    ids = [i for i in cats if cats[i] == "A"]
    r = SP.compare_pair({i: out["T2"][i] for i in ids}, {i: out["B2"][i] for i in ids}, seed=7)
    assert r["n"] == 40 and r["binary"] and r["mcnemar"]["c"] == 0 and r["mcnemar"]["b"] > 5
    assert r["difference"] == pytest.approx(r["mean_treatment"] - r["mean_control"])
    assert r["bootstrap"]["percentile"][0] < r["difference"] < r["bootstrap"]["percentile"][1] or r["bootstrap"]["percentile"][1] == r["difference"]


def test_category_breakdown_never_merges_categories():
    out, cats = _data()
    per = SP.compare_by_category(out, cats, "T2", "B2", seed=11)
    assert set(per) == {"A", "B"} and per["A"]["n"] == 40 and per["B"]["n"] == 40
    assert per["A"]["difference"] > 0.15 and abs(per["B"]["difference"]) < 1e-12           # B has no real effect and must not be lifted by A
    assert not any(hasattr(SP, n) for n in ("overall", "pooled", "composite", "collapse", "aggregate_categories", "overall_score"))


def test_category_results_independent_of_which_other_categories_are_analysed():
    out, cats = _data()
    both = SP.compare_by_category(out, cats, "T2", "B2", seed=11)
    only = SP.compare_by_category(out, cats, "T2", "B2", seed=11, only_categories={"A"})
    assert only["A"]["bootstrap"] == both["A"]["bootstrap"]


def test_unevaluated_or_unknown_arm_is_refused_not_estimated():
    out, cats = _data()
    with pytest.raises(SchemaViolation) as e:
        SP.compare_by_category({"T2": out["T2"]}, cats, "T2", "R", seed=1)
    assert e.value.code == "ARM_NOT_EVALUATED"
    with pytest.raises(SchemaViolation) as e:
        SP.compare_by_category(out, cats, "T2", "ZZ", seed=1)
    assert e.value.code == "UNKNOWN_ARM"


# ------------------------------------------------------------------------------------------------ multiplicity
P = {"a": 0.01, "b": 0.04, "c": 0.03, "d": 0.005}


def test_bonferroni_holm_bh_match_hand_computed_values():
    assert SP.adjust_pvalues(P, "bonferroni") == pytest.approx({"a": 0.04, "b": 0.16, "c": 0.12, "d": 0.02})
    assert SP.adjust_pvalues(P, "holm") == pytest.approx({"d": 0.02, "a": 0.03, "c": 0.06, "b": 0.06})
    assert SP.adjust_pvalues(P, "benjamini_hochberg") == pytest.approx({"d": 0.02, "a": 0.02, "c": 0.04, "b": 0.04})


def test_adjusted_p_never_below_raw_and_holm_never_exceeds_bonferroni():
    rng = random.Random(2)
    p = {str(i): rng.random() ** 2 for i in range(12)}
    bon, holm, bh = (SP.adjust_pvalues(p, m) for m in ("bonferroni", "holm", "benjamini_hochberg"))
    for k in p:
        assert p[k] <= bh[k] + 1e-12 and bh[k] <= holm[k] + 1e-12 <= bon[k] + 1e-12 and 0 <= bon[k] <= 1


def test_adjust_rejects_bad_inputs():
    with pytest.raises(SchemaViolation):
        SP.adjust_pvalues({"a": 1.2}, "holm")
    with pytest.raises(SchemaViolation):
        SP.adjust_pvalues({"a": 0.1}, "sidak")
    assert SP.adjust_pvalues({}, "holm") == {}


def test_families_are_explicit_exclusive_and_exploratory_is_never_adjusted_into_significance():
    fams = [{"name": "primary", "alpha": 0.05, "endpoints": ["a", "b", "c"]}]
    res = SP.apply_families(fams, {"a": 0.012, "b": 0.03, "c": 0.2, "x": 0.001}, "bonferroni", exploratory=("x",))
    assert res["a"]["adjusted_p"] == pytest.approx(0.036) and res["a"]["significant_after_correction"] and res["a"]["family_size"] == 3
    assert not res["b"]["significant_after_correction"]
    assert res["x"]["status"] == "EXPLORATORY_UNADJUSTED" and res["x"]["adjusted_p"] is None and res["x"]["significant_after_correction"] is False
    with pytest.raises(SchemaViolation) as e:
        SP.apply_families(fams, {"a": 0.01, "b": 0.01, "c": 0.01, "y": 0.0}, "holm")
    assert e.value.code == "ENDPOINT_WITHOUT_FAMILY"
    with pytest.raises(SchemaViolation) as e:
        SP.apply_families(fams + [{"name": "dup", "alpha": 0.05, "endpoints": ["a"]}], {"a": 0.01, "b": 0.01, "c": 0.01}, "holm")
    assert e.value.code == "ENDPOINT_IN_TWO_FAMILIES"
    with pytest.raises(SchemaViolation) as e:
        SP.apply_families(fams, {"a": 0.01, "b": 0.01}, "holm")
    assert e.value.code == "FAMILY_ENDPOINT_WITHOUT_RESULT"


def test_family_size_changes_the_correction():
    small = SP.apply_families([{"name": "f", "alpha": .05, "endpoints": ["a"]}], {"a": 0.02}, "bonferroni")
    big = SP.apply_families([{"name": "f", "alpha": .05, "endpoints": ["a", "b", "c", "d"]}], {"a": 0.02, "b": 0.5, "c": 0.5, "d": 0.5}, "bonferroni")
    assert small["a"]["significant_after_correction"] and not big["a"]["significant_after_correction"]


# ------------------------------------------------------------------------------------------------ replicates / zero tolerance
def test_replicate_aggregation_and_seed_replication():
    agg = SP.aggregate_replicates([{"i": 1.0, "j": 0.0}, {"i": 0.0, "j": 0.0}, {"i": 1.0, "j": 1.0}])
    assert agg == {"i": pytest.approx(2 / 3), "j": pytest.approx(1 / 3)}
    with pytest.raises(SchemaViolation):
        SP.aggregate_replicates([{"i": 1.0}, {"j": 1.0}])
    per = {s: {"T2": {"a": 1.0, "b": 1.0, "c": 0.0}, "B2": {"a": 0.0, "b": 1.0, "c": 0.0}} for s in (1, 2, 3)}
    r = SP.seed_replication(per, "T2", "B2")
    assert r["all_positive"] and r["n_seeds"] == 3
    per[3]["T2"]["a"] = 0.0
    assert not SP.seed_replication(per, "T2", "B2")["all_positive"]
    with pytest.raises(SchemaViolation) as e:
        SP.seed_replication({1: per[1], 2: per[2]}, "T2", "B2")
    assert e.value.code == "TOO_FEW_SEEDS"


def test_zero_tolerance_counts_failures_per_arm_and_category():
    outcomes = {"T2": {"a": 1.0, "b": 0.0, "c": 1.0}, "B2": {"a": 1.0, "b": 1.0, "c": 1.0}}
    cats = {"a": 14, "b": 14, "c": 3}
    z = SP.zero_tolerance_summary(outcomes, cats, [14, 15])
    assert z["T2"][14] == {"n": 2, "failures": 1} and z["B2"][14] == {"n": 2, "failures": 0} and z["T2"][15] == {"n": 0, "failures": 0}
