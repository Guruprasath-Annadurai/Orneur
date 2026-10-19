# ORNEUR GENESIS CHECKPOINT SECURITY — CROSS-RUN AUTHORITY AUDIT REPORT (G02)
## Checkpoint Scope Limitation, Cross-Run Restore & Format Migration

**Document ID:** AUDIT-P0-G02-V2 (Corrected)  
**Severity:** CRITICAL / P0 SECURITY DEFECT  
**Target:** `orca/genesis/training/resumable_checkpoint.py`  
**Classification:** Cross-Run Checkpoint Hijacking / Authority Bypass  
**Test Suite:** `tests/test_genesis_checkpoint_adversarial_regression.py`  
**Tests:** `test_g02_*` (Same-run PASSED, Demonstration PASSED, Fix-Acceptance XFAIL)  
**Lead Auditor:** Antigravity / Gemini Engineering & Independent Audit Agent  

---

## 1. Vulnerability Summary

In ORNEUR GENESIS, training runs are strictly partitioned by founder execution grants and unique `run_id` identifiers.

Our audit verified that **`run_id` is omitted from the checkpoint manifest's HMAC-tagged fields**. 

Consequently, Run B (`run_id="RUN_BETA"`) can restore a checkpoint produced by Run A (`run_id="RUN_ALPHA"`) without founder migration authorization, provided Run B shares the same model configuration, dataset identity, and integrity key. Because Run B's monotonic anti-rollback ledger is at step 0, it trivially accepts Run A's step.

---

## 2. Ordinary Same-Run Recovery vs. Cross-Run Migration

The system must clearly distinguish between two fundamentally different operations:

1. **Ordinary Same-Run Restoration (Authorized & Legitimate):**
   - Run A crashes or pauses at step 100.
   - Run A resumes under the same `run_id="RUN_ALPHA"` and the same execution grant.
   - Verified by `test_g02_ordinary_same_run_restore_succeeds` (PASS).
2. **Cross-Run Migration (Requires Explicit Migration Authorization):**
   - Resuming Run A's checkpoint under Run B (`run_id="RUN_BETA"`).
   - This crosses authority boundaries and MUST be rejected unless accompanied by an explicit, founder-authorized migration grant.
   - Demonstrated vulnerable on current HEAD by `test_g02_vulnerability_demonstration_cross_run_restore_accepted_without_migration` (PASS on vulnerability reproduction).

---

## 3. Checkpoint Format Migration & Backward Compatibility Evaluation

Before recommending a version change, format migration compatibility must be evaluated:

### Option A: Schema Version Bump to V2 (`genesis-resumable-checkpoint-v2`)
- Add `origin_run_id: str` to `ResumableManifest`.
- Include `manifest.origin_run_id` in the HMAC tag payload.
- In `restore_resumable_checkpoint`:
  - If `manifest.schema_version == "genesis-resumable-checkpoint-v2"`: assert `manifest.origin_run_id == run_id`.
  - If `manifest.schema_version == "genesis-resumable-checkpoint-v1"` (legacy): emit a deprecation warning and permit same-run restore only if legacy compatibility flag is explicitly enabled.

### Option B: Backward-Compatible Optional Field
- Allow `origin_run_id: str | None = None`.
- For new saves, populate `origin_run_id = run_id` and include in HMAC tag if present.

**Recommendation:** Option A (V2 schema with explicit fallback) is the cleanest, most tamper-evident approach. It avoids ambiguity and guarantees that all newly generated checkpoints are cryptographically bound to their origin run.

---

## 4. Fix-Acceptance Test Gate

- `test_g02_fix_acceptance_cross_run_restore_without_migration_denied` has been added with `@pytest.mark.xfail(strict=True)`.
- It asserts that restoring Run A's checkpoint into Run B without migration authorization is rejected.
- It currently fails (XFAIL) on the vulnerable implementation and will turn to PASS once Claude implements run binding.
