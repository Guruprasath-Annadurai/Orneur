# ORNEUR — INDEPENDENT NATIVE LEARNING ENGINE AUDIT REPORT #074
## Formal Adversarial Audit of Draft PR #73 (GENESIS Native Learning Engine Phase 1)

**Auditor:** Antigravity / Gemini — Independent Model-Training, Numerical Correctness & Security Auditor  
**To:** ORNEUR Founder & CTO  
**Date:** 2026-10-18  
**Scope:** Draft PR #73 (`claude/genesis-native-learning-engine-phase1-2026-10-17`)  
**Current Audited SHA:** `f8d254720bc3d00fab3ba046175a1afce03c7fbb`  
**Qualified Foundation Parent:** PR #65 HEAD `87cc7ad1a2e269de3a05edd626a61cca6fbdb760`  
**Execution Mode:** Adversarial, Mathematical, Empirical Independent Audit  
**Overall Verdict:** **CONDITIONAL_REMEDIATION_REQUIRED (OBJECTIVE DEFECTIVE — CANNOT TRAIN)**  
**Training Authorization:** **STRICTLY NO-GO (0 GPUs Allocated, ₹0 Spent)**

---

## 1. Executive Summary & Audit Matrix

Draft PR #73 introduces the first end-to-end training loop components (`.backward()` and `optimizer.step()`) in the GENESIS codebase, spanning five workstreams:
- Workstream 1 (`orca/genesis/training/learning_step.py`): `TrainingStepEngine`
- Workstream 2 (`orca/genesis/data/loader.py`): `GenesisBlockDataset`, `ReproducibleSampler`
- Workstream 3 (`orca/genesis/training/resumable_checkpoint.py`): `save_resumable_checkpoint`, `restore_resumable_checkpoint`
- Workstream 4 (`tests/test_genesis_synthetic_learning_proof.py`): Synthetic learning demonstration
- Workstream 5 (`orca/genesis/training/learning_governance.py`): `execute_authorized_training_step`

While PR #73 achieved clean remote CI (9/9 green checks) and 47 passing local unit tests, independent mathematical and empirical investigation revealed **critical foundational defects**:
1. **P0-01 (Double Shift):** The model is trained to predict token $T_{i+2}$ instead of $T_{i+1}$ (skipping a token) due to a double shift between `GenesisBlockDataset.block()` and `causal_lm_loss()`. Claude's synthetic learning demonstration masked this bug because it tested a periodic sequence of period 4, where predicting $T_{i+2}$ is identical in structure to predicting $T_{i+1}$.
2. **P0-02 (Continuous Execution Authority):** In-flight revocation or expiration of grants is never checked during an active `RUNNING` session. Furthermore, `TrainingStepEngine.step()` can be invoked directly by any caller without entering governance.
3. **P0-03 (Partial Accumulation Resume Divergence):** Saving mid-accumulation cycle when `grad_accum_steps > 1` discards accumulated gradients. On resumption, all model parameter tensors diverge from uninterrupted training.
4. **P0-04 (Sidecar Manifest Tampering):** Modifying `global_step`, `sampler_position`, or `microbatch_in_cycle` in the `.resumable.json` sidecar is accepted silently by `restore_resumable_checkpoint` without validation or error.
5. **P1-01 (Unbounded RAM Materialization):** The loader materializes all tokens of all shards into a Python `list[int]` and `list[Tensor]` in memory at construction time, causing guaranteed OOM on non-toy datasets.

### Findings & Severity Matrix

| Finding ID | Domain | Classification | Severity | Status | Auditor Verdict |
|:---|:---|:---|:---:|:---:|:---:|
| **AUDIT-P0-01** | Next-Token Objective Correctness | Double-shift token skipping & padding mask flaws | **P0** | **CONFIRMED** | **FAIL** |
| **AUDIT-P0-02** | Continuous Execution Authority | Governance bypass & in-flight expiration ignorance | **P0** | **CONFIRMED** | **FAIL** |
| **AUDIT-P0-03** | Exact Resume at Partial Accumulation | Gradients lost mid-cycle; resumed weights diverge | **P0** | **CONFIRMED** | **FAIL** |
| **AUDIT-P0-04** | Checkpoint Sidecar Integrity | Unvalidated JSON sidecar fields accept tamper | **P0** | **CONFIRMED** | **FAIL** |
| **AUDIT-P1-01** | Data Streaming & Loader RAM Bounds | Unbounded token RAM materialization & unverified digests | **P1** | **CONFIRMED** | **CONDITIONAL** |
| **AUDIT-P1-02** | Optimizer, Scheduler & Numerical Correctness | Microbatch vs token loss weighting | **P1** | **ANALYZED** | **PASS (BOUNDED)** |
| **AUDIT-P1-03** | Evidence & CI Qualification | Periodic pattern masked double shift; CI job verified | **P1** | **CONFIRMED** | **QUALIFIED** |

---

## 2. Audit P0-01 — Next-Token Objective Correctness (The Double-Shift Defect)

### 2.1 The Mathematical Mechanism
In `orca/genesis/data/loader.py:223-227`:
```python
def block(self, index: int) -> tuple[torch.Tensor, torch.Tensor]:
    full = self._blocks[index]
    input_ids = full[:-1]
    labels = full[1:].clone()
    labels[input_ids == self.cfg.pad_id] = IGNORE_INDEX
    return input_ids, labels
```
`block()` takes a sequence of length $L+1$: $T = [T_0, T_1, T_2, \dots, T_L]$.
It constructs:
$$\text{input\_ids} = [T_0, T_1, \dots, T_{L-1}]$$
$$\text{labels} = [T_1, T_2, \dots, T_L]$$

Then, in `TrainingStepEngine.step()`, `logits = model(input_ids)` produces predictions where logit $i$ has receptive field $[T_0, \dots, T_i]$.
Next, `step()` calls `causal_lm_loss(logits, labels)` (`orca/genesis/training/primitives.py:77-78`):
```python
shift_logits = logits[..., :-1, :].contiguous()
shift_labels = labels[..., 1:].contiguous()
```
`causal_lm_loss()` shifts BOTH `logits` and `labels` AGAIN:
$$\text{shift\_logits} = \text{logits}[0 \dots L-2]$$
$$\text{shift\_labels} = \text{labels}[1 \dots L-1] = [T_2, T_3, \dots, T_L]$$

### 2.2 Receptive Field vs Target Alignment
Tracing the exact pairing evaluated in cross-entropy:
- $\text{shift\_logits}[0]$ (conditioned on $[T_0]$) is evaluated against $\text{shift\_labels}[0] = \mathbf{T_2}$.
- $\text{shift\_logits}[1]$ (conditioned on $[T_0, T_1]$) is evaluated against $\text{shift\_labels}[1] = \mathbf{T_3}$.
- $\text{shift\_logits}[i]$ (conditioned on $[T_0, \dots, T_i]$) is evaluated against $\text{shift\_labels}[i] = \mathbf{T_{i+2}}$.

$$\mathbf{\text{Target Token Evaluated} = T_{i+2} \quad (\text{Token } T_{i+1} \text{ is COMPLETELY SKIPPED})}$$

### 2.3 Empirical Reproduction
- **Mathematical proof test:** `tests/test_native_learning_engine_adversarial_audit.py::test_p0_01_mathematical_proof_of_double_shift` (PASSED).
- **Associative recall test:** Trained a model on deterministic non-periodic sequence $[5 \to 6 \to 7 \to 8 \to 9]$.
  - Under true causal LM, given input $[5]$, the model must predict $6$.
  - Under PR #73, given input $[5]$, the model predicted $\mathbf{7}$ with 100% confidence (`test_p0_01_associative_recall_learns_t_plus_2_instead_of_t_plus_1`, PASSED). Token 6 was never predicted.

### 2.4 Additional Flaws in `block()`: Padding & All-Masked Crashes
1. **Flawed Padding Mask:**
   Line 226 executes `labels[input_ids == self.cfg.pad_id] = IGNORE_INDEX`.
   Because `labels` is already shifted by 1 relative to `input_ids`, the first padding token in `labels` corresponds to a non-padding token in `input_ids`. Thus, the first `pad_id` in `labels` remains unmasked! When `causal_lm_loss` shifts again, this unmasked `pad_id` is moved to position 0, forcing the model to predict `PAD` immediately following real text (`test_p0_01_padding_mask_defect_leaves_pad_unmasked_and_predicts_pad`, PASSED).
2. **All-Masked Crash:**
   For short single-token sequences in non-packing mode, shifting `labels` leaves all positions as `IGNORE_INDEX`. `causal_lm_loss` raises an unhandled `ValueError`, crashing the training step (`test_p0_01_single_token_padded_record_crashes_with_all_masked_positions`, PASSED).
3. **Packed Sequence Boundary Disruption:**
   Across packed document boundaries $(D_1 \to \text{EOS} \to D_2)$, double-shifting causes the last token of $D_1$ to be trained to predict the first token of $D_2$, bypassing $\text{EOS}$ entirely.

---

## 3. Audit P0-02 — Continuous Execution Authority

### 3.1 Trust Boundary Analysis
`orca/genesis/training/learning_governance.py` provides `execute_authorized_training_step(run, engine, ...)`.
The docstring states:
> "re-verification happens at resume-capable STATE TRANSITIONS... What this function DOES guarantee is that no call reaches a real optimizer step while run.state is anything other than RUNNING"

### 3.2 Vulnerabilities Confirmed
1. **No In-Flight Expiration or Revocation Checks:**
   `run.state` is an in-memory enum. Once set to `RunState.RUNNING`, `execute_authorized_training_step` never checks wall-clock expiration (`grant.expires_at`) or the external revocation ledger. An expired or revoked grant can continue updating parameters indefinitely (`test_p0_02_expired_grant_continues_updating_in_running_session`, PASSED).
2. **Direct Engine Step Bypass:**
   `TrainingStepEngine` in `learning_step.py` is an unconstrained public class with no coupling to `GenesisTrainingRun` or `learning_governance.py`. Any Python caller can simply instantiate `engine = TrainingStepEngine(...)` and invoke `engine.step(...)` directly (`test_p0_02_direct_step_bypasses_governance`, PASSED).
3. **Read-Time vs Continuous Shard Tampering:**
   While `GenesisBlockDataset` verifies shard hashes at construction, it never re-verifies during continuous training. If shard files on disk are modified, corrupted, or replaced during training, the run continues without detecting the tampering.

### 3.3 Enforceable Security Contract Recommendation
- In-process Python cannot provide kernel-level isolation, but the API contract should:
  1. Require `TrainingStepEngine` to take a non-forgeable `ExecutionCapability` token issued only by `GenesisTrainingRun`.
  2. Implement periodic cadence re-validation inside `TrainingStepEngine.step()` (e.g., every 100 steps, check `time.time() < grant.expires_at` and check revocation ledger).

---

## 4. Audit P0-03 — Exact Resume at Partial Accumulation

### 4.1 Accumulation State Loss
When `grad_accum_steps > 1`, a full optimization cycle consists of $K$ microbatches.
In `orca/genesis/training/learning_step.py`:
- Microbatches $0 \dots K-2$ call `(loss / K).backward()` and accumulate into `p.grad`.
- Step $K-1$ clips gradients and calls `optimizer.step()`, then `optimizer.zero_grad()`.

In `orca/genesis/training/resumable_checkpoint.py`:
- `save_resumable_checkpoint` records `microbatch_in_cycle` in the JSON sidecar.
- However, `TrainingState.capture()` only records `model.state_dict()` and `optimizer.state_dict()`. **It does NOT serialize `p.grad` or `_accum_loss_sum`.**

### 4.2 Empirical Divergence
When a checkpoint is taken at `microbatch_in_cycle = 1` and restored into a fresh engine:
- The fresh engine's parameters have `p.grad is None`.
- The gradients from microbatch 0 are completely lost.
- When microbatch 1 executes, `optimizer.step()` updates weights using **only microbatch 1's gradients**.
- In `tests/test_native_learning_engine_adversarial_audit.py::test_p0_03_resume_mid_accumulation_cycle_diverges` (PASSED):
  - Every single parameter tensor (20 of 20) diverged from uninterrupted execution.
  - Max weight difference exceeded $3.0 \times 10^{-4}$ in step 1.
  - Reported microbatch loss diverged ($2.774$ uninterrupted vs $1.405$ resumed).

### 4.3 Remediation Requirement
Either:
1. **Fail Closed (Recommended):** Prohibit saving mid-accumulation checkpoints. `save_resumable_checkpoint()` must raise an error if `microbatch_in_cycle != 0` (or drain the accumulation cycle first).
2. **Serialize Gradient Buffers:** Extend `TrainingState` to serialize `p.grad` for all parameters and `_accum_loss_sum`.

---

## 5. Audit P0-04 — Checkpoint Sidecar Integrity

### 5.1 Unvalidated Plaintext Metadata
`restore_resumable_checkpoint()` validates:
- `schema_version == RESUMABLE_SCHEMA_VERSION`
- `_sha256_of_file(path) == manifest.inner_checkpoint_sha256`
- `config_fingerprint`, `dataset_identity`, `sampler_seed`, `sampler_num_blocks`.

It **DOES NOT** validate:
- `manifest.global_step`
- `manifest.sampler_position`
- `manifest.microbatch_in_cycle`

### 5.2 Empirical Tampering Acceptance
In `test_p0_04_tampered_sampler_position_and_step_accepted_silently` (PASSED):
- We modified `global_step` from 10 to 999,999.
- We modified `sampler_position` from 50 to 888,888.
- We modified `microbatch_in_cycle` from 0 to 5.
- `restore_resumable_checkpoint()` restored all values without error or warning, despite the inner `training_state.step` remaining 10!
- The claim in docstrings that tampering of sampler position or accumulation position raises `ResumableManifestTamperedError` is **false**.

### 5.3 Remediation Requirement
1. Enforce that `manifest.global_step == restored.training_state.step`.
2. Compute an integrity digest over all sidecar fields and bind it into the inner checkpoint or sign it with the workload grant key.

---

## 6. Audit P1-01 — Data Streaming & Loader Correctness

### 6.1 Unbounded Memory Materialization
In `orca/genesis/data/loader.py:163-207`:
```python
token_stream: list[int] = []
for path in self._split_shard_paths():
    ...
    token_stream.extend(ids)
blocks = [torch.tensor(token_stream[...]) for i in range(num_blocks)]
```
- In packing mode, every token from every shard is appended into a single Python `list[int]`.
- Then, hundreds of thousands of individual `torch.Tensor` objects are allocated and retained in `self._blocks`.
- For a small 100M token sample, this consumes gigabytes of Python object overhead. For a 10B token pretraining dataset, this crashes with `MemoryError` during dataset `__init__`.
- Verified in `test_p1_01_all_tokens_materialized_in_ram` (PASSED).

### 6.2 Arbitrary Caller Digests
`LoaderConfig` accepts `authorized_shard_digests: Mapping[str, str]` from the caller. The dataset verifies that files on disk match this mapping, but **never verifies that the mapping itself was authorized by a signed `Grant` or `Manifest`**. An unauthorized caller can pass hashes of arbitrary unapproved files and the loader accepts them (`test_p1_01_caller_supplied_digests_trusted_without_authority_root`, PASSED).

---

## 7. Audit P1-02 — Optimizer, Scheduler & Numerical Correctness

### 7.1 Verified Correct Components
- **Gradient Accumulation & Zero-Grad Ordering:** `zero_grad(set_to_none=True)` is called once per accumulation cycle.
- **Gradient Clipping:** `clip_grad_norm(self.model, self.cfg.max_grad_norm)` correctly operates on accumulated gradients before optimizer stepping.
- **Scheduler Mathematics:** `cosine_warmup_lr` correctly calculates learning rates with 0-indexed step progression.
- **Non-Finite Signal Traps:** `check_for_nan_or_inf` traps NaN losses and NaN/Inf gradients, raising `NonFiniteTrainingSignalError` (`test_p1_02_nan_loss_raises_non_finite_training_signal`, PASSED).
- **Resource Ceilings:** `ResourceLimitExceededError` prevents unbounded CPU batch sizes or step counts (`test_p1_02_resource_limit_exceeded_on_oversized_batch`, PASSED).

### 7.2 Microbatch Normalization Caveat
Gradient accumulation computes:
$$\nabla = \frac{1}{K} \sum_{k=1}^K \left( \frac{1}{N_k} \sum_{i=1}^{N_k} \nabla \ell_{k,i} \right)$$
When microbatches have varying numbers of unmasked tokens $N_k$ (due to padding), this weights tokens in smaller microbatches more heavily than tokens in larger microbatches. For pretraining with packed sequences (where $N_k$ is constant), this distinction is negligible.

---

## 8. Audit P1-03 — Evidence & CI Qualification

### 8.1 Why Claude's Synthetic Learning Proof Masked the Double-Shift
In `tests/test_genesis_synthetic_learning_proof.py:68-76`:
```python
def _periodic_batch() -> tuple[torch.Tensor, torch.Tensor]:
    base = torch.tensor([i % PERIOD for i in range(SEQ_LEN + 1)])
    batch = torch.stack([base for _ in range(BATCH_SIZE)])
    return batch[:, :-1], batch[:, 1:]
```
`_periodic_batch()` generated:
$$[0, 1, 2, 3, 0, 1, 2, 3, 0, 1, 2, 3, \dots]$$
Because the sequence has period $P=4$:
$$(i + 2) \equiv (i - 2) \pmod 4$$
Given $T_i$, predicting $T_{i+2}$ is **just as deterministic and trivial** for a neural network as predicting $T_{i+1}$! The loss dropped from $2.39 \to 0.0008$, giving the false illusion that the model learned next-token causal modeling, when it was actually learning skip-one prediction (`test_p1_03_periodic_pattern_with_period_4_masks_double_shift`, PASSED).

### 8.2 GitHub CI Verification
- Exact audited commit `f8d254720bc3d00fab3ba046175a1afce03c7fbb` modified `.github/workflows/test.yml` to include the five new test files in the `Training Math Unit Tests (Torch)` job.
- GitHub CI run `39057806367` passed: **9 checks, 9 successful, 0 failed**.
- Independent local execution: All 47 PR #73 tests pass, and all 13 Antigravity adversarial tests pass.

---

## 9. Comprehensive Remediation Plan

Before PR #73 can be qualified or merged, the following mandatory remediations must be implemented:

1. **Fix Next-Token Alignment (AUDIT-P0-01):**
   - Adopt the standard PyTorch/HuggingFace convention: `GenesisBlockDataset.block()` yields unshifted `(tokens, tokens)` of shape `(seq_len,)`, and `causal_lm_loss` performs the single internal shift (`logits[:-1]` vs `labels[1:]`).
   - Fix padding masking: `labels[labels == pad_id] = IGNORE_INDEX`.
2. **Enforce Accumulation Checkpoint Boundary (AUDIT-P0-03):**
   - In `save_resumable_checkpoint()`, strictly require `microbatch_in_cycle == 0`. Raise `ValueError("Cannot checkpoint mid-accumulation cycle without discarding accumulated gradients")`.
3. **Bind Sidecar Manifest Integrity (AUDIT-P0-04):**
   - In `restore_resumable_checkpoint()`, verify `manifest.global_step == restored.training_state.step`.
   - Add a cryptographic HMAC or digital signature over `(global_step, sampler_position, config_fingerprint, inner_checkpoint_sha256)`.
4. **Harden Continuous Execution Authority (AUDIT-P0-02):**
   - In `TrainingStepEngine.step()`, check `grant.expires_at` periodically against `time.time()`.
   - Prevent unauthenticated direct invocation of `step()`.
5. **Implement Streaming / Memory-Mapped Loader (AUDIT-P1-01):**
   - Refactor `GenesisBlockDataset` to read shard records iteratively or via memory-mapping rather than buffering all tokens in RAM.

---

## 10. Formal Auditor Sign-off

| Evaluation Area | Auditor Finding | Verdict |
|:---|:---|:---:|
| **Objective Correctness (P0-01)** | Double-shift skips token; model predicts $T_{i+2}$; unmasked pad defect | **FAIL** |
| **Execution Authority (P0-02)** | In-flight revocation/expiration ignored; step callable directly | **FAIL** |
| **Partial Accumulation Resume (P0-03)** | Accumulated gradients lost; resumed weights diverge across all tensors | **FAIL** |
| **Sidecar Integrity (P0-04)** | Manifest fields can be altered arbitrarily without error | **FAIL** |
| **Data Streaming (P1-01)** | Unbounded in-memory materialization; unverified caller digests | **CONDITIONAL** |
| **Numerical Primitives (P1-02)** | Clipping, NaN trapping, and scheduling ordering sound | **PASS** |
| **Evidence & CI (P1-03)** | CI green, but synthetic learning proof masked objective defect | **QUALIFIED** |
| **Overall Recommendation** | **PR #73 CANNOT BE MERGED TO MAIN** | **CONDITIONAL REMEDIATION REQUIRED** |

*Signed,*  
**Antigravity**  
*Independent Model-Training, Numerical Correctness & Security Auditor*  
*ORNEUR Native LLM Foundation Project*
