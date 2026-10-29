# FOUNDATION-02 Authorization Assurance

**Parent tip:** `b384348fa3bc789585bf69d81a772c8a4d75d493`  
**Verdict:** Fail-closed for ORNEUR training entry points. **NO-GO** for real training.

## Surfaces audited

| Surface | Gate |
|---|---|
| `orca.train.finetune.train` / `_train_impl` | `authorize_training()` + grant integrity |
| `orca.train.cloud.CloudTrainer.run` | authorize before SSH/upload |
| CLI `orneur train run|nano|core|ultra|cloud` | exit 2 on denial |
| GENESIS native `authorize_native_pretraining` | separate signing domain; empty registry + empty ledger |
| Readiness gate | reports blockers; never authorizes execution |

## Residuals (honest)

See `FOUNDATION_02_AUDIT_TAIL_RESIDUAL.md` (P2).  
`test_truncating_the_audit_log_tail_is_detected` remains `@pytest.mark.xfail(strict=True)` — **not a pass**.
