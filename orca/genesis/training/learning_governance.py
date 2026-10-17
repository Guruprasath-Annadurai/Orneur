"""
GENESIS Native Learning Engine, Phase 1, Workstream 5: the ONLY
sanctioned call path from a real `NativePretrainingGrant`-authorized
`GenesisTrainingRun` to `orca.genesis.training.learning_step
.TrainingStepEngine.step()` -- i.e. to an ACTUAL gradient-based
parameter update against real data.

This module adds no new authorization logic of its own; it adds exactly
one fail-closed GATE in front of `TrainingStepEngine.step()`, reusing
`orca.genesis.training.orchestration.GenesisTrainingRun`'s already-
built, already-audited (Mission 2, Audit #71 P0-01) state machine and
identity-drift/revocation/shard-tampering checks unchanged. Today, with
the real founder-acceptance ledger and authority registry both
committed empty (`NOT_AUTHORIZED`), `GenesisTrainingRun.start()` and
`.resume()` always raise before a real run can ever reach `RUNNING` --
so this gate, by construction, cannot currently be satisfied by any
real (non-test-fixture) grant. Production execution stays disabled not
because this module trusts a flag, but because the thing it checks
(`run.state is RunState.RUNNING`) is unreachable without a real,
founder-signed authorization this repository does not have.

**No bypass of any kind is implemented or honored here**:
- No environment variable is read anywhere in this module.
- `run` must be a real `GenesisTrainingRun` INSTANCE
  (`isinstance` checked, not duck-typed) -- a stub, mock, or
  dict-with-the-right-keys is rejected, never silently accepted as
  "close enough."
- There is no parameter, flag, or keyword argument on
  `execute_authorized_training_step()` that weakens or skips the
  `isinstance`/state check below. Adding one would defeat this module's
  entire purpose; none exists."""
from __future__ import annotations

import torch

from orca.genesis.training.learning_step import StepResult, TrainingStepEngine
from orca.genesis.training.orchestration import GenesisTrainingRun, RunState


class TrainingNotAuthorizedForExecutionError(Exception):
    """Raised whenever `execute_authorized_training_step()` is called
    without a real `GenesisTrainingRun` in `RunState.RUNNING`. This is
    the single, fail-closed gate this entire module exists to provide --
    every call that reaches `TrainingStepEngine.step()` through this
    function passed this check; no other path through this module
    exists."""


def execute_authorized_training_step(
    run: GenesisTrainingRun, engine: TrainingStepEngine, input_ids: torch.Tensor, labels: torch.Tensor,
) -> StepResult:
    """The sanctioned entrypoint. Raises
    `TrainingNotAuthorizedForExecutionError` immediately, before calling
    `engine.step()` at all, unless `run` is a genuine
    `GenesisTrainingRun` instance currently in `RunState.RUNNING` --
    which itself requires having passed `validate()` (including, per
    Audit #71 P0-01, live on-disk shard-digest binding),
    `request_authorization()`, `authorize()` against a real, sealed,
    workload-bound `NativePretrainingGrant`, and `start()`'s own
    founder-acceptance-ledger + grant re-verification gate.

    This function does not, and cannot, re-verify the grant itself here
    on every single training step (that would mean re-checking a signed
    record's cryptographic integrity and the founder-acceptance ledger
    on every microbatch, which `GenesisTrainingRun`'s own design
    deliberately does NOT require -- re-verification happens at
    resume-capable STATE TRANSITIONS, documented and tested there, not
    at every call into this function). What this function DOES guarantee
    is that no call reaches a real optimizer step while `run.state` is
    anything other than `RUNNING` -- a caller who wants per-step
    re-verification must call `run.pause()`/`run.resume()` around a
    step, which re-triggers the full grant/identity/ledger check via
    `GenesisTrainingRun`'s own existing, tested transition logic."""
    if not isinstance(run, GenesisTrainingRun):
        raise TrainingNotAuthorizedForExecutionError(
            f"execute_authorized_training_step() requires a real GenesisTrainingRun instance, got "
            f"{type(run).__name__!r} -- no stub, mock, or duck-typed substitute is ever accepted"
        )
    if run.state is not RunState.RUNNING:
        raise TrainingNotAuthorizedForExecutionError(
            f"run {run.identity.run_id!r} is in state {run.state.value}, not RUNNING -- a real training "
            f"step may only execute while this run's own authorization state machine has independently "
            f"verified it is authorized to run right now"
        )
    return engine.step(input_ids, labels)
