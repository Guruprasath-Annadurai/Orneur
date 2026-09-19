"""
Phase 21B.4.10/.10.1: tested, executable encoding of the Phase
21B.4.9.x/10.1 Genesis Frontier statistical contract
(orca.eval.frontier_stats). All fixtures here are synthetic -- no real
candidate, reference, or control data is used anywhere in this file.
"""
from __future__ import annotations

import random

import pytest

from orca.eval.frontier_stats import (
    CONTROL_QUORUM_REQUIRED,
    CONTROL_TARGET_SET,
    DELTA_BEST_REFERENCE,
    DELTA_CONTROL_SUPERIORITY,
    DELTA_FRONTIER,
    DELTA_QUANTIZATION,
    DELTA_TIE,
    FRONTIER_REFERENCE_QUORUM_MIN,
    FRONTIER_REFERENCE_QUORUM_MIN_LINEAGES,
    FRONTIER_STATISTICAL_CONTRACT_VERSION,
    FRONTIER_TARGET_REFERENCES,
    REGISTERED_FRONTIER_REFERENCES,
    Classification,
    ConfidenceInterval,
    QuorumStatus,
    StatisticalUnit,
    StatisticalUnitValidationError,
    bootstrap_best_reference_ci,
    bootstrap_control_superiority_ci,
    bootstrap_frontier_median_ci,
    classify_best_reference,
    classify_control_superiority,
    classify_frontier_gap,
    classify_pairwise_finalist,
    classify_quantization,
    clustered_units,
    independent_units,
    paired_bootstrap_ci,
    validate_control_quorum,
    validate_frontier_reference_quorum,
    validate_statistical_units,
)


def test_locked_constants_match_the_methodology_documents():
    assert FRONTIER_STATISTICAL_CONTRACT_VERSION == "genesis-frontier-stats-v2"
    assert DELTA_FRONTIER == 0.08
    assert DELTA_BEST_REFERENCE == 0.20
    assert DELTA_CONTROL_SUPERIORITY == 0.10
    assert DELTA_TIE == 0.03
    assert DELTA_QUANTIZATION == 0.05
    assert FRONTIER_TARGET_REFERENCES == 6
    assert FRONTIER_REFERENCE_QUORUM_MIN == 4
    assert FRONTIER_REFERENCE_QUORUM_MIN_LINEAGES == 3
    assert CONTROL_TARGET_SET == ("Qwen3-8B", "Mistral-Nemo-Instruct-2407", "Phi-4")
    assert CONTROL_QUORUM_REQUIRED == 3
    assert len(REGISTERED_FRONTIER_REFERENCES) == 6
    assert len(set(REGISTERED_FRONTIER_REFERENCES.values())) == 6  # each reference has a distinct organization


# ── ConfidenceInterval ────────────────────────────────────────────────────


def test_confidence_interval_rejects_lower_above_upper():
    with pytest.raises(ValueError):
        ConfidenceInterval(lower=0.5, upper=0.1)


# ── validate_statistical_units ────────────────────────────────────────────


def test_validate_statistical_units_accepts_clean_input():
    units = independent_units(["t-1", "t-2"])
    validate_statistical_units(units, [{"t-1": 0.5, "t-2": 0.5}, {"t-1": 0.1, "t-2": 0.9}])  # must not raise


def test_validate_statistical_units_rejects_empty_unit_id():
    with pytest.raises(StatisticalUnitValidationError, match="empty"):
        validate_statistical_units([StatisticalUnit("", ("t-1",))], [{"t-1": 0.5}])


def test_validate_statistical_units_rejects_duplicate_unit_id():
    units = [StatisticalUnit("u-1", ("t-1",)), StatisticalUnit("u-1", ("t-2",))]
    with pytest.raises(StatisticalUnitValidationError, match="duplicate statistical_unit_id"):
        validate_statistical_units(units, [{"t-1": 0.5, "t-2": 0.5}])


def test_validate_statistical_units_rejects_task_in_more_than_one_unit():
    units = [StatisticalUnit("u-1", ("t-1",)), StatisticalUnit("u-2", ("t-1",))]
    with pytest.raises(StatisticalUnitValidationError, match="more than one statistical unit"):
        validate_statistical_units(units, [{"t-1": 0.5}])


def test_validate_statistical_units_rejects_duplicate_task_inside_one_unit():
    units = [StatisticalUnit("u-1", ("t-1", "t-1"))]
    with pytest.raises(StatisticalUnitValidationError, match="duplicate task_id"):
        validate_statistical_units(units, [{"t-1": 0.5}])


def test_validate_statistical_units_rejects_missing_score():
    units = independent_units(["t-1", "t-2"])
    with pytest.raises(StatisticalUnitValidationError, match="missing from a required score dict"):
        validate_statistical_units(units, [{"t-1": 0.5}])  # t-2 missing


def test_validate_statistical_units_rejects_nan_score():
    units = independent_units(["t-1"])
    with pytest.raises(StatisticalUnitValidationError, match="NaN/infinite"):
        validate_statistical_units(units, [{"t-1": float("nan")}])


def test_validate_statistical_units_rejects_infinite_score():
    units = independent_units(["t-1"])
    with pytest.raises(StatisticalUnitValidationError, match="NaN/infinite"):
        validate_statistical_units(units, [{"t-1": float("inf")}])


def test_validate_statistical_units_rejects_out_of_range_score():
    units = independent_units(["t-1"])
    with pytest.raises(StatisticalUnitValidationError, match=r"outside the required \[0,1\]"):
        validate_statistical_units(units, [{"t-1": 1.5}])
    with pytest.raises(StatisticalUnitValidationError, match=r"outside the required \[0,1\]"):
        validate_statistical_units(units, [{"t-1": -0.1}])


def test_validate_statistical_units_rejects_missing_expected_task():
    units = independent_units(["t-1"])
    with pytest.raises(StatisticalUnitValidationError, match="missing"):
        validate_statistical_units(units, [{"t-1": 0.5}], expected_task_ids=frozenset({"t-1", "t-2"}))


def test_validate_statistical_units_rejects_unexpected_extra_task():
    units = independent_units(["t-1", "t-2"])
    with pytest.raises(StatisticalUnitValidationError, match="unexpected"):
        validate_statistical_units(units, [{"t-1": 0.5, "t-2": 0.5}], expected_task_ids=frozenset({"t-1"}))


def test_validate_statistical_units_requires_at_least_one_unit():
    with pytest.raises(StatisticalUnitValidationError, match="no statistical units"):
        validate_statistical_units([], [{}])


# ── Classifier: frontier gap ────────────────────────────────────────────


def test_classify_frontier_gap_non_inferior():
    assert classify_frontier_gap(ConfidenceInterval(-0.05, 0.10)) == Classification.NON_INFERIOR


def test_classify_frontier_gap_material():
    assert classify_frontier_gap(ConfidenceInterval(-0.30, -0.15)) == Classification.MATERIAL_GAP


def test_classify_frontier_gap_inconclusive():
    assert classify_frontier_gap(ConfidenceInterval(-0.20, -0.02)) == Classification.INCONCLUSIVE


# ── Classifier: best-reference ceiling guard ─────────────────────────────


def test_classify_best_reference_ceiling_noninferior():
    assert classify_best_reference(ConfidenceInterval(-0.15, 0.05)) == Classification.CEILING_NONINFERIOR


def test_classify_best_reference_dramatically_behind():
    assert classify_best_reference(ConfidenceInterval(-0.50, -0.25)) == Classification.DRAMATICALLY_BEHIND_CEILING


def test_classify_best_reference_inconclusive_never_passes():
    result = classify_best_reference(ConfidenceInterval(-0.30, -0.10))
    assert result == Classification.INCONCLUSIVE
    assert result != Classification.CEILING_NONINFERIOR


# ── Classifier: control superiority ──────────────────────────────────────


def test_classify_control_superiority_satisfied():
    assert classify_control_superiority(ConfidenceInterval(0.12, 0.30)) == Classification.SUBSTANTIALLY_SUPERIOR


def test_classify_control_superiority_not_satisfied_even_when_positive():
    assert classify_control_superiority(ConfidenceInterval(0.02, 0.15)) == Classification.NOT_SATISFIED


# ── Classifier: pairwise finalist tie region -- exact locked worked examples ──


@pytest.mark.parametrize(
    "lower,upper,expected",
    [
        (0.04, 0.10, Classification.A_MEANINGFULLY_AHEAD),
        (-0.10, -0.04, Classification.B_MEANINGFULLY_AHEAD),
        (0.01, 0.04, Classification.INCONCLUSIVE),
        (-0.02, 0.02, Classification.PRACTICALLY_EQUIVALENT),
        (-0.05, 0.01, Classification.INCONCLUSIVE),
    ],
)
def test_classify_pairwise_finalist_locked_worked_examples(lower, upper, expected):
    assert classify_pairwise_finalist(ConfidenceInterval(lower, upper)) == expected


def test_classify_pairwise_finalist_boundary_exactly_at_tie_margin_is_equivalent():
    assert classify_pairwise_finalist(ConfidenceInterval(-0.03, 0.03)) == Classification.PRACTICALLY_EQUIVALENT


# ── Classifier: quantization certification ───────────────────────────────


def test_classify_quantization_certified():
    assert classify_quantization(ConfidenceInterval(-0.01, 0.03)) == Classification.CERTIFIED_FOR_SCREENING


def test_classify_quantization_not_certified():
    assert classify_quantization(ConfidenceInterval(0.02, 0.09)) == Classification.NOT_CERTIFIED


# ── Quorum validators (hardened, Phase 21B.4.10.1) ───────────────────────


def test_frontier_reference_quorum_met_with_real_registered_names():
    refs = [
        ("DeepSeek V4.1-Flash", "DeepSeek AI"),
        ("GLM-5.3 (flagship)", "Zhipu AI / Z.ai"),
        ("Mistral Large 3", "Mistral AI"),
        ("Kimi K3", "Moonshot AI"),
    ]
    assert validate_frontier_reference_quorum(refs) == QuorumStatus.QUORUM_MET


def test_frontier_reference_quorum_incomplete_too_few():
    refs = [
        ("DeepSeek V4.1-Flash", "DeepSeek AI"),
        ("GLM-5.3 (flagship)", "Zhipu AI / Z.ai"),
        ("Kimi K3", "Moonshot AI"),
    ]
    assert validate_frontier_reference_quorum(refs) == QuorumStatus.REFERENCE_SET_INCOMPLETE


def test_frontier_reference_quorum_rejects_unknown_reference_name():
    refs = [
        ("DeepSeek V4.1-Flash", "DeepSeek AI"),
        ("A Totally Fabricated Model", "Fake Org"),
        ("Mistral Large 3", "Mistral AI"),
        ("Kimi K3", "Moonshot AI"),
    ]
    with pytest.raises(StatisticalUnitValidationError, match="unknown frontier reference"):
        validate_frontier_reference_quorum(refs)


def test_frontier_reference_quorum_rejects_wrong_organization():
    refs = [
        ("DeepSeek V4.1-Flash", "Wrong Org"),
        ("GLM-5.3 (flagship)", "Zhipu AI / Z.ai"),
        ("Mistral Large 3", "Mistral AI"),
        ("Kimi K3", "Moonshot AI"),
    ]
    with pytest.raises(StatisticalUnitValidationError, match="registered organization"):
        validate_frontier_reference_quorum(refs)


def test_frontier_reference_quorum_rejects_duplicate_reference():
    refs = [
        ("DeepSeek V4.1-Flash", "DeepSeek AI"),
        ("DeepSeek V4.1-Flash", "DeepSeek AI"),
        ("GLM-5.3 (flagship)", "Zhipu AI / Z.ai"),
        ("Mistral Large 3", "Mistral AI"),
    ]
    with pytest.raises(StatisticalUnitValidationError, match="duplicate frontier reference"):
        validate_frontier_reference_quorum(refs)


def test_all_six_registered_references_satisfy_quorum():
    refs = list(REGISTERED_FRONTIER_REFERENCES.items())
    assert validate_frontier_reference_quorum(refs) == QuorumStatus.QUORUM_MET


def test_control_quorum_met_with_all_three():
    assert validate_control_quorum(list(CONTROL_TARGET_SET)) == QuorumStatus.QUORUM_MET


def test_control_quorum_incomplete_missing_one():
    assert validate_control_quorum(["Qwen3-8B", "Phi-4"]) == QuorumStatus.CONTROL_SET_INCOMPLETE


def test_control_quorum_rejects_unknown_control_name():
    with pytest.raises(StatisticalUnitValidationError, match="unknown control name"):
        validate_control_quorum(["Qwen3-8B", "Mistral-Nemo-Instruct-2407", "Phi-4", "Extra-Model"])


def test_control_quorum_rejects_duplicate_control_name():
    with pytest.raises(StatisticalUnitValidationError, match="duplicate control name"):
        validate_control_quorum(["Qwen3-8B", "Qwen3-8B", "Phi-4"])


# ── Paired bootstrap: independent units, synthetic fixtures only ────────


def test_paired_bootstrap_ci_candidate_strictly_better_yields_positive_interval():
    task_ids = [f"t-{i:03d}" for i in range(30)]
    candidate_scores = {tid: 1.0 for tid in task_ids}
    comparator_scores = {tid: 0.0 for tid in task_ids}
    units = independent_units(task_ids)
    ci = paired_bootstrap_ci(candidate_scores, comparator_scores, units, resamples=2000, rng=random.Random(42))
    assert ci.lower > 0.9
    assert ci.upper <= 1.0 + 1e-9


def test_paired_bootstrap_ci_identical_scores_yields_zero_width_interval():
    task_ids = [f"t-{i:03d}" for i in range(20)]
    scores = {tid: 0.7 for tid in task_ids}
    units = independent_units(task_ids)
    ci = paired_bootstrap_ci(scores, dict(scores), units, resamples=500, rng=random.Random(1))
    assert ci.lower == pytest.approx(0.0, abs=1e-9)
    assert ci.upper == pytest.approx(0.0, abs=1e-9)


def test_paired_bootstrap_ci_mixed_scores_interval_contains_point_estimate():
    task_ids = [f"t-{i:03d}" for i in range(50)]
    rng_data = random.Random(7)
    candidate_scores = {tid: rng_data.choice([0.0, 1.0]) for tid in task_ids}
    comparator_scores = {tid: rng_data.choice([0.0, 1.0]) for tid in task_ids}
    units = independent_units(task_ids)
    point_estimate = sum(candidate_scores.values()) / len(task_ids) - sum(comparator_scores.values()) / len(task_ids)
    ci = paired_bootstrap_ci(candidate_scores, comparator_scores, units, resamples=3000, rng=random.Random(99))
    assert ci.lower <= point_estimate <= ci.upper


def test_paired_bootstrap_ci_requires_at_least_one_unit():
    with pytest.raises(StatisticalUnitValidationError, match="no statistical units"):
        paired_bootstrap_ci({}, {}, [], resamples=100, rng=random.Random(0))


def test_paired_bootstrap_ci_rejects_zero_resamples():
    units = independent_units(["t-001"])
    with pytest.raises(ValueError, match="resamples"):
        paired_bootstrap_ci({"t-001": 1.0}, {"t-001": 0.0}, units, resamples=0, rng=random.Random(0))


# ── Paired bootstrap: THE ESTIMAND -- unit-level weighting (Phase 21B.4.10.1) ──


def test_a_large_cluster_does_not_dominate_a_singleton_unit():
    """The core Phase 21B.4.10.1 fix: a 10-task cluster and a 1-task
    singleton must each contribute ONE unit-level observation, not 10x
    vs 1x weight. Construct a fixture where the singleton and the
    cluster disagree in DIRECTION -- if task-count-weighted (the old,
    buggy behavior), the 10-task cluster would swamp the single task and
    the overall point estimate would be strongly negative; under correct
    unit-weighting, the two units are equally weighted and the estimate
    is exactly their average."""
    cluster_tasks = [f"c-{i}" for i in range(10)]
    singleton_task = "s-1"
    candidate_scores = {**{t: 0.0 for t in cluster_tasks}, singleton_task: 1.0}
    comparator_scores = {**{t: 1.0 for t in cluster_tasks}, singleton_task: 0.0}
    units = clustered_units({"cluster": cluster_tasks, "singleton": [singleton_task]})

    # With correct unit weighting: cluster unit_diff = 0.0 - 1.0 = -1.0;
    # singleton unit_diff = 1.0 - 0.0 = +1.0. Resampling 2 units with
    # replacement and averaging their diffs must keep the overall
    # point estimate bounded within [-1, 1] and, critically, the
    # bootstrap distribution must include values near 0 (when one of
    # each is sampled) alongside +-1 (when both sampled units are the
    # same) -- it must NOT be overwhelmingly negative the way naive
    # task-count-weighting (11 negative task-level observations vs 1
    # positive) would produce.
    ci = paired_bootstrap_ci(candidate_scores, comparator_scores, units, resamples=5000, rng=random.Random(3))
    # A task-count-weighted (buggy) computation would produce a point
    # estimate around (10*(-1) + 1*(+1)) / 11 ≈ -0.818, entirely outside
    # the correctly-weighted equal-units case's possible per-resample
    # values of {-1.0, 0.0, +1.0}. The corrected mean must lie strictly
    # within (-1, 1) and be much closer to 0 than -0.818.
    midpoint = (ci.lower + ci.upper) / 2
    assert -0.5 < midpoint < 0.5, f"midpoint {midpoint} suggests task-count weighting leaked back in"


def test_clustered_units_resample_together_not_independently():
    """A cluster of 3 near-identical variant tasks must be resampled as
    ONE unit -- never as if they were 3 independent observations, which
    would understate the true variance."""
    cluster_a_tasks = ["a-1", "a-2", "a-3"]
    cluster_b_tasks = ["b-1", "b-2", "b-3"]
    all_tasks = cluster_a_tasks + cluster_b_tasks
    candidate_scores = {**{t: 1.0 for t in cluster_a_tasks}, **{t: 0.0 for t in cluster_b_tasks}}
    comparator_scores = {**{t: 0.0 for t in cluster_a_tasks}, **{t: 1.0 for t in cluster_b_tasks}}

    clustered = clustered_units({"cluster-a": cluster_a_tasks, "cluster-b": cluster_b_tasks})
    independent = independent_units(all_tasks)

    ci_clustered = paired_bootstrap_ci(candidate_scores, comparator_scores, clustered, resamples=5000, rng=random.Random(11))
    ci_independent = paired_bootstrap_ci(candidate_scores, comparator_scores, independent, resamples=5000, rng=random.Random(11))

    clustered_width = ci_clustered.upper - ci_clustered.lower
    independent_width = ci_independent.upper - ci_independent.lower
    assert clustered_width > independent_width


def test_clustered_units_builder_preserves_task_membership():
    units = clustered_units({"family-1": ["t-1", "t-2"], "family-2": ["t-3"]})
    by_id = {u.statistical_unit_id: u.task_ids for u in units}
    assert by_id["family-1"] == ("t-1", "t-2")
    assert by_id["family-2"] == ("t-3",)


def test_statistical_unit_rejects_empty_task_ids():
    with pytest.raises(ValueError):
        StatisticalUnit(statistical_unit_id="empty", task_ids=())


# ── Dedicated comparator functions (Phase 21B.4.10.1 §3-5) ──────────────


def test_bootstrap_frontier_median_ci_recomputes_median_per_resample():
    task_ids = [f"t-{i}" for i in range(20)]
    units = independent_units(task_ids)
    candidate_scores = {tid: 0.9 for tid in task_ids}
    # Three references with clearly different means -> median should sit near the middle one.
    references = {
        "ref-low": {tid: 0.3 for tid in task_ids},
        "ref-mid": {tid: 0.6 for tid in task_ids},
        "ref-high": {tid: 0.95 for tid in task_ids},
    }
    ci = bootstrap_frontier_median_ci(candidate_scores, references, units, resamples=2000, rng=random.Random(5))
    # candidate (0.9) - median reference (0.6) ~= 0.3
    assert 0.2 < (ci.lower + ci.upper) / 2 < 0.4


def test_bootstrap_frontier_median_ci_requires_at_least_one_reference():
    units = independent_units(["t-1"])
    with pytest.raises(ValueError, match="no reference scores"):
        bootstrap_frontier_median_ci({"t-1": 0.5}, {}, units, resamples=10, rng=random.Random(0))


def test_bootstrap_best_reference_ci_uses_per_resample_strongest_not_per_task_max():
    """Two references that alternate which one is stronger, task by
    task -- per-task max() would synthesize a 'super-reference' that
    always wins, which this function must NOT do. Instead each
    resample picks whichever reference has the higher MEAN for that
    resample's sampled units."""
    task_ids = [f"t-{i}" for i in range(10)]
    units = independent_units(task_ids)
    candidate_scores = {tid: 0.5 for tid in task_ids}
    # ref-a wins on even-indexed tasks, ref-b wins on odd-indexed tasks --
    # neither reference has an overall mean higher than the other by much,
    # and NEITHER individually reaches the per-task-max envelope.
    ref_a = {tid: (0.9 if i % 2 == 0 else 0.1) for i, tid in enumerate(task_ids)}
    ref_b = {tid: (0.1 if i % 2 == 0 else 0.9) for i, tid in enumerate(task_ids)}
    per_task_max_mean = sum(max(ref_a[t], ref_b[t]) for t in task_ids) / len(task_ids)  # would be 0.9 if buggy
    ci = bootstrap_best_reference_ci(candidate_scores, {"ref-a": ref_a, "ref-b": ref_b}, units, resamples=3000, rng=random.Random(6))
    implied_strongest_reference_mean = 0.5 - (ci.lower + ci.upper) / 2
    assert implied_strongest_reference_mean < per_task_max_mean - 0.05, (
        "best-reference comparator appears to be using a per-task max() envelope instead of "
        "the strongest single reference's own mean per resample"
    )


def test_bootstrap_control_superiority_ci_uses_per_resample_strongest_control():
    task_ids = [f"t-{i}" for i in range(10)]
    units = independent_units(task_ids)
    candidate_scores = {tid: 0.8 for tid in task_ids}
    controls = {
        "Qwen3-8B": {tid: 0.4 for tid in task_ids},
        "Mistral-Nemo-Instruct-2407": {tid: 0.5 for tid in task_ids},
        "Phi-4": {tid: 0.3 for tid in task_ids},
    }
    ci = bootstrap_control_superiority_ci(candidate_scores, controls, units, resamples=2000, rng=random.Random(8))
    # candidate (0.8) - strongest control (Mistral-Nemo at 0.5) ~= 0.3
    assert 0.2 < (ci.lower + ci.upper) / 2 < 0.4


def test_bootstrap_control_superiority_ci_requires_at_least_one_control():
    units = independent_units(["t-1"])
    with pytest.raises(ValueError, match="no control scores"):
        bootstrap_control_superiority_ci({"t-1": 0.5}, {}, units, resamples=10, rng=random.Random(0))


def test_dedicated_comparators_validate_units_before_bootstrapping():
    units = independent_units(["t-1", "t-2"])
    with pytest.raises(StatisticalUnitValidationError, match="missing"):
        bootstrap_frontier_median_ci({"t-1": 0.5}, {"ref": {"t-1": 0.5}}, units, resamples=10, rng=random.Random(0))
