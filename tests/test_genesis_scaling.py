"""
GENESIS Foundation Sprint 2, Workstream E: compute and scaling realism
tests. No gradient-based training, GPU provisioning, or hardware
benchmark is performed anywhere in this file -- every number verified
here is a closed-form arithmetic calculation.
"""
from __future__ import annotations

import pytest

torch = pytest.importorskip("torch")  # GenesisModelConfig construction instantiates a real model in some tests

from orca.genesis.model.config import GenesisModelConfig  # noqa: E402
from orca.genesis.model.scaling import (  # noqa: E402
    CORRECTED_SCALING_TIERS,
    estimate_training_compute,
    estimate_training_memory,
    resolve_corrected_tier,
    theoretical_flops_per_token,
)


def _tiny_config(**overrides):
    defaults = dict(vocab_size=1000, d_model=64, n_layers=4, n_heads=4, n_kv_heads=2, d_ff=128, max_seq_len=512)
    defaults.update(overrides)
    return GenesisModelConfig(**defaults)


# ------------------------------------------------- corrected tiers --

def test_all_six_corrected_tiers_resolve_within_tolerance():
    """The decisive correctness check: every tier's REAL computed total
    (from real, derived dimensions) must be within tolerance of its
    stated target -- the exact property Audit #015's Stage 1 config
    violated by 2.2x."""
    for tier in CORRECTED_SCALING_TIERS:
        cfg = resolve_corrected_tier(tier, tolerance=0.1)
        real_total = cfg.total_parameters()
        assert abs(real_total - tier.target_params) <= tier.target_params * 0.1, (
            f"{tier.name}: real total {real_total:,} is not within 10% of target {tier.target_params:,}"
        )


def test_corrected_tiers_are_monotonically_increasing_in_scale():
    """A basic sanity property: the six tiers must actually represent an
    increasing scale ladder, not an accidental ordering mistake."""
    resolved = [resolve_corrected_tier(t) for t in CORRECTED_SCALING_TIERS]
    totals = [cfg.total_parameters() for cfg in resolved]
    assert totals == sorted(totals)


def test_smallest_tier_embedding_dominance_is_a_real_flagged_property():
    """Documents, as an executable fact, the real finding from this
    sprint's own investigation: at vocab_size=64,000, the smallest
    (10M-smoke) tier's embedding table dominates its own parameter
    budget -- a real architectural property worth a human decision
    (e.g. a smaller vocabulary for the smoke-test tier specifically),
    not silently smoothed over."""
    smoke_tier = next(t for t in CORRECTED_SCALING_TIERS if t.name == "10M-smoke")
    cfg = resolve_corrected_tier(smoke_tier)
    embedding_fraction = cfg.breakdown()["embedding"] / cfg.total_parameters()
    assert embedding_fraction > 0.5, (
        "expected this test to document the known embedding-dominance finding at this "
        "tier/vocab combination; if this no longer holds, the finding itself needs updating, "
        "not just this assertion"
    )


# ------------------------------------------------------ memory estimate --

def test_memory_estimate_scales_with_parameter_count():
    small = _tiny_config(d_model=64)
    large = _tiny_config(d_model=256)
    mem_small = estimate_training_memory(small, batch_size=4, seq_len=128)
    mem_large = estimate_training_memory(large, batch_size=4, seq_len=128)
    assert mem_large.total > mem_small.total


def test_memory_estimate_components_sum_to_total():
    cfg = _tiny_config()
    mem = estimate_training_memory(cfg, batch_size=4, seq_len=128)
    assert mem.total == (
        mem.model_weights_bf16 + mem.optimizer_state_fp32 + mem.gradients_bf16 + mem.activations_estimate
    )


def test_optimizer_state_is_three_times_fp32_param_bytes():
    """Verifies the stated AdamW memory formula directly: fp32 master
    weight + exp_avg + exp_avg_sq = 3 * 4 bytes/param, not an arbitrary
    multiplier."""
    cfg = _tiny_config()
    mem = estimate_training_memory(cfg, batch_size=1, seq_len=1)
    expected = cfg.total_parameters() * 4 * 3
    assert mem.optimizer_state_fp32 == expected


def test_memory_estimate_increases_with_batch_size_and_seq_len():
    cfg = _tiny_config()
    small_batch = estimate_training_memory(cfg, batch_size=1, seq_len=128)
    large_batch = estimate_training_memory(cfg, batch_size=8, seq_len=128)
    assert large_batch.activations_estimate > small_batch.activations_estimate
    assert large_batch.total > small_batch.total


# ------------------------------------------------------- compute estimate --

def test_theoretical_flops_per_token_is_six_times_param_count():
    cfg = _tiny_config()
    assert theoretical_flops_per_token(cfg) == pytest.approx(6.0 * cfg.total_parameters())


def test_compute_estimate_without_measured_mfu_leaves_measured_seconds_none():
    """The decisive separation check Workstream E requires: a caller who
    does not supply a real measurement gets an explicit None, never a
    silently-invented default MFU."""
    cfg = _tiny_config()
    est = estimate_training_compute(cfg, total_tokens=1_000_000, peak_flops_per_second=1e15)
    assert est.measured_seconds_estimate is None
    assert est.mfu_used is None
    assert est.theoretical_seconds_at_peak > 0


def test_compute_estimate_with_measured_mfu_produces_a_slower_real_estimate():
    """A real (caller-supplied) MFU below 100% must make the
    'measured'-labeled estimate slower than the theoretical-peak one --
    confirming the two numbers are genuinely different calculations, not
    the same value under two names."""
    cfg = _tiny_config()
    est = estimate_training_compute(cfg, total_tokens=1_000_000, peak_flops_per_second=1e15, measured_mfu=0.3)
    assert est.measured_seconds_estimate > est.theoretical_seconds_at_peak
    assert est.measured_seconds_estimate == pytest.approx(est.theoretical_seconds_at_peak / 0.3)


def test_compute_estimate_rejects_invalid_mfu():
    cfg = _tiny_config()
    with pytest.raises(ValueError, match="measured_mfu"):
        estimate_training_compute(cfg, total_tokens=1000, peak_flops_per_second=1e15, measured_mfu=1.5)
    with pytest.raises(ValueError, match="measured_mfu"):
        estimate_training_compute(cfg, total_tokens=1000, peak_flops_per_second=1e15, measured_mfu=0.0)
