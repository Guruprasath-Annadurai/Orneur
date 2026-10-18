# ORNEUR — INDEPENDENT SUCCESSOR REQUALIFICATION REPORT #075
## Requalification of Claude's Audit #074 Remediations & Native Learning Engine Foundations

**Auditor:** Antigravity / Gemini — Independent Model-Training, Numerical Correctness & Security Auditor  
**To:** ORNEUR Founder & CTO  
**Date:** 2026-10-18  
**Scope:** Draft PR #73 (`claude/genesis-native-learning-engine-phase1-2026-10-17`)  
**Remediation Code SHA:** `740a7ee18b520797a752db9e2ebff2ff71d35ed3`  
**Final Report SHA:** `5a1f095bb89852554883768cbdf81cf517c89dc2`  
**Audit Baseline (Audit #074):** PR #74 (`f3d7bd902505fb765fd7aa3eb451695cfb0fe71f`)  
**Overall Verdict:** **CONDITIONAL_REMEDIATION_REQUIRED**  
**Training Injunction:** **STRICTLY NO-GO (0 GPUs Allocated, ₹0 Spent)**

---

## 1. Executive Summary & Audited HEAD Verification

Following the delivery of Independent Audit #074 (`f3d7bd9`), which issued a `CONDITIONAL_REMEDIATION_REQUIRED (OBJECTIVE DEFECTIVE)` verdict due to a double-shift target skipping bug, continuous governance bypasses, gradient loss on partial resume, unvalidated sidecar manifests, and unbounded token memory, Claude implemented remediations in commit `740a7ee18b520797a752db9e2ebff2ff71d35ed3` and closed CI in commit `5a1f095bb89852554883768cbdf81cf517c89dc2`.

Antigravity conducted an independent, empirical successor requalification across:
- **Phase A:** Re-verification of all four P0 findings (Causal-LM objective alignment, continuous execution authority, checkpoint resumption at accumulation boundaries, and sidecar integrity HMAC).
- **Phase B:** Re-qualification of P1 data loading scalability (on-disk block store, cache collision, concurrency, and tampering) and numerical correctness.
- **Phase C:** Adversarial evidence integrity, test suite reconciliation, and CI verification.

### Verification Matrix & Sub-Domain Verdicts

| Evaluation Domain | Finding / Subsystem | Remediation Status | Auditor Verdict | Notes |
|:---|:---|:---:|:---:|:---|
| **Mathematical Learning Correctness** | P0-01: Double shift eliminated; unshifted `(tokens, labels)` aligned | Remediated | **PASS** | True next-token prediction confirmed via associative recall & manual cross-entropy oracle. |
| **Checkpoint / Resumption Correctness** | P0-03 & P0-04: Fail-closed mid-cycle; HMAC sidecar validation | Remediated | **PASS** | `microbatch_in_cycle != 0` strictly rejected; completed cycle resume is bit-identical (`1e-6`). |
| **In-Process Authorization (Cooperative)** | P0-02: In-flight revocation & expiry checking | Remediated | **PASS** | `revalidate_every_n_calls=1` actively catches in-flight revocation, expiry, and shard drift. |
| **Authorization Against Untrusted Execution** | P0-02: Direct capability issuance & caller-controlled revalidation | Unmitigated | **FAIL** | Capability token bypassable in-process; requires OS-isolated worker architecture. |
| **Data Scalability & Block Store Integrity** | P1-01: Bounded memory; on-disk block store cache & concurrency | Partially Remediated | **CONDITIONAL** | Memory bounded, but block store lacks `seq_len` in cache ID, lacks `flock`, and lacks read checksums. |
| **Numerical Primitives & Scheduling** | P1-02: Gradient accumulation, clipping, LR schedule, non-finite traps | Verified | **PASS** | Numerically sound; microbatch vs global token weighting caveats documented. |
| **Single-Host Synthetic Readiness** | Synthetic training step mechanics | Qualified | **PASS** | Suitable for local algorithm prototyping and unit testing. |
| **Readiness for Real Native Training** | Real pretraining readiness | Blocked | **STRICTLY NO-GO** | Blocked on process-isolated worker architecture, distributed consensus, and real corpus authorization. |

---

## 2. Phase A — Re-Verification of the Four P0 Corrections

### 2.1 P0-01: Causal-LM Objective & Boundary Alignment (`PASS`)
- **Remediation Mechanism:**
  - `GenesisBlockDataset.block()` was refactored in `orca/genesis/data/loader.py:305-368` to return identical, unshifted tensors: `input_ids = tokens` and `labels = tokens.clone()`, with pad tokens masked as `IGNORE_INDEX` on the unshifted array.
  - The block size was adjusted from `seq_len + 1` to exactly `seq_len`. Exactly one shift occurs in the entire pipeline, located inside `orca/genesis/training/primitives.py:causal_lm_loss()` (`logits[:-1]` vs `labels[1:]`).
- **Independent Empirical Verification:**
  1. *Mathematical Alignment Oracle:* Tested irregular non-periodic sequence `[11, 23, 37, 41]`. Proved that logit position $i$ (receptive field $T_0 \dots T_i$) is evaluated against $T_{i+1}$ (target 23 at pos 0, 37 at pos 1, 41 at pos 2) with zero token skipping (`test_p0_01_oracle_proves_every_logit_predicts_exact_next_token`).
  2. *Associative Recall Requalification:* Trained a 2-layer transformer on non-periodic transitions $5 \to 6 \to 7 \to 8 \to 9$. When prompted with $[5]$, the model predicted $\mathbf{6}$ with 100% confidence (previously predicted 7 under the double shift). Prompted with $[5, 6]$, it predicted $\mathbf{7}$ (`test_p0_01_remediated_associative_recall_learns_t_plus_1`).
  3. *Padding Mask Requalification:* In non-packing mode, padding tokens are masked at source. Unshifted labels $[10, 20, \text{PAD}, \text{PAD}]$ produce shifted targets $[20, -100, -100]$. Position 0 predicts real token 20, and the model is **never** trained to predict `PAD` (`test_p0_01_remediated_padding_mask_does_not_predict_pad`).
  4. *Short-Sequence Handling:* Records with $<2$ tokens cannot form a supervised pair under single-shift modeling. The loader rejects them at load time with `MalformedRecordError` and increments `LoadReport.records_rejected_malformed`, preventing crashes inside `causal_lm_loss()` (`test_p0_01_short_sequence_load_time_rejection`).
  5. *Packed Boundaries:* In packing mode, documents are separated by `EOS_ID`. The token preceding EOS is supervised to predict `EOS_ID` exactly once, without skipping to the next document.

---

### 2.2 P0-02: Continuous Execution Authority (`PASS` Cooperative / `FAIL` Untrusted)
- **Remediation Mechanism:**
  - `orca/genesis/training/learning_governance.py:execute_authorized_training_step()` now independently calls `assert_execution_permitted()` (re-checking HMAC signature, wall-clock expiry, and live revocation) and compares `run._current_identity_snapshot()` against `_authorized_identity` on every call by default (`revalidate_every_n_calls=1`).
  - `TrainingStepEngine.step()` requires an `ExecutionCapability` token, issued via `_issue_capability_for_governance()` or `ExecutionCapability.for_unchecked_synthetic_test()`.
- **Independent Empirical Challenge & Bypasses:**
  1. *Cooperative Caller Protection:* When called through `execute_authorized_training_step()` with default settings:
     - In-flight revocation mid-run (without pause/resume) is caught on the very next step, raising `TrainingNotAuthorizedForExecutionError`.
     - In-flight wall-clock expiry is caught immediately.
     - In-flight shard byte modification is caught immediately.
     - Hollow runs forging `RunState.RUNNING` are rejected.
  2. *Caller-Controlled Cadence Weakness:*
     - Line 152 evaluates `due = (engine.global_step % max(revalidate_every_n_calls, 1)) == 0`.
     - Because `engine.global_step` only increments on completed accumulation cycles, setting `revalidate_every_n_calls=5` allows an adversary to execute parameter updates under a revoked grant for steps 1 through 4 without detection (`test_p0_02_caller_controlled_revalidate_cadence_bypasses_revocation`).
  3. *In-Process Capability Token Unenforceability:*
     - Any in-process caller can bypass governance entirely via:
       a) `cap = ExecutionCapability.for_unchecked_synthetic_test()`
       b) `cap = engine._issue_capability_for_governance()`
     - In both cases, `engine.step()` executes optimizer updates with zero authorization (`test_p0_02_synthetic_test_bypass_and_direct_governance_issuance`).
- **Architectural Requirement for Real Training:**
  As Claude's report openly concedes, pure Python code sharing an interpreter process cannot enforce security against untrusted code. **Before any real native pretraining can be authorized, an isolated-worker architecture must be deployed**:
  - The model, optimizer, and GPU memory must reside in a dedicated daemon worker process.
  - The worker process must only accept commands across an IPC/socket channel authenticated by mutual cryptographic tokens.
  - Client processes must have no access to the worker's address space or internal capabilities.

---

### 2.3 P0-03: Checkpoint Resumption under Accumulation (`PASS`)
- **Remediation Mechanism:**
  - Claude selected Option A (fail closed at accumulation boundaries).
  - In `orca/genesis/training/resumable_checkpoint.py:256-263`:
    `if microbatch_in_cycle != 0: raise MidAccumulationCheckpointError(...)`
- **Independent Empirical Verification:**
  1. *Mid-Cycle Fail-Closed:* Attempting to save a checkpoint at `microbatch_in_cycle = 1` when `grad_accum_steps = 2` immediately raises `MidAccumulationCheckpointError`. No partial checkpoint file or manifest is left on disk (`test_p0_03_mid_accumulation_checkpoint_fails_closed`).
  2. *Completed Boundary Exact Resume:* Saved at `microbatch_in_cycle = 0` after 1 complete cycle (2 microbatches). Restored into a fresh engine and executed a second complete cycle (2 microbatches). Compared against an uninterrupted 4-microbatch run:
     - **All parameter tensors are bit-identical** (`torch.allclose(..., atol=1e-6)`).
     - Optimizer momentum buffers and learning rate progression matched identically (`test_p0_03_completed_cycle_resume_is_bit_identical`).

---

### 2.4 P0-04: Checkpoint Sidecar Integrity & HMAC (`PASS`)
- **Remediation Mechanism:**
  - `save_resumable_checkpoint()` and `restore_resumable_checkpoint()` require `integrity_key: bytes`.
  - An HMAC-SHA256 (`_compute_integrity_tag`) is computed over all sidecar fields (`schema_version`, `inner_checkpoint_sha256`, `global_step`, `microbatch_in_cycle`, `sampler_position`, `sampler_seed`, `sampler_num_blocks`, `config_fingerprint`, `dataset_identity`).
  - `restore_resumable_checkpoint()` re-computes and checks the HMAC using `hmac.compare_digest()`, and cross-checks `manifest.global_step == training_state.step`.
- **Independent Empirical Challenge:**
  1. *Field Mutation Detection:* Modifying `sampler_position`, `global_step`, or `microbatch_in_cycle` in the `.resumable.json` manifest invalidates the HMAC tag and raises `ResumableManifestTamperedError` (`test_p0_04_tampered_sidecar_fields_rejected_by_hmac`).
  2. *Wrong Key Rejection:* Attempting to restore using a mismatched key fails the HMAC check and raises `ResumableManifestTamperedError`.
  3. *Inner Step Cross-Check:* If an attacker possesses the HMAC key and modifies `manifest.global_step` to 999 with a valid HMAC, `restore_resumable_checkpoint()` compares `manifest.global_step` against the inner `training_state.step` (5) and raises `ResumableManifestTamperedError` (`test_p0_04_inner_step_mismatch_rejected_even_if_hmac_valid`).
  4. *Swapped Checkpoint Pairs:* Pairing Checkpoint A with Manifest B is rejected because `manifest.inner_checkpoint_sha256` does not match the actual SHA-256 of Checkpoint A.
  5. *Rollback Protection Limitation:* The HMAC tag guarantees integrity and authenticity under a secret key, but **does not prevent rollback attacks**. An adversary can restore an older, validly signed checkpoint (step 5) in place of a newer checkpoint (step 100), and `restore_resumable_checkpoint()` will accept it (`test_p0_04_rollback_vulnerability_demonstration`). Rollback prevention requires a monotonically increasing state ledger or external audit chain.
  6. *Weak Key Custody:* Line 264 only verifies `if not integrity_key`. Passing a 1-byte weak key `b"x"` is accepted without minimum length/entropy enforcement.

---

## 3. Phase B — Re-Qualification of P1 Data & Numerical Correctness

### 3.1 P1-01: On-Disk Block Store Concurrency, Scalability & Integrity (`CONDITIONAL`)
Claude replaced the in-memory token list with an append-only binary block store (`.block_store_<split>_<packing>.bin`, 8 bytes/token `array('q')`). While this solves the memory scaling issue, Antigravity's deep audit uncovered **four architectural limitations**:

1. **Cache Identity Collision on Differing `seq_len` or Tokenizers:**
   - In `loader.py:176`:
     `self._store_path = Path(cfg.shard_dir) / f".block_store_{cfg.split}_{'packed' if cfg.packing else 'padded'}.bin"`
   - The cache filename omits `cfg.seq_len`, `tokenizer` digest, and dataset manifest hash.
   - If Dataset A is constructed with `seq_len=128`, and Dataset B is constructed with `seq_len=2048` pointing to the same `shard_dir`, **both target the exact same file path** (`test_p1_01_cache_identity_collision_on_differing_seq_len`).
2. **Missing Concurrency File Locks (`flock`):**
   - Line 233 executes `with open(self._store_path, "wb") as store:` without acquiring any file lock.
   - If two worker processes instantiate `GenesisBlockDataset` concurrently, the second process truncates the binary store while the first process is writing or reading.
   - Line 362 executes `raw = self._store_file.read(...)` without asserting `len(raw) == block_len * 8`. If the file is truncated or partially written, `block()` silently returns an undersized or empty tensor (`test_p1_01_concurrent_writers_truncate_without_flock`).
3. **No Read-Time Integrity Verification on Derived Store:**
   - Shard integrity is verified against `authorized_shard_digests` at construction time.
   - However, once `.block_store_*.bin` is written, `block(i)` seeks and reads raw bytes directly without any HMAC or checksum. If the derived binary file is modified post-construction, tampered tokens are fed directly to the model (`test_p1_01_derived_block_store_tampering_unverified_at_read_time`).
4. **Bounded Memory Verified:**
   - Tested using `tracemalloc` across 10,000 tokens with a 500-token construction buffer. Peak memory remained strictly bounded (<5 MB) (`test_p1_01_peak_memory_bounded_tracemalloc`).

---

### 3.2 P1-02: Optimizer, Scheduler & Numerical Correctness (`PASS`)
- **Microbatch Weighting Caveat:**
  `causal_lm_loss()` normalizes loss by active tokens per microbatch. When padding varies across microbatches, microbatch-mean accumulation weights tokens in short microbatches more heavily than tokens in long microbatches (`test_p1_02_microbatch_vs_token_mean_weighting`). For pretraining with packed sequences (where active token count is uniform), this effect is zero.
- **Numerical Guards:** Non-finite losses and gradients properly trigger `NonFiniteTrainingSignalError`.
- **Resource Limits:** `ResourceLimitExceededError` properly guards batch token counts and step bounds.

---

## 4. Phase C — Adversarial Evidence & CI Integrity

### 4.1 Test Suite Reconciliation
1. **Historical Vulnerability Demonstration Suite (`tests/test_native_learning_engine_adversarial_audit.py`):**
   - Retained verbatim without modification.
   - Execution results: **3 passed, 10 failed**.
   - Analysis of failures:
     - 8 failures represent **intended flips** where the vulnerable behavior no longer exists.
     - 2 failures (`test_p1_02_nan_loss` and `test_p1_02_resource_limit`) fail with `TypeError` because they predate the required `capability` argument.
2. **Successor Adversarial Requalification Suite (`tests/test_audit74_successor_adversarial_requalification.py`):**
   - Implemented by Antigravity containing 16 rigorous tests directly exercising the remediated APIs with capabilities, keys, and edge-case attacks.
   - Execution results: **16 passed, 0 failed** in 6.08s.
3. **PR #73 New Test Suite (Workstreams 1–5):**
   - 72 tests across 5 test files (`test_genesis_learning_step.py`: 17, `test_genesis_data_loader.py`: 19, `test_genesis_resumable_checkpoint.py`: 16, `test_genesis_learning_governance.py`: 9, `test_genesis_synthetic_learning_proof.py`: 11).
   - Execution results: **72 passed, 0 failed** in 37.13s.

### 4.2 GitHub Actions CI Qualification
- **Exact Audited Commit:** `5a1f095bb89852554883768cbdf81cf517c89dc2` on PR #73.
- **CI Status:** **9/9 checks successful**.
- All Torch-enabled test files genuinely executed in the `TrainingMath Unit Tests (Torch)` job (443 tests run, 0 skipped).
- `scripts/ci/run_deterministic_tests.sh` correctly deselects the 2 verbatim audit files to avoid false collection failures in torch-less jobs, while the successor suite includes `pytest.importorskip("torch")` to guarantee clean skips when torch is absent.

---

## 5. Required Remediations for Mainline Qualification

Before the native learning engine can be merged into `main` or used for multi-node experiments, the following conditions must be met:

1. **Block Store Identity Binding:** Include `seq_len`, tokenizer digest, and dataset manifest hash in the block store filename (e.g. `.block_store_{split}_{packing}_seq{seq_len}_{tok_digest[:8]}.bin`).
2. **Block Store Concurrency Locking:** Wrap `_build_block_store()` in an exclusive file lock (`fcntl.flock(store.fileno(), fcntl.LOCK_EX)`), write to a temporary file, and atomically rename (`os.replace`).
3. **Block Store Read Length Assertion:** In `block(i)`, assert that `len(raw) == block_len * _TOKEN_ITEM_SIZE` before decoding bytes into tensors.
4. **Process-Isolated Training Daemon:** Prior to real pretraining authorization, move `TrainingStepEngine` into an isolated background worker process accessible only via authenticated IPC.

---

## 6. Formal Auditor Sign-off

| Evaluation Area | Auditor Finding | Verdict |
|:---|:---|:---:|
| **Mathematical Objective (P0-01)** | Next-token target alignment mathematically verified | **PASS** |
| **Accumulation Resumption (P0-03)** | Fail-closed mid-cycle; exact bit-identical continuation | **PASS** |
| **Sidecar Integrity HMAC (P0-04)** | Field mutation and inner-step desynchronization detected | **PASS** |
| **In-Process Authorization (P0-02)** | In-flight revocation & expiry caught for cooperative callers | **PASS (COOPERATIVE)** |
| **Untrusted Caller Authorization** | Capability token bypassable in same interpreter | **FAIL (REQUIRES WORKER)** |
| **Data Scalability & Concurrency** | Bounded RAM achieved; block store cache/lock gaps identified | **CONDITIONAL** |
| **Numerical Primitives & Scheduling** | Clipping, NaN traps, and learning rate scheduling verified | **PASS** |
| **Overall Requalification Status** | **PR #73 Foundation Significantly Hardened** | **CONDITIONAL REMEDIATION REQUIRED** |

*Signed,*  
**Antigravity**  
*Independent Model-Training, Numerical Correctness & Security Auditor*  
*ORNEUR Native LLM Foundation Project*
