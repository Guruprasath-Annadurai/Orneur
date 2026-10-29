# FOUNDATION-02 Authorization Assurance

**Tip context:** `52e74597ae0185bbbddcd45a70e86b006955229e`  
**Verdict:** Fail-closed for ORNEUR training entry points. **NO-GO** for real training.

## Surfaces audited

| Surface | Gate |
|---|---|
| `orca.train.finetune.train` / `_train_impl` | `authorize_training()` + grant integrity |
| `orca.train.cloud.CloudTrainer.run` | authorize before SSH/upload |
| CLI `orneur train run|nano|core|ultra|cloud` | exit 2 on denial |
| GENESIS native `authorize_native_pretraining` | separate signing domain; empty registry + empty ledger |
| Readiness gate | reports blockers; never authorizes execution |

## Negative properties covered by tests

Missing/invalid/expired/revoked grants, stale SHA, wrong family/dataset bindings
(where applicable), grant tampering, env-var bypass attempts, concurrent budget
exhaustion, audit-chain tamper detection (residual: tail truncation xfail).

## Residuals (honest)

1. Same-process attackers can edit source / call internals.
2. Operator scripts and offline notebooks are outside the gate.
3. Audit tail truncation remains a documented residual (xfail).
4. Empty authority registries mean **nothing can authorize** until founder provisioning.
