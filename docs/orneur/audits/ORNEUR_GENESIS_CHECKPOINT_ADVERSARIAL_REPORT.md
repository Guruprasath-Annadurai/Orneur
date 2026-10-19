# ORNEUR GENESIS CHECKPOINT SECURITY — ADVERSARIAL AUDIT REPORT (G01)
## Checkpoint Confinement, Relative Path Discrepancy & TOCTOU Race Analysis

**Document ID:** AUDIT-P0-G01-V2 (Corrected)  
**Severity:** CRITICAL / P0 SECURITY DEFECT  
**Target:** `orca/genesis/training/isolated_worker.py` (`_handle_save_checkpoint`, `_handle_restore_checkpoint`)  
**Classification:** Checkpoint Confinement Bypass & Workspace Escape  
**Test Suite:** `tests/test_genesis_checkpoint_adversarial_regression.py`  
**Tests:** `test_g01_*` (Demonstration PASSED; Fix-Acceptance XFAIL)  
**Lead Auditor:** Antigravity / Gemini Engineering & Independent Audit Agent  

---

## 1. Vulnerability Summary

Our independent adversarial audit discovered that `_enforce_checkpoint_path_confinement` in `isolated_worker.py` creates a critical path validation discrepancy:

1. **Validation Path:** The validator computes `candidate = (workspace / raw_path).resolve()` and checks `candidate.is_relative_to(workspace)`.
2. **Execution Path:** The worker handler then calls:
   ```python
   save_resumable_checkpoint(path=Path(payload["path"]), ...)
   # and
   restore_resumable_checkpoint(path=Path(payload["path"]), ...)
   ```
3. **The Escape:** When `payload["path"]` is a relative path (e.g. `"step100.pt"`), validation succeeds because `workspace / "step100.pt"` is within the workspace. But `save_resumable_checkpoint` interprets `Path("step100.pt")` relative to `os.getcwd()` (the process current working directory, which is the repository root).
4. **Impact:** Checkpoints and manifests are saved outside the designated workspace into the repository root, escaping confinement. On restore, the worker attempts to read from CWD instead of the workspace.

---

## 2. Dynamic Symlink Substitution (TOCTOU Race Window)

In addition to the relative path discrepancy, resolving the pathname string once before passing it to `save_resumable_checkpoint` leaves a **Time-of-Check to Time-of-Use (TOCTOU) race condition**:

- **Attack Vector:** An attacker or concurrent thread swaps an intermediate directory component inside `checkpoint_workspace_dir` for a symlink pointing outside the workspace between the confinement check and the file write.
- **Root Cause:** Standard Python `open(path, "wb")` and `atomic_write` follow symlinks in path components.
- **Demonstration:** Verified in `test_g01_dynamic_symlink_substitution_toctou`.

---

## 3. Desired Safe Behavior & Fix-Acceptance Criteria

A complete, race-safe fix requires:
1. **Resolved Path Anchoring:** `_enforce_checkpoint_path_confinement` must return the safely anchored, resolved `Path` object, and the worker handlers MUST pass that returned path to `save_resumable_checkpoint` and `restore_resumable_checkpoint`.
2. **Directory Ownership & Permission Invariants:** The workspace directory must be strictly owned by the current process UID with permissions `0o700` before creation.
3. **Atomic File Creation:** Temporary files must be created using `O_CREAT | O_EXCL | O_NOFOLLOW` flags to prevent following pre-planted symlinks.

### Fix-Acceptance Test Gate:
- `test_g01_fix_acceptance_worker_confinement_desired_behavior` has been added with `@pytest.mark.xfail(strict=True)`.
- It executes against the worker save handler and asserts that relative path checkpoints exist inside `workspace` and NOT in `os.getcwd()`.
- It currently fails (XFAIL) as expected on the vulnerable code, and will turn to PASS once Claude applies the fix.
