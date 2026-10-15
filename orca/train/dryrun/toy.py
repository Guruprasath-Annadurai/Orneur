"""A pure-Python toy "model" (linear regression on lists) with a real optimizer, LR scheduler, gradient accumulation, dropout RNG and a
data-order cursor, so checkpoint/resume machinery is exercised against genuinely stateful training code.

SYNTHETIC ONLY. There is no tensor library, no pretrained weight, no tokenizer, no file read and no network here -- standard-library math
only. Every operation used (+ - * / sqrt and 64-bit integer arithmetic) is correctly rounded or exact in IEEE-754 / Python ints, so a given
plan produces bit-identical results on any platform (no exp/log/cos/pow from libm). Floats are serialized with float.hex() so a checkpoint
round-trips exactly.
"""
from __future__ import annotations

import math
from dataclasses import dataclass, field
from typing import Callable

from orca.train.dryrun.canon import hash_obj

MASK64 = (1 << 64) - 1
OPTIMIZERS = ("adam", "sgd_momentum")


class StateInvalid(ValueError):
    """A serialized train state is malformed, non-finite, or internally inconsistent."""


class NonFiniteValue(ArithmeticError):
    """A loss or gradient was NaN/Infinity. Raised BEFORE the step is committed, so the poisoned step never becomes state."""


class SplitMix64:
    """Tiny deterministic PRNG whose whole state is one 64-bit integer (so it checkpoints trivially and identically everywhere)."""

    def __init__(self, state: int):
        self.state = int(state) & MASK64

    def next_u64(self) -> int:
        self.state = (self.state + 0x9E3779B97F4A7C15) & MASK64
        z = self.state
        z = ((z ^ (z >> 30)) * 0xBF58476D1CE4E5B9) & MASK64
        z = ((z ^ (z >> 27)) * 0x94D049BB133111EB) & MASK64
        return z ^ (z >> 31)

    def uniform(self) -> float:
        return (self.next_u64() >> 11) / float(1 << 53)      # exact in [0, 1)


def _is_int(v) -> bool:
    return isinstance(v, int) and not isinstance(v, bool)


@dataclass(frozen=True)
class Plan:
    """Everything that defines a synthetic run. Its canonical hash (plan_sha256) is bound into every checkpoint and the run ledger."""
    seed: int = 1234
    data_seed: int = 99
    n_examples: int = 64
    n_features: int = 4
    micro_batch: int = 4
    grad_accum: int = 2
    total_steps: int = 12
    checkpoint_every: int = 4
    optimizer: str = "adam"
    lr: float = 0.05
    beta1: float = 0.9
    beta2: float = 0.999
    eps: float = 1e-8
    weight_decay: float = 0.01
    momentum: float = 0.9
    warmup_steps: int = 3
    min_lr_ratio: float = 0.1
    grad_clip: float = 1.0
    dropout_p: float = 0.1
    tokens_per_example: int = 8

    def __post_init__(self):
        for name in ("seed", "data_seed", "n_examples", "n_features", "micro_batch", "grad_accum", "total_steps", "checkpoint_every",
                     "warmup_steps", "tokens_per_example"):
            if not _is_int(getattr(self, name)):
                raise ValueError(f"Plan.{name} must be an int")
        for name in ("n_examples", "n_features", "micro_batch", "grad_accum", "total_steps", "checkpoint_every", "tokens_per_example"):
            if getattr(self, name) < 1:
                raise ValueError(f"Plan.{name} must be >= 1")
        if self.warmup_steps < 0 or self.warmup_steps > self.total_steps:
            raise ValueError("Plan.warmup_steps must be within [0, total_steps]")
        if self.optimizer not in OPTIMIZERS:
            raise ValueError("Plan.optimizer unknown")
        for name in ("lr", "beta1", "beta2", "eps", "weight_decay", "momentum", "min_lr_ratio", "grad_clip", "dropout_p"):
            v = getattr(self, name)
            if isinstance(v, bool) or not isinstance(v, (int, float)) or not math.isfinite(v):
                raise ValueError(f"Plan.{name} must be a finite number")
        if not (self.lr > 0 and 0 <= self.beta1 < 1 and 0 <= self.beta2 < 1 and self.eps > 0 and self.weight_decay >= 0
                and 0 <= self.momentum < 1 and 0 <= self.min_lr_ratio <= 1 and self.grad_clip > 0 and 0 <= self.dropout_p < 1):
            raise ValueError("Plan hyperparameter out of range")

    def as_dict(self) -> dict:
        return {f: getattr(self, f) for f in self.__dataclass_fields__}

    @property
    def sha256(self) -> str:
        return hash_obj({"schema": "orneur-dryrun-plan/1", **self.as_dict()})

    @property
    def examples_per_step(self) -> int:
        return self.micro_batch * self.grad_accum

    @property
    def tokens_per_step(self) -> int:
        return self.examples_per_step * self.tokens_per_example


# ─── dataset + deterministic data order ───────────────────────────────────────────────────────────────────────────────────────────

def make_dataset(plan: Plan) -> tuple:
    """Synthetic regression data derived only from plan.data_seed. Returns (X, y)."""
    rng = SplitMix64(plan.data_seed)
    w_true = [rng.uniform() * 2.0 - 1.0 for _ in range(plan.n_features)]
    b_true = rng.uniform() - 0.5
    xs, ys = [], []
    for _ in range(plan.n_examples):
        x = [rng.uniform() * 2.0 - 1.0 for _ in range(plan.n_features)]
        y = b_true
        for wj, xj in zip(w_true, x):
            y += wj * xj
        y += 0.01 * (rng.uniform() - 0.5)
        xs.append(x)
        ys.append(y)
    return xs, ys


def epoch_permutation(plan: Plan, epoch: int) -> list:
    """Fisher-Yates shuffle of range(n_examples) derived ONLY from (data_seed, epoch): the data order is a pure function of the cursor."""
    rng = SplitMix64(plan.data_seed ^ (((epoch + 1) * 0xD1B54A32D192ED03) & MASK64))
    perm = list(range(plan.n_examples))
    for i in range(plan.n_examples - 1, 0, -1):
        j = rng.next_u64() % (i + 1)
        perm[i], perm[j] = perm[j], perm[i]
    return perm


class DataStream:
    """Maps the integer cursor `examples_seen` to dataset indices. Caches one epoch permutation; holds no other state."""

    def __init__(self, plan: Plan):
        self.plan = plan
        self._epoch = -1
        self._perm: list = []

    def index_at(self, examples_seen: int) -> int:
        epoch, pos = divmod(examples_seen, self.plan.n_examples)
        if epoch != self._epoch:
            self._perm, self._epoch = epoch_permutation(self.plan, epoch), epoch
        return self._perm[pos]


# ─── state ────────────────────────────────────────────────────────────────────────────────────────────────────────────────────────

def init_opt_state(plan: Plan) -> dict:
    n = plan.n_features + 1
    if plan.optimizer == "adam":
        return {"kind": "adam", "t": 0, "m": [0.0] * n, "v": [0.0] * n, "b1_pow": 1.0, "b2_pow": 1.0}
    return {"kind": "sgd_momentum", "buf": [0.0] * n}


def initial_rng_state(plan: Plan) -> int:
    return SplitMix64(plan.seed ^ 0xA5A5A5A5A5A5A5A5).state


@dataclass
class TrainState:
    step: int                     # optimizer steps committed
    examples_seen: int            # data-order cursor
    tokens_seen: int
    params: list                  # n_features weights then the bias
    opt: dict                     # optimizer moments / momentum buffer
    sched_step: int               # LR scheduler position
    rng_state: int                # dropout RNG
    losses: list = field(default_factory=list)   # mean loss of every committed step

    def clone(self) -> "TrainState":
        opt = {k: (list(v) if isinstance(v, list) else v) for k, v in self.opt.items()}
        return TrainState(self.step, self.examples_seen, self.tokens_seen, list(self.params), opt, self.sched_step, self.rng_state, list(self.losses))

    def to_json_obj(self) -> dict:
        return {
            "step": self.step, "examples_seen": self.examples_seen, "tokens_seen": self.tokens_seen,
            "params": [x.hex() for x in self.params],
            "opt": {k: ([x.hex() for x in v] if isinstance(v, list) else (v.hex() if isinstance(v, float) else v)) for k, v in sorted(self.opt.items())},
            "sched_step": self.sched_step, "rng_state": self.rng_state, "losses": [x.hex() for x in self.losses],
        }

    @property
    def sha256(self) -> str:
        return hash_obj(self.to_json_obj())


_STATE_KEYS = {"step", "examples_seen", "tokens_seen", "params", "opt", "sched_step", "rng_state", "losses"}


def _dehex(v, what: str) -> float:
    if not isinstance(v, str):
        raise StateInvalid(f"{what}: expected hex float string")
    try:
        x = float.fromhex(v)
    except ValueError as e:
        raise StateInvalid(f"{what}: bad hex float") from e
    if not math.isfinite(x):
        raise StateInvalid(f"{what}: non-finite")
    return x


def state_from_json_obj(obj, plan: Plan) -> TrainState:
    """Strict inverse of TrainState.to_json_obj(); anything off-schema, non-finite, or inconsistent with `plan` is StateInvalid."""
    if not isinstance(obj, dict) or set(obj) != _STATE_KEYS:
        raise StateInvalid("state schema mismatch")
    for k in ("step", "examples_seen", "tokens_seen", "sched_step", "rng_state"):
        if not _is_int(obj[k]) or obj[k] < 0:
            raise StateInvalid(f"state.{k} invalid")
    if obj["rng_state"] > MASK64:
        raise StateInvalid("state.rng_state out of range")
    n = plan.n_features + 1
    if not isinstance(obj["params"], list) or len(obj["params"]) != n:
        raise StateInvalid("state.params length mismatch")
    params = [_dehex(x, "params") for x in obj["params"]]
    raw_opt = obj["opt"]
    if not isinstance(raw_opt, dict) or raw_opt.get("kind") != plan.optimizer:
        raise StateInvalid("state.opt kind mismatch")
    opt: dict = {}
    for k, v in raw_opt.items():
        if k == "kind":
            opt[k] = v
        elif k == "t":
            if not _is_int(v) or v < 0:
                raise StateInvalid("opt.t invalid")
            opt[k] = v
        elif isinstance(v, list):
            if len(v) != n:
                raise StateInvalid(f"opt.{k} length mismatch")
            opt[k] = [_dehex(x, f"opt.{k}") for x in v]
        else:
            opt[k] = _dehex(v, f"opt.{k}")
    if set(opt) != set(init_opt_state(plan)):
        raise StateInvalid("opt keys mismatch")
    if not isinstance(obj["losses"], list) or len(obj["losses"]) != obj["step"]:
        raise StateInvalid("losses length != step")
    losses = [_dehex(x, "losses") for x in obj["losses"]]
    if obj["step"] > plan.total_steps or obj["sched_step"] > plan.total_steps:
        raise StateInvalid("state beyond plan.total_steps")
    return TrainState(obj["step"], obj["examples_seen"], obj["tokens_seen"], params, opt, obj["sched_step"], obj["rng_state"], losses)


def initial_state(plan: Plan) -> TrainState:
    rng = SplitMix64(plan.seed)
    params = [(rng.uniform() - 0.5) * 0.1 for _ in range(plan.n_features + 1)]
    return TrainState(0, 0, 0, params, init_opt_state(plan), 0, initial_rng_state(plan))


# ─── scheduler / optimizer / step ─────────────────────────────────────────────────────────────────────────────────────────────

def lr_at(plan: Plan, sched_step: int) -> float:
    """Linear warmup then linear decay to lr*min_lr_ratio. Depends on the scheduler position ONLY, so losing it visibly changes the run."""
    if sched_step < plan.warmup_steps:
        return plan.lr * (sched_step + 1) / plan.warmup_steps
    span = max(1, plan.total_steps - plan.warmup_steps)
    progress = min(1.0, (sched_step - plan.warmup_steps) / span)
    return plan.lr * (plan.min_lr_ratio + (1.0 - plan.min_lr_ratio) * (1.0 - progress))


def _micro_gradient(plan: Plan, params: list, batch: list, rng: SplitMix64) -> tuple:
    d = plan.n_features
    grad = [0.0] * (d + 1)
    loss = 0.0
    keep_scale = 1.0 / (1.0 - plan.dropout_p)
    for x, y in batch:
        xm = [(xi * keep_scale if rng.uniform() >= plan.dropout_p else 0.0) for xi in x]
        pred = params[d]
        for j in range(d):
            pred += params[j] * xm[j]
        err = pred - y
        loss += err * err
        for j in range(d):
            grad[j] += 2.0 * err * xm[j]
        grad[d] += 2.0 * err
    b = float(len(batch))
    return [g / b for g in grad], loss / b


def _apply_optimizer(plan: Plan, params: list, opt: dict, grad: list, lr: float) -> None:
    n = len(params)
    if plan.optimizer == "adam":
        opt["t"] += 1
        opt["b1_pow"] *= plan.beta1
        opt["b2_pow"] *= plan.beta2
        c1, c2 = 1.0 - opt["b1_pow"], 1.0 - opt["b2_pow"]
        for i in range(n):
            opt["m"][i] = plan.beta1 * opt["m"][i] + (1.0 - plan.beta1) * grad[i]
            opt["v"][i] = plan.beta2 * opt["v"][i] + (1.0 - plan.beta2) * grad[i] * grad[i]
            mhat, vhat = opt["m"][i] / c1, opt["v"][i] / c2
            params[i] -= lr * plan.weight_decay * params[i]
            params[i] -= lr * mhat / (math.sqrt(vhat) + plan.eps)
    else:
        for i in range(n):
            opt["buf"][i] = plan.momentum * opt["buf"][i] + grad[i]
            params[i] -= lr * opt["buf"][i]


MicroHook = Callable[[int, int], None]     # (step_index_being_computed, micro_index) -> may raise to abort the in-flight step


class ToyEngine:
    """Computes one optimizer step as a PURE function of the committed state: the input is never mutated, so aborting mid-step (kill switch,
    cap, NaN, injected fault) leaves the committed state exactly as it was -- rollback is simply discarding the returned clone."""

    def __init__(self, plan: Plan):
        self.plan = plan
        self.x, self.y = make_dataset(plan)
        self.stream = DataStream(plan)

    def compute_step(self, state: TrainState, before_micro: MicroHook | None = None, poison_nan: bool = False) -> TrainState:
        plan = self.plan
        work = state.clone()
        rng = SplitMix64(work.rng_state)
        acc = [0.0] * (plan.n_features + 1)
        loss_sum = 0.0
        for micro in range(plan.grad_accum):
            if before_micro is not None:
                before_micro(work.step, micro)
            batch = []
            for _ in range(plan.micro_batch):
                i = self.stream.index_at(work.examples_seen)
                batch.append((self.x[i], self.y[i]))
                work.examples_seen += 1
            g, loss = _micro_gradient(plan, work.params, batch, rng)
            if poison_nan:
                loss = float("nan")
            if not math.isfinite(loss) or not all(math.isfinite(v) for v in g):
                raise NonFiniteValue(f"non-finite loss/gradient at step {work.step} micro {micro}")
            for i in range(len(acc)):
                acc[i] += g[i] / plan.grad_accum
            loss_sum += loss / plan.grad_accum
        norm = math.sqrt(sum(v * v for v in acc))
        if norm > plan.grad_clip:
            factor = plan.grad_clip / norm
            acc = [v * factor for v in acc]
        _apply_optimizer(plan, work.params, work.opt, acc, lr_at(plan, work.sched_step))
        if not all(math.isfinite(p) for p in work.params):
            raise NonFiniteValue(f"non-finite parameters after step {work.step}")
        work.sched_step += 1
        work.step += 1
        work.tokens_seen += plan.tokens_per_step
        work.rng_state = rng.state
        work.losses.append(loss_sum)
        return work
