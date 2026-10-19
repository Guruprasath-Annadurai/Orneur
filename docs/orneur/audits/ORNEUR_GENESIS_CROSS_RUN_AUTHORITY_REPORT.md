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

## 3. Checkpoint Format Migration & Contract Decision

Before implementing the repair, the engine contract must resolve two architectural decisions:

### A. Schema Versioning & HMAC Tag Scope
- **Schema Bump:** Bump `RESUMABLE_SCHEMA_VERSION` from `"genesis-resumable-checkpoint-v1"` to `"genesis-resumable-checkpoint-v2"`.
- **Field Binding:** Add `origin_run_id: str` to `ResumableManifest`. Include `manifest.origin_run_id` in the HMAC tag computation payload alongside `dataset_identity`, `config_fingerprint`, and sampler state.
- **Verification Rule:** `restore_resumable_checkpoint(path=..., run_id=run_id, ...)` checks:
  ```python
  if manifest.origin_run_id != run_id and not migration_grant:
      raise PermissionError(
          f"Cross-run restore rejected: checkpoint originated from run {manifest.origin_run_id!r}, "
          f"but caller run is {run_id!r}. An explicit founder migration grant is required."
      )
  ```
  If an attacker modifies `origin_run_id` in the JSON manifest, HMAC tag verification fails, raising `ResumableManifestTamperedError`.
- **Legacy Fallback Contract:** If `manifest.schema_version == "genesis-resumable-checkpoint-v1"` (missing `origin_run_id`), `restore_resumable_checkpoint` must require an explicit opt-in flag (`allow_legacy_v1_checkpoints=True`) or treat it as unvetted migration.

### B. Intentional Cross-Run Migration Contract
When a team legitimately needs to initialize Run B from Run A's checkpoint (e.g., branching an experiment or starting an authorized fine-tuning phase):
- An unauthenticated cross-run restore is strictly forbidden.
- An explicit **Migration Grant** signed by founder Ed25519 authority must be supplied (`migration_grant: MigrationGrant`), specifying `source_run_id`, `target_run_id`, `checkpoint_hash`, and expiry timestamp.

---

## 4. Fix-Acceptance Test Gate & Strict Assertion Contract

In `tests/test_genesis_checkpoint_adversarial_regression.py`:

- **Ordinary Same-Run Restoration:**
  - `test_g02_ordinary_same_run_restore_succeeds` saves and restores under `run_id="RUN_ALPHA"`.
  - **Status:** PASSED (proves baseline same-run recovery is fully functional).
- **Vulnerability Demonstration:**
  - `test_g02_vulnerability_demonstration_cross_run_restore_accepted_without_migration` attempts restoring Run A's checkpoint into Run B on vulnerable code.
  - **Status:** PASSED (confirms vulnerability exists on current HEAD; Run B restores Run A with zero errors).
- **Fix-Acceptance Test Gate:**
  - `test_g02_fix_acceptance_cross_run_restore_without_migration_denied` is marked `@pytest.mark.xfail(strict=True)`.
  - **Direct Exception Assertion:** Uses `pytest.raises((ResumableManifestTamperedError, PermissionError))` directly enclosing `restore_resumable_checkpoint`. No substitute or synthetic exception is raised inside the test itself.
  - **Current Status:** Fails strictly with `XFAIL` because current `restore_resumable_checkpoint` returns successfully without raising.
  - Once Claude implements origin run binding, this test will pass, prompting the removal of the XFAIL marker.

