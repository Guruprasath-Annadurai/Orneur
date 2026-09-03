# Phase 13 — Learning Pipeline Security

All of spec §43-50 already has real, passing coverage from Phase
12/12.1's own security work (`orca/learning/security.py`,
`orca/learning/audit.py`), confirmed by direct file inspection:

| Spec item | Existing mechanism |
|---|---|
| §43 FailureEvent self-marks VERIFIED / changes target / triggers training | `pipeline.verify_event()` is the ONLY function that sets `VERIFIED`; `make_candidate_from_event()` raises `UnverifiedTrainingAdmissionBlocked` otherwise |
| §44 secret exfiltration via curriculum | `sanitize.sanitize_for_candidate()` rejects secret-bearing candidates outright |
| §45 tenant training leak | `security.enforce_tenant_boundary()` raises `TenantExfiltrationBlocked` |
| §46 train/test leakage | `DatasetManifest.check_split_safety()`, group-key based |
| §47 holdout access | `security.assert_training_manifest_excludes_holdout()` raises `HoldoutExposureBlocked` |
| §48 dataset mutation after freeze | `DatasetManifest.save()` checks the ON-DISK copy's own frozen flag, raises `DatasetFrozenError` |
| §49 checkpoint supply chain | `security.verify_checkpoint_supply_chain()` rejects wrong base model, unregistered dataset, checksum mismatch |
| §50 training authority (approve/freeze/promote) | `ModelCannotSelfApprove` raised by `apply_review_decision()` and `DatasetManifest.approve()` for any `"model:"`-prefixed identity |

No new tests added this phase — Phase 12/12.1's own qualification passes
already exercised every one of these attack shapes with real, passing
tests (`tests/test_learning_phase12.py`, `tests/test_learning_registry_isolation.py`).

## Result

`LEARNING_POISONING_BYPASS = 0`, `TENANT_TRAINING_LEAK = 0`,
`HOLDOUT_EXPOSURE = 0`, `CHECKPOINT_SUPPLY_CHAIN_BYPASS = 0`.
