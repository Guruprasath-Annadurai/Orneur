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

## 1. Vulnerability Summary & Live Worker IPC Reproduction

Our independent adversarial audit discovered that `_enforce_checkpoint_path_confinement` in `isolated_worker.py` creates a critical path validation discrepancy:

1. **Validation Path:** The validator computes `candidate = (workspace / raw_path).resolve()` and checks `candidate.is_relative_to(workspace)`.
2. **Execution Path:** The worker handler then calls:
   ```python
   save_resumable_checkpoint(path=Path(payload["path"]), ...)
   # and
   restore_resumable_checkpoint(path=Path(payload["path"]), ...)
   ```
3. **The Escape:** When `payload["path"]` is a relative path (e.g. `"step100.pt"`), validation succeeds because `workspace / "step100.pt"` is within the workspace. But `save_resumable_checkpoint` interprets `Path("step100.pt")` relative to `os.getcwd()` (the process current working directory, which is the repository root).
4. **Live IPC Socket Evidence (`test_g01_worker_ipc_vulnerability_demonstration_relative_path_escapes_to_cwd`):**
   - The test spawns a genuine `IsolatedTrainingWorker` background process and connects via UNIX domain socket client (`worker.client()`).
   - The client invokes `client.save_checkpoint(path="ipc_leak_demonstration.pt", ...)`.
   - The worker returns `{"ok": True}`, but inspection of disk reveals:
     - `(workspace / "ipc_leak_demonstration.pt").exists() == False` (authorized workspace remains completely empty).
     - `Path("ipc_leak_demonstration.pt").exists() == True` (checkpoint and `.resumable.json` escaped into repository root).
   - The test passes, definitively proving the vulnerability exists on real inter-process boundaries.

---

## 2. Path Traversal & Dynamic Symlink Substitution (TOCTOU)

1. **Parent Traversal and Absolute Escapes:**
   - Evaluated in `test_g01_checkpoint_path_confinement_directory_traversal_and_absolute_escapes`.
   - `_enforce_checkpoint_path_confinement` correctly raises `CheckpointWorkspaceViolationError` when paths contain `../` escaping workspace or absolute paths targeting system directories (e.g. `/etc/passwd`, `/tmp/malicious.pt`).
2. **Dynamic Symlink Substitution (TOCTOU Race Window):**
   - Evaluated in `test_g01_dynamic_symlink_substitution_toctou`.
   - Resolving the pathname string once before passing it to `save_resumable_checkpoint` leaves a **Time-of-Check to Time-of-Use (TOCTOU) race condition**:
     - **Attack Vector:** An attacker or concurrent thread swaps an intermediate directory component inside `checkpoint_workspace_dir` for a symlink pointing outside the workspace between the confinement check and the file write.
     - **Root Cause:** Standard Python `open(path, "wb")` and `atomic_write` follow symlinks in path components.

---

## 3. Desired Safe Behavior & Fix-Acceptance Criteria

A complete, race-safe fix requires:
1. **Resolved Path Anchoring:** `_enforce_checkpoint_path_confinement` must return the safely anchored, resolved `Path` object (e.g. `workspace / raw_path`), and the worker handlers MUST pass that returned path to `save_resumable_checkpoint` and `restore_resumable_checkpoint`.
2. **Directory Ownership & Permission Invariants:** The workspace directory must be strictly owned by the current process UID with permissions `0o700` before creation.
3. **Atomic File Creation:** Temporary files must be created using `O_CREAT | O_EXCL | O_NOFOLLOW` flags to prevent following pre-planted symlinks.

### Fix-Acceptance Test Gate (`test_g01_fix_acceptance_worker_confinement_desired_behavior`):
- Annotated with `@pytest.mark.xfail(strict=True)`.
- Spawns a live `IsolatedTrainingWorker` and commands `save_checkpoint(path="ipc_safe_target.pt")`.
- Asserts:
  - `(workspace / "ipc_safe_target.pt").exists() == True`
  - `Path("ipc_safe_target.pt").exists() == False`
- **Current Status:** Fails strictly with `XFAIL` on vulnerable code because the file lands in CWD.
- Once Claude repairs the handler to anchor relative paths to `workspace`, this test will automatically pass, triggering strict XPASS until `@pytest.mark.xfail` is removed.

