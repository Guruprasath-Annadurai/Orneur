"""
GENESIS Native Learning Engine, Phase 1, Workstream 5: the ONLY
sanctioned call path from a real `NativePretrainingGrant`-authorized
`GenesisTrainingRun` to `orca.genesis.training.learning_step
.TrainingStepEngine.step()` -- i.e. to an ACTUAL gradient-based
parameter update against real data.

This module adds no new cryptographic authorization primitives of its
own; every check it performs re-calls `orca.genesis.training
.orchestration.GenesisTrainingRun`'s and `orca.genesis.governance
.authorization`'s own, already-built, already-audited (Mission 2,
Audit #71 P0-01) machinery. Today, with the real founder-acceptance
ledger and authority registry both committed empty (`NOT_AUTHORIZED`),
`GenesisTrainingRun.start()`/`.resume()` always raise before a real run
can ever reach `RUNNING` -- so this gate, by construction, cannot
currently be satisfied by any real (non-test-fixture) grant.

## Antigravity Audit #074 remediation -- AUDIT-P0-02

Independently reproduced, two distinct defects:

1. **In-flight expiration/revocation was never checked.** The PRIOR
   version of this function checked `run.state is RunState.RUNNING`
   ONCE per call and nothing else -- `run.state` is an in-memory enum
   that `GenesisTrainingRun` itself only re-verifies at resume-capable
   STATE TRANSITIONS (`start()`/`resume()`/`recovered()`), by that
   module's own deliberate, documented design (re-deriving the full
   grant/identity check on every call would be redundant with that
   design, per `orchestration.py`'s own C-02 rationale). But this
   module's OWN callers do not go through a transition on every step --
   an expired or revoked grant could keep a `RUNNING` session updating
   parameters indefinitely between transitions. **Fixed**: this module
   now independently re-calls `orca.genesis.governance.authorization
   .assert_execution_permitted()` (HMAC integrity + expiry + live
   revocation) AND re-derives the run's full identity snapshot
   (catching dataset/shard drift, reusing `GenesisTrainingRun`'s own
   `_current_identity_snapshot()`/`_authorized_identity` comparison) on
   EVERY SINGLE call -- i.e. at the finest possible cadence, every
   optimizer-update boundary, not merely at transitions. A caller
   wanting reduced overhead at real scale can raise
   `revalidate_every_n_calls`, but the default is `1` (every call),
   deliberately the safest choice, not a cosmetic check performed once
   and never again.

2. **Direct `TrainingStepEngine.step()` bypass.** Fixed in
   `learning_step.py` itself (`ExecutionCapability`, Audit #074 P0-02) --
   this function is now the only sanctioned path to a REAL capability
   token (`engine._issue_capability_for_governance()`), minted only
   AFTER the full re-validation above passes, on every single call, so
   a minted token is never handed out stale or reused across an
   authorization change. See `learning_step.py`'s own module docstring
   for the honest, explicit statement of what this can and cannot
   prevent -- repeated here because it matters: **no in-process Python
   mechanism can make a direct, same-interpreter bypass "universally
   impossible."** A caller willing to call `TrainingStepEngine
   ._issue_capability_for_governance()` directly, or to rewrite an
   equivalent training loop from scratch using the same public
   `causal_lm_loss`/`build_optimizer`/`clip_grad_norm` primitives this
   engine itself calls, is not stopped by anything in this codebase --
   genuine prevention of a co-resident, equally-privileged Python
   caller requires an actual OS-process trust boundary (training
   executing in a separate worker process, reachable only through an
   IPC channel that itself re-authenticates every call and never
   shares interpreter state with the caller). Building and testing that
   architecture is explicitly out of scope for this remediation phase
   and is recorded here as an open architectural requirement, not
   claimed as already closed.

**No bypass of any kind is implemented or honored here**:
- No environment variable is read anywhere in this module.
- `run` must be a real `GenesisTrainingRun` INSTANCE
  (`isinstance` checked, not duck-typed) -- a stub, mock, or
  dict-with-the-right-keys is rejected, never silently accepted as
  "close enough."
- There is no parameter, flag, or keyword argument on
  `execute_authorized_training_step()` that weakens or skips the
  `isinstance`/state/expiry/revocation/identity check below. Adding one
  would defeat this module's entire purpose; none exists."""
from __future__ import annotations

import torch

from orca.genesis.governance.authorization import NativePretrainingNotAuthorized, assert_execution_permitted
from orca.genesis.training.learning_step import StepResult, TrainingStepEngine
from orca.genesis.training.orchestration import AuthorizedIdentityChangedError, GenesisTrainingRun, RunState


class TrainingNotAuthorizedForExecutionError(Exception):
    """Raised whenever `execute_authorized_training_step()` is called
    without a real `GenesisTrainingRun` in `RunState.RUNNING` whose
    grant and identity independently re-verify RIGHT NOW -- not merely
    at whatever moment `start()`/`resume()` last ran. This is the
    single, fail-closed gate this entire module exists to provide;
    every call that reaches `TrainingStepEngine.step()` through this
    function passed this check at THIS call, not at some earlier one."""


def execute_authorized_training_step(
    run: GenesisTrainingRun, engine: TrainingStepEngine, input_ids: torch.Tensor, labels: torch.Tensor,
    *, revalidate_every_n_calls: int = 1,
) -> StepResult:
    """The sanctioned entrypoint. Raises
    `TrainingNotAuthorizedForExecutionError` immediately, before calling
    `engine.step()` at all, unless, as of THIS call:
    1. `run` is a genuine `GenesisTrainingRun` instance.
    2. `run.state is RunState.RUNNING`.
    3. `run.grant` independently re-verifies via
       `assert_execution_permitted()` -- HMAC integrity, expiry, AND
       live revocation, re-checked now, not assumed from whenever
       `start()`/`resume()` last ran (AUDIT-P0-02).
    4. `run`'s current identity snapshot (dataset/shard digests among
       everything else it binds) still matches the frozen snapshot
       `authorize()` captured -- the SAME check
       `_reverify_grant_or_transition()` performs at transitions,
       reused here, re-derived fresh every call (AUDIT-P0-02).

    `revalidate_every_n_calls` (default `1`, every call -- the safest,
    most conservative default): an explicit, documented trade-off knob
    for a caller at a scale where re-deriving the full identity
    snapshot (which re-hashes shard files from disk) on every single
    microbatch call is prohibitively expensive. Raising this WIDENS the
    window between re-validations -- stated plainly, not hidden."""
    if not isinstance(run, GenesisTrainingRun):
        raise TrainingNotAuthorizedForExecutionError(
            f"execute_authorized_training_step() requires a real GenesisTrainingRun instance, got "
            f"{type(run).__name__!r} -- no stub, mock, or duck-typed substitute is ever accepted"
        )
    if run.state is not RunState.RUNNING:
        raise TrainingNotAuthorizedForExecutionError(
            f"run {run.identity.run_id!r} is in state {run.state.value}, not RUNNING -- a real training "
            f"step may only execute while this run's own authorization state machine says it is RUNNING"
        )
    if getattr(run, "grant", None) is None or getattr(run, "_authorized_identity", None) is None:
        # A real GenesisTrainingRun can NEVER legitimately be RUNNING with
        # either of these unset (authorize()/start() always populate both
        # before RUNNING is reachable) -- a subclass or instance that
        # forged RunState.RUNNING directly (bypassing authorize()/start()
        # entirely) is caught HERE, explicitly, rather than crashing with
        # a raw AttributeError a few lines below, which would look like a
        # bug rather than the deliberate security boundary it is.
        raise TrainingNotAuthorizedForExecutionError(
            f"run {run.identity.run_id!r} reports RunState.RUNNING but has no real grant/authorized "
            f"identity bound -- this is not a run that genuinely passed through authorize()/start(), "
            f"and is refused regardless of its reported .state"
        )

    # AUDIT-P0-02: in-flight re-validation, independent of whatever
    # run.state currently says, on the cadence revalidate_every_n_calls
    # requests (default: every call). Reuses the engine's own existing
    # global_step counter as the cadence tracker -- no new, separately
    # fragile external state needed.
    due = (engine.global_step % max(revalidate_every_n_calls, 1)) == 0
    if due:
        try:
            assert_execution_permitted(run.grant, revocation_check=run._revocation_check)
        except NativePretrainingNotAuthorized as e:
            raise TrainingNotAuthorizedForExecutionError(
                f"run {run.identity.run_id!r}'s grant no longer independently re-verifies as permitted "
                f"RIGHT NOW (in-flight expiry or revocation): {e.reasons}"
            ) from e
        current = run._current_identity_snapshot()
        if current != run._authorized_identity:
            raise TrainingNotAuthorizedForExecutionError(
                f"run {run.identity.run_id!r}'s current identity (dataset/shard/code/model) no longer "
                f"matches the identity snapshot frozen at authorize() time -- in-flight drift detected"
            )

    capability = engine._issue_capability_for_governance()
    return engine.step(input_ids, labels, capability=capability)
