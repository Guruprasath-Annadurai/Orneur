# ORNEUR GENESIS CHECKPOINT SECURITY — ADVERSARIAL AUDIT REPORT (G01)

**Defect ID:** AUDIT-P0-G01  
**Severity:** CRITICAL / P0 SECURITY DEFECT  
**Target:** `orca/genesis/training/isolated_worker.py` & `resumable_checkpoint.py`  
**Classification:** Checkpoint Confinement Bypass / Workspace Escape  
**Test Reproduction:** `tests/test_genesis_checkpoint_adversarial_regression.py::test_g01_*`  
**Lead Auditor:** Antigravity / Gemini Engineering & Independent Audit Agent  

---

## 1. Vulnerability Summary

During the adversarial security qualification of Claude's GENESIS training foundation, an independent code analysis and reproduction identified a critical workspace escape discrepancy in `_enforce_checkpoint_path_confinement`.

While the confinement validator checks that `(workspace / raw_path).resolve()` remains within `cfg.checkpoint_workspace_dir`, the caller (`_handle_save_checkpoint`) subsequently passes `path=Path(payload["path"])` directly to `save_resumable_checkpoint`. 

When `payload["path"]` is a relative path (e.g. `"checkpoint_step_100.pt"`):
1. Confinement validation succeeds because `(workspace / "checkpoint_step_100.pt")` is within the workspace.
2. But `save_resumable_checkpoint` interprets `Path("checkpoint_step_100.pt")` relative to `os.getcwd()` (the process current working directory, which is the repository root `/app` or `/Users/.../Orneur`).
3. As a result, checkpoints and manifests are written **outside the authorized workspace directory**, leaking artifacts into the repository root.

---

## 2. Root Cause Analysis

### Vulnerable Code in `orca/genesis/training/isolated_worker.py`:

```python
# Lines 559-566
def _enforce_checkpoint_path_confinement(cfg: WorkerConfig, raw_path: str) -> None:
    workspace = Path(cfg.checkpoint_workspace_dir).resolve()
    candidate = (workspace / raw_path).resolve()
    if not candidate.is_relative_to(workspace):
        raise GenesisCheckpointSecurityError(
            f"Checkpoint path {raw_path!r} escapes the authorized workspace {str(workspace)!r}"
        )

# Lines 584-586
_enforce_checkpoint_path_confinement(cfg, payload["path"])
...
# Lines 594-596
save_resumable_checkpoint(
    path=Path(payload["path"]), # <-- DEFECT: Unresolved relative path passed!
    training_state=state,
    ...
)
```

### Exploit Demonstration:
1. Orchestrator configures `checkpoint_workspace_dir = "/tmp/secure_isolated_workspace"`.
2. Client sends save request: `{"path": "escaped_checkpoint.pt"}`.
3. Confinement check evaluates `candidate = Path("/tmp/secure_isolated_workspace/escaped_checkpoint.pt")`. `candidate.is_relative_to(workspace)` evaluates to `True`.
4. Check passes.
5. `save_resumable_checkpoint` receives `Path("escaped_checkpoint.pt")`.
6. File is saved at `os.getcwd() / "escaped_checkpoint.pt"`.
7. Confinement is completely defeated; the checkpoint is written to the project root.

---

## 3. Secondary Defect: TOCTOU Symlink Window

In addition to the relative path discrepancy, resolving the path before creation leaves a Time-of-Check to Time-of-Use (TOCTOU) race condition:
- If a subdirectory within `checkpoint_workspace_dir` is replaced by a symlink pointing to `/etc` or `~/.ssh` between the confinement check and file opening, `torch.save` will follow the symlink outside the workspace.
- `_mkdir_owner_only` in `resumable_checkpoint.py` creates parent directories with `0o700`, but atomic temporary files must also use `O_NOFOLLOW` and `O_CREAT | O_EXCL` flags during creation.

---

## 4. Independent Adversarial Reproduction

The vulnerability is deterministically reproduced in `tests/test_genesis_checkpoint_adversarial_regression.py`:

```python
def test_g01_checkpoint_path_confinement_relative_path_discrepancy(tmp_path):
    # Proves that passing relative path "step1.pt" causes confinement check to pass
    # but writes the file to Path("step1.pt").resolve() which does NOT equal the workspace path.
```

Test output:
```
tests/test_genesis_checkpoint_adversarial_regression.py::test_g01_checkpoint_path_confinement_relative_path_discrepancy PASSED [ 25%]
tests/test_genesis_checkpoint_adversarial_regression.py::test_g01_checkpoint_path_confinement_directory_traversal_and_absolute_escapes PASSED [ 50%]
```

---

## 5. Smallest Viable Remediating Patch

`_enforce_checkpoint_path_confinement` must return the sanitized, resolved `Path` object, and the caller must use that returned `Path`:

```diff
--- a/orca/genesis/training/isolated_worker.py
+++ b/orca/genesis/training/isolated_worker.py
@@ -559,7 +559,7 @@ def _verify_grant_or_die(cfg: WorkerConfig) -> None:
-def _enforce_checkpoint_path_confinement(cfg: WorkerConfig, raw_path: str) -> None:
+def _enforce_checkpoint_path_confinement(cfg: WorkerConfig, raw_path: str) -> Path:
     workspace = Path(cfg.checkpoint_workspace_dir).resolve()
     candidate = (workspace / raw_path).resolve()
     if not candidate.is_relative_to(workspace):
         raise GenesisCheckpointSecurityError(
             f"Checkpoint path {raw_path!r} escapes the authorized workspace {str(workspace)!r}"
         )
+    return candidate

@@ -584,3 +584,3 @@ def _handle_save_checkpoint(cfg: WorkerConfig, payload: dict[str, Any]) -> dict[
-    _enforce_checkpoint_path_confinement(cfg, payload["path"])
+    safe_checkpoint_path = _enforce_checkpoint_path_confinement(cfg, payload["path"])
     ...
     save_resumable_checkpoint(
-        path=Path(payload["path"]),
+        path=safe_checkpoint_path,
```

This patch guarantees that all relative paths are safely anchored to `workspace`, closing the escape vulnerability completely.
