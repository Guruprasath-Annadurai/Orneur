"""
Phase 21B.4.10: tested, executable encoding of the Phase 21B.4.9.x
Genesis Frontier statistical contract (orca.eval.frontier_stats). All
fixtures here are synthetic -- no real candidate, reference, or control
data is used anywhere in this file.
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
    Classification,
    ConfidenceInterval,
    QuorumStatus,
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
)


def test_locked_constants_match_the_methodology_documents():
    assert FRONTIER_STATISTICAL_CONTRACT_VERSION == "genesis-frontier-stats-v1"
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


# ── ConfidenceInterval ────────────────────────────────────────────────────


def test_confidence_interval_rejects_lower_above_upper():
    with pytest.raises(ValueError):
        ConfidenceInterval(lower=0.5, upper=0.1)


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


# ── Quorum validators ─────────────────────────────────────────────────────


def test_frontier_reference_quorum_met():
    refs = [("DeepSeek V4.1-Flash", "DeepSeek AI"), ("GLM-5.3", "Zhipu/Z.ai"),
            ("Mistral Large 3", "Mistral AI"), ("Kimi K3", "Moonshot AI")]
    assert validate_frontier_reference_quorum(refs) == QuorumStatus.QUORUM_MET


def test_frontier_reference_quorum_incomplete_too_few():
    refs = [("DeepSeek V4.1-Flash", "DeepSeek AI"), ("GLM-5.3", "Zhipu/Z.ai"), ("Kimi K3", "Moonshot AI")]
    assert validate_frontier_reference_quorum(refs) == QuorumStatus.REFERENCE_SET_INCOMPLETE


def test_frontier_reference_quorum_incomplete_too_few_lineages():
    # 4 references but only 2 distinct organizations -- fails the lineage requirement.
    refs = [("Model A", "Org1"), ("Model B", "Org1"), ("Model C", "Org2"), ("Model D", "Org2")]
    assert validate_frontier_reference_quorum(refs) == QuorumStatus.REFERENCE_SET_INCOMPLETE


def test_control_quorum_met_with_all_three():
    assert validate_control_quorum(list(CONTROL_TARGET_SET)) == QuorumStatus.QUORUM_MET


def test_control_quorum_incomplete_missing_one():
    assert validate_control_quorum(["Qwen3-8B", "Phi-4"]) == QuorumStatus.CONTROL_SET_INCOMPLETE


def test_control_quorum_extra_controls_do_not_bypass_requirement():
    # Present a superset that still contains all three -- must pass.
    assert validate_control_quorum(["Qwen3-8B", "Mistral-Nemo-Instruct-2407", "Phi-4", "Extra-Model"]) == QuorumStatus.QUORUM_MET


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
    with pytest.raises(ValueError, match="no statistical units"):
        paired_bootstrap_ci({}, {}, [], resamples=100, rng=random.Random(0))


def test_paired_bootstrap_ci_rejects_zero_resamples():
    units = independent_units(["t-001"])
    with pytest.raises(ValueError, match="resamples"):
        paired_bootstrap_ci({"t-001": 1.0}, {"t-001": 0.0}, units, resamples=0, rng=random.Random(0))


# ── Paired bootstrap: cluster-aware resampling (Phase 21B.4.10 §6) ──────


def test_clustered_units_resample_together_not_independently():
    """A cluster of 3 near-identical variant tasks must be resampled as
    ONE unit -- never as if they were 3 independent observations, which
    would understate the true variance. This test proves the clustered
    variance is HIGHER (wider CI) than treating the same tasks as fully
    independent, for a fixture deliberately constructed so within-
    cluster scores are perfectly correlated (candidate always wins its
    own cluster, loses the other)."""
    # Cluster A: 3 variants where the candidate always wins.
    # Cluster B: 3 variants where the candidate always loses.
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
    # Treating 2 genuinely-correlated clusters as 6 independent tasks
    # understates the true uncertainty -- the clustered (correct) CI
    # must be at least as wide, and in this deliberately-correlated
    # fixture, strictly wider.
    assert clustered_width > independent_width


def test_clustered_units_builder_preserves_task_membership():
    units = clustered_units({"family-1": ["t-1", "t-2"], "family-2": ["t-3"]})
    by_id = {u.statistical_unit_id: u.task_ids for u in units}
    assert by_id["family-1"] == ("t-1", "t-2")
    assert by_id["family-2"] == ("t-3",)


def test_statistical_unit_rejects_empty_task_ids():
    from orca.eval.frontier_stats import StatisticalUnit

    with pytest.raises(ValueError):
        StatisticalUnit(statistical_unit_id="empty", task_ids=())
