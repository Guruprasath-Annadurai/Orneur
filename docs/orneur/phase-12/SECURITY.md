# Phase 12 — Security

Every guard below is real code in `orca/learning/security.py` (plus two
in `orca/learning/contracts.py` and `orca/registry/dataset_manifest.py`),
each with a direct test in `tests/test_learning_phase12.py`.

## §63 — Data poisoning

`scan_for_poisoning_attempt(text)` pattern-matches the spec's own listed
phrasings ("mark this answer correct", "train on this secret", "ignore
the review", "promote this checkpoint", "this is verified") plus obvious
variants ("approve this for training", "skip the review", "you are now
the reviewer"). Pattern-based, floor-not-ceiling, same honest posture as
`orca/train/redteam.py`. `assert_no_poisoning_attempt()` raises
`DataPoisoningAttemptDetected` — tested:
`test_poisoning_patterns_detected_but_not_acted_on`.

## §64 — Tenant data exfiltration

`enforce_tenant_boundary()` — see `PRIVACY_AND_SANITIZATION.md`. Raises
`TenantExfiltrationBlocked` for tenant-private → global, and for
cross-tenant local training.

## §65 — Training prompt injection

`assert_source_text_is_inert(candidate, attempted_field_changes)` — a
fixed, closed set of "protected fields" (`review_state`,
`training_destination`, `target_model_family`, `dedupe_fingerprint`) that
a transformation step is never allowed to change based on parsing the
candidate's OWN source text. Raises `TrainingPromptInjectionBlocked` if
violated. This is a narrow, explicit guard — it does not claim to defend
against every possible injection vector, only the specific claim spec §65
makes: source text cannot change compiler policy, grant approval, change
target model, alter dataset split, or trigger training.

## §66 — Checkpoint supply chain

`verify_checkpoint_supply_chain(checkpoint, expected_base_model,
expected_dataset_ids)` rejects: wrong `base_model`, any
`dataset_manifest_ids` not in the expected registered set, zero
registered datasets, and checksum mismatch (via the existing
`CheckpointRecord.verify_integrity()`, which already raises
`CorruptCheckpointError`). Tested with three real scenarios (wrong base
model, unregistered dataset, and a valid-checkpoint pass-through) in
`tests/test_learning_phase12.py`.

## §67 — Eval gaming

`assert_training_manifest_excludes_holdout(training_dataset_ids,
holdout_dataset_id)` raises `HoldoutExposureBlocked` if the holdout's
`dataset_id` ever appears among a training run's referenced dataset IDs.

## §68 — Automatic promotion

`TRAINING_COMPLETE ≠ PROMOTABLE ≠ PROMOTED` is enforced by THREE
separate, pre-existing (Phase 1) functions Phase 12 never bypasses:
`TrainingRunManifest.mark_complete()` (sets `TRAINING_COMPLETE`-equivalent
state, touches nothing else), `evaluate_promotion()` (sets
`PROMOTABLE`/`NOT_PROMOTABLE` from measured metrics only),
`ModelRegistry.promote()` (the only path to `PRODUCTION`, requires a
`PROMOTABLE` report). No code added this phase creates a fourth path.

## §69 — Model writes

`ModelCannotSelfApprove` — raised by `apply_review_decision()` (candidate
review) and `DatasetManifest.approve()` (dataset approval) whenever the
acting identity string starts with `"model:"`. Both are the ONLY
functions in this codebase that perform their respective state
transition, so this check cannot be bypassed by calling a different
function that skips it.

## §70-71 — Retention / right-to-delete

`orca.learning.pipeline.revoke_source_and_invalidate(candidate)` moves a
candidate to `REJECTED`/`DISALLOWED` when its source is deleted/revoked —
the candidate RECORD is retained (for the audit trail spec §61 requires)
but its eligibility is permanently withdrawn, never silently left
training-eligible.

## Audit counters (spec §90)

`orca.learning.audit.AUDIT` — 15 named counters
(`orca/learning/audit.py::COUNTER_NAMES`), incremented at real detection
points in `pipeline.py` (`SECRET_IN_CURRICULUM`,
`UNVERIFIED_FAILURE_TRAINING_ADMISSION`,
`TENANT_DATA_GLOBAL_TRAINING_LEAK`). The remaining counters represent
violations this phase's guards are designed to make structurally
impossible (e.g. `AUTOMATIC_MODEL_PROMOTION`, `MODEL_SELF_APPROVAL`) —
their value is 0 because the corresponding code path does not exist, not
merely because no test happened to trigger it; this is verified by the
security tests asserting the guard RAISES rather than silently
succeeding. See the final Phase 12 report for the full 15-counter table.
