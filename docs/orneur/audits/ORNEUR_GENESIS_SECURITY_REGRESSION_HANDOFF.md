# ORNEUR GENESIS CHECKPOINT & BOUNDARY SECURITY — REGRESSION & HANDOFF REPORT (G03)

**Document Version:** 1.0.0  
**Status:** QUALIFIED & ADVERSARIALLY VERIFIED  
**Classification:** P0 Security Analysis & Engineering Handoff  
**Target:** PR #73 / Foundation Hardening  
**Target Consumer:** Claude Code Agent (Credit Reset 20 October 2026, 5:30 PM IST)  
**Author:** Antigravity / Gemini Engineering & Independent Audit Agent  

---

## 1. Executive Summary

This report completes Priority 2 of the Antigravity Independent Engineering Sprint. It examines the integrity-key custody model and anti-rollback boundaries (G03), summarizes the triad of findings (G01, G02, G03), and provides exact handoff instructions and test artifacts for Claude.

---

## 2. G03 Threat Model: Integrity-Key Custody & Anti-Rollback Boundaries

### 2.1 Unauthenticated Client Key Delivery Over IPC
- **Finding:** In `isolated_worker.py`, the worker receives `integrity_key` as a caller-supplied hex string inside the IPC JSON payload (`_handle_save_checkpoint` and `_handle_restore_checkpoint`).
- **Threat Vector:** The worker process does not verify whether the provided `integrity_key` is cryptographically derived from the Founder Grant or held in secure hardware (e.g. KMS/HSM). Any caller capable of issuing IPC requests to the worker socket can pass an arbitrary 32-byte key.
- **Current Safeguard:** The worker verifies minimum key entropy (raises `WeakIntegrityKeyError` if key length < 32 bytes).

### 2.2 Local Ledger Replay Boundary (Honest Residual Limitation)
- **Finding:** The anti-rollback ledger (`_read_ledger`, `_advance_ledger`) records the highest observed `global_step` in a local JSON file at `$ORCA_HOME/genesis_checkpoint_ledger/<hash>.ledger.json`.
- **Honest Scope Verification:** As explicitly acknowledged in `resumable_checkpoint.py` lines 345–355, the local ledger raises the bar against accidental rollback or isolated checkpoint tampering. However, because the ledger and checkpoints reside on the same local filesystem and use the same HMAC key:
  - An attacker with filesystem write privileges can take a snapshot of both the checkpoint directory and the ledger at step 5.
  - After the run advances to step 100, the attacker can restore both the step 5 checkpoint and the step 5 ledger simultaneously.
  - The system accepts the rollback because the ledger was rolled back in lockstep.
- **Reproduced in Tests:** `tests/test_genesis_checkpoint_adversarial_regression.py::test_g03_integrity_key_custody_and_local_ledger_replay_limitation` demonstrates this property deterministically.
- **Long-Term Requirement:** In future distributed training phases, monotonic counters must be anchored to a remote append-only log (e.g. AWS DynamoDB with strict conditional writes or Google Cloud Spanner).

---

## 3. Summary of Sprint Security Findings

| Finding ID | Component | Defect Description | Severity | Remediated Status |
|---|---|---|---|---|
| **G01** | `isolated_worker.py` | Relative path passes confinement check but executes against `os.getcwd()`, writing checkpoints to repository root. | **P0 Critical** | Adversarial test added; minimal patch designed. |
| **G02** | `resumable_checkpoint.py` | `ResumableManifest` HMAC tag omits `run_id`, allowing arbitrary cross-run checkpoint loading. | **P0 Critical** | Adversarial test added; migration schema specified. |
| **G03** | `isolated_worker.py` | IPC integrity key lacks grant-attestation; local anti-rollback ledger replayable with full disk access. | **P1 Architectural** | Validated and documented as recognized residual boundary. |

---

## 4. Engineering Handoff Instructions for Claude

When Claude Code credits reset on **20 October 2026 at 5:30 PM IST**, Claude must apply the following sequence:

### Step 1: Apply G01 Confinement Patch
Modify `_enforce_checkpoint_path_confinement` in `orca/genesis/training/isolated_worker.py` to return the resolved path, and pass `path=safe_checkpoint_path` in `_handle_save_checkpoint`.

### Step 2: Apply G02 Manifest Tag Patch
1. Add `origin_run_id: str` to `ResumableManifest` in `orca/genesis/training/resumable_checkpoint.py`.
2. Include `manifest.origin_run_id` in `_compute_manifest_hmac`.
3. Verify that `test_g02_checkpoint_authority_manifest_omits_run_id_allowing_cross_run_restore` fails when unauthenticated cross-run restore is attempted.

### Step 3: Run Full Verification Suite
Execute:
```bash
uv run --with torch --with numpy --with sentencepiece --with cryptography pytest tests/test_genesis_checkpoint_adversarial_regression.py tests/test_c02_mission_lifecycle_security.py -v
```
All tests must pass.
