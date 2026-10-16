"""
GENESIS model configuration and parameter-count arithmetic.

GENESIS Foundation Sprint 1, Phase 1 correction: an earlier scoring pass
(referenced as "Audit #015" in the directing document) proposed a config
whose embedding parameters alone exceeded its own stated 30M total-
parameter budget. That specific document does not exist anywhere in this
repository (grepped directly -- no match), so there is nothing to amend
in place; the correction this module makes is structural: every config
constructed here computes its OWN real parameter count from its OWN real
dimensions, so this exact class of error (declaring a total that the
component counts contradict) cannot recur silently -- `GenesisModelConfig.
total_parameters()` and `.breakdown()` are the single source of truth, and
`from_param_budget()` solves for dimensions that actually fit a requested
budget instead of asserting one.

Architecture version: this module defines GENESIS model architecture
version "genesis-arch-v1" -- a plain, well-established decoder-only
Transformer (RoPE + GQA + RMSNorm + SwiGLU, LLaMA/Mistral-family shape).
No part of this is claimed as an ORNEUR invention; the engineering here
is an independent implementation of well-published techniques, not new
research.
"""
from __future__ import annotations

from dataclasses import dataclass


ARCHITECTURE_VERSION = "genesis-arch-v1"


@dataclass(frozen=True)
class GenesisModelConfig:
    vocab_size: int
    d_model: int
    n_layers: int
    n_heads: int
    n_kv_heads: int  # grouped-query attention: n_kv_heads <= n_heads, n_heads % n_kv_heads == 0
    d_ff: int  # SwiGLU hidden dim (the *gate+up* projection width before the down-projection)
    max_seq_len: int
    rope_theta: float = 10000.0
    rms_norm_eps: float = 1e-5
    tie_embeddings: bool = True  # tie input embedding and output (LM head) weight matrices
    architecture_version: str = ARCHITECTURE_VERSION

    def __post_init__(self) -> None:
        if self.d_model <= 0 or self.n_layers <= 0 or self.n_heads <= 0:
            raise ValueError("d_model, n_layers, n_heads must be positive")
        if self.d_model % self.n_heads != 0:
            raise ValueError(f"d_model ({self.d_model}) must be divisible by n_heads ({self.n_heads})")
        if self.n_kv_heads <= 0:
            raise ValueError("n_kv_heads must be positive")
        if self.n_kv_heads > self.n_heads:
            raise ValueError(f"n_kv_heads ({self.n_kv_heads}) cannot exceed n_heads ({self.n_heads})")
        if self.n_heads % self.n_kv_heads != 0:
            raise ValueError(f"n_heads ({self.n_heads}) must be a multiple of n_kv_heads ({self.n_kv_heads})")
        if self.vocab_size <= 0 or self.max_seq_len <= 0 or self.d_ff <= 0:
            raise ValueError("vocab_size, max_seq_len, d_ff must be positive")

    @property
    def head_dim(self) -> int:
        return self.d_model // self.n_heads

    def breakdown(self) -> dict[str, int]:
        """Exact parameter count per component, computed from real dimensions
        -- not a target asserted in advance. Every number here is derived,
        never hand-entered, so a config's stated total can never silently
        diverge from what its own dimensions actually produce."""
        d = self.d_model
        hd = self.head_dim
        kv_dim = hd * self.n_kv_heads

        embedding = self.vocab_size * d
        # Per-layer: attention (q, k, v, o projections) + SwiGLU MLP (gate, up, down) + 2 RMSNorm
        attn_q = d * d
        attn_k = d * kv_dim
        attn_v = d * kv_dim
        attn_o = d * d
        attn_total = attn_q + attn_k + attn_v + attn_o
        mlp_gate = d * self.d_ff
        mlp_up = d * self.d_ff
        mlp_down = self.d_ff * d
        mlp_total = mlp_gate + mlp_up + mlp_down
        norm_total = 2 * d  # RMSNorm has one learned scale vector per norm, no bias
        per_layer = attn_total + mlp_total + norm_total
        all_layers = per_layer * self.n_layers

        final_norm = d
        lm_head = 0 if self.tie_embeddings else self.vocab_size * d

        return {
            "embedding": embedding,
            "per_layer_attention": attn_total,
            "per_layer_mlp": mlp_total,
            "per_layer_norm": norm_total,
            "all_layers": all_layers,
            "final_norm": final_norm,
            "lm_head": lm_head,
        }

    def total_parameters(self) -> int:
        b = self.breakdown()
        return b["embedding"] + b["all_layers"] + b["final_norm"] + b["lm_head"]

    @classmethod
    def from_param_budget(
        cls,
        *,
        target_total_params: int,
        vocab_size: int,
        max_seq_len: int,
        n_layers: int,
        n_heads: int,
        n_kv_heads: int,
        rope_theta: float = 10000.0,
        rms_norm_eps: float = 1e-5,
        tie_embeddings: bool = True,
        tolerance: float = 0.05,
    ) -> "GenesisModelConfig":
        """Solves for d_model (and a conventional d_ff = 8/3 * d_model,
        rounded to a multiple of 256 as is standard practice for SwiGLU
        MLPs) that fits `target_total_params` within `tolerance` -- rather
        than the earlier, corrected error of asserting a total and a set
        of dimensions independently and letting them silently disagree.
        Raises if the embedding table ALONE would exceed the target
        budget for the given vocab_size -- exactly the Phase-1 error
        class this module exists to make structurally impossible."""
        if not (0 < tolerance < 1):
            raise ValueError("tolerance must be in (0, 1)")

        embedding_only_min_d = 8  # smallest d_model this search will try
        if vocab_size * embedding_only_min_d > target_total_params:
            raise ValueError(
                f"vocab_size={vocab_size} alone requires at least "
                f"{vocab_size * embedding_only_min_d} parameters at the smallest "
                f"tested d_model ({embedding_only_min_d}), which already exceeds "
                f"the {target_total_params:,}-parameter budget. No config exists "
                f"at this budget for this vocabulary -- shrink vocab_size or "
                f"raise the budget instead of silently picking an inconsistent d_model."
            )

        best: GenesisModelConfig | None = None
        best_diff = float("inf")
        # Search over d_model values that are valid multiples of n_heads
        # and (for clean head_dim/RoPE behavior) typically a multiple of
        # a small power of two; a plain linear search is intentional here
        # for traceability over cleverness -- there is no training-time
        # cost to this being simple.
        step = n_heads
        d_model = step
        while d_model <= max(target_total_params, 1):
            d_ff = max(256, round((d_model * 8 / 3) / 256) * 256)
            try:
                cfg = cls(
                    vocab_size=vocab_size, d_model=d_model, n_layers=n_layers, n_heads=n_heads,
                    n_kv_heads=n_kv_heads, d_ff=d_ff, max_seq_len=max_seq_len,
                    rope_theta=rope_theta, rms_norm_eps=rms_norm_eps, tie_embeddings=tie_embeddings,
                )
            except ValueError:
                d_model += step
                continue
            total = cfg.total_parameters()
            diff = abs(total - target_total_params)
            if diff < best_diff:
                best, best_diff = cfg, diff
            if total > target_total_params * (1 + tolerance) and best is not None:
                break
            d_model += step

        if best is None:
            raise ValueError("no valid d_model found for the given constraints")
        if best_diff > target_total_params * tolerance:
            raise ValueError(
                f"best config found ({best.total_parameters():,} params) misses the "
                f"{target_total_params:,}-parameter target by more than {tolerance:.0%} "
                f"-- relax n_layers/n_heads constraints or the tolerance rather than "
                f"accept a config that doesn't actually match the stated budget."
            )
        return best
