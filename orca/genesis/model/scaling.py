"""
GENESIS Foundation Sprint 2, Workstream E: compute and scaling realism.

Every estimate in this module is a THEORETICAL calculation from known
formulas (parameter counts, standard AdamW memory overhead, the
widely-published `6N` FLOPs-per-token approximation from Kaplan et al.
2020 / the Chinchilla scaling-laws literature). **None of it is a
measured hardware throughput number.** No benchmark was run on real
hardware as part of this module (none is provisioned, per this sprint's
own restrictions) -- `measured_mfu` is always an explicit input a caller
supplies from their OWN real measurement, never a default this module
invents, and every function that produces a wall-clock estimate makes
that dependency on a measured, caller-supplied number impossible to miss.
"""
from __future__ import annotations

from dataclasses import dataclass

from orca.genesis.model.config import GenesisModelConfig


BYTES_PER_PARAM_FP32 = 4
BYTES_PER_PARAM_BF16 = 2


@dataclass(frozen=True)
class MemoryEstimate:
    """All fields in bytes. `optimizer_state` assumes AdamW with fp32
    master weights and fp32 exp_avg/exp_avg_sq (the standard "mixed
    precision + AdamW" memory profile: 2 bytes/param for the bf16
    training copy, plus 4+4+4 = 12 bytes/param for the fp32 master
    weight, first moment, and second moment) -- a widely-documented
    formula (e.g. the "Zero Redundancy Optimizer" paper's own memory
    breakdown table), not derived from any real measurement in this
    module."""
    model_weights_bf16: int
    optimizer_state_fp32: int
    gradients_bf16: int
    activations_estimate: int
    logits_estimate: int
    total: int


def estimate_training_memory(cfg: GenesisModelConfig, *, batch_size: int, seq_len: int | None = None) -> MemoryEstimate:
    """Theoretical memory estimate for training (not inference) this
    config, in the standard bf16-weights + fp32-AdamW-state regime.
    `activations_estimate` is a rough, intentionally conservative
    approximation (stored activations roughly proportional to
    `n_layers * batch_size * seq_len * d_model`, without gradient
    checkpointing) -- real activation memory depends heavily on the
    specific training framework's memory-saving techniques (gradient
    checkpointing, activation recomputation, sequence parallelism),
    none of which this module assumes or implements. Treat this field as
    a conservative upper bound to plan against, not a precise prediction.

    `logits_estimate` (Audit #017 DEFECT-05 remediation): the prior
    version of this function omitted the vocabulary-logits tensor
    entirely. Before cross-entropy loss, the model produces logits of
    shape `(batch_size, seq_len, vocab_size)` -- computed in fp32 for
    numerically stable softmax/cross-entropy, the standard practice this
    estimate assumes. For a large vocabulary at long sequence lengths
    this tensor alone can dwarf every other activation this function
    estimates (the audit's own reproduction: ~4.2 GB of logits against
    ~113 MB of estimated non-logits activations for the `10M-smoke` tier
    at batch_size=4, seq_len=4096 -- roughly 37x). It is reported as its
    own field, not folded silently into `activations_estimate`, so a
    caller can see exactly how much of the total this one tensor accounts
    for."""
    seq_len = seq_len or cfg.max_seq_len
    n_params = cfg.total_parameters()

    model_weights = n_params * BYTES_PER_PARAM_BF16
    gradients = n_params * BYTES_PER_PARAM_BF16
    # AdamW fp32 state: master weight + exp_avg + exp_avg_sq, 4 bytes each.
    optimizer_state = n_params * BYTES_PER_PARAM_FP32 * 3
    # Deliberately rough, deliberately conservative (no checkpointing
    # assumed): roughly 2 bytes (bf16) per activation element, with a
    # small constant-factor fudge for the several tensors kept per layer
    # (attention scores, MLP intermediate, residual stream).
    activations = 2 * cfg.n_layers * batch_size * seq_len * cfg.d_model * 6
    # Vocabulary logits: (batch_size, seq_len, vocab_size) in fp32.
    logits = batch_size * seq_len * cfg.vocab_size * BYTES_PER_PARAM_FP32

    total = model_weights + gradients + optimizer_state + activations + logits
    return MemoryEstimate(
        model_weights_bf16=model_weights,
        optimizer_state_fp32=optimizer_state,
        gradients_bf16=gradients,
        activations_estimate=activations,
        logits_estimate=logits,
        total=total,
    )


def theoretical_flops_per_token(cfg: GenesisModelConfig) -> float:
    """The standard `6N` approximation (Kaplan et al. 2020, "Scaling
    Laws for Neural Language Models", and used throughout the Chinchilla
    scaling-laws literature): roughly 6 FLOPs per parameter per token for
    a forward+backward training step (2N forward, 4N backward). This is
    a well-established APPROXIMATION, not an exact count for this
    specific architecture (it does not separately account for attention
    FLOPs scaling with sequence length, which matters more at long
    context lengths than this approximation captures) -- stated plainly,
    not smoothed over."""
    return 6.0 * cfg.total_parameters()


@dataclass(frozen=True)
class ComputeEstimate:
    total_flops: float
    theoretical_seconds_at_peak: float
    measured_seconds_estimate: float | None
    mfu_used: float | None


def estimate_training_compute(
    cfg: GenesisModelConfig,
    *,
    total_tokens: int,
    peak_flops_per_second: float,
    measured_mfu: float | None = None,
) -> ComputeEstimate:
    """`peak_flops_per_second` is the hardware's advertised peak
    throughput (a datasheet number, e.g. an H100's published BF16 TFLOPS
    figure converted to FLOPs/s) -- still a THEORETICAL ceiling, not a
    measurement. `measured_mfu` (Model FLOPs Utilization, the fraction of
    peak FLOPs actually achieved in a REAL run) is OPTIONAL and, if
    provided, MUST come from the caller's own real measurement on real
    hardware -- this function never invents a default MFU value itself
    (no "assume 30%" shortcut), precisely to keep the always-theoretical
    `theoretical_seconds_at_peak` field separate from any claim about
    real achievable throughput. If `measured_mfu` is omitted,
    `measured_seconds_estimate` is `None` -- not silently defaulted."""
    if measured_mfu is not None and not (0 < measured_mfu <= 1.0):
        raise ValueError("measured_mfu must be in (0, 1] when provided")
    total_flops = theoretical_flops_per_token(cfg) * total_tokens
    theoretical_seconds = total_flops / peak_flops_per_second
    measured_seconds = (total_flops / (peak_flops_per_second * measured_mfu)) if measured_mfu else None
    return ComputeEstimate(
        total_flops=total_flops,
        theoretical_seconds_at_peak=theoretical_seconds,
        measured_seconds_estimate=measured_seconds,
        mfu_used=measured_mfu,
    )


@dataclass(frozen=True)
class ScalingTier:
    name: str
    target_params: int
    vocab_size: int
    max_seq_len: int
    n_layers: int
    n_heads: int
    n_kv_heads: int


# GENESIS Foundation Sprint 2, Workstream E correction: these six tiers
# are DERIVED configs (via GenesisModelConfig.from_param_budget), not
# independently hand-specified dimensions paired with an independently
# hand-specified "~XM parameters" label -- the exact error class found in
# Audit #015's own Stage 1 config (embedding alone exceeding the stated
# total by 2.2x). Every tier's `d_model`/`d_ff` here is whatever
# from_param_budget() actually solves for; nothing is asserted
# independently of what the real component counts produce.
CORRECTED_SCALING_TIERS: tuple[ScalingTier, ...] = (
    ScalingTier("10M-smoke", 10_000_000, 64_000, 4096, 4, 4, 2),
    ScalingTier("30M-validation", 30_000_000, 64_000, 2048, 12, 8, 4),
    ScalingTier("100M", 100_000_000, 64_000, 2048, 12, 8, 4),
    ScalingTier("300M", 300_000_000, 64_000, 4096, 24, 16, 8),
    ScalingTier("1B", 1_000_000_000, 64_000, 4096, 24, 16, 8),
    ScalingTier("3B", 3_000_000_000, 64_000, 4096, 32, 32, 8),
)


def resolve_corrected_tier(tier: ScalingTier, *, tolerance: float = 0.1) -> GenesisModelConfig:
    """Resolves one tier to a real, internally-consistent
    GenesisModelConfig via the budget solver -- the corrected replacement
    for an independently hand-specified (d_model, n_layers, ...) tuple
    paired with an independently hand-specified "~XM parameters" label."""
    return GenesisModelConfig.from_param_budget(
        target_total_params=tier.target_params, vocab_size=tier.vocab_size, max_seq_len=tier.max_seq_len,
        n_layers=tier.n_layers, n_heads=tier.n_heads, n_kv_heads=tier.n_kv_heads, tolerance=tolerance,
    )
