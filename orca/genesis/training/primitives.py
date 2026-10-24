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
    tests/test_genesis_training_primitives.py, not asserted.

    Audit #016 DEFECT-05 fix: raises for `seq_len < 2` rather than
    silently computing cross-entropy over an empty shifted slice (which
    returns `nan`, not an error) -- a sequence of length 1 has no
    next-token pair to predict at all, so there is no loss to compute,
    not a degenerate zero loss.

    Audit #016 DEFECT-03 fix (fail-closed, not a silent differentiable
    zero): when EVERY position in a batch is `ignore_index`, this
    function raises rather than returning a value. Considered the
    alternative the audit itself proposed (a differentiable
    `torch.tensor(0.0, requires_grad=True)`) and rejected it for this
    call site: a fully-masked batch reaching a loss computation at all
    usually indicates an upstream data-pipeline defect (e.g. a sample
    with no supervised tokens ever entered the batch), and silently
    reporting "loss: 0.0" for it would look, in any training log or
    loss-averaging code, exactly like a real, successful, zero-loss
    step -- precisely the "silently turning an invalid training batch
    into successful progress" this fix exists to avoid. A real training
    loop that legitimately expects occasional fully-masked batches (e.g.
    certain packed-sequence layouts) should filter them out explicitly,
    with its own logging, before calling this primitive -- not rely on
    this primitive to paper over the condition."""
    if logits.shape[:-1] != labels.shape:
        raise ValueError(
            f"logits shape {tuple(logits.shape)} and labels shape {tuple(labels.shape)} "
            f"are inconsistent -- expected logits (..., vocab_size) to match labels (...)"
        )
    if logits.shape[-2] < 2:
        raise ValueError(
            f"causal_lm_loss requires seq_len >= 2 (a sequence of length "
            f"{logits.shape[-2]} has no next-token pair to predict), not a degenerate zero loss"
        )
    shift_logits = logits[..., :-1, :].contiguous()
    shift_labels = labels[..., 1:].contiguous()
    active = (shift_labels != ignore_index).sum()
    if active == 0:
        raise ValueError(
            "causal_lm_loss received a batch where every shifted position is "
            "ignore_index -- there is no supervised token to compute a loss "
            "from; this is a fail-closed rejection, not a differentiable zero "
            "loss, so an upstream data-pipeline defect is never silently "
            "reported as a successful training step"
        )
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
    testable without an optimizer or model in the loop at all.

    Indexing, precisely (zero-based): `step=0` is the FIRST training
    step, not a "before training starts" sentinel. With `warmup_steps=W`,
    `step=0` returns `max_lr * 1/W` (the first nonzero rung of the
    ramp, not `0.0`), and `step=W-1` returns `max_lr * W/W = max_lr` --
    i.e. the schedule reaches `max_lr` exactly at the LAST warmup step,
    not one step after it. `step=warmup_steps` is the first COSINE-decay
    step (`progress=0`, still exactly `max_lr`, continuous with the
    warmup phase's own endpoint). `step=total_steps-1` is the last
    scheduled step (`progress` approaches but does not necessarily equal
    `1.0`, depending on step count); any `step >= total_steps` clamps to
    `min_lr`, it does not raise -- running past the planned schedule
    length is a normal, recoverable condition a caller may legitimately
    hit (e.g. an early-stopped then resumed run), unlike a negative step,
    which cannot correspond to any real training-step count and is
    always a caller error.

    Audit #016 DEFECT-04 fix: `step < 0` now raises, rather than
    returning a nonsensical negative learning rate (the pre-fix
    behavior: `cosine_warmup_lr(-2, ...)` silently returned `-0.0001`)."""
    if step < 0:
        raise ValueError(f"step must be non-negative (0-based: step=0 is the first training step), got {step}")
    if warmup_steps < 0 or total_steps <= 0:
        raise ValueError("warmup_steps must be >= 0 and total_steps must be > 0")
    if warmup_steps >= total_steps:
        raise ValueError("warmup_steps must be less than total_steps")
    if max_lr < 0 or min_lr < 0:
        raise ValueError("max_lr and min_lr must be non-negative")
    if min_lr > max_lr:
        raise ValueError(f"min_lr ({min_lr}) must not exceed max_lr ({max_lr})")
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
        validate_optimizer_state(model, self.optimizer_state_dict)
        model.load_state_dict(self.model_state_dict)
        optimizer.load_state_dict(self.optimizer_state_dict)
        random.setstate(self.python_rng_state)
        torch.set_rng_state(torch.ByteTensor(list(self.torch_rng_state)))
        if self.cuda_rng_state and torch.cuda.is_available():
            for i, state in enumerate(self.cuda_rng_state):
                torch.cuda.set_rng_state(torch.ByteTensor(list(state)), i)


class OptimizerStateCorruptionError(Exception):
    """Raised when optimizer state cannot belong to this model.

    Checks slot coverage, moment shapes, finiteness, and a non-negative
    step. It does not detect an equal-shaped moment swapped between two
    parameters; checkpoint HMAC binding covers that case.
    """


def _trainable_parameter_order(model: torch.nn.Module) -> list[torch.nn.Parameter]:
    """Same order `grouped_parameters` feeds AdamW: decay matrices, then 1-D."""
    decay, no_decay = [], []
    for param in model.parameters():
        if not param.requires_grad:
            continue
        (decay if param.dim() >= 2 else no_decay).append(param)
    return decay + no_decay


def validate_optimizer_state(model: torch.nn.Module, optimizer_state_dict: dict) -> None:
    """Reject an optimizer state dict that does not match `model`.

    An empty `state` mapping is valid: AdamW leaves it empty until the
    first `step()`. A partial mapping, a non-finite moment, a negative
    step, or a shape mismatch is not valid and must not be loaded.
    """
    if not isinstance(optimizer_state_dict, dict):
        raise OptimizerStateCorruptionError("optimizer state is not a dict")
    state = optimizer_state_dict.get("state")
    groups = optimizer_state_dict.get("param_groups")
    if not isinstance(state, dict) or not isinstance(groups, list):
        raise OptimizerStateCorruptionError("optimizer state dict is missing state or param_groups")
    ordered = _trainable_parameter_order(model)
    referenced: list[int] = []
    for group in groups:
        if not isinstance(group, dict) or not isinstance(group.get("params"), (list, tuple)):
            raise OptimizerStateCorruptionError("optimizer param group is malformed")
        for raw_index in group["params"]:
            try:
                referenced.append(int(raw_index))
            except (TypeError, ValueError) as exc:
                raise OptimizerStateCorruptionError("optimizer param index is not an integer") from exc
    if referenced != list(range(len(ordered))):
        raise OptimizerStateCorruptionError(
            f"optimizer tracks {referenced} but this model has {len(ordered)} trainable parameters "
            "in decay-then-nodecay order"
        )
    normalized: dict[int, dict] = {}
    for key, slot in state.items():
        try:
            index = int(key)
        except (TypeError, ValueError) as exc:
            raise OptimizerStateCorruptionError(f"optimizer state key {key!r} is not an index") from exc
        if index < 0 or index >= len(ordered):
            raise OptimizerStateCorruptionError(f"optimizer state key {index} is outside the model")
        if not isinstance(slot, dict):
            raise OptimizerStateCorruptionError(f"optimizer slot {index} is not a dict")
        normalized[index] = slot
    if not normalized:
        return
    if set(normalized) != set(range(len(ordered))):
        raise OptimizerStateCorruptionError("optimizer state covers only some parameters")
    for index, param in enumerate(ordered):
        slot = normalized[index]
        for moment_name in ("exp_avg", "exp_avg_sq"):
            moment = slot.get(moment_name)
            if not torch.is_tensor(moment):
                raise OptimizerStateCorruptionError(f"optimizer slot {index} is missing tensor {moment_name}")
            if tuple(moment.shape) != tuple(param.shape):
                raise OptimizerStateCorruptionError(
                    f"optimizer slot {index} {moment_name} shape {tuple(moment.shape)} != parameter shape {tuple(param.shape)}"
                )
            if not bool(torch.isfinite(moment).all()):
                raise OptimizerStateCorruptionError(f"optimizer slot {index} {moment_name} is not finite")
        step = slot.get("step")
        if step is None:
            raise OptimizerStateCorruptionError(f"optimizer slot {index} is missing step")
        if torch.is_tensor(step):
            if step.numel() != 1 or not bool(torch.isfinite(step).all()):
                raise OptimizerStateCorruptionError(f"optimizer slot {index} step is not a finite scalar")
            step_val = int(step.detach().item())
        else:
            try:
                step_val = int(step)
            except (TypeError, ValueError) as exc:
                raise OptimizerStateCorruptionError(f"optimizer slot {index} step is not an integer") from exc
        if step_val < 0:
            raise OptimizerStateCorruptionError(f"optimizer slot {index} step is negative ({step_val})")


def save_training_state(state: TrainingState, path: Path) -> None:
    """Atomic write (temp file + rename), matching this codebase's
    established pattern elsewhere (orca/brain/memory.py's ledger writes)
    for the same reason: a crash mid-write must never leave a half-
    written, unreadable checkpoint file.

    Audit #016 DEFECT-02 fixes, each independently reproduced before this
    fix (not assumed from the audit's description alone):

    1. **Deterministic-tempfile collision**: the prior `path.with_suffix(
       path.suffix + ".tmp")` name is the SAME for every writer targeting
       this `path`. `tempfile.NamedTemporaryFile(dir=path.parent, ...)`
       instead gives every call its own randomly-named file, so two
       concurrent writers can never interleave writes into the same
       underlying file -- each completes its own independent write before
       either renames.
    2. **Symlink-following overwrite**: reproduced directly -- a
       pre-planted symlink at the old deterministic `.tmp` path caused
       `torch.save` to follow it and overwrite an unrelated file outside
       `path.parent` entirely. A `NamedTemporaryFile`'s randomly-generated
       name cannot match a symlink an attacker planted in advance (they
       cannot predict it), which structurally closes this path rather
       than attempting to detect and reject a symlink after the fact.
    3. **Missing restrictive permissions**: reproduced directly -- the
       prior code left the written file at the ambient umask (`0o644`
       observed). The parent directory is now created via this
       codebase's existing, already-tested `_mkdir_owner_only` helper
       (`orca/config.py`, 0700, owner-only, symlink-safe ancestor walk --
       the exact pattern Phase 3 instructed reusing rather than
       reinventing), and the checkpoint file itself is `chmod`'d to
       `0o600` before the atomic rename.
    4. **Exclusive-writer policy for concurrent writers**: an
       `fcntl.flock` exclusive lock on a sibling `.lock` file is held for
       the full duration of this function (write + fsync + rename).
       Two concurrent callers targeting the same `path` are serialized,
       not merely prevented from corrupting each other's bytes -- the
       second caller's entire save (including which `TrainingState` ends
       up as the final, readable content at `path`) waits for the first
       to fully complete, so "whichever call's rename happened to land
       last, non-deterministically" is replaced by "whichever call
       started second, deterministically, completes second." This is an
       exclusive-writer policy, not a full distributed-training
       coordination protocol -- sufficient for this primitive's own
       correctness contract, not a claim about any larger system built
       on top of it.
    5. **Durability**: `os.fsync()` on the temp file's descriptor before
       closing, and on the parent directory's descriptor after the
       rename, so the rename itself is not lost by a crash immediately
       after `os.replace()` returns but before the directory entry is
       flushed to disk -- the standard "fsync the directory too" rule for
       a truly durable atomic rename.

    AUDIT-077 P0-01 fix (intermediate-ancestor TOCTOU escape,
    independently reproduced and found by Antigravity's requalification
    before this fix): the prior code validated/created `path.parent` via
    `_mkdir_owner_only()`, which deliberately FOLLOWS a same-uid-owned
    ancestor symlink (correct for ITS own, different threat model -- see
    its own docstring) -- then performed every subsequent operation
    (lock file, temp file, rename) by RE-RESOLVING fresh path strings
    under that parent, each one an independent opportunity for a
    same-uid attacker to have swapped an intermediate ancestor directory
    for a symlink in the gap since the previous resolution. This
    function now opens the parent directory ONCE via
    `_open_dir_no_symlinks()` (which rejects any non-root-owned ancestor
    symlink outright, never following it) and performs every subsequent
    operation through that single held `dir_fd` -- never re-resolving a
    path string afterward, so there is no remaining re-resolution point
    for the race to target."""
    import fcntl
    import os

    from orca.config import _dirfd_mkstemp, _open_dir_no_symlinks

    path = Path(path)
    parent_fd = _open_dir_no_symlinks(path.parent, parents=True)
    try:
        lock_name = f".{path.name}.lock"
        lock_fd = os.open(lock_name, os.O_RDWR | os.O_CREAT, 0o600, dir_fd=parent_fd)
        try:
            fcntl.flock(lock_fd, fcntl.LOCK_EX)
            try:
                tmp_fd, tmp_name = _dirfd_mkstemp(parent_fd, prefix=f".{path.name}.tmp-")
                try:
                    os.fchmod(tmp_fd, 0o600)  # force exact mode regardless of umask, matching the prior tmp.chmod(0o600)
                    with os.fdopen(tmp_fd, "wb") as f:
                        torch.save(state.to_dict(), f)
                        f.flush()
                        os.fsync(f.fileno())
                    os.replace(tmp_name, path.name, src_dir_fd=parent_fd, dst_dir_fd=parent_fd)
                    os.fsync(parent_fd)
                except BaseException:
                    try:
                        os.unlink(tmp_name, dir_fd=parent_fd)
                    except FileNotFoundError:
                        pass
                    raise
            finally:
                fcntl.flock(lock_fd, fcntl.LOCK_UN)
        finally:
            os.close(lock_fd)
    finally:
        os.close(parent_fd)


def load_training_state(path: Path) -> TrainingState:
    """Loads a checkpoint written by `save_training_state`.

    Audit #016 DEFECT-01 fix, independently reproduced before this fix
    (not assumed from the audit's description alone): the prior
    `weights_only=False` call used Python's full pickle engine, and a
    crafted checkpoint file containing a `__reduce__` method executed
    arbitrary code immediately upon loading -- confirmed directly against
    THIS function (not merely against a standalone `torch.load` call) by
    crafting a payload whose `__reduce__` ran `os.system(...)` and
    observing it execute during an actual `load_training_state()` call.
    `weights_only=True` loads every legitimate `TrainingState` checkpoint
    (verified: `TrainingState.to_dict()` contains only plain Python
    ints/tuples/lists, raw bytes, and PyTorch tensor dicts -- all
    representable without the general pickle engine) while rejecting a
    malicious payload with a loud, immediate `UnpicklingError` instead of
    running it.

    This function still does NOT perform trust/provenance verification
    on ITS OWN -- callers handling a checkpoint from outside this
    process's own control should additionally verify provenance via
    `orca.registry.provenance` before calling this; `weights_only=True`
    closes the arbitrary-code-execution path, it does not establish that
    the checkpoint's CONTENT is the one a caller actually expects."""
    path = Path(path)
    if not path.exists():
        raise FileNotFoundError(f"no checkpoint at {path}")
    d = torch.load(path, weights_only=True)
    return TrainingState.from_dict(d)
