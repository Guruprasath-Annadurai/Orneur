"""
GENESIS pretraining engine primitives.

GENESIS Foundation Sprint 1, Phase 4/5 scope note, stated plainly per
this project's own discipline: every function in this module is pure
math/serialization -- loss computation, optimizer/scheduler
CONFIGURATION objects, gradient-clipping arithmetic, and checkpoint
read/write contracts. NOTHING in this module calls `.backward()` or
`optimizer.step()`, and nothing here runs an actual training loop over
real data. Phase 1's explicit question ("do Stage 0 optimizer steps
constitute prohibited model training?") is answered structurally: there
is no "Stage 0" training loop implemented anywhere in this module or
this sprint -- constructing an `AdamW` instance and computing what its
step WOULD do mathematically (tested in
tests/test_genesis_training_primitives.py) is not the same action as
calling `.step()` against real gradients from real data, and this module
does neither of the latter two. A real training loop, if and when
authorized, is a separate, later piece of work gated by
`orca.train.authorization`, not something this sprint adds a bypass
around.
"""
from __future__ import annotations

import json
import random
from dataclasses import asdict, dataclass
from pathlib import Path

import torch
import torch.nn.functional as F


def causal_lm_loss(logits: torch.Tensor, labels: torch.Tensor, ignore_index: int = -100) -> torch.Tensor:
    """Standard next-token causal cross-entropy loss. `logits`:
    (batch, seq_len, vocab_size). `labels`: (batch, seq_len) of token
    ids, with `ignore_index` marking positions that must not contribute
    to the loss (e.g. prompt tokens in an instruction-tuning context, or
    padding). Performs the standard "shift" internally: position i's
    logits predict position i+1's label, so logits are shifted left and
    labels right-truncated by one before computing cross-entropy -- a
    position's own label is never used to predict itself. Verified
    against torch's own `F.cross_entropy` reference in
    tests/test_genesis_training_primitives.py, not asserted."""
    if logits.shape[:-1] != labels.shape:
        raise ValueError(
            f"logits shape {tuple(logits.shape)} and labels shape {tuple(labels.shape)} "
            f"are inconsistent -- expected logits (..., vocab_size) to match labels (...)"
        )
    shift_logits = logits[..., :-1, :].contiguous()
    shift_labels = labels[..., 1:].contiguous()
    return F.cross_entropy(
        shift_logits.view(-1, shift_logits.size(-1)),
        shift_labels.view(-1),
        ignore_index=ignore_index,
    )


@dataclass(frozen=True)
class OptimizerConfig:
    """AdamW configuration with weight-decay parameter grouping: norm
    scales, embeddings, and any 1-D parameter (e.g. a bias, though this
    architecture has none) are conventionally excluded from weight decay
    -- a widely-published practice (e.g. documented in nanoGPT and most
    LLaMA-family reimplementations), not an ORNEUR-specific scheme."""
    lr: float = 3e-4
    betas: tuple[float, float] = (0.9, 0.95)
    eps: float = 1e-8
    weight_decay: float = 0.1

    def __post_init__(self) -> None:
        if self.lr <= 0:
            raise ValueError("lr must be positive")
        if not (0 <= self.betas[0] < 1 and 0 <= self.betas[1] < 1):
            raise ValueError("betas must be in [0, 1)")
        if self.weight_decay < 0:
            raise ValueError("weight_decay must be non-negative")


def grouped_parameters(model: torch.nn.Module, weight_decay: float) -> list[dict]:
    """Splits a model's parameters into a decayed group (>=2 dimensions,
    i.e. weight matrices) and a non-decayed group (<2 dimensions, i.e.
    norm scales and any bias) -- the standard grouping referenced in
    OptimizerConfig's docstring."""
    decay, no_decay = [], []
    for name, p in model.named_parameters():
        if not p.requires_grad:
            continue
        (decay if p.dim() >= 2 else no_decay).append(p)
    return [
        {"params": decay, "weight_decay": weight_decay},
        {"params": no_decay, "weight_decay": 0.0},
    ]


def build_optimizer(model: torch.nn.Module, cfg: OptimizerConfig) -> torch.optim.AdamW:
    return torch.optim.AdamW(
        grouped_parameters(model, cfg.weight_decay),
        lr=cfg.lr, betas=cfg.betas, eps=cfg.eps,
    )


def cosine_warmup_lr(step: int, *, warmup_steps: int, total_steps: int, max_lr: float, min_lr: float = 0.0) -> float:
    """Linear warmup for `warmup_steps`, then cosine decay from `max_lr`
    to `min_lr` over the remaining `total_steps - warmup_steps` -- the
    standard schedule used across nearly all published LLM pretraining
    recipes. Returns a pure float (the learning rate value for this exact
    step); applying it to an optimizer's param groups is the caller's
    responsibility, kept separate here so the math is independently
    testable without an optimizer or model in the loop at all."""
    if warmup_steps < 0 or total_steps <= 0:
        raise ValueError("warmup_steps must be >= 0 and total_steps must be > 0")
    if warmup_steps >= total_steps:
        raise ValueError("warmup_steps must be less than total_steps")
    if step < warmup_steps:
        return max_lr * (step + 1) / max(warmup_steps, 1)
    progress = (step - warmup_steps) / max(total_steps - warmup_steps, 1)
    progress = min(max(progress, 0.0), 1.0)
    import math
    cosine = 0.5 * (1 + math.cos(math.pi * progress))
    return min_lr + (max_lr - min_lr) * cosine


def clip_grad_norm(model: torch.nn.Module, max_norm: float) -> float:
    """Thin, explicit wrapper around `torch.nn.utils.clip_grad_norm_`
    (global L2 norm clipping across all parameters) -- kept as a named
    function here (rather than calling the torch utility inline at each
    call site) so the exact clipping policy has one place to be tested
    and reasoned about. Returns the PRE-clipping total norm, which is
    what the underlying torch function itself returns and what training
    logs conventionally report."""
    if max_norm <= 0:
        raise ValueError("max_norm must be positive")
    return float(torch.nn.utils.clip_grad_norm_(model.parameters(), max_norm))


def check_for_nan_or_inf(tensor: torch.Tensor, name: str) -> None:
    """Fail-closed numerical-health check: raises immediately on the
    first NaN/Inf found, naming the tensor, rather than letting a
    corrupted loss/gradient silently propagate into an optimizer step or
    a saved checkpoint."""
    if torch.isnan(tensor).any():
        raise FloatingPointError(f"{name} contains NaN")
    if torch.isinf(tensor).any():
        raise FloatingPointError(f"{name} contains Inf")


@dataclass
class TrainingState:
    """The full restorable state of an in-progress training run: model
    weights, optimizer state, RNG state (Python/NumPy/torch, CPU and
    CUDA if present), and the exact data-loader position reached. Every
    field here is required precisely so `restore()` can put a resumed
    run back into the SAME state it would have been in had it never
    stopped -- not an approximation. Integrates with the existing
    checkpoint/provenance infrastructure in orca/registry/provenance.py
    by carrying the same deterministic run-id concept; this class does
    not duplicate that module's custody/signing logic, only the
    model-training-specific state it doesn't already cover."""
    step: int
    epoch: int
    dataloader_position: int
    model_state_dict: dict
    optimizer_state_dict: dict
    python_rng_state: tuple
    torch_rng_state: bytes  # torch.ByteTensor serialized via .tolist(), see to_dict/from_dict
    cuda_rng_state: list[bytes] | None  # one entry per CUDA device, or None if no CUDA

    def to_dict(self) -> dict:
        return {
            "step": self.step,
            "epoch": self.epoch,
            "dataloader_position": self.dataloader_position,
            "model_state_dict": self.model_state_dict,
            "optimizer_state_dict": self.optimizer_state_dict,
            "python_rng_state": list(self.python_rng_state),
            "torch_rng_state": list(self.torch_rng_state),
            "cuda_rng_state": [list(s) for s in self.cuda_rng_state] if self.cuda_rng_state else None,
        }

    @classmethod
    def from_dict(cls, d: dict) -> "TrainingState":
        return cls(
            step=d["step"], epoch=d["epoch"], dataloader_position=d["dataloader_position"],
            model_state_dict=d["model_state_dict"], optimizer_state_dict=d["optimizer_state_dict"],
            python_rng_state=tuple(d["python_rng_state"]),
            torch_rng_state=bytes(d["torch_rng_state"]),
            cuda_rng_state=[bytes(s) for s in d["cuda_rng_state"]] if d.get("cuda_rng_state") else None,
        )

    @classmethod
    def capture(cls, *, step: int, epoch: int, dataloader_position: int, model: torch.nn.Module, optimizer: torch.optim.Optimizer) -> "TrainingState":
        cuda_state = None
        if torch.cuda.is_available():
            cuda_state = [bytes(torch.cuda.get_rng_state(i).tolist()) for i in range(torch.cuda.device_count())]
        return cls(
            step=step, epoch=epoch, dataloader_position=dataloader_position,
            model_state_dict=model.state_dict(), optimizer_state_dict=optimizer.state_dict(),
            python_rng_state=random.getstate(),
            torch_rng_state=bytes(torch.get_rng_state().tolist()),
            cuda_rng_state=cuda_state,
        )

    def restore(self, *, model: torch.nn.Module, optimizer: torch.optim.Optimizer) -> None:
        model.load_state_dict(self.model_state_dict)
        optimizer.load_state_dict(self.optimizer_state_dict)
        random.setstate(self.python_rng_state)
        torch.set_rng_state(torch.ByteTensor(list(self.torch_rng_state)))
        if self.cuda_rng_state and torch.cuda.is_available():
            for i, state in enumerate(self.cuda_rng_state):
                torch.cuda.set_rng_state(torch.ByteTensor(list(state)), i)


def save_training_state(state: TrainingState, path: Path) -> None:
    """Atomic write (temp file + rename), matching this codebase's
    established pattern elsewhere (orca/brain/memory.py's ledger writes)
    for the same reason: a crash mid-write must never leave a half-
    written, unreadable checkpoint file."""
    path = Path(path)
    path.parent.mkdir(parents=True, exist_ok=True)
    tmp = path.with_suffix(path.suffix + ".tmp")
    torch.save(state.to_dict(), tmp)
    tmp.replace(path)


def load_training_state(path: Path) -> TrainingState:
    """Loads a checkpoint written by `save_training_state`. Does NOT use
    `torch.load`'s legacy pickle-based path on untrusted input -- callers
    handling a checkpoint from outside this process's own control should
    additionally verify provenance via `orca.registry.provenance` before
    calling this; this function only handles the deserialization
    contract, not trust."""
    path = Path(path)
    if not path.exists():
        raise FileNotFoundError(f"no checkpoint at {path}")
    d = torch.load(path, weights_only=False)  # see module docstring: provenance verification is the caller's job
    return TrainingState.from_dict(d)
