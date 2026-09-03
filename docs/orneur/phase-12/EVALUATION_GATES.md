# Phase 12 — Evaluation & Promotion Gates

## Before/after evaluation (spec §32)

Every candidate checkpoint must run baseline + post-training eval via the
existing `orca.registry.evaluation_registry.EvaluationReport` +
`evaluate_promotion()` — unmodified Phase 1 code, reused directly.
`evaluate_promotion()` already treats a missing (`UNMEASURED`) metric as a
gate failure, never as a pass (spec §34's "do not overclaim").

## Regression gates (spec §33)

`evaluate_promotion()`'s `required_metrics` dict already checks FOUR
independent metrics (`eval_accuracy`, `jailbreak_block_rate`,
`bias_flag_rate`, `domain_eval`) against `PERSONA_CLAIM_THRESHOLDS` — a
gain in one does not mask a regression in another, because every metric
is checked independently and ANY failing metric sets
`pass_fail_status=NOT_PROMOTABLE`. Verified directly:
`test_eval_regression_blocks_promotion` constructs a report with a
regressed `jailbreak_block_rate` (50.0, below the required threshold)
alongside strong `eval_accuracy`/`domain_eval`, and confirms the overall
result is still `NOT_PROMOTABLE`.

## Significance (spec §34)

This phase does not run a live model-accuracy comparison (no controlled
training experiment executed — see `TRAINING_RUNS.md`), so there are no
sample-size or confidence-interval claims to make. `EvaluationReport`'s
existing `metrics` dict stores raw measured values, never a rounded or
inflated summary; a future report with a small holdout should state its
sample count explicitly in `failure_reasons`/documentation, per spec —
this is a requirement on FUTURE report authors, not new code Phase 12
adds (the existing dataclass already has room for it via `metrics`).

## Promotion invariant (spec §55, §68, §31)

`orca.registry.model_registry.ModelRegistry.promote()` (Phase 1,
unmodified) is the ONLY function that sets `LifecycleState.PRODUCTION`,
and it refuses outright (`PromotionDenied`) unless passed an
`EvaluationReport` whose `pass_fail_status == "PROMOTABLE"`. Training
completion produces, at most, `LifecycleState.TRAINED` or `CANDIDATE` —
never `PRODUCTION` directly. Verified structurally:
`test_training_completion_does_not_promote` confirms `TrainingRunManifest`
has no code path touching `ModelRegistry` at all, and
`LifecycleState.TRAINED != LifecycleState.PRODUCTION`.

## Rollback (spec §56)

`ModelRegistry.rollback_target()` (Phase 1, unmodified) remains usable —
Phase 12 adds no new promotion path and therefore cannot have broken this
lineage; confirmed by the full deterministic suite (`test_registry_*`,
`test_model_registry_*`) staying green throughout this phase.
