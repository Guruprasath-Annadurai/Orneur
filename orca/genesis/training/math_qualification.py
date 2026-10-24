"""CPU-only checks for GENESIS training mathematics.

These helpers run on tiny tensors. They do not start a training job, do
not read a corpus, and do not change authorization. Numerical comparisons
that use a tolerance say so; they are not bit-exact claims.
"""
from __future__ import annotations

import math

import torch

from orca.genesis.training.primitives import causal_lm_loss


class FiniteDifferenceError(Exception):
    """Analytic gradient and a central finite difference disagreed."""


def supervised_token_count(labels: torch.Tensor, ignore_index: int = -100) -> int:
    """How many positions `causal_lm_loss` will supervise.

    The loss shifts labels by one. A sequence shorter than 2 contributes
    nothing. Padding and other `ignore_index` positions in the shifted
    labels do not contribute.
    """
    if labels.ndim == 0 or labels.shape[-1] < 2:
        return 0
    shifted = labels[..., 1:]
    return int((shifted != ignore_index).sum().item())


def reference_adamw_step(
    param: torch.Tensor,
    grad: torch.Tensor,
    exp_avg: torch.Tensor,
    exp_avg_sq: torch.Tensor,
    *,
    step: int,
    lr: float,
    beta1: float,
    beta2: float,
    eps: float,
    weight_decay: float,
) -> tuple[torch.Tensor, torch.Tensor, torch.Tensor]:
    """One decoupled AdamW update, matching PyTorch's formula on CPU.

    Weight decay is applied to the parameter first. Moments are updated
    from `grad`. Bias correction uses 1-based `step`. Returns the new
    parameter, exp_avg, and exp_avg_sq. Does not mutate the inputs.
    """
    if step < 1:
        raise ValueError("step is 1-based and must be >= 1")
    exp_avg = beta1 * exp_avg + (1.0 - beta1) * grad
    exp_avg_sq = beta2 * exp_avg_sq + (1.0 - beta2) * grad * grad
    bias_correction1 = 1.0 - beta1 ** step
    bias_correction2 = 1.0 - beta2 ** step
    denom = exp_avg_sq.sqrt() / math.sqrt(bias_correction2) + eps
    updated = param * (1.0 - lr * weight_decay)
    updated = updated - (lr / bias_correction1) * exp_avg / denom
    return updated, exp_avg, exp_avg_sq


def finite_difference_gradients(
    model: torch.nn.Module,
    input_ids: torch.Tensor,
    labels: torch.Tensor,
    *,
    epsilon: float = 1e-3,
    atol: float = 2e-3,
    samples_per_parameter: int = 2,
    attn_backend: str = "manual",
) -> dict[str, float]:
    """Compare backward() to a central difference on a few elements.

    Uses `attn_backend="manual"` by default so the check does not depend
    on a fused SDPA kernel. `atol` is an absolute tolerance. A passing
    result is not a claim of bit-exact gradients.

    Returns the worst absolute error observed, under `max_abs_error`.
    """
    if epsilon <= 0:
        raise ValueError("epsilon must be positive")
    model.train()

    def loss_value() -> float:
        logits = model(input_ids, attn_backend=attn_backend)
        return float(causal_lm_loss(logits, labels).detach())

    model.zero_grad(set_to_none=True)
    analytic = causal_lm_loss(model(input_ids, attn_backend=attn_backend), labels)
    analytic.backward()

    worst = 0.0
    worst_where = ""
    checked = 0
    saw_nontrivial = False
    for name, param in model.named_parameters():
        if param.grad is None:
            continue
        grad_flat = param.grad.detach().flatten()
        if float(grad_flat.abs().max()) > 1e-4:
            saw_nontrivial = True
        data_flat = param.data.detach().flatten()
        take = min(samples_per_parameter, data_flat.numel())
        for index in range(take):
            original = data_flat[index].item()
            with torch.no_grad():
                data_flat[index] = original + epsilon
            plus = loss_value()
            with torch.no_grad():
                data_flat[index] = original - epsilon
            minus = loss_value()
            with torch.no_grad():
                data_flat[index] = original
            estimate = (plus - minus) / (2.0 * epsilon)
            actual = grad_flat[index].item()
            error = abs(estimate - actual)
            checked += 1
            if error > worst:
                worst = error
                worst_where = f"{name}[{index}] finite_difference={estimate} analytic={actual}"
    if checked == 0:
        raise FiniteDifferenceError("no parameter gradients were produced")
    if not saw_nontrivial:
        raise FiniteDifferenceError("every sampled analytic gradient was ~0; the check would be vacuous")
    if worst > atol:
        raise FiniteDifferenceError(f"max abs error {worst} exceeds atol {atol} at {worst_where}")
    return {"checked_elements": float(checked), "max_abs_error": worst}
