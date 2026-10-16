"""
GENESIS Foundation Sprint 2, Workstream C: training-orchestration state
machine.

Models the full lifecycle a real GENESIS native-pretraining run would go
through -- PLANNED, VALIDATED, AWAITING_AUTHORIZATION, AUTHORIZED, RUNNING,
PAUSED, RECOVERING, COMPLETED, FAILED, REJECTED -- with fail-closed
transitions and real, independently-checkable evidence at every step. **No
training loop is executed by this module, and no gradient/optimizer step
ever runs here.** `record_step()` exists so a REAL training loop (which
does not exist yet anywhere in this codebase) could report genuine
progress; nothing in this module itself ever calls it.

## The authorization boundary this module deliberately does NOT invent

GENESIS Foundation Sprint 2 Mission 1A built a `TrainingRunRecord`: a plain
JSON file with `run_id`/`checkpoint_sha256`/`authorized` fields
(`orca/genesis/model/eval_adapter.py`). An independent audit correctly
challenged whether a self-authored JSON boolean can ever qualify as real
founder authorization -- it cannot, and this module does not repeat that
design. ORNEUR already has a real, cryptographically-sound training
authorization gate: `orca.train.authorization.authorize_training()`,
which requires an Ed25519-signed record, verified against a PINNED,
committed authority-key registry (empty today -- nothing is authorized
until the founder provisions a key, a separate action), and issues a
`TrainingGrant`: a sealed object that cannot be hand-constructed, copied,
or pickled, and whose fields are HMAC-tagged against a per-process secret
so a forged or edited copy fails `verify_integrity()`.

**`authorize()` below requires exactly this kind of object -- a real
`orca.train.authorization.TrainingGrant` instance that passes
`verify_integrity()` -- not a boolean, not a string, not a dict.** This is
the module's actual authorization boundary.

**Stated honestly, this integration is currently BLOCKED, not
manufactured**: `orca.train.authorization.authorize_training()` is built
around `orca.train.config.TrainingConfig` (LoRA rank, `resolve_training_data_inputs()`,
dataset-file-based provenance) -- the shape of ORNEUR's existing LoRA/QLoRA
fine-tune path, not GENESIS's native-pretraining config
(`orca.genesis.model.config.GenesisModelConfig`, which has no LoRA rank or
file-based dataset at all). **No code path in this repository today can
actually produce a legitimate `TrainingGrant` for a GENESIS native-pretraining
request.** This module enforces the right INVARIANT (only a real, sealed,
tamper-evident grant object moves a run to `AUTHORIZED`) while being honest
that nothing can satisfy it yet for GENESIS specifically -- extending
`orca.train.authorization` (or building an equally-rigorous GENESIS-specific
sibling with its own signed-record/pinned-registry scheme) is future,
separately-scoped work, not something this module fakes a path around.
"""
from __future__ import annotations

import hashlib
import json
import re
from dataclasses import dataclass, field
from datetime import datetime, timezone
from enum import Enum
from pathlib import Path

from orca.genesis.model.config import ARCHITECTURE_VERSION
from orca.genesis.training.checkpoint_integrity import (
    CheckpointManifest,
    _manifest_path,
    load_verified_training_state,
)
from orca.train.authorization import TrainingGrant, TrainingNotAuthorized

_TS_RE = re.compile(r"^\d{4}-\d{2}-\d{2}T\d{2}:\d{2}:\d{2}Z$")


def _now_iso() -> str:
    return datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")


def _parse_iso(s: str | None) -> datetime | None:
    """A small, local ISO-8601 parser -- deliberately NOT importing
    `orca.train.authorization`'s private `_parse_ts()`. This module
    integrates with that module's PUBLIC authorization contract
    (`TrainingGrant`, `verify_integrity()`), not its private internals."""
    if not isinstance(s, str) or not _TS_RE.match(s):
        return None
    try:
        return datetime.strptime(s, "%Y-%m-%dT%H:%M:%SZ").replace(tzinfo=timezone.utc)
    except ValueError:
        return None


_SHA256_HEX = re.compile(r"^[0-9a-f]{64}$")


class RunState(str, Enum):
    PLANNED = "PLANNED"
    VALIDATED = "VALIDATED"
    AWAITING_AUTHORIZATION = "AWAITING_AUTHORIZATION"
    AUTHORIZED = "AUTHORIZED"
    RUNNING = "RUNNING"
    PAUSED = "PAUSED"
    RECOVERING = "RECOVERING"
    COMPLETED = "COMPLETED"
    FAILED = "FAILED"
    REJECTED = "REJECTED"


TERMINAL_STATES = frozenset({RunState.COMPLETED, RunState.FAILED, RunState.REJECTED})

# The complete, fail-closed transition graph. Any (from, to) pair not listed
# here is forbidden -- including skipping states (PLANNED -> RUNNING),
# reversing a terminal state, or re-entering AWAITING_AUTHORIZATION/AUTHORIZED
# once a run has moved past them.
_ALLOWED_TRANSITIONS: dict[RunState, frozenset[RunState]] = {
    RunState.PLANNED: frozenset({RunState.VALIDATED, RunState.REJECTED}),
    RunState.VALIDATED: frozenset({RunState.AWAITING_AUTHORIZATION, RunState.REJECTED}),
    RunState.AWAITING_AUTHORIZATION: frozenset({RunState.AUTHORIZED, RunState.REJECTED}),
    RunState.AUTHORIZED: frozenset({RunState.RUNNING, RunState.REJECTED}),
    RunState.RUNNING: frozenset({RunState.PAUSED, RunState.COMPLETED, RunState.FAILED}),
    RunState.PAUSED: frozenset({RunState.RUNNING, RunState.RECOVERING, RunState.FAILED}),
    RunState.RECOVERING: frozenset({RunState.RUNNING, RunState.FAILED}),
    RunState.COMPLETED: frozenset(),
    RunState.FAILED: frozenset(),
    RunState.REJECTED: frozenset(),
}


class InvalidTransitionError(Exception):
    """Raised for any transition not present in `_ALLOWED_TRANSITIONS`,
    including attempts to skip states, restart a terminal run, or re-enter
    an already-passed authorization step."""


class ReplayedAuthorizationError(Exception):
    """Raised when a `TrainingGrant` whose `authorization_id` has already
    been consumed by a DIFFERENT run in this process is presented again.
    `orca.train.authorization`'s own run-slot ledger is the authoritative
    defense against reusing one authorization across more actual training
    runs than it permits; this is an additional, narrower safety net
    specific to this orchestrator's own in-process bookkeeping, not a
    replacement for that ledger."""


class StaleAuthorizationError(Exception):
    """Raised when a grant's own `expires_at` has passed at the moment
    `start()` is called -- re-checked at start time, not only trusted from
    whenever `authorize()` ran."""


class ForgedCompletionError(Exception):
    """Raised when `complete()` is given a checkpoint path that does not
    actually pass `load_verified_training_state()`'s full trust boundary,
    or whose verified step does not match this run's own recorded
    execution evidence -- a claimed completion is never accepted on the
    caller's word alone."""


@dataclass
class RunIdentity:
    """Model architecture identity + training dataset identity -- kept as
    two explicitly separate fields per the continuation order, never
    merged into one opaque blob."""
    run_id: str
    model_architecture_version: str
    dataset_manifest_ids: tuple[str, ...]
    dataset_digest: str | None = None  # set by validate(); None beforehand


@dataclass
class ExecutionEvidence:
    """Actual execution evidence -- distinct from permission to execute
    (the `TrainingGrant`) and from completion evidence. Append-only in
    spirit: `steps_recorded` only ever increases (enforced by
    `record_step()`), so a run cannot silently claim it progressed further
    than it really did, and cannot un-claim progress either."""
    steps_recorded: int = 0
    last_recorded_at: str | None = None


@dataclass(frozen=True)
class CompletionEvidence:
    """Completion evidence -- distinct from execution evidence (steps
    happened) and from checkpoint identity verification (the checkpoint is
    real and hash-verified); `complete()` is the only code path that
    constructs this, and only after independently re-verifying both."""
    checkpoint_path: str
    checkpoint_manifest_sha256: str
    final_step: int
    completed_at: str


@dataclass(frozen=True)
class EvaluatorApproval:
    """Evaluator approval -- explicitly separate from training
    authorization (permission to execute) and from completion evidence
    (execution happened). An evaluator approving a checkpoint's quality is
    a different claim from a founder authorizing the run that produced it,
    and from the run itself having actually produced that checkpoint."""
    evaluator_identity: str
    approved: bool
    evaluation_report_sha256: str
    approved_at: str


class GenesisTrainingRun:
    """One run's state machine instance. Every transition method either
    succeeds and advances `state`, or raises without changing `state` --
    there is no partial-transition state."""

    _consumed_authorization_ids: set[str] = set()  # process-wide replay guard, see ReplayedAuthorizationError

    def __init__(self, run_id: str, *, dataset_manifest_ids: tuple[str, ...], architecture_version: str = ARCHITECTURE_VERSION):
        self.state = RunState.PLANNED
        self.identity = RunIdentity(run_id=run_id, model_architecture_version=architecture_version, dataset_manifest_ids=tuple(dataset_manifest_ids))
        self.grant: TrainingGrant | None = None
        self.execution: ExecutionEvidence | None = None
        self.completion: CompletionEvidence | None = None
        self.evaluator_approval: EvaluatorApproval | None = None
        self.history: list[tuple[str, str, str]] = []  # (from_state, to_state, reason)

    def _transition(self, to: RunState, *, reason: str) -> None:
        allowed = _ALLOWED_TRANSITIONS.get(self.state, frozenset())
        if to not in allowed:
            raise InvalidTransitionError(f"{self.state.value} -> {to.value} is not an allowed transition (reason attempted: {reason!r})")
        self.history.append((self.state.value, to.value, reason))
        self.state = to

    # ---- PLANNED -> VALIDATED --------------------------------------------------------------
    def validate(self, *, dataset_digest: str) -> None:
        """Training dataset identity is bound here: `dataset_digest` must
        be a real 64-hex-char SHA-256 the caller computed from the actual
        dataset bytes (this method does not compute it itself -- it has
        no dataset-loading code of its own, deliberately, to avoid
        duplicating `orca.registry.provenance`'s dataset-binding
        responsibility)."""
        if self.state != RunState.PLANNED:
            raise InvalidTransitionError(f"validate() requires PLANNED, got {self.state.value}")
        if not isinstance(dataset_digest, str) or not _SHA256_HEX.match(dataset_digest):
            self._transition(RunState.REJECTED, reason="invalid dataset_digest at validation")
            raise ValueError(f"dataset_digest must be a 64-character lowercase hex SHA-256, got {dataset_digest!r}")
        self.identity.dataset_digest = dataset_digest
        self._transition(RunState.VALIDATED, reason="dataset identity recorded and well-formed")

    # ---- VALIDATED -> AWAITING_AUTHORIZATION -----------------------------------------------
    def request_authorization(self) -> None:
        if self.state != RunState.VALIDATED:
            raise InvalidTransitionError(f"request_authorization() requires VALIDATED, got {self.state.value}")
        self._transition(RunState.AWAITING_AUTHORIZATION, reason="awaiting founder-trusted authorization")

    # ---- AWAITING_AUTHORIZATION -> AUTHORIZED ----------------------------------------------
    def authorize(self, grant: TrainingGrant) -> None:
        """The real authorization boundary -- see module docstring. Raises
        `TrainingNotAuthorized` (propagated from `grant.verify_integrity()`,
        never swallowed) for anything that is not a genuinely sealed,
        untampered grant object, and `ReplayedAuthorizationError` for one
        already consumed by a different run in this process."""
        if self.state != RunState.AWAITING_AUTHORIZATION:
            raise InvalidTransitionError(f"authorize() requires AWAITING_AUTHORIZATION, got {self.state.value}")
        if not isinstance(grant, TrainingGrant):
            self._transition(RunState.REJECTED, reason="authorization rejected: not a real TrainingGrant instance")
            raise TrainingNotAuthorized(["NO_TRAINING_GRANT"])
        try:
            grant.verify_integrity()
        except TrainingNotAuthorized:
            self._transition(RunState.REJECTED, reason="authorization rejected: grant failed integrity verification (forged or tampered)")
            raise
        if grant.authorization_id in GenesisTrainingRun._consumed_authorization_ids:
            self._transition(RunState.REJECTED, reason="authorization rejected: replayed authorization_id")
            raise ReplayedAuthorizationError(
                f"authorization_id {grant.authorization_id!r} has already authorized a different run in this process"
            )
        GenesisTrainingRun._consumed_authorization_ids.add(grant.authorization_id)
        self.grant = grant
        self._transition(RunState.AUTHORIZED, reason=f"authorized via verified grant {grant.authorization_id}")

    # ---- AUTHORIZED -> RUNNING --------------------------------------------------------------
    def start(self) -> None:
        """Re-verifies the grant's integrity AND its expiry at the moment
        execution actually begins, not only at `authorize()` time -- a
        grant that was valid when authorized but has since expired must
        not silently start a run."""
        if self.state != RunState.AUTHORIZED:
            raise InvalidTransitionError(f"start() requires AUTHORIZED, got {self.state.value}")
        if self.grant is None:
            raise InvalidTransitionError("start() called with no grant recorded -- internal invariant violated")
        try:
            self.grant.verify_integrity()
        except TrainingNotAuthorized:
            self._transition(RunState.REJECTED, reason="grant failed integrity verification at start() -- forged or tampered since authorize()")
            raise
        expires = _parse_iso(self.grant.expires_at)
        if expires is None or datetime.now(timezone.utc) >= expires:
            self._transition(RunState.REJECTED, reason="authorization expired before execution started")
            raise StaleAuthorizationError(f"grant {self.grant.authorization_id} expired at {self.grant.expires_at}")
        self.execution = ExecutionEvidence()
        self._transition(RunState.RUNNING, reason="execution started under a freshly re-verified grant")

    # ---- RUNNING: execution evidence (never called by this module itself) -----------------
    def record_step(self, step: int, *, loss: float | None = None) -> None:
        """A real training loop would call this once per optimizer step.
        Nothing in this codebase does, because no GENESIS native training
        loop exists yet (see the GENESIS Sprint governance docs: native
        pretraining is `NOT_AUTHORIZED`). `step` must strictly increase --
        this is append-only progress, never a rewritable claim."""
        if self.state != RunState.RUNNING:
            raise InvalidTransitionError(f"record_step() requires RUNNING, got {self.state.value}")
        if self.execution is None:
            raise InvalidTransitionError("record_step() called with no execution evidence initialized")
        if not isinstance(step, int) or step <= self.execution.steps_recorded:
            raise ValueError(f"step must be a strictly increasing integer; got {step}, last recorded {self.execution.steps_recorded}")
        self.execution.steps_recorded = step
        self.execution.last_recorded_at = _now_iso()

    # ---- RUNNING -> PAUSED -> RUNNING / RECOVERING -----------------------------------------
    def pause(self, *, reason: str = "paused") -> None:
        if self.state != RunState.RUNNING:
            raise InvalidTransitionError(f"pause() requires RUNNING, got {self.state.value}")
        self._transition(RunState.PAUSED, reason=reason)

    def resume(self) -> None:
        if self.state != RunState.PAUSED:
            raise InvalidTransitionError(f"resume() requires PAUSED, got {self.state.value}")
        self._transition(RunState.RUNNING, reason="resumed from pause")

    def begin_recovery(self, *, reason: str) -> None:
        if self.state != RunState.PAUSED:
            raise InvalidTransitionError(f"begin_recovery() requires PAUSED, got {self.state.value}")
        self._transition(RunState.RECOVERING, reason=reason)

    def recovered(self) -> None:
        """RECOVERING -> RUNNING. Re-verifies the grant exactly like
        `start()` does -- an interrupted-and-recovered run must not resume
        on a since-expired or since-revoked-and-tampered-with grant
        either."""
        if self.state != RunState.RECOVERING:
            raise InvalidTransitionError(f"recovered() requires RECOVERING, got {self.state.value}")
        if self.grant is None:
            raise InvalidTransitionError("recovered() called with no grant recorded -- internal invariant violated")
        try:
            self.grant.verify_integrity()
        except TrainingNotAuthorized:
            self._transition(RunState.FAILED, reason="grant failed integrity verification during recovery -- forged or tampered")
            raise
        expires = _parse_iso(self.grant.expires_at)
        if expires is None or datetime.now(timezone.utc) >= expires:
            self._transition(RunState.FAILED, reason="authorization expired during recovery")
            raise StaleAuthorizationError(f"grant {self.grant.authorization_id} expired at {self.grant.expires_at}")
        self._transition(RunState.RUNNING, reason="recovered and resumed")

    # ---- RUNNING/PAUSED/RECOVERING -> FAILED -----------------------------------------------
    def fail(self, *, reason: str) -> None:
        if self.state not in (RunState.RUNNING, RunState.PAUSED, RunState.RECOVERING):
            raise InvalidTransitionError(f"fail() requires RUNNING, PAUSED, or RECOVERING, got {self.state.value}")
        self._transition(RunState.FAILED, reason=reason)

    # ---- any non-terminal state -> REJECTED ------------------------------------------------
    def reject(self, *, reason: str) -> None:
        if self.state in TERMINAL_STATES:
            raise InvalidTransitionError(f"reject() cannot be called on a terminal state ({self.state.value})")
        self._transition(RunState.REJECTED, reason=reason)

    # ---- RUNNING -> COMPLETED ---------------------------------------------------------------
    def complete(self, *, checkpoint_path: str | Path) -> None:
        """Completion evidence AND checkpoint identity, both independently
        re-verified here -- never accepted on the caller's word. Raises
        `ForgedCompletionError` if the checkpoint does not pass the full
        `load_verified_training_state()` trust boundary, or if its
        verified step does not match this run's own recorded execution
        evidence (closing the exact "forged completion" case the
        continuation order names: a caller claiming completion with a
        checkpoint that either isn't real, isn't verified, or doesn't
        correspond to what this run actually executed)."""
        if self.state != RunState.RUNNING:
            raise InvalidTransitionError(f"complete() requires RUNNING, got {self.state.value}")
        if self.execution is None or self.execution.steps_recorded == 0:
            raise ForgedCompletionError("cannot complete a run with no recorded execution evidence -- nothing was ever actually run")
        checkpoint_path = Path(checkpoint_path)
        try:
            state = load_verified_training_state(checkpoint_path)
        except Exception as e:
            raise ForgedCompletionError(f"checkpoint at {checkpoint_path} failed verification: {e!r}") from e
        if state.step != self.execution.steps_recorded:
            raise ForgedCompletionError(
                f"checkpoint's verified step ({state.step}) does not match this run's recorded execution "
                f"evidence ({self.execution.steps_recorded}) -- this checkpoint does not correspond to this run"
            )
        manifest = CheckpointManifest.from_dict(json.loads(_manifest_path(checkpoint_path).read_text()))
        self.completion = CompletionEvidence(
            checkpoint_path=str(checkpoint_path), checkpoint_manifest_sha256=manifest.sha256,
            final_step=state.step, completed_at=_now_iso(),
        )
        self._transition(RunState.COMPLETED, reason=f"completion verified against checkpoint step {state.step}")

    # ---- evaluator approval: COMPLETED only, separate from everything above ---------------
    def record_evaluator_approval(self, *, evaluator_identity: str, approved: bool, evaluation_report_sha256: str) -> None:
        """Evaluator approval is recorded only AFTER completion, and is
        explicitly a different claim from training authorization or
        execution/completion evidence -- an evaluator judges the
        RESULTING checkpoint's quality; nothing about that act re-proves
        or substitutes for whether the run was authorized or actually
        executed."""
        if self.state != RunState.COMPLETED:
            raise InvalidTransitionError(f"record_evaluator_approval() requires COMPLETED, got {self.state.value}")
        if self.completion is None:
            raise InvalidTransitionError("record_evaluator_approval() called with no completion evidence recorded")
        if not isinstance(evaluation_report_sha256, str) or not _SHA256_HEX.match(evaluation_report_sha256):
            raise ValueError(f"evaluation_report_sha256 must be a 64-character lowercase hex SHA-256, got {evaluation_report_sha256!r}")
        self.evaluator_approval = EvaluatorApproval(
            evaluator_identity=evaluator_identity, approved=approved,
            evaluation_report_sha256=evaluation_report_sha256, approved_at=_now_iso(),
        )
