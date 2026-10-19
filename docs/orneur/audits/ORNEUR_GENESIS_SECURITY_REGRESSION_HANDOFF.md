# ORNEUR GENESIS CHECKPOINT & BOUNDARY SECURITY — REGRESSION & HANDOFF REPORT (G03)
## Threat Model, Trusted Controller Assumptions & Claude Fix-Acceptance Gates

**Document ID:** AUDIT-P0-G03-V2 (Corrected)  
**Status:** QUALIFIED & ADVERSARIALLY VERIFIED (LOCAL ONLY)  
**Classification:** P0 Security Analysis & Engineering Handoff  
**Target:** PR #73 / Foundation Hardening  
**Target Consumer:** Claude Code Engineering Agent (Credit Reset 20 October 2026, 5:30 PM IST)  
**Author:** Antigravity / Gemini Engineering & Independent Audit Agent  

---

## 1. Executive Summary

This report establishes the verified threat model, key-custody assumptions, and exact fix-acceptance criteria for the triad of GENESIS checkpoint security findings (G01, G02, G03).

In strict adherence to independent audit rules, **no checkpoint production code has been modified in this independent audit branch**. All deliverables consist of concrete, reproducible regression tests, fix-acceptance test gates (`@pytest.mark.xfail(strict=True)`), and actionable architectural specifications.

---

## 2. G03 Threat Model: Trusted Controller & Key-Custody Scope

### 2.1 The Trusted Controller Architecture
- **Trusted Controller (`GenesisTrainingRun`):** The orchestrating parent process holds the founder execution grant and generates a high-entropy 32-byte `integrity_key` in process memory.
- **IPC Communication Channel:** The controller communicates with the worker subprocess over a local Unix domain socket (`AF_UNIX`) protected by process UID ownership and strict `0o700` filesystem permissions.
- **Worker Key Reception:** The worker receives `integrity_key` over this local IPC channel. The worker verifies that key length is >= 32 bytes (raising `WeakIntegrityKeyError` if insufficient).
- **Scope Boundary:** Because IPC is local to the machine, the worker relies on the local Unix socket boundary for transport security. No additional founder-grant capabilities need to be invented for single-host training.

### 2.2 Local Anti-Rollback Ledger Boundaries (Honest Residual Scope)
- **Mechanism:** The worker records the highest observed `global_step` in a monotonic ledger file under `$ORCA_HOME/genesis_checkpoint_ledger/<hash>.ledger.json`.
- **Verified Protection:** Protects against unintentional rollback, accidental resumption from older steps, or isolated replacement of a checkpoint file.
- **Documented Residual Limit:** Because both the ledger and the checkpoint files reside on the same local filesystem and use the same HMAC key:
  - An attacker with full local filesystem write access can snapshot both the checkpoint and ledger at step 5, and later restore both simultaneously.
  - This is an honest, documented residual boundary: genuine hardware-enforced rollback protection against full local disk compromise requires an external monotonic counter (Cloud KMS / HSM or append-only distributed ledger), which is out of scope for single-host offline development.

---

## 3. Summary of Sprint Security Findings & Acceptance Status

| Finding ID | Component | Defect Summary | Current Verification | Fix-Acceptance Test Gate | Status |
|---|---|---|---|---|---|
| **G01** | `isolated_worker.py` | Relative paths write to `os.getcwd()` instead of workspace; TOCTOU dynamic symlink window. | `test_g01_*` (PASSED) | `test_g01_fix_acceptance_worker_confinement_desired_behavior` (XFAIL) | **CONFIRMED DEFECT** |
| **G02** | `resumable_checkpoint.py` | `ResumableManifest` omits `run_id` from HMAC tag; Run B restores Run A's state without migration grant. | `test_g02_*` (PASSED) | `test_g02_fix_acceptance_cross_run_restore_without_migration_denied` (XFAIL) | **CONFIRMED DEFECT** |
| **G03** | `resumable_checkpoint.py` | Weak key rejected; local ledger replayable with full disk access under local threat model. | `test_g03_*` (PASSED) | Verified within documented threat model scope. | **DOCUMENTED BOUNDARY** |

---

## 4. Expected-Failure (XFAIL) & Vulnerability Test Lifecycle

This test suite uses strict test segregation between **vulnerability demonstrations** and **fix-acceptance gates**. When Claude repairs the codebase, Claude must follow this explicit lifecycle:

### 4.1 The Role of Strict XFAIL (`@pytest.mark.xfail(strict=True)`)
- `test_g01_fix_acceptance_worker_confinement_desired_behavior` and `test_g02_fix_acceptance_cross_run_restore_without_migration_denied` are marked `@pytest.mark.xfail(strict=True)`.
- **Pre-Fix (Current State):** They execute real operations, fail because the codebase is vulnerable, and pytest reports them as `XFAIL`. The overall test suite exits `0`.
- **Post-Fix (When Claude Fixes Code):** When the underlying implementation is fixed, these tests will succeed. Because `strict=True` is specified, pytest treats unexpected passes as **failures (`XPASS -> FAILED`)**.
- **Claude Action:** Once the fix is applied, Claude **MUST remove the `@pytest.mark.xfail` decorators** from both fix-acceptance tests. They then become permanent, passing regression tests (`PASSED`).

### 4.2 Retiring / Inverting Vulnerability Demonstrations
Currently, two tests actively assert the vulnerable state to prove defect existence on real processes:
1. `test_g01_worker_ipc_vulnerability_demonstration_relative_path_escapes_to_cwd`:
   - *Current assertion:* Asserts `not (workspace / rel_name).exists()` and `Path(rel_name).exists()`.
   - *Post-Fix:* This test will fail once the worker anchors relative paths to workspace.
   - *Claude Action:* Retire this demonstration test, or update its assertions to match `test_g01_fix_acceptance_worker_confinement_desired_behavior`.
2. `test_g02_vulnerability_demonstration_cross_run_restore_accepted_without_migration`:
   - *Current assertion:* Asserts that `restore_resumable_checkpoint(run_id="RUN_BETA")` completes successfully without error.
   - *Post-Fix:* This test will fail because `restore_resumable_checkpoint` will raise `PermissionError` or `ResumableManifestTamperedError`.
   - *Claude Action:* Retire this test in favor of the fix-acceptance test, or invert the assertion to expect `PermissionError`.

---

## 5. Prioritized Engineering Checklist for Claude (20 Oct 5:30 PM IST)

When Claude resumes, execute the following repair sequence:

1. **G01 Repair (`isolated_worker.py`):**
   - In `_enforce_checkpoint_path_confinement`, return the resolved path anchored to `cfg.checkpoint_workspace_dir`.
   - In `_handle_save_checkpoint` and `_handle_restore_checkpoint`, pass the resolved path to `save_resumable_checkpoint` and `restore_resumable_checkpoint`.
2. **G02 Repair (`resumable_checkpoint.py`):**
   - Bump schema to `genesis-resumable-checkpoint-v2`.
   - Add `origin_run_id: str` to `ResumableManifest` and include it in `_compute_manifest_hmac`.
   - Update `restore_resumable_checkpoint` to assert `manifest.origin_run_id == run_id` (raising `PermissionError` without migration grant).
3. **Update Test Markers & Suite:**
   - Remove `@pytest.mark.xfail(strict=True)` from `test_g01_fix_acceptance_worker_confinement_desired_behavior` and `test_g02_fix_acceptance_cross_run_restore_without_migration_denied`.
   - Retire or invert the two vulnerability demonstrations.
4. **Run Regression Verification:**
   ```bash
   uv run --no-sync --frozen --with torch --with numpy --with sentencepiece --with cryptography pytest tests/test_genesis_checkpoint_adversarial_regression.py tests/test_c02_mission_lifecycle_security.py -v
   ```
   All 21 tests must report clean **`21 passed`** (0 failed, 0 xfailed, 0 xpassed).

