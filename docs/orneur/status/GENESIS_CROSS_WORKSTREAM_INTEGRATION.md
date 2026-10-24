# GENESIS Foundation Sprint 2 — Cross-Workstream Integration (Mission F6, second half)

Status date: 2026-10-16. Branch:
`claude/genesis-cross-workstream-integration-2026-10-16`. This closes the
one item Workstream F's own report (`GENESIS_WORKSTREAM_F_GOVERNANCE_IMPLEMENTATION.md`)
explicitly marked `NOT_IMPLEMENTED`: a real, cross-branch end-to-end test
binding Workstream A, C, and F's actual code together.

**All parent branches remain draft, unaccepted, and unmerged to `main`.
This branch must never be merged on its own authority — it exists solely
to prove the code genuinely interoperates.** No training, GPU use,
model-weight modification, real signed grant, or merge occurred.

## Exact ancestry

```
88ac6da  (PR #55, Sprint 1 -- merge-base of all three workstreams)
   |
   +-- 3a27245  (PR #58, Workstream B/D + Mission 1A -- draft, independent
   |             Audit #017 successor verdict: CONDITIONAL_REMEDIATION_REQUIRED)
   |      |
   |      +-- ff9175f  (PR #61, Workstream C -- draft, CI 18/18 passing,
   |                     independent review pending)
   |
   +-- a1fab6e  (PR #63, Workstream A -- draft, CI 18/18 passing)
   |
   +-- 6cd6127  (PR #64, Workstream F -- draft, CI passing except one
                  transient infra flake on the push-triggered run, see below)

claude/genesis-cross-workstream-integration-2026-10-16:
  6cd6127 (start: Workstream F's head)
    --merge--> ff9175f (brings in PR #61, transitively PR #58)
    --merge--> a1fab6e (brings in PR #63)
    + this branch's own new test file
```

Both merges (`ff9175f` and `a1fab6e` into the Workstream F branch) were
clean -- no code conflicts; a single conflict in `.github/workflows/test.yml`
(both parent branches had appended their own test files to the same
pytest invocation line) was resolved by combining both lists.

**PR #58's independent-audit status is the one unresolved item among the
four ancestors** -- its Audit #017 successor verdict remains
`CONDITIONAL_REMEDIATION_REQUIRED`. This integration branch inherits that
status unchanged; nothing here resolves or bypasses it, and the checkpoint/
eval-adapter code this branch exercises (via `GenesisTrainingRun`'s own
dependency on `orca.genesis.training.checkpoint_integrity`) remains subject
to that same open finding.

## What this proves, concretely

`tests/test_genesis_cross_workstream_integration.py`, **7/7 passing**, all
using REAL objects from all three workstreams (no stubs, no mocks of the
production classes themselves):

1. **`test_a_real_dataset_manifest_content_digest_passes_governance_binding`**
   -- a real `GenesisDatasetManifest` (Workstream A), independently
   re-verified against its own source records
   (`verify_against_records()`), has its real `manifest_id` and
   `source_content_digest` accepted by Workstream F's
   `authorize_native_pretraining()` -- the direct Mission F3 proof that
   dataset identity flows from verified source contents into the
   authorization layer, not from an arbitrary caller string.
2. **`test_a_tampered_dataset_content_digest_is_rejected_by_governance`** --
   a signed record claiming a forged `dataset_content_digest` (not
   matching the real manifest) is rejected (`WRONG_DATASET_CONTENT_DIGEST`),
   even though the accompanying request still carries the genuine digest.
3. **`test_a_manifest_tampered_after_the_fact_is_caught_before_governance_ever_sees_it`**
   -- Workstream A's own `verify_against_records()` independently catches
   a manifest whose underlying records were substituted, demonstrating the
   two workstreams' trust boundaries are complementary (A catches content
   tampering; F catches identity-binding tampering), not redundant.
4. **`test_a_native_pretraining_grant_cannot_authorize_a_genesis_training_run`**
   -- a real `NativePretrainingGrant` (Workstream F) cannot satisfy
   `GenesisTrainingRun.authorize()` (Workstream C), which requires a real
   `orca.train.authorization.TrainingGrant` specifically -- the two grant
   types are structurally, not just policy-, incompatible.
5. **`test_a_lora_training_grant_still_cannot_authorize_a_genesis_training_run`**
   -- re-confirms Workstream C's own C-01 fix still holds with Workstream
   F's new layer present: a real, legitimately-issued LoRA-shaped
   `TrainingGrant` is still rejected by `GenesisTrainingRun`.
6. **`test_authorizing_a_genesis_training_run_does_not_itself_authorize_native_pretraining`**
   -- confirms the converse: nothing about a `GenesisTrainingRun`'s own
   state gives it standing to satisfy Workstream F's authorization gate,
   which independently and unconditionally still requires the real,
   currently-empty founder-acceptance ledger.
7. **`test_full_real_object_chain_dataset_manifest_to_training_run_to_native_grant`**
   -- the complete positive chain: one real manifest's identity flows
   correctly into both a `GenesisTrainingRun` and a `NativePretrainingGrant`
   independently, confirming identity AGREEMENT without implying
   INTERCHANGEABILITY (the grant still cannot authorize the run).

## Regression evidence

Full local run (`/Users/ag/orca/.venv`, Python 3.11.15, torch 2.13.0):

```
tests/test_genesis_cross_workstream_integration.py ....... 7 passed
tests/test_genesis_data_manifest.py, test_genesis_data_pipeline.py,
tests/test_genesis_data_contamination.py, test_genesis_data_multilingual.py,
tests/test_genesis_training_orchestration.py, test_genesis_governance_authorization.py,
tests/test_genesis_checkpoint_integrity.py, test_genesis_eval_adapter.py, test_genesis_scaling.py,
tests/test_genesis_model_architecture.py, test_genesis_training_primitives.py, test_genesis_tokenizer.py,
tests/test_genesis_audit016_remediation.py, test_genesis_eval_v1.py,
tests/test_training_authorization_gate.py, test_acceptance_engine.py (all pre-existing, unmodified) ... all passing

== 514 passed in 83.36s ==
```

No existing test's assertions were modified; the only non-test-file change
beyond the new integration test is the mechanical merge-conflict resolution
in `.github/workflows/test.yml` (combining both parent branches' own
already-reviewed test-file lists into one).

CI on this exact commit: pending at time of writing — will be updated once
pushed and observed.

## Known limitations (unchanged from each workstream's own report)

- PR #58's `CONDITIONAL_REMEDIATION_REQUIRED` status is inherited
  unresolved — this branch does not touch or re-litigate it.
- Workstream F's own documented limitations (in-process-only nonce/replay
  guards, the founder-acceptance ledger's current empty state, no real
  signing key provisioned) all still apply unchanged here.
- Workstream A's A-07 through A-11 findings (posted to PR #63 for
  independent review) are likewise unchanged and not addressed by this
  integration work.
- This integration branch is NOT a replacement for independent review of
  any of its four ancestors — it proves interoperability, not correctness
  or security of any individual component beyond what each workstream's
  own report already claims.

## Verdict

**`READY_FOR_INDEPENDENT_AUDIT`** for the cross-workstream integration
specifically. This branch must not be merged to `main`; all four ancestor
PRs remain independently unaccepted, and PR #58 in particular carries an
unresolved `CONDITIONAL_REMEDIATION_REQUIRED` verdict. Native-model
training remains `NO-GO`.
