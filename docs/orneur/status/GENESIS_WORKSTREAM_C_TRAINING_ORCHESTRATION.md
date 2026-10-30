# GENESIS Foundation — Workstream C: Training-Orchestration State Machine

Status date: 2026-10-16. Implementation branch: `claude/genesis-workstream-c-2026-10-16`,
branched from PR #58's head at the time, commit `3a27245` ("Mission 1A --
real checkpoint provenance..."), since Workstream C depends on
`orca.genesis.training.checkpoint_integrity`'s `load_verified_training_state()`
and `CheckpointManifest`, which exist only on that branch, not yet on `main`.

**No training loop executes anywhere in this work. No optimizer step, no
GPU, no spend. Native-model training remains `NOT_AUTHORIZED`.**

## What this delivers

`orca/genesis/training/orchestration.py`: a `GenesisTrainingRun` state
machine modeling the full lifecycle a real GENESIS native-pretraining run
would go through:

```
PLANNED -> VALIDATED -> AWAITING_AUTHORIZATION -> AUTHORIZED -> RUNNING
RUNNING -> PAUSED -> RUNNING
RUNNING -> PAUSED -> RECOVERING -> RUNNING
RUNNING -> COMPLETED | FAILED
(any non-terminal state) -> REJECTED
```

Every transition not in this graph is rejected with `InvalidTransitionError`
-- there is no way to skip a state (e.g. `PLANNED` straight to `RUNNING`),
reverse a terminal state, or re-enter `AWAITING_AUTHORIZATION`/`AUTHORIZED`
once a run has moved past them.

## The authorization boundary -- the central design decision

The founder's continuation order was explicit: *"A plain JSON boolean does
not qualify as founder authorization."* This is a direct, correct challenge
to this sprint's own Mission 1A `TrainingRunRecord` (a JSON file with
`run_id`/`checkpoint_sha256`/`authorized` fields) -- which was never claimed
to be a real authorization mechanism (its own docstring states the gap), but
Workstream C's state machine must not repeat that pattern as if it were one.

**Investigation finding, not assumed**: ORNEUR already has a real,
cryptographically-sound training authorization gate,
`orca.train.authorization.authorize_training()` (pre-existing, audited,
used by the LoRA/QLoRA fine-tune path in `orca/train/finetune.py`). It
requires an Ed25519-signed authorization record, verified against a PINNED,
committed authority-key registry (the committed registry is empty today --
nothing is authorized until the founder provisions a key, a separate,
explicit action), and issues a `TrainingGrant`: a sealed object that
cannot be hand-constructed (its own `__post_init__` rejects construction
without a module-private sentinel), cannot be copied or pickled
(`__reduce__` raises), and is HMAC-tagged against a per-process secret key
so any field edited after issuance fails `verify_integrity()`.

`GenesisTrainingRun.authorize()` requires exactly this: a real
`orca.train.authorization.TrainingGrant` instance, re-verified via
`grant.verify_integrity()` at `authorize()`, again at `start()`, and again
at `recovered()` (an interrupted-and-recovered run must not resume on a
since-expired or since-tampered grant either).

### The honest limitation, stated rather than papered over

`orca.train.authorization.authorize_training()` is built around
`orca.train.config.TrainingConfig` -- LoRA rank, file-based dataset
resolution, the shape of ORNEUR's existing fine-tune path. GENESIS's
native-pretraining config (`orca.genesis.model.config.GenesisModelConfig`)
has no LoRA rank and no file-based dataset at all. **No code path in this
repository today can actually produce a legitimate `TrainingGrant` for a
GENESIS native-pretraining request.** This is marked `BLOCKED`, exactly as
instructed ("mark the system BLOCKED rather than manufacturing trust"), not
worked around. `GenesisTrainingRun` enforces the correct invariant (only a
real, sealed, tamper-evident grant moves a run to `AUTHORIZED`) while being
honest that nothing in this codebase can satisfy it for GENESIS specifically
yet. Closing this gap -- either by extending `orca.train.authorization` to
accept a GENESIS-shaped request, or by building an equally-rigorous
GENESIS-specific sibling with its own signed-record/pinned-registry scheme
-- is explicitly out of this bounded increment's scope and is the single
largest remaining dependency before Workstream C could support an actual
authorized run.

## The four required distinctions, each a separate field

| Concept | Field | Populated by | Never conflated with |
|---|---|---|---|
| Permission to execute | `self.grant` (a verified `TrainingGrant`) | `authorize()` | Execution ever having happened |
| Actual execution evidence | `self.execution` (`ExecutionEvidence.steps_recorded`, append-only, strictly increasing) | `record_step()` -- called only by a real training loop, which does not exist yet; nothing in this module calls it itself | Permission, or completion |
| Completion evidence | `self.completion` (`CompletionEvidence`) | `complete()`, only after independently re-verifying the checkpoint | A caller's unverified claim |
| Checkpoint identity | `CompletionEvidence.checkpoint_manifest_sha256` | `complete()`, read from the checkpoint's own real, hash-verified manifest | A string the caller asserts |
| Training dataset identity | `RunIdentity.dataset_digest` | `validate()`, caller-supplied but required to be a real 64-hex-char SHA-256 | Model architecture identity |
| Model architecture identity | `RunIdentity.model_architecture_version` | Constructor, defaults to `orca.genesis.model.config.ARCHITECTURE_VERSION` | Dataset identity |
| Evaluator approval | `self.evaluator_approval` (`EvaluatorApproval`) | `record_evaluator_approval()`, only after `COMPLETED` | Training authorization or completion -- an evaluator judging checkpoint quality is a different claim entirely |

## Adversarial test coverage

`tests/test_genesis_training_orchestration.py`, **29/29 passing**. Real
`TrainingGrant` objects are minted via the exact same synthetic-world
fixture (`tests/test_training_authorization_gate.py`'s `World` class)
that module's own test suite uses -- throw-away Ed25519 keys generated per
test, a throw-away registry and git repo, the gate's pin patched to point
at it. Nothing touches the real, empty, committed authority registry.

Per the continuation order's explicit list:

- **Forbidden transitions**: skipping `PLANNED` straight to `RUNNING`;
  authorizing before `request_authorization()`; restarting a `COMPLETED`
  run; resuming or rejecting a `FAILED` run; rejecting any terminal state.
- **Spoofed authorization**: a plain `bool`/`dict`/`str`/`int` claiming to
  be authorization; a hand-constructed `TrainingGrant`-shaped object
  (rejected by `TrainingGrant`'s own `__post_init__`, independently of this
  module's checks).
- **Tampering**: a real, legitimately-issued grant with a field edited via
  `object.__setattr__` after issuance -- caught by `verify_integrity()`'s
  HMAC check, both at `authorize()` time and again, independently, at
  `start()` time.
- **Interrupted execution**: the full `RUNNING -> PAUSED -> RECOVERING ->
  RUNNING` cycle, including a dedicated test that `recovered()` re-checks
  grant integrity and expiry exactly like `start()` does.
- **Replay**: the same `authorization_id` cannot authorize two different
  `GenesisTrainingRun` instances -- an additional, narrower in-process
  safety net, explicitly documented as NOT a replacement for
  `orca.train.authorization`'s own run-slot ledger (which remains the
  authoritative defense against reuse across more real training runs than
  an authorization permits).
- **Revocation**: not independently re-implemented in this module (that
  would duplicate the authority system the continuation order explicitly
  says not to duplicate) -- revocation is `orca.train.authorization`'s own
  responsibility, exercised by that module's own test suite
  (`test_revoked_key_expired_key_and_unactivated_key_are_rejected`,
  `test_revocation_list_revokes_a_grant`), re-run unmodified as part of this
  increment's regression evidence below.
- **Stale records**: a grant whose `expires_at` has already passed by the
  time `start()` or `recovered()` is called, even though it was valid at
  `authorize()` time -- a dedicated test simulates this by advancing the
  grant's `expires_at` into the past between `authorize()` and `start()`.
  A separate test confirms the authorization gate ITSELF (not this module)
  already denies an already-expired record at the source.
- **Forged completion**: `complete()` with a file that was never saved
  through `save_verified_training_state()` (no manifest, not hash-verified)
  is rejected; a genuinely valid, hash-verified checkpoint whose step does
  not match this run's own recorded execution evidence is also rejected
  (the checkpoint is real, just not the right one for this run); completing
  a run with zero recorded execution steps is rejected (nothing was ever
  actually run).
- **Unauthorized restart**: calling `start()` twice; authorizing an
  already-`AUTHORIZED` run again with the same grant.

## Regression evidence

Full local run (`/Users/ag/orca/.venv`, Python 3.11.15, torch 2.13.0):

```
tests/test_genesis_training_orchestration.py ............................. 29 passed
tests/test_training_authorization_gate.py (unmodified, re-run as-is) ...... all passing
tests/test_genesis_eval_adapter.py, test_genesis_scaling.py,
tests/test_genesis_checkpoint_integrity.py, test_genesis_model_architecture.py,
tests/test_genesis_training_primitives.py, test_genesis_tokenizer.py,
tests/test_genesis_audit016_remediation.py, test_genesis_eval_v1.py ....... all passing

== 349 passed in 93.62s ==
```

`orca/train/authorization.py` was NOT modified -- Workstream C integrates
with it by import only, confirmed by this full re-run of its own test file
passing unchanged.

CI on this exact commit: pending at the time of writing -- will be updated
with the real run link once pushed.

## Dependency on PR #58

This branch inherits PR #58's own dependency on PR #55 (Sprint 1, not yet
merged to `main`). Workstream C additionally depends on PR #58's own
Workstream B (`checkpoint_integrity.py`) and Mission 1A
(`state_dict_fingerprint`, though not directly used here) -- it cannot be
merged ahead of or independently of PR #58's resolution.

## What remains (explicit statuses)

- **`BLOCKED`**: producing an actual, legitimate `TrainingGrant` for a
  GENESIS native-pretraining request. `orca.train.authorization.authorize_training()`
  is shaped for the LoRA/QLoRA fine-tune path; no code path adapts it (or
  an equally-rigorous equivalent) for `GenesisModelConfig`. This is the
  single blocking dependency before any GENESIS run could legitimately
  reach `AUTHORIZED`.
- **`NOT_IMPLEMENTED`**: a real training loop that would call
  `record_step()` -- intentionally out of scope; GENESIS pretraining
  remains `NOT_AUTHORIZED`.
- **`NOT_IMPLEMENTED`**: persistence/reload of a `GenesisTrainingRun`
  across process restarts (the directive's "stale records"/"interrupted
  execution" cases are tested within one process; a real deployment would
  need to serialize run state to disk and re-verify the grant on reload --
  not attempted in this bounded increment).
- **GENESIS Workstream A** (dataset pipeline foundations) and
  **Workstream F** (training governance package) remain `NOT_IMPLEMENTED`
  -- deferred per the founder's own instruction to complete Workstream C
  properly before advancing further, not attempted in this increment.
- **NOVUS/AETERNUM native-architecture prototypes**: `NOT_IMPLEMENTED` --
  not started in this increment.

## Verdict

**`READY_FOR_INDEPENDENT_AUDIT`** for Workstream C's state machine and its
adversarial test coverage, scoped exactly as described above. The
authorization-boundary integration gap for GENESIS specifically is
`BLOCKED`, stated plainly rather than worked around. No training, GPU
provisioning, spend, or merge to `main` occurred or is requested.
