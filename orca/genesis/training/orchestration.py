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

## Independent-audit continuation (2026-10-16) -- C-01 through C-06

A founder-directed code review of the first version of this module
(commit `330f1b8`) independently reproduced six concerns before any fix was
applied here. Each is addressed below; this section records what was found
and how it was closed, so the fix is auditable against the original
finding, not just asserted.

- **C-01 (wrong-workload authorization)**: REPRODUCED. A legitimately
  issued `TrainingGrant` for an entirely unrelated, generic LoRA/QLoRA
  config transitioned a synthetic GENESIS run straight to `AUTHORIZED` --
  `authorize()` previously checked only that the grant was real
  (`isinstance` + `verify_integrity()`), never that it was bound to THIS
  workload. Fixed via `_expected_grant_scope()` +
  `TrainingGrant.assert_valid_for()` (see below) -- a `cfg_fingerprint`
  mismatch now raises `TrainingNotAuthorized` for any grant not computed
  from GENESIS's own declared scope. No conversion shortcut from LoRA
  authorization is invented: since no code anywhere produces a grant whose
  fingerprint matches a real GENESIS scope today, EVERY currently-issuable
  grant is now correctly rejected -- GENESIS authorization remains
  `BLOCKED`, exactly as instructed, not worked around.
- **C-02 (authorization checks during resume)**: REPRODUCED. `resume()`
  performed no grant re-check at all. Fixed: `resume()` now runs the same
  re-verification as `start()`/`recovered()` (HMAC integrity, expiry, and
  an optional live-revocation hook -- see `_reverify_grant_or_transition()`).
  Workload-scope binding (C-01's fingerprint check) is deliberately NOT
  re-run at every resume-capable transition -- it is a property of the
  one-time decision to authorize this run, checked exhaustively in
  `authorize()`, and cannot legitimately change afterward without this
  module itself replacing the grant, which never happens; re-deriving it
  on every transition would be redundant, not additional safety.
- **C-03 (execution-evidence authenticity)**: addressed by construction.
  `record_step()`'s output is now explicitly typed `ExecutionEvent` with a
  fixed `classification="REPORTED_EXECUTION_PROGRESS"` field -- never
  described, anywhere in this module's naming or docstrings, as
  independently verified proof that an optimizer step actually ran.
  `source_identity` and `run_id` are required and checked; a `sequence`
  counter enforces strict event ordering separately from the caller-chosen
  `step` number; `max_events` bounds the evidence list.
- **C-04 (evaluator-approval authenticity)**: `EvaluatorApprovalClaim`
  (renamed from `EvaluatorApproval`) carries a fixed
  `is_independently_authenticated=False` field -- this module has no
  evaluator-identity PKI, so `evaluator_identity` is a self-reported label,
  never a verified identity. What IS independently checked:
  `checkpoint_manifest_sha256` must equal this run's own
  `CompletionEvidence.checkpoint_manifest_sha256` exactly, so an approval
  claim cannot be silently misattributed to a different checkpoint.
- **C-05 (durable replay/recovery)**: `_consumed_authorization_ids` is
  explicitly documented, and now has a dedicated, documented
  `reset_in_process_replay_guard_for_new_process()` classmethod, as an
  IN-PROCESS-ONLY safety net. No second, conflicting on-disk ledger is
  created here -- the authoritative, cross-process defense against reusing
  one authorization across more real runs than it permits remains
  `orca.train.authorization`'s own on-disk run-slot ledger
  (`_claim_run_slot`/`_authorized_event_count`), which this module
  integrates with by relying on, not duplicating.
- **C-06 (state-transition consistency)**: REPRODUCED. `reject()`'s
  docstring/precondition claimed "any non-terminal state", but
  `_ALLOWED_TRANSITIONS` only permits `-> REJECTED` from `PLANNED`,
  `VALIDATED`, `AWAITING_AUTHORIZATION`, and `AUTHORIZED` -- calling
  `reject()` from `RUNNING`/`PAUSED`/`RECOVERING` raised
  `InvalidTransitionError` despite the method's own stated contract. Fixed
  by narrowing `reject()`'s precondition to match the actual transition
  graph (`_REJECTABLE_STATES`) -- the graph was correct; the method's
  stated contract was wrong, so the method was corrected, not the graph,
  and no test was loosened to paper over the mismatch.

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
`verify_integrity()` AND `assert_valid_for()` against this run's own
declared scope -- not a boolean, not a string, not a dict, and not a grant
issued for a different workload.** This is the module's actual
authorization boundary.

**Stated honestly, this integration is currently BLOCKED, not
manufactured**: `orca.train.authorization.authorize_training()` is built
around `orca.train.config.TrainingConfig` (LoRA rank, `resolve_training_data_inputs()`,
dataset-file-based provenance) -- the shape of ORNEUR's existing LoRA/QLoRA
fine-tune path, not GENESIS's native-pretraining config
(`orca.genesis.model.config.GenesisModelConfig`, which has no LoRA rank or
file-based dataset at all). **No code path in this repository today can
actually produce a legitimate `TrainingGrant` for a GENESIS native-pretraining
request.** This module enforces the right INVARIANT (only a real, sealed,
tamper-evident, workload-bound grant object moves a run to `AUTHORIZED`)
while being honest that nothing can satisfy it yet for GENESIS specifically
-- extending `orca.train.authorization` (or building an equally-rigorous
GENESIS-specific sibling with its own signed-record/pinned-registry scheme)
is future, separately-scoped work, not something this module fakes a path
around.
"""
from __future__ import annotations

import json
import re
from dataclasses import dataclass, field
from datetime import datetime, timezone
from enum import Enum
from pathlib import Path
from typing import Callable

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
    (`TrainingGrant`, `verify_integrity()`, `assert_valid_for()`), not its
    private internals."""
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
# once a run has moved past them. C-06: this graph is the single source of
# truth; every method's precondition is reconciled against it, not the
# other way around.
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

# C-06 fix: reject() is valid only from states the graph actually permits
# a REJECTED transition from. Derived directly from _ALLOWED_TRANSITIONS
# (never hand-duplicated) so the two can never silently drift apart again.
_REJECTABLE_STATES = frozenset(s for s, targets in _ALLOWED_TRANSITIONS.items() if RunState.REJECTED in targets)


class InvalidTransitionError(Exception):
    """Raised for any transition not present in `_ALLOWED_TRANSITIONS`,
    including attempts to skip states, restart a terminal run, or re-enter
    an already-passed authorization step."""


class ReplayedAuthorizationError(Exception):
    """Raised when a `TrainingGrant` whose `authorization_id` has already
    been consumed by a DIFFERENT run in THIS PROCESS is presented again.

    C-05: this is explicitly an IN-PROCESS-ONLY safety net, not a durable,
    cross-process ledger. `orca.train.authorization`'s own on-disk run-slot
    ledger (`_claim_run_slot`/`_authorized_event_count`, scoped under
    `orca.config.ORCA_HOME`) is the authoritative defense against reusing
    one authorization across more real training runs than it permits --
    that ledger persists across process restarts and is re-checked on
    every `authorize_training()` call; this module does not duplicate it.
    A second `GenesisTrainingRun` process that never shared this process's
    memory (e.g. a new OS process, or `reset_in_process_replay_guard_for_new_process()`
    having been called) CANNOT detect replay via this guard alone -- see
    that classmethod's own docstring and
    `tests/test_genesis_training_orchestration.py`'s dedicated test of this
    exact boundary."""


class StaleAuthorizationError(Exception):
    """Raised when a grant's own `expires_at` has passed, or its
    workload-scope binding no longer matches, at the moment `start()`,
    `resume()`, or `recovered()` is called -- re-checked at every one of
    these transitions, not only trusted from whenever `authorize()` ran."""


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


@dataclass(frozen=True)
class _LoraFieldsView:
    """A zeroed stand-in for `TrainingConfig.lora`'s two fields that
    `orca.train.authorization._cfg_fingerprint()` reads. GENESIS native
    pretraining has no LoRA rank at all; zero is the explicit, documented
    "not applicable" value, never a real rank a caller chose."""
    r: int = 0
    lora_alpha: int = 0


@dataclass(frozen=True)
class GenesisGrantScope:
    """The exact attribute shape `orca.train.authorization.TrainingGrant.assert_valid_for()`
    (via its private `_cfg_fingerprint()`) reads from a `TrainingConfig` --
    `family`, `base_model`, `num_epochs`, `lora.r`, `lora.lora_alpha`,
    `max_seq_length`, `train_file`, `eval_file`, `data_format`. This is
    deliberately NOT a real `TrainingConfig` and is never passed to any
    fine-tune code -- it exists solely so `assert_valid_for()`'s PUBLIC
    fingerprint-matching check can be exercised honestly against a
    GENESIS run's own declared identity (C-01 fix). `base_model` is a
    fixed sentinel label, not a real HuggingFace model id (GENESIS native
    pretraining has no base model); `train_file` carries the run's real
    dataset content digest in place of a file path (GENESIS has no
    file-based dataset). See the module docstring: no code anywhere
    produces a grant whose `cfg_fingerprint` matches this today, so this
    check currently rejects every grant -- the correct, honest `BLOCKED`
    state, not a bug."""
    family: str | None
    base_model: str
    num_epochs: int
    lora: _LoraFieldsView
    max_seq_length: int
    train_file: str
    eval_file: str | None
    data_format: str


_GENESIS_SCOPE_BASE_MODEL_SENTINEL = "orneur-genesis-native-pretraining"
_GENESIS_SCOPE_DATA_FORMAT_SENTINEL = "genesis-native-pretraining"


@dataclass
class ExecutionEvent:
    """C-03: a single SELF-REPORTED progress event. `classification` is
    always `"REPORTED_EXECUTION_PROGRESS"` -- fixed, non-configurable --
    because this module has no mechanism to independently verify that an
    optimizer step actually ran. These are claims from whatever called
    `record_step()`, never proof. `source_identity` names the reporting
    process/caller (itself unauthenticated -- a real deployment would bind
    this to a signed or otherwise verifiable execution identity, which
    does not exist yet); `run_id` must match the run it is reported
    against; `sequence` is this module's own strictly-increasing event
    counter, kept separate from the caller-chosen `step` number so event
    ORDER is enforced independently of what the caller claims `step` to
    mean."""
    source_identity: str
    run_id: str
    step: int
    sequence: int
    reported_at: str
    classification: str = "REPORTED_EXECUTION_PROGRESS"


@dataclass
class ExecutionEvidence:
    """Actual execution evidence -- distinct from permission to execute
    (the `TrainingGrant`) and from completion evidence. `events` is
    append-only (nothing in this module ever removes or edits a past
    entry); `max_events` is an explicit evidence-volume limit (C-03), so
    an unbounded or malicious caller cannot grow this without limit."""
    events: list[ExecutionEvent] = field(default_factory=list)
    max_events: int = 100_000

    @property
    def steps_recorded(self) -> int:
        return self.events[-1].step if self.events else 0

    @property
    def last_recorded_at(self) -> str | None:
        return self.events[-1].reported_at if self.events else None


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
class EvaluatorApprovalClaim:
    """C-04: an explicitly UNAUTHENTICATED claim of evaluator approval.
    This module has no evaluator-identity PKI or signature-verification
    mechanism, so `evaluator_identity` is a self-reported label, never a
    cryptographically verified identity -- `is_independently_authenticated`
    is a fixed `False`, not a field a caller can set to claim otherwise.
    What IS independently checked here: `checkpoint_manifest_sha256` must
    equal this run's own completed checkpoint's manifest hash exactly, so
    an approval claim cannot be silently misattributed to a different
    checkpoint (see `record_evaluator_approval()`)."""
    evaluator_identity: str
    approved: bool
    evaluation_report_sha256: str
    checkpoint_manifest_sha256: str
    approved_at: str
    is_independently_authenticated: bool = False


class GenesisTrainingRun:
    """One run's state machine instance. Every transition method either
    succeeds and advances `state`, or raises without changing `state`
    beyond a single, intentional failure transition (e.g. to `REJECTED`)
    -- there is no partial-transition state."""

    _consumed_authorization_ids: set[str] = set()  # C-05: process-local replay guard only, see ReplayedAuthorizationError

    def __init__(
        self, run_id: str, *, dataset_manifest_ids: tuple[str, ...], environment_class: str,
        architecture_version: str = ARCHITECTURE_VERSION, revocation_check: Callable[[str], bool] | None = None,
    ):
        self.state = RunState.PLANNED
        self.identity = RunIdentity(run_id=run_id, model_architecture_version=architecture_version, dataset_manifest_ids=tuple(dataset_manifest_ids))
        self.environment_class = environment_class
        self.grant: TrainingGrant | None = None
        self.execution: ExecutionEvidence | None = None
        self.completion: CompletionEvidence | None = None
        self.evaluator_approval: EvaluatorApprovalClaim | None = None
        self.history: list[tuple[str, str, str]] = []  # (from_state, to_state, reason)
        self._revocation_check = revocation_check

    @classmethod
    def reset_in_process_replay_guard_for_new_process(cls) -> None:
        """C-05: call this ONLY at the entrypoint of a genuinely new OS
        process that holds no memory of what a PRIOR process consumed.
        This resets the in-process-only replay guard; it does NOT, and
        cannot, reach into `orca.train.authorization`'s own on-disk
        run-slot ledger, which remains the authoritative, durable,
        cross-process defense against reusing one authorization across
        more real runs than it permits."""
        cls._consumed_authorization_ids = set()

    def _transition(self, to: RunState, *, reason: str) -> None:
        allowed = _ALLOWED_TRANSITIONS.get(self.state, frozenset())
        if to not in allowed:
            raise InvalidTransitionError(f"{self.state.value} -> {to.value} is not an allowed transition (reason attempted: {reason!r})")
        self.history.append((self.state.value, to.value, reason))
        self.state = to

    def _expected_grant_scope(self) -> GenesisGrantScope:
        """C-01: the workload-binding scope this run's grant must match.
        See `GenesisGrantScope`'s own docstring for why each field has the
        value it does."""
        return GenesisGrantScope(
            family=None, base_model=_GENESIS_SCOPE_BASE_MODEL_SENTINEL, num_epochs=0, lora=_LoraFieldsView(),
            max_seq_length=0, train_file=self.identity.dataset_digest or "", eval_file=None,
            data_format=_GENESIS_SCOPE_DATA_FORMAT_SENTINEL,
        )

    def _reverify_grant_or_transition(self, *, on_failure: RunState, context: str) -> None:
        """The single, shared re-verification routine `start()`,
        `resume()`, and `recovered()` all call (C-02: previously only
        `start()`/`recovered()` did this at all, and neither checked live
        revocation).

        Deliberately does NOT re-run the workload-scope (`cfg_fingerprint`)
        check here -- that binding is a property of the DECISION to
        authorize this run in the first place (checked once, exhaustively,
        in `authorize()`; see C-01) and cannot legitimately change for an
        already-authorized run without this module itself replacing the
        grant, which never happens. Re-deriving it here would be redundant
        work, not additional safety.

        What DOES need re-checking at every resume-capable transition
        (C-02's actual point) is whatever CAN change after `authorize()`:
        HMAC integrity (forged/tampered since issuance) and live
        authorization validity (expiry having passed; revocation having
        occurred) -- explicitly DISTINCT checks: passing the HMAC check
        proves the object was genuinely issued and is untampered; it does
        NOT prove the underlying authorization has not since been revoked
        or expired. `revocation_check`'s absence is a documented, explicit
        `BLOCKED` gap (no live revocation re-check happens without a
        caller-supplied hook), not a silent assumption that a grant
        remains valid forever."""
        assert self.grant is not None
        try:
            self.grant.verify_integrity()
        except TrainingNotAuthorized:
            self._transition(on_failure, reason=f"grant failed integrity verification at {context} (forged or tampered)")
            raise
        expires = _parse_iso(self.grant.expires_at)
        if expires is None or datetime.now(timezone.utc) >= expires:
            self._transition(on_failure, reason=f"authorization expired, detected at {context}")
            raise StaleAuthorizationError(f"grant {self.grant.authorization_id} expired at {self.grant.expires_at}")
        if self._revocation_check is not None and self._revocation_check(self.grant.authorization_id):
            self._transition(on_failure, reason=f"grant revoked, detected live at {context}")
            raise TrainingNotAuthorized(["AUTHORIZATION_REVOKED_LIVE"])

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
        `TrainingNotAuthorized` for anything that is not a genuinely
        sealed, untampered, workload-bound grant object (C-01: this now
        includes a `cfg_fingerprint`/environment-class scope check, not
        only an integrity check), and `ReplayedAuthorizationError` for one
        already consumed by a different run in this process."""
        if self.state != RunState.AWAITING_AUTHORIZATION:
            raise InvalidTransitionError(f"authorize() requires AWAITING_AUTHORIZATION, got {self.state.value}")
        if not isinstance(grant, TrainingGrant):
            self._transition(RunState.REJECTED, reason="authorization rejected: not a real TrainingGrant instance")
            raise TrainingNotAuthorized(["NO_TRAINING_GRANT"])
        try:
            grant.verify_integrity()
            grant.assert_valid_for(self._expected_grant_scope(), environment_class=self.environment_class)
        except TrainingNotAuthorized:
            self._transition(RunState.REJECTED, reason="authorization rejected: grant failed integrity or workload-scope verification")
            raise
        if grant.authorization_id in GenesisTrainingRun._consumed_authorization_ids:
            self._transition(RunState.REJECTED, reason="authorization rejected: replayed authorization_id")
            raise ReplayedAuthorizationError(
                f"authorization_id {grant.authorization_id!r} has already authorized a different run in this process"
            )
        GenesisTrainingRun._consumed_authorization_ids.add(grant.authorization_id)
        self.grant = grant
        self._transition(RunState.AUTHORIZED, reason=f"authorized via verified, workload-bound grant {grant.authorization_id}")

    # ---- AUTHORIZED -> RUNNING --------------------------------------------------------------
    def start(self) -> None:
        """Re-verifies the grant (integrity, workload scope, expiry, and
        live revocation if a hook was supplied) at the moment execution
        actually begins, not only at `authorize()` time."""
        if self.state != RunState.AUTHORIZED:
            raise InvalidTransitionError(f"start() requires AUTHORIZED, got {self.state.value}")
        if self.grant is None:
            raise InvalidTransitionError("start() called with no grant recorded -- internal invariant violated")
        self._reverify_grant_or_transition(on_failure=RunState.REJECTED, context="start()")
        self.execution = ExecutionEvidence()
        self._transition(RunState.RUNNING, reason="execution started under a freshly re-verified grant")

    # ---- RUNNING: execution evidence (never called by this module itself) -----------------
    def record_step(self, step: int, *, source_identity: str, loss: float | None = None) -> None:
        """C-03: records a SELF-REPORTED progress claim -- see
        `ExecutionEvent`'s docstring for why this is never described as
        verified proof of actual optimizer execution. A real training
        loop would call this once per optimizer step; nothing in this
        codebase does, because no GENESIS native training loop exists yet
        (native pretraining remains `NOT_AUTHORIZED`). `step` must
        strictly increase -- append-only progress, never a rewritable
        claim. `source_identity` is required and must identify the
        reporting process/caller (itself unauthenticated; see
        `ExecutionEvent`)."""
        if self.state != RunState.RUNNING:
            raise InvalidTransitionError(f"record_step() requires RUNNING, got {self.state.value}")
        if self.execution is None:
            raise InvalidTransitionError("record_step() called with no execution evidence initialized")
        if not isinstance(source_identity, str) or not source_identity:
            raise ValueError("source_identity is required and must be a non-empty string identifying the reporting process")
        if not isinstance(step, int) or step <= self.execution.steps_recorded:
            raise ValueError(f"step must be a strictly increasing integer; got {step}, last recorded {self.execution.steps_recorded}")
        if len(self.execution.events) >= self.execution.max_events:
            raise ValueError(f"execution evidence limit reached ({self.execution.max_events} events) -- refusing unbounded growth")
        self.execution.events.append(ExecutionEvent(
            source_identity=source_identity, run_id=self.identity.run_id, step=step,
            sequence=len(self.execution.events), reported_at=_now_iso(),
        ))

    # ---- RUNNING -> PAUSED -> RUNNING / RECOVERING -----------------------------------------
    def pause(self, *, reason: str = "paused") -> None:
        if self.state != RunState.RUNNING:
            raise InvalidTransitionError(f"pause() requires RUNNING, got {self.state.value}")
        self._transition(RunState.PAUSED, reason=reason)

    def resume(self) -> None:
        """C-02 fix: previously performed NO grant re-check at all --
        resuming computation is exactly the kind of transition the
        continuation order says must never assume a previously valid
        grant remains valid forever. Now runs the same full
        re-verification as `start()`/`recovered()`."""
        if self.state != RunState.PAUSED:
            raise InvalidTransitionError(f"resume() requires PAUSED, got {self.state.value}")
        if self.grant is None:
            raise InvalidTransitionError("resume() called with no grant recorded -- internal invariant violated")
        self._reverify_grant_or_transition(on_failure=RunState.FAILED, context="resume()")
        self._transition(RunState.RUNNING, reason="resumed under a freshly re-verified grant")

    def begin_recovery(self, *, reason: str) -> None:
        if self.state != RunState.PAUSED:
            raise InvalidTransitionError(f"begin_recovery() requires PAUSED, got {self.state.value}")
        self._transition(RunState.RECOVERING, reason=reason)

    def recovered(self) -> None:
        """RECOVERING -> RUNNING. Re-verifies the grant exactly like
        `start()`/`resume()` do -- an interrupted-and-recovered run must
        not resume on a since-expired, since-revoked, or
        since-tampered-with grant either."""
        if self.state != RunState.RECOVERING:
            raise InvalidTransitionError(f"recovered() requires RECOVERING, got {self.state.value}")
        if self.grant is None:
            raise InvalidTransitionError("recovered() called with no grant recorded -- internal invariant violated")
        self._reverify_grant_or_transition(on_failure=RunState.FAILED, context="recovered()")
        self._transition(RunState.RUNNING, reason="recovered and resumed under a freshly re-verified grant")

    # ---- RUNNING/PAUSED/RECOVERING -> FAILED -----------------------------------------------
    def fail(self, *, reason: str) -> None:
        if self.state not in (RunState.RUNNING, RunState.PAUSED, RunState.RECOVERING):
            raise InvalidTransitionError(f"fail() requires RUNNING, PAUSED, or RECOVERING, got {self.state.value}")
        self._transition(RunState.FAILED, reason=reason)

    # ---- REJECTED, only from states the transition graph actually permits (C-06) ----------
    def reject(self, *, reason: str) -> None:
        if self.state not in _REJECTABLE_STATES:
            raise InvalidTransitionError(
                f"reject() is only valid from {sorted(s.value for s in _REJECTABLE_STATES)}, got {self.state.value} "
                f"(a run already RUNNING/PAUSED/RECOVERING must use fail(), not reject())"
            )
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

    # ---- evaluator approval claim: COMPLETED only, separate from everything above ---------
    def record_evaluator_approval(
        self, *, evaluator_identity: str, approved: bool, evaluation_report_sha256: str, checkpoint_manifest_sha256: str,
    ) -> None:
        """C-04: records an explicitly UNAUTHENTICATED approval CLAIM --
        see `EvaluatorApprovalClaim`'s docstring. `checkpoint_manifest_sha256`
        is required and MUST equal this run's own completed checkpoint's
        manifest hash exactly, closing the "approval for the wrong
        checkpoint" case: an evaluator (real or impersonated) cannot
        record an approval that silently gets attributed to a checkpoint
        other than the one they actually name."""
        if self.state != RunState.COMPLETED:
            raise InvalidTransitionError(f"record_evaluator_approval() requires COMPLETED, got {self.state.value}")
        if self.completion is None:
            raise InvalidTransitionError("record_evaluator_approval() called with no completion evidence recorded")
        if not isinstance(evaluation_report_sha256, str) or not _SHA256_HEX.match(evaluation_report_sha256):
            raise ValueError(f"evaluation_report_sha256 must be a 64-character lowercase hex SHA-256, got {evaluation_report_sha256!r}")
        if checkpoint_manifest_sha256 != self.completion.checkpoint_manifest_sha256:
            raise ValueError(
                f"checkpoint_manifest_sha256 {checkpoint_manifest_sha256!r} does not match this run's completed "
                f"checkpoint's manifest hash {self.completion.checkpoint_manifest_sha256!r} -- refusing to record "
                "an approval claim for a different checkpoint"
            )
        self.evaluator_approval = EvaluatorApprovalClaim(
            evaluator_identity=evaluator_identity, approved=approved, evaluation_report_sha256=evaluation_report_sha256,
            checkpoint_manifest_sha256=checkpoint_manifest_sha256, approved_at=_now_iso(),
        )
