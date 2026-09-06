"""
Custom training losses.

Real motivation: this project's fine-tuning history repeatedly found that
OVERSAMPLING a target domain to teach a specific behavior (v3/v5's
honesty_hedging oversampling at a 27% data share, see docs/MASTER_PLAN.md)
backfired — it broke general capability by skewing the overall training
distribution, not just the targeted behavior. This module offers a
different, more surgical lever: TOKEN-WEIGHTED loss, which changes how
much the model is penalized for getting SPECIFIC tokens/spans wrong,
without changing the domain mix or example ratio in the dataset at all.

HONEST SCOPE: this is real, numerically-tested loss-computation code (see
tests/test_train_losses.py — genuine assertions against real tensors and
against torch's own reference cross_entropy, not mocks). What this
module's own correctness CANNOT establish: whether weighting these
specific spans actually improves the target behavior (refusal
reliability, citation discipline) in a real fine-tuning run — that
requires an actual training run on GPU, a real resourcing decision (see
docs/FRONTIER_ROADMAP.md), not something unit tests on CPU can prove.
"""
from __future__ import annotations

import torch
import torch.nn.functional as F


def weighted_causal_lm_loss(
    logits: torch.Tensor,
    labels: torch.Tensor,
    token_weights: torch.Tensor | None = None,
    ignore_index: int = -100,
) -> torch.Tensor:
    """
    Standard causal LM next-token cross-entropy loss, with an optional
    per-token weight multiplier applied before averaging.

    token_weights lets specific spans (e.g. a refusal phrase in a safety
    example, or a [D#] citation marker) contribute more to the loss than
    an ordinary token under flat averaging — without touching how many
    examples of that domain exist in the dataset.

    Shapes follow the standard HuggingFace causal-LM convention:
      logits:        (batch, seq_len, vocab_size) — NOT pre-shifted
      labels:         (batch, seq_len) — target token ids, ignore_index for masked positions
      token_weights:  (batch, seq_len) or None (defaults to uniform weight 1.0)

    This function performs the standard shift-by-one internally (position
    i's logits predict token i+1), matching transformers' own loss
    computation, so labels/token_weights can be passed in exactly as
    loaded from a dataset — no pre-shifting expected from the caller.
    """
    shift_logits = logits[..., :-1, :].contiguous()
    shift_labels = labels[..., 1:].contiguous()

    per_token_loss = F.cross_entropy(
        shift_logits.view(-1, shift_logits.size(-1)),
        shift_labels.view(-1),
        ignore_index=ignore_index,
        reduction="none",
    ).view(shift_labels.shape)

    mask = (shift_labels != ignore_index).float()

    if token_weights is not None:
        shift_weights = token_weights[..., 1:].contiguous()
        weight = shift_weights * mask
    else:
        weight = mask

    weighted_sum = (per_token_loss * weight).sum()
    total_weight = weight.sum().clamp(min=1e-8)
    return weighted_sum / total_weight


def build_span_weight_mask(
    input_ids: torch.Tensor,
    critical_token_ids: set[int],
    critical_weight: float = 3.0,
    base_weight: float = 1.0,
) -> torch.Tensor:
    """
    Builds a per-token weight tensor: critical_weight wherever input_ids
    contains one of critical_token_ids, base_weight everywhere else.

    HONEST SCOPE: this is an exact-token-id membership mask — it does NOT
    do span/phrase-level matching across multiple tokens (e.g. "I can't
    help with that" as a contiguous phrase spanning several token ids).
    A real implementation for a specific base model's tokenizer needs to
    identify the actual token-id sequence that phrase decomposes into for
    THAT tokenizer, which is base-model-specific and out of scope for
    this general-purpose utility. This gives callers the primitive to
    build that on top of, not the phrase-detection logic itself.
    """
    is_critical = torch.zeros_like(input_ids, dtype=torch.bool)
    for tid in critical_token_ids:
        is_critical |= (input_ids == tid)
    return torch.where(
        is_critical,
        torch.tensor(critical_weight, dtype=torch.float),
        torch.tensor(base_weight, dtype=torch.float),
    )
