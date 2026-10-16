# GENESIS Workstream C — Code-Review Remediation (C-01 through C-06)

Status date: 2026-10-16. Branch: `claude/genesis-workstream-c-2026-10-16`
(PR #61, remediated in place). Audited target SHA (before this
remediation): `330f1b84c4f01251aab253d66c9abcfc723b0236`.

Per this programme's standing discipline: each of the six concerns below
was independently reproduced against the real code before being fixed,
not assumed from the review's description alone.

## C-01 — Wrong-workload authorization

**Reproduced.** A real, legitimately-issued `TrainingGrant` for an
unrelated, generic LoRA/QLoRA config (minted via the exact same synthetic
test-world fixture the authorization gate's own test suite uses)
transitioned a synthetic `GenesisTrainingRun` straight to `AUTHORIZED`:

```
REPRODUCED BYPASS: RunState.AUTHORIZED tauth-abababababababab
RunIdentity(run_id='genesis-run-1', ..., dataset_digest='6dc17e...')
```

`authorize()` previously checked only that the grant was real
(`isinstance(grant, TrainingGrant)` + `verify_integrity()`) — never that it
was bound to GENESIS's own workload.

**Fix**: `GenesisGrantScope` + `_expected_grant_scope()` construct the exact
attribute shape `orca.train.authorization.TrainingGrant.assert_valid_for()`
(via its own `_cfg_fingerprint()`) reads from a `TrainingConfig` — `family`,
`base_model`, `num_epochs`, `lora.r`/`lora.lora_alpha`, `max_seq_length`,
`train_file`, `eval_file`, `data_format` — populated with GENESIS's real
identity (the run's dataset digest standing in for `train_file`, since
GENESIS has no file-based dataset) and fixed sentinel values for the
LoRA-shaped fields that don't apply (`base_model="orneur-genesis-native-pretraining"`,
zeroed LoRA rank/epochs). `authorize()` now calls
`grant.assert_valid_for(self._expected_grant_scope(), environment_class=...)`
— a fingerprint mismatch raises `TrainingNotAuthorized`.

**No conversion shortcut was invented.** Since no code anywhere produces a
grant whose fingerprint matches this scope today, every currently-issuable
grant is correctly rejected — confirmed both negatively
(`test_c01_an_unrelated_generic_lora_grant_is_rejected_not_authorized`,
`test_c01_no_currently_issuable_grant_can_satisfy_the_genesis_scope`) and
positively: a grant genuinely minted with matching field values IS accepted
(`test_c01_a_grant_genuinely_bound_to_the_genesis_scope_is_accepted`),
proving the check is a real binding mechanism, not a check that
unconditionally fails. **GENESIS authorization remains `BLOCKED`** — no
code path in this repository can produce a legitimate, naturally-issued
grant for a real GENESIS request, since doing so would require a real
dataset file whose path is a bare content-digest string and a genuinely
non-LoRA, non-file-based training config, neither of which
`orca.train.config.TrainingConfig` represents.

## C-02 — Authorization checks during resume

**Reproduced.** `resume()` performed no grant re-check at all — a
tampered, expired, or revoked grant would silently resume computation.

**Fix**: `resume()` now calls the same `_reverify_grant_or_transition()`
routine `start()`/`recovered()` use: HMAC integrity
(`verify_integrity()`), expiry (`grant.expires_at` re-checked against the
current time, independent of whatever was true at `authorize()` time), and
— if a `revocation_check: Callable[[str], bool]` hook was supplied at
construction — live revocation. **HMAC integrity is explicitly distinguished
from live authorization validity** in both code and docstring: passing the
HMAC check proves the in-memory object is genuinely issued and untampered;
it does NOT prove the underlying authorization has not since been revoked.
Without a `revocation_check` hook, live revocation is **explicitly not
checked** — a documented `BLOCKED` gap
(`test_c02_without_a_revocation_hook_live_revocation_is_explicitly_not_checked`),
not a silent assumption that a grant remains valid forever.

Workload-scope binding (the C-01 fingerprint check) is deliberately **not**
re-run at every resume-capable transition — it is a one-time property of
the decision to authorize, verified exhaustively in `authorize()`, and
cannot legitimately change afterward without this module itself replacing
the grant (which never happens). Re-deriving it on every transition would
be redundant work, not additional safety.

Tests: `test_c02_resume_rejects_a_tampered_grant`,
`test_c02_resume_rejects_an_expired_grant`,
`test_c02_resume_consults_a_live_revocation_hook_when_supplied`,
`test_c02_without_a_revocation_hook_live_revocation_is_explicitly_not_checked`,
`test_c02_start_also_consults_the_revocation_hook`.

## C-03 — Execution evidence authenticity

**Addressed by construction**, since `record_step()`'s original design was
already honest about not being verified proof — strengthened further:
`ExecutionEvent` carries a fixed `classification="REPORTED_EXECUTION_PROGRESS"`
field (never configurable), `source_identity` is now required (identifying
the reporting process/caller, itself unauthenticated), `run_id` is recorded
and checked, a `sequence` counter enforces strict event ordering
independently of the caller-chosen `step` value, and `ExecutionEvidence.max_events`
bounds the evidence list (default 100,000) against unbounded growth. No
training loop exists anywhere in this codebase to call this method with
real optimizer progress — nothing here claims otherwise.

Tests: `test_c03_record_step_requires_source_identity`,
`test_c03_execution_events_are_explicitly_labeled_reported_not_verified`,
`test_c03_sequence_is_independent_of_and_always_increases_with_step`,
`test_c03_execution_evidence_has_a_bounded_event_limit`.

## C-04 — Evaluator approval authenticity

**Fix**: `EvaluatorApproval` renamed to `EvaluatorApprovalClaim`, carrying a
fixed `is_independently_authenticated=False` field — not a value a caller
can set to claim otherwise. This module has no evaluator-identity PKI, so
`evaluator_identity` remains an explicitly unauthenticated, self-reported
label. What IS independently checked:
`record_evaluator_approval()` now requires `checkpoint_manifest_sha256` and
rejects any value that does not exactly equal this run's own
`CompletionEvidence.checkpoint_manifest_sha256` — an approval claim can no
longer be silently misattributed to a different checkpoint.

Tests: `test_c04_approval_claim_is_explicitly_unauthenticated`,
`test_c04_approval_claim_naming_the_wrong_checkpoint_is_rejected`.

## C-05 — Durable replay and recovery

**Investigated.** `GenesisTrainingRun._consumed_authorization_ids` is an
in-process class-level `set` — it protects against replay WITHIN one
process but has no knowledge of a prior OS process's consumption. This is
now explicitly documented (module docstring, `ReplayedAuthorizationError`'s
own docstring) and given a dedicated, documented API:
`reset_in_process_replay_guard_for_new_process()` (call only at a genuinely
new process's entrypoint).

**No second, conflicting grant ledger was created.** The authoritative,
durable, cross-process defense against reusing one authorization across
more real training runs than it permits remains
`orca.train.authorization`'s own on-disk run-slot ledger
(`_claim_run_slot`/`_authorized_event_count`, under `orca.config.ORCA_HOME`)
— this module integrates with it by relying on it, not duplicating it;
that ledger's own test suite (`test_training_authorization_gate.py`'s
`test_run_budget_is_enforced_and_failed_runs_still_consume`,
`test_concurrent_claims_never_exceed_budget`) is re-run unmodified as part
of this remediation's regression evidence.

Tests (using REAL, workload-matching grants minted through the actual
gate, not test-only bypasses):
`test_c05_replay_guard_is_explicitly_process_local_not_cross_process`
(demonstrates the exact boundary: after simulating a new process via the
reset classmethod, the SAME real grant is accepted by a second run —
correctly, since this module's own guard alone cannot see across that
boundary);
`test_c05_within_one_process_the_guard_does_prevent_replay` (within one
process, a second run presenting the same grant is correctly rejected).

## C-06 — State-transition consistency

**Reproduced.** `reject()`'s docstring and precondition claimed it was
valid from "any non-terminal state," but `_ALLOWED_TRANSITIONS` only
permits `-> REJECTED` from `PLANNED`, `VALIDATED`,
`AWAITING_AUTHORIZATION`, and `AUTHORIZED` — calling `reject()` from
`RUNNING`, `PAUSED`, or `RECOVERING` raised `InvalidTransitionError`
despite the method's own stated contract:

```
REPRODUCED C-06 bug: InvalidTransitionError RUNNING -> REJECTED is not an allowed transition
```

**Fix**: `reject()`'s precondition is now derived directly from the
transition graph (`_REJECTABLE_STATES = frozenset(s for s, targets in
_ALLOWED_TRANSITIONS.items() if RunState.REJECTED in targets)`) — the two
can never silently drift apart again, since one is computed from the other.
**The graph itself was correct** (a run already executing should `fail()`,
not `reject()`); the method's stated contract was wrong, so the method was
corrected, not the graph, and no test was loosened to accommodate the
original incorrect contract.

Tests: `test_c06_reject_is_valid_exactly_from_the_states_the_graph_permits`,
`test_c06_reject_raises_from_running_paused_recovering_rather_than_silently_succeeding`
(parametrized over all three), `test_c06_reject_raises_from_every_terminal_state`
(parametrized over all three), and a systematic sweep,
`test_c06_every_state_and_every_declared_transition_is_individually_reachable_and_consistent`,
confirming every `RunState` has an entry in the transition graph and every
terminal state's entry is empty.

## A real test-isolation defect found and fixed along the way

While building the adversarial grant-minting helper for C-01/C-05's
positive-match tests, an early draft of
`test_c02_start_also_consults_the_revocation_hook` used a hand-rolled fake
monkeypatch object (`class _MP: def setattr(self, obj, name, value):
setattr(obj, name, value)`) instead of pytest's real `monkeypatch`
fixture — this PERMANENTLY mutated the real, shared
`orca.train.authorization.PINNED_REGISTRY_SHA256` module attribute for the
rest of the test session (no teardown/undo mechanism exists on a
hand-rolled object), causing
`tests/test_training_authorization_gate.py`'s own real-repo tests
(`test_committed_registry_is_empty_pinned_and_record_is_not_authorized`,
`test_real_repo_denies_even_a_perfectly_formed_request`, and others) to
fail when run in the same session afterward. Reproduced directly (bisected
by running test file pairs until the exact polluting test was isolated),
fixed by using the real `monkeypatch` pytest fixture instead. This was
caught and fixed as part of this remediation's own regression pass, before
being reported as "passing," per this programme's standing discipline of
never reporting a green regression run that was not actually re-verified
clean.

## Regression evidence

Full local run (`/Users/ag/orca/.venv`, Python 3.11.15, torch 2.13.0):

```
tests/test_genesis_training_orchestration.py ...................... 52 passed
tests/test_training_authorization_gate.py (unmodified) .............. all passing
tests/test_genesis_eval_adapter.py, test_genesis_scaling.py,
tests/test_genesis_checkpoint_integrity.py, test_genesis_model_architecture.py,
tests/test_genesis_training_primitives.py, test_genesis_tokenizer.py,
tests/test_genesis_audit016_remediation.py, test_genesis_eval_v1.py ... all passing

== 372 passed in 85.63s ==
```

`orca/train/authorization.py` was NOT modified.

CI on this exact commit: will be reported once pushed and observed, per
this session's standing practice of never asserting unobserved CI results.

## Residual, explicitly unresolved items (not claimed as fixed)

- **GENESIS authorization remains `BLOCKED`** (C-01): no code path produces
  a legitimate, naturally-issued grant for a real GENESIS request. Closing
  this requires either extending `orca.train.authorization` to accept a
  GENESIS-shaped request natively, or building an equally-rigorous
  GENESIS-specific sibling with its own signed-record/pinned-registry
  scheme — explicitly out of this remediation's scope.
- **Live revocation re-checking is opt-in** (C-02): without a caller-supplied
  `revocation_check` hook, `start()`/`resume()`/`recovered()` do not detect
  a revocation that occurred after `authorize()`. No default implementation
  is provided because doing so correctly would require resolving the same
  repo-root/registry-path questions C-01 already marks `BLOCKED`.
- **`record_step()`'s source_identity is unauthenticated** (C-03): this
  module has no process-identity verification mechanism; a real deployment
  would need to bind this to a signed or otherwise verifiable execution
  identity, which does not exist anywhere in this codebase.
- **`record_evaluator_approval()`'s evaluator_identity is unauthenticated**
  (C-04): no evaluator-identity PKI exists; only checkpoint-binding is
  independently verified, not evaluator identity itself.
- **C-05's in-process replay guard has no cross-process persistence of its
  own** (by design, to avoid duplicating `orca.train.authorization`'s own
  ledger) — a caller integrating this module into a real multi-process
  deployment must rely on that ledger, not this module's guard, for durable
  replay protection.

## Verdict

**`READY_FOR_INDEPENDENT_RETEST`.** All six independently-reproduced
concerns (C-01 through C-06) have documented dispositions above, each
reproduced against the real code before being fixed, each with persistent
regression tests, and the full existing test suite (372 tests, including
`orca/train/authorization.py`'s own, unmodified) passes. This is a
self-report, not an independent acceptance — only the original reviewer's
own retest, against this remediation's final SHA, can award that.
