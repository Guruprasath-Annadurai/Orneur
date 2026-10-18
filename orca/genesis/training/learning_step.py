"""
GENESIS Native Learning Engine, Phase 1, Workstream 1: a real PyTorch
training-STEP mechanism for `GenesisTransformer`.

This is the piece every prior GENESIS sprint explicitly stopped short
of: `orca/genesis/model/transformer.py` defines the forward pass only;
`orca/genesis/training/primitives.py` defines the loss/optimizer/
scheduler MATH as pure, standalone functions but never calls
`.backward()` or `optimizer.step()`. This module is the first place in
the codebase that actually performs a gradient-based parameter update --
it reuses every one of those existing, already-tested primitives rather
than reimplementing them (`causal_lm_loss`, `build_optimizer`,
`cosine_warmup_lr`, `clip_grad_norm`, `check_for_nan_or_inf`), and adds
only the orchestration a real step requires: correct zero-grad/backward/
step ordering, gradient accumulation across microbatches, deterministic
seeding, and fail-closed non-finite detection.

**This module performs real optimizer steps when called.** It is NOT
gated by the production training-authorization state machine itself --
that gate lives one layer up, in
`orca/genesis/training/learning_governance.py` (Workstream 5), which is
the ONLY sanctioned caller for anything beyond this module's own
CPU-bounded synthetic unit tests. Calling `TrainingStepEngine.step()`
directly, outside that gate, against real data, is exactly the kind of
bypass this phase's directive prohibits -- this module itself has no
way to tell a synthetic unit-test tensor from a real corpus tensor, so
the authorization boundary is enforced by WHO is allowed to construct
and call it with real data, not by anything checkable from inside this
module. See `learning_governance.py`'s own docstring for the actual
enforcement.

## Antigravity Audit #074 remediation -- AUDIT-P0-02 (capability token)

Independently reproduced: `step()` previously took no token or
capability of any kind -- `engine.step(batch, labels)` executed a real
optimizer step for ANY caller holding a reference to the engine, with
zero coupling to `GenesisTrainingRun`/`learning_governance.py` at all.
`step()` now REQUIRES a `capability: ExecutionCapability`, an opaque
token this engine itself mints (`_issue_capability_for_governance()`)
but which is only ever CALLED by `learning_governance
.execute_authorized_training_step()` -- the sanctioned, documented, and
now the only ergonomic path to a real step.

**Honestly scoped, per this phase's own directive**: this raises the
bar for a COOPERATING caller sticking to this module's public, intended
API (a bare `engine.step(batch, labels)` with no token now raises
`TypeError` immediately, closing the specific, trivial reproduction
Audit #074 demonstrated) -- it does NOT, and cannot, prevent a
determined caller in the SAME process/interpreter who is willing to (a)
call the clearly-internal, single-underscore `_issue_capability_for_
governance()` directly themselves, or (b) ignore this engine entirely
and write their own forward/backward/optimizer-step loop from scratch
against the same public `causal_lm_loss`/`build_optimizer`/`clip_grad_
norm` primitives this engine itself calls. Python provides no mechanism
to make either of those impossible for a caller who already shares the
same interpreter, memory space, and import access as this code -- this
is not a shortfall of this implementation, it is what "in-process" means.
Genuine prevention of a co-resident, equally-privileged Python caller
requires an actual OS-process boundary (e.g. training executes in a
separate worker process, reachable only via an IPC channel that itself
re-authenticates every call and never shares interpreter state with the
caller) -- building and testing that architecture is explicitly out of
scope for this remediation phase and is recorded as an open
requirement, not claimed as already closed.

## Antigravity Audit #075 (independent successor requalification) remediation

Audit #075 named `ExecutionCapability.for_unchecked_synthetic_test()`,
`TrainingStepEngine._issue_capability_for_governance()`, and the
(now-removed, see `learning_governance.py`) caller-controlled
revalidation cadence as the three concrete "production bypass paths"
requiring remediation. Addressed here as follows, stated honestly
rather than oversold:

- **The genuine fix is architectural, not a tighter in-process check**:
  `orca.genesis.training.isolated_worker` (new in this phase) is now
  the ONLY path by which a real, governance-authorized training step
  can execute -- the worker constructs its own private
  `TrainingStepEngine` inside a SEPARATE OS process, calls
  `_issue_capability_for_governance()` on it internally, and never
  exposes the engine, the model, the optimizer, or any capability
  object across its IPC boundary to a client. A client process
  literally has no Python reference to call either bypass method ON,
  because it never has a reference to the real engine at all -- this
  is what actually closes the "production bypass" concern, not any
  change to these two methods' own code.
  See `isolated_worker.py`'s own module docstring for the full design,
  its threat model, and what it explicitly does NOT achieve (it is a
  real OS-process boundary with authenticated IPC, not a container or
  separate-uid sandbox by default).
- **`for_unchecked_synthetic_test()` now additionally requires `pytest`
  to be the importing context** (`"pytest" in sys.modules`), raising
  `SyntheticTestBypassMisuseError` otherwise. This is explicitly
  **misuse-resistance, not a security boundary**: it prevents this
  bypass from being casually left in, or accidentally reached by,
  ordinary (non-test) code, since `pytest` is never imported by a real
  training entrypoint. It does NOT stop a determined, co-resident
  caller, who can trivially `import pytest` first, or monkeypatch
  `sys.modules`, or call `ExecutionCapability(token=b"", _unchecked=True)`
  directly (the constructor itself takes no such guard, by design,
  since `__slots__`-based classes cannot be made un-instantiable from
  within the same interpreter). Stated plainly, per this phase's own
  instruction not to claim Python API conventions make arbitrary
  in-process code untrustable: they do not, and this guard does not
  claim otherwise."""
from __future__ import annotations

import hmac
import random
import secrets
import sys
from dataclasses import dataclass, field

import torch

from orca.genesis.model.transformer import GenesisTransformer
from orca.genesis.training.primitives import (
    OptimizerConfig,
    build_optimizer,
    causal_lm_loss,
    check_for_nan_or_inf,
    clip_grad_norm,
    cosine_warmup_lr,
)

_MAX_REASONABLE_BATCH_TOKENS = 1_000_000  # batch_size * seq_len; an explicit, documented sanity ceiling, not a tuned production limit


class NonFiniteTrainingSignalError(Exception):
    """Raised when a loss or (post-accumulation, pre-clip) gradient is
    NaN/Inf. Fail-closed: the step is never applied to the optimizer,
    and the exception identifies which signal failed and at which
    global step, so a caller can distinguish "this run hit a real
    numerical problem" from a silent, corrupted parameter update."""


class ResourceLimitExceededError(Exception):
    """Raised when a batch's total token count (batch_size * seq_len)
    exceeds `_MAX_REASONABLE_BATCH_TOKENS`, or when `max_steps` (if the
    caller supplied one) has already been reached. An explicit,
    documented resource ceiling -- not a tuned production limit, but a
    sanity bound that stops a misconfigured test or caller from running
    an unbounded amount of CPU work silently."""


class MissingExecutionCapabilityError(Exception):
    """AUDIT-P0-02 fix: raised by `TrainingStepEngine.step()` when
    `capability` is missing, the wrong type, or does not match this
    engine's own token. See `ExecutionCapability`'s own docstring."""


class SyntheticTestBypassMisuseError(Exception):
    """AUDIT-075: raised by `ExecutionCapability.for_unchecked_synthetic
    _test()` when `pytest` is not present in `sys.modules` -- misuse-
    resistance against this bypass being reached from ordinary,
    non-test code, explicitly NOT a security boundary against a
    determined in-process caller. See this module's own docstring,
    "Audit #075", for the honest, full scope of what this is and is
    not."""


def set_deterministic_seed(seed: int) -> None:
    """Seeds Python's `random`, and torch's CPU (and CUDA, if present)
    RNGs, and asks torch for deterministic algorithm implementations
    where available. Two calls with the same `seed`, followed by
    identical model construction and training steps, must produce
    bit-identical results on CPU -- this is directly exercised by
    `tests/test_genesis_learning_step.py`'s own determinism test, not
    merely asserted here."""
    random.seed(seed)
    torch.manual_seed(seed)
    if torch.cuda.is_available():
        torch.cuda.manual_seed_all(seed)
    torch.use_deterministic_algorithms(True, warn_only=True)


@dataclass(frozen=True)
class TrainingStepConfig:
    """Every knob a real training step needs, with explicit, validated
    bounds -- deliberately a plain dataclass (no framework/trainer
    abstraction) so the actual step logic in `TrainingStepEngine` stays
    inspectable line by line, per this phase's own instruction to avoid
    abstractions that obscure training correctness."""
    grad_accum_steps: int = 1
    max_grad_norm: float = 1.0
    warmup_steps: int = 10
    total_steps: int = 100
    max_lr: float = 3e-4
    min_lr: float = 0.0
    seed: int = 0
    optimizer: OptimizerConfig = field(default_factory=OptimizerConfig)
    attn_backend: str = "sdpa"
    max_steps: int | None = None  # explicit, optional hard ceiling on global steps this engine will ever take

    def __post_init__(self) -> None:
        if self.grad_accum_steps < 1:
            raise ValueError("grad_accum_steps must be >= 1")
        if self.max_grad_norm <= 0:
            raise ValueError("max_grad_norm must be positive")
        if self.max_steps is not None and self.max_steps < 1:
            raise ValueError("max_steps, if given, must be >= 1")


@dataclass
class StepResult:
    """What one microbatch's worth of work produced. `applied` is True
    only on the microbatch that completed a full accumulation cycle and
    actually called `optimizer.step()` -- every other microbatch in the
    cycle returns `applied=False` with its own loss, so a caller can
    distinguish "a gradient was accumulated" from "a parameter update
    actually happened" without inspecting the engine's internal
    counters."""
    microbatch_loss: float
    applied: bool
    global_step: int
    accumulation_index: int  # 0-based position within the current accumulation cycle
    lr: float | None  # the learning rate actually applied this call, or None if applied=False
    grad_norm: float | None  # pre-clip grad norm, only populated when applied=True


class ExecutionCapability:
    """AUDIT-P0-02 fix: an opaque token `TrainingStepEngine.step()` now
    requires. Two, and only two, ways to construct one:
    1. `ExecutionCapability.for_unchecked_synthetic_test()` -- performs
       ZERO authorization, explicitly, unmistakably named so that
       grepping the codebase for this exact name finds every single
       bypass call site. Exists only because this phase's own directive
       explicitly permits it ("synthetic, ephemeral CPU tests may
       continue within existing authorized test boundaries") -- used
       exclusively by this module's own and other Workstream unit tests
       that deliberately exercise `step()`'s mechanics in isolation,
       never by anything claiming real authorization.
    2. The private, engine-bound token `learning_governance
       .execute_authorized_training_step()` obtains by calling
       `TrainingStepEngine._issue_capability_for_governance()` -- gated
       by a live `GenesisTrainingRun` state/expiry/revocation/identity
       re-check performed immediately before minting, every single call.

    See `learning_step.py`'s own module docstring (AUDIT-P0-02 section)
    for exactly what this does and does not prevent -- it raises the bar
    for a cooperating caller using this module's intended, documented
    API; it cannot prevent a caller willing to call this class's own
    constructor, or `_issue_capability_for_governance()`, directly, nor
    one who bypasses this module entirely and writes an equivalent
    training loop from scratch. No in-process Python mechanism can."""
    __slots__ = ("_token", "_unchecked")

    def __init__(self, token: bytes, *, _unchecked: bool = False):
        self._token = token
        self._unchecked = _unchecked

    @classmethod
    def for_unchecked_synthetic_test(cls) -> "ExecutionCapability":
        if "pytest" not in sys.modules:
            raise SyntheticTestBypassMisuseError(
                "ExecutionCapability.for_unchecked_synthetic_test() may only be called from a pytest "
                "process ('pytest' not found in sys.modules) -- see SyntheticTestBypassMisuseError's own "
                "docstring for why this is misuse-resistance, not a security boundary"
            )
        return cls(token=b"", _unchecked=True)


class TrainingStepEngine:
    """Owns one model, one optimizer, and the accumulation/step-counter
    state needed to perform a real, resumable training run one
    microbatch at a time. Deliberately NOT a general-purpose "Trainer"
    -- it has exactly one method that does real work (`step`), and every
    piece of state it carries is also exactly what
    `orca/genesis/training/resumable_checkpoint.py` (Workstream 3) needs
    to checkpoint and restore a run bit-for-bit."""

    def __init__(self, model: GenesisTransformer, cfg: TrainingStepConfig):
        self.model = model
        self.cfg = cfg
        self.optimizer = build_optimizer(model, cfg.optimizer)
        self.global_step = 0
        self.microbatch_in_cycle = 0  # 0-based position within the current accumulation cycle; resets to 0 after each applied step
        self._accum_loss_sum = 0.0
        self._capability_token = secrets.token_bytes(32)  # AUDIT-P0-02: minted once per engine; never persisted, never logged
        self.optimizer.zero_grad(set_to_none=True)

    def _issue_capability_for_governance(self) -> ExecutionCapability:
        """Returns a real, this-engine-bound `ExecutionCapability`.
        Single-underscore (not name-mangled) so `learning_governance.py`
        can call it after its own, independent authorization re-check --
        but, honestly, nothing in Python stops any other caller in this
        same process/interpreter from calling it too. See the module
        docstring for exactly what this is, and is not, a defense
        against."""
        return ExecutionCapability(self._capability_token)

    def step(self, input_ids: torch.Tensor, labels: torch.Tensor, capability: ExecutionCapability) -> StepResult:
        """One microbatch. `input_ids`/`labels`: (batch, seq_len) of
        token ids -- `labels` already shifted-and-masked by the caller's
        choice of `ignore_index` positions (see
        `orca/genesis/data/loader.py`); `causal_lm_loss` performs ITS
        OWN internal next-token shift on top of that, exactly as it
        already does for every other caller.

        `capability`: see `ExecutionCapability`'s own docstring. Must
        either be this engine's own, real token (obtained only via
        `_issue_capability_for_governance()`) or an explicit
        `ExecutionCapability.for_unchecked_synthetic_test()` instance --
        anything else raises `MissingExecutionCapabilityError` before a
        single tensor operation runs.

        Correct zero-grad/step ordering, explicitly: `zero_grad()` is
        called exactly once per accumulation CYCLE (in `__init__` for
        the very first cycle, and again immediately after each
        `optimizer.step()` below) -- never per microbatch. Every
        microbatch's `.backward()` call accumulates into the same
        `.grad` buffers until a full cycle completes."""
        if not isinstance(capability, ExecutionCapability):
            raise MissingExecutionCapabilityError(
                "step() requires a real ExecutionCapability -- see learning_governance"
                ".execute_authorized_training_step() for the sanctioned way to obtain one, or "
                "ExecutionCapability.for_unchecked_synthetic_test() for an explicit, named test-only bypass"
            )
        if not capability._unchecked and not hmac.compare_digest(capability._token, self._capability_token):
            raise MissingExecutionCapabilityError("capability token does not match this engine's own token")
        if self.cfg.max_steps is not None and self.global_step >= self.cfg.max_steps:
            raise ResourceLimitExceededError(
                f"global_step {self.global_step} has already reached max_steps={self.cfg.max_steps}"
            )
        batch_tokens = input_ids.shape[0] * input_ids.shape[1]
        if batch_tokens > _MAX_REASONABLE_BATCH_TOKENS:
            raise ResourceLimitExceededError(
                f"batch of {batch_tokens} tokens (batch_size={input_ids.shape[0]} * "
                f"seq_len={input_ids.shape[1]}) exceeds the sanity ceiling of "
                f"{_MAX_REASONABLE_BATCH_TOKENS}"
            )

        self.model.train()
        logits = self.model(input_ids, attn_backend=self.cfg.attn_backend)
        loss = causal_lm_loss(logits, labels)
        try:
            check_for_nan_or_inf(loss, f"loss at global_step={self.global_step}, microbatch={self.microbatch_in_cycle}")
        except FloatingPointError as e:
            raise NonFiniteTrainingSignalError(str(e)) from e

        (loss / self.cfg.grad_accum_steps).backward()
        self._accum_loss_sum += float(loss.detach())
        accumulation_index = self.microbatch_in_cycle
        self.microbatch_in_cycle += 1

        if self.microbatch_in_cycle < self.cfg.grad_accum_steps:
            return StepResult(
                microbatch_loss=float(loss.detach()), applied=False, global_step=self.global_step,
                accumulation_index=accumulation_index, lr=None, grad_norm=None,
            )

        # Full accumulation cycle complete: check accumulated gradients
        # are finite BEFORE clipping/stepping -- a corrupted gradient
        # must never reach the optimizer, even once.
        for name, p in self.model.named_parameters():
            if p.grad is not None:
                try:
                    check_for_nan_or_inf(p.grad, f"grad[{name}] at global_step={self.global_step}")
                except FloatingPointError as e:
                    raise NonFiniteTrainingSignalError(str(e)) from e

        grad_norm = clip_grad_norm(self.model, self.cfg.max_grad_norm)
        lr = cosine_warmup_lr(
            self.global_step, warmup_steps=self.cfg.warmup_steps, total_steps=self.cfg.total_steps,
            max_lr=self.cfg.max_lr, min_lr=self.cfg.min_lr,
        )
        for group in self.optimizer.param_groups:
            group["lr"] = lr
        self.optimizer.step()
        self.optimizer.zero_grad(set_to_none=True)

        mean_loss = self._accum_loss_sum / self.cfg.grad_accum_steps
        self.global_step += 1
        self.microbatch_in_cycle = 0
        self._accum_loss_sum = 0.0

        return StepResult(
            microbatch_loss=mean_loss, applied=True, global_step=self.global_step - 1,
            accumulation_index=accumulation_index, lr=lr, grad_norm=grad_norm,
        )
