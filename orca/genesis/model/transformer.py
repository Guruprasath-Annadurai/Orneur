"""
GENESIS decoder-only Transformer (architecture version: see config.py's
ARCHITECTURE_VERSION).

A standard, well-published decoder-only architecture (RMSNorm, rotary
positional embeddings, grouped-query attention, SwiGLU MLP, causal
masking) -- the same family as LLaMA/Mistral. This is an INDEPENDENT
implementation of well-established public techniques (see the per-class
docstrings for the specific published source each piece follows); nothing
here is claimed as an ORNEUR invention, per Phase 2's explicit
instruction.

GENESIS Foundation Sprint 1, Phase 5 scope note: this module defines the
architecture and its forward pass only. It performs NO optimizer step and
NO gradient-based training of any kind -- constructing a model, running a
forward pass to check shapes, or computing a loss value for a unit test
is not training (no parameter is ever updated by anything in this
module). An actual training loop that calls `.backward()` and
`optimizer.step()` lives in `orca/genesis/training/`, gated by the
existing training-authorization infrastructure, and is explicitly NOT
invoked anywhere here.
"""
from __future__ import annotations

import torch
import torch.nn as nn
import torch.nn.functional as F

from orca.genesis.model.config import GenesisModelConfig


class RMSNorm(nn.Module):
    """Root Mean Square Layer Normalization (Zhang & Sennrich, 2019,
    https://arxiv.org/abs/1910.07467). Unlike LayerNorm, RMSNorm has no
    mean-centering step and no learned bias -- only a learned per-channel
    scale, applied after normalizing by the root-mean-square of the
    activations. Independently implemented here, not vendored."""

    def __init__(self, dim: int, eps: float = 1e-5):
        super().__init__()
        self.eps = eps
        self.weight = nn.Parameter(torch.ones(dim))

    def forward(self, x: torch.Tensor) -> torch.Tensor:
        # Compute in float32 for numerical stability regardless of the
        # input's own dtype (standard practice for norm layers under
        # mixed precision), then cast back.
        input_dtype = x.dtype
        x = x.float()
        variance = x.pow(2).mean(dim=-1, keepdim=True)
        x = x * torch.rsqrt(variance + self.eps)
        return (self.weight * x.to(input_dtype))


def precompute_rope_angles(head_dim: int, max_seq_len: int, theta: float = 10000.0) -> torch.Tensor:
    """Rotary Position Embedding angle table (Su et al., 2021,
    https://arxiv.org/abs/2104.09864, "RoFormer"). Returns a
    (max_seq_len, head_dim // 2) tensor of angles; applied via
    `apply_rope` below. head_dim must be even (RoPE operates on pairs of
    dimensions)."""
    if head_dim % 2 != 0:
        raise ValueError(f"RoPE requires an even head_dim, got {head_dim}")
    inv_freq = 1.0 / (theta ** (torch.arange(0, head_dim, 2, dtype=torch.float32) / head_dim))
    positions = torch.arange(max_seq_len, dtype=torch.float32)
    angles = torch.outer(positions, inv_freq)  # (max_seq_len, head_dim // 2)
    return angles


def apply_rope(x: torch.Tensor, angles: torch.Tensor) -> torch.Tensor:
    """Applies rotary position embeddings to `x` of shape
    (batch, n_heads, seq_len, head_dim), using the precomputed angle table
    sliced to `seq_len`. Uses the "rotate half" formulation (splitting
    head_dim into two halves rather than interleaving pairs), the same
    convention used by the widely-published reference implementations of
    this technique."""
    seq_len = x.shape[-2]
    angles = angles[:seq_len].to(x.device)
    cos = torch.cat([angles.cos(), angles.cos()], dim=-1)  # (seq_len, head_dim)
    sin = torch.cat([angles.sin(), angles.sin()], dim=-1)
    half = x.shape[-1] // 2
    x1, x2 = x[..., :half], x[..., half:]
    rotated = torch.cat([-x2, x1], dim=-1)
    return x * cos + rotated * sin


def repeat_kv(x: torch.Tensor, n_rep: int) -> torch.Tensor:
    """Grouped-query attention's key/value head expansion (Ainslie et al.,
    2023, https://arxiv.org/abs/2305.13245): repeats each of the
    `n_kv_heads` key/value heads `n_rep` times so they broadcast against
    `n_heads` query heads without materializing a full copy per query
    head via naive indexing. `x`: (batch, n_kv_heads, seq_len, head_dim)."""
    if n_rep == 1:
        return x
    batch, n_kv_heads, seq_len, head_dim = x.shape
    x = x[:, :, None, :, :].expand(batch, n_kv_heads, n_rep, seq_len, head_dim)
    return x.reshape(batch, n_kv_heads * n_rep, seq_len, head_dim)


class CausalSelfAttention(nn.Module):
    """Causal self-attention with grouped-query attention and rotary
    position embeddings. Supports two backends: `"manual"` (explicit
    QK^T/softmax/mask, used by the reference numerical tests) and
    `"sdpa"` (PyTorch's built-in `scaled_dot_product_attention`, which can
    dispatch to a fused/flash kernel where available) -- selectable per
    forward call so tests can compare them against each other."""

    def __init__(self, cfg: GenesisModelConfig):
        super().__init__()
        self.cfg = cfg
        self.n_heads = cfg.n_heads
        self.n_kv_heads = cfg.n_kv_heads
        self.n_rep = cfg.n_heads // cfg.n_kv_heads
        self.head_dim = cfg.head_dim

        self.wq = nn.Linear(cfg.d_model, cfg.n_heads * self.head_dim, bias=False)
        self.wk = nn.Linear(cfg.d_model, cfg.n_kv_heads * self.head_dim, bias=False)
        self.wv = nn.Linear(cfg.d_model, cfg.n_kv_heads * self.head_dim, bias=False)
        self.wo = nn.Linear(cfg.n_heads * self.head_dim, cfg.d_model, bias=False)

    def forward(self, x: torch.Tensor, rope_angles: torch.Tensor, attn_backend: str = "sdpa") -> torch.Tensor:
        batch, seq_len, _ = x.shape

        q = self.wq(x).view(batch, seq_len, self.n_heads, self.head_dim).transpose(1, 2)
        k = self.wk(x).view(batch, seq_len, self.n_kv_heads, self.head_dim).transpose(1, 2)
        v = self.wv(x).view(batch, seq_len, self.n_kv_heads, self.head_dim).transpose(1, 2)

        q = apply_rope(q, rope_angles)
        k = apply_rope(k, rope_angles)

        k = repeat_kv(k, self.n_rep)
        v = repeat_kv(v, self.n_rep)

        if attn_backend == "sdpa":
            out = F.scaled_dot_product_attention(q, k, v, is_causal=True)
        elif attn_backend == "manual":
            scale = 1.0 / (self.head_dim ** 0.5)
            scores = (q.float() @ k.float().transpose(-2, -1)) * scale
            causal_mask = torch.full((seq_len, seq_len), float("-inf"), device=x.device).triu(diagonal=1)
            scores = scores + causal_mask
            probs = F.softmax(scores, dim=-1).to(q.dtype)
            out = probs @ v
        else:
            raise ValueError(f"unknown attn_backend: {attn_backend!r} (expected 'sdpa' or 'manual')")

        out = out.transpose(1, 2).contiguous().view(batch, seq_len, self.n_heads * self.head_dim)
        return self.wo(out)


class SwiGLU(nn.Module):
    """SwiGLU feed-forward block (Shazeer, 2020,
    https://arxiv.org/abs/2002.05202): a gated linear unit using the SiLU
    (swish) activation on the gate projection, elementwise-multiplied
    with a separate "up" projection, then down-projected back to d_model.
    No bias terms, matching the convention this architecture family
    uses."""

    def __init__(self, cfg: GenesisModelConfig):
        super().__init__()
        self.gate_proj = nn.Linear(cfg.d_model, cfg.d_ff, bias=False)
        self.up_proj = nn.Linear(cfg.d_model, cfg.d_ff, bias=False)
        self.down_proj = nn.Linear(cfg.d_ff, cfg.d_model, bias=False)

    def forward(self, x: torch.Tensor) -> torch.Tensor:
        return self.down_proj(F.silu(self.gate_proj(x)) * self.up_proj(x))


class TransformerBlock(nn.Module):
    """One decoder layer: pre-norm attention, pre-norm SwiGLU MLP, each
    with a residual connection -- the standard "pre-norm Transformer"
    shape (Xiong et al., 2020, https://arxiv.org/abs/2002.04745) used to
    keep deep stacks numerically stable without extra tricks."""

    def __init__(self, cfg: GenesisModelConfig):
        super().__init__()
        self.attn_norm = RMSNorm(cfg.d_model, eps=cfg.rms_norm_eps)
        self.attn = CausalSelfAttention(cfg)
        self.mlp_norm = RMSNorm(cfg.d_model, eps=cfg.rms_norm_eps)
        self.mlp = SwiGLU(cfg)

    def forward(self, x: torch.Tensor, rope_angles: torch.Tensor, attn_backend: str = "sdpa") -> torch.Tensor:
        x = x + self.attn(self.attn_norm(x), rope_angles, attn_backend=attn_backend)
        x = x + self.mlp(self.mlp_norm(x))
        return x


class GenesisTransformer(nn.Module):
    """The full GENESIS decoder-only Transformer. Deterministic
    initialization: pass a fixed `torch.Generator` (or call
    `torch.manual_seed(...)` before construction) to get bit-for-bit
    reproducible initial weights across runs -- required for any future
    training run's own reproducibility story, verified by this module's
    test suite, not merely asserted."""

    def __init__(self, cfg: GenesisModelConfig):
        super().__init__()
        self.cfg = cfg
        self.tok_embeddings = nn.Embedding(cfg.vocab_size, cfg.d_model)
        self.layers = nn.ModuleList([TransformerBlock(cfg) for _ in range(cfg.n_layers)])
        self.final_norm = RMSNorm(cfg.d_model, eps=cfg.rms_norm_eps)
        if cfg.tie_embeddings:
            self.lm_head = None
        else:
            self.lm_head = nn.Linear(cfg.d_model, cfg.vocab_size, bias=False)

        rope_angles = precompute_rope_angles(cfg.head_dim, cfg.max_seq_len, theta=cfg.rope_theta)
        self.register_buffer("rope_angles", rope_angles, persistent=False)

        self._init_weights()

    def _init_weights(self) -> None:
        """Standard LLaMA-family initialization: normal(0, 0.02) for
        linear/embedding weights, ones for norm scales -- a widely-used,
        published default, not a novel scheme. Deterministic given the
        ambient RNG state at call time (i.e. deterministic given a prior
        `torch.manual_seed(...)` or an explicit generator passed to the
        module's construction site)."""
        for module in self.modules():
            if isinstance(module, nn.Linear):
                nn.init.normal_(module.weight, mean=0.0, std=0.02)
            elif isinstance(module, nn.Embedding):
                nn.init.normal_(module.weight, mean=0.0, std=0.02)

    def forward(self, input_ids: torch.Tensor, attn_backend: str = "sdpa") -> torch.Tensor:
        """input_ids: (batch, seq_len) of token ids. Returns logits:
        (batch, seq_len, vocab_size). No sampling, no generation loop --
        a single forward pass only (used both for training-loss
        computation elsewhere and for one greedy/sampled step at a time
        by `generate_step` below)."""
        if input_ids.shape[-1] > self.cfg.max_seq_len:
            raise ValueError(
                f"input sequence length {input_ids.shape[-1]} exceeds "
                f"max_seq_len={self.cfg.max_seq_len}"
            )
        x = self.tok_embeddings(input_ids)
        for layer in self.layers:
            x = layer(x, self.rope_angles, attn_backend=attn_backend)
        x = self.final_norm(x)
        if self.lm_head is not None:
            return self.lm_head(x)
        # Tied embeddings: project with the embedding matrix's own weight, transposed.
        return F.linear(x, self.tok_embeddings.weight)

    @torch.no_grad()
    def generate_step(self, input_ids: torch.Tensor, temperature: float = 1.0) -> torch.Tensor:
        """Generation-compatible interface: one autoregressive step.
        Returns the next-token id for each sequence in the batch
        (argmax if temperature==0, else a sample from the
        temperature-scaled softmax). Explicitly `@torch.no_grad()` --
        this is inference-shaped code, never a training step, and cannot
        update any parameter even if called from training code by
        mistake."""
        logits = self.forward(input_ids)[:, -1, :]
        if temperature == 0:
            return logits.argmax(dim=-1)
        probs = F.softmax(logits / temperature, dim=-1)
        return torch.multinomial(probs, num_samples=1).squeeze(-1)

    def num_parameters(self, trainable_only: bool = True) -> int:
        return sum(p.numel() for p in self.parameters() if (p.requires_grad or not trainable_only))
