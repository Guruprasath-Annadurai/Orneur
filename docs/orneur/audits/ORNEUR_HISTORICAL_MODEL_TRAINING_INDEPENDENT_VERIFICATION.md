# ORNEUR — INDEPENDENT HISTORICAL MODEL TRAINING FORENSICS & VERIFICATION

**To:** ORNEUR CTO & Founder  
**From:** Antigravity / Gemini — Independent Research, Security and Model Assurance Lead  
**Date:** 2026-10-16  
**Audited Reference:** PR #60 (`claude/historical-training-audit-2026-10-16`, commit `6f301c39fce40b6c82917164d13949b76eac9292`)  
**Main Branch SHA:** `20a8546f5a1ece7e5af655c0f30ca7e305f71b1a`  
**Execution Mode:** Read-only forensic analysis and live local verification  
**Forensic Verdict:** `LEGACY_FINETUNING_VERIFIED_AUTHENTIC` | `NATIVE_PRETRAINING_ABSENT`

---

## Executive Summary

This independent forensic audit investigated whether ORNEUR's historical fine-tuned models actually exist, whether past training claims are substantiated by primary evidence, and how the historical ORCA-era lineage relates to the current native-pretraining programme.

### Key Forensic Determinations:
1. **Legacy Fine-Tuned Checkpoints (ORCA Era) are REAL and VERIFIED:**
   - Live execution of `ollama list` and `ollama show` on this machine confirmed the active presence of four fine-tuned model artifacts: `orca-nano` (`orca-nano-v4`), `orca-nano-v7`, `orca-core-combined`, and `orca-core-combined-v2`.
   - Inspection of `~/.orca/registry/checkpoints/` confirmed persisted metadata records, SHA-256 digests, and dataset linkages.
   - All legacy checkpoints are **parameter fine-tunes (SFT / DPO via LoRA/QLoRA) built upon third-party base models** (`Qwen/Qwen2.5-7B-Instruct` and `meta-llama/Meta-Llama-3.1-8B-Instruct`).
2. **Native Pretraining from Scratch is STRICTLY ZERO:**
   - Neither GENESIS, NOVUS, nor AETERNUM has ever executed an original pretraining run from random initialization.
   - The current GENESIS Transformer code in PR #55/58 represents inert architectural primitives. No native checkpoint exists anywhere.
3. **Legacy AETERNUM Never Existed:**
   - Search across `~/.orca/registry/` and Ollama confirmed zero checkpoints or datasets for AETERNUM.
   - The architectural target discrepancy (historical `Llama-3.1-70B-Instruct` vs current `~14B provisional`) was traced to a deliberate, owner-reviewed TDD commit (`fef1be0`, 2026-09-12), setting `base_model=None` and `base_model_status="UNSELECTED_PROVISIONAL"`.
4. **Historical Benchmark Authenticity & Promotion Status:**
   - Cross-checking against `novus-combined-v2-full-eval.json` confirmed historical scores: **Accuracy 72.8%, Jailbreak Block 70.0%, Domain Eval 37.5%**.
   - These evaluations were **internal keyword/heuristic evaluations on a tiny 72-record dataset**, not external frontier benchmarks.
   - The recorded status was strictly **`NOT_PROMOTABLE`** (failed minimum 92% jailbreak threshold and 75% domain threshold). No historical model was ever promoted to production.

---

## 1. Evidence Provenance Taxonomy

Every claim in this forensic report is explicitly tagged:
- **`[ORIGINAL OBSERVATION]`**: Verified live on this local workstation via direct commands (`ollama list`, file inspection, SHA-256 verification).
- **`[ARCHIVED EVIDENCE]`**: Verified from committed repository artifacts, historical evaluation JSONs, and model registry records.
- **`[UNAVAILABLE ARTIFACT]`**: Checkpoint or training run documented in historical logs but not currently present on this local machine.
- **`[UNVERIFIED CLAIM]`**: External platform claims (e.g. Kaggle/Colab kernel execution runs) that cannot be independently reproduced without external credentials.

---

## 2. Complete Model-by-Model Forensic Audit Table

| Model Family & Checkpoint ID | Base Model Lineage | Training Method | Artifact Existence & Size | Live Verification Evidence | Reported Checksum vs Actual | Evaluated Capabilities | Lifecycle Status | Forensic Classification |
| :--- | :--- | :--- | :--- | :--- | :--- | :--- | :--- | :--- |
| **Legacy Genesis** `orca-nano` (`v4`) | `Qwen2.5-7B-Instruct` | SFT + DPO (LoRA) on Kaggle/Colab | **EXISTS** (4.7 GB GGUF) | `[ORIGINAL OBSERVATION]` Present in `ollama list` (ID `2ab5910cb763`). | Recorded: `sha256:5ce04...`. Verified identical ID across `v1` and `v4`. | General instruction following; uncalibrated. | `RETIRED` | `LEGACY_FINETUNED_MODEL` |
| **Legacy Genesis** `orca-nano-v7` | `Qwen2.5-7B-Instruct` (7.6B params, qwen2) | SFT + Safety DPO (LoRA) | **EXISTS** (4.7 GB GGUF) | `[ORIGINAL OBSERVATION]` Present in `ollama list` (ID `dca5de8d5e6a`). `ollama show` confirmed 7.6B qwen2 architecture. | Recorded: `sha256:5ce043a5...` in `~/.orca/registry/checkpoints/orca-nano-v7.json`. | Minimal test inference confirmed operational. Internal heuristic evals only. | `EXPERIMENTAL` | `LEGACY_FINETUNED_MODEL` |
| **Legacy Novus** `orca-core` | `Meta-Llama-3.1-8B-Instruct` | SFT (LoRA) | `[UNAVAILABLE ARTIFACT]` Absent from local Ollama | `[ARCHIVED EVIDENCE]` Recorded in `~/.orca/registry/checkpoints/orca-core.json`. | Not locally present to re-hash. | Initial baseline fine-tune; severe calibration decay. | `RETIRED` | `LEGACY_FINETUNED_MODEL` |
| **Legacy Novus** `orca-core-combined` | `Meta-Llama-3.1-8B-Instruct` | SFT (joint safety+calibration 1:2 ratio) | **EXISTS** (4.9 GB GGUF) | `[ORIGINAL OBSERVATION]` Present in `ollama list` (ID `24e5f55c01e3`). | Recorded: `sha256:f9e41d90...` in `orca-core-combined.json`. | Jailbreak 70%, Bias 12.5%, Calibration 0.0% (failed calibration). | `SUPERSEDED` | `LEGACY_FINETUNED_MODEL` |
| **Legacy Novus** `orca-core-combined-v2` | `Meta-Llama-3.1-8B-Instruct` (8.0B params, llama) | SFT (joint safety+calibration 1:5 ratio, 72 records) | **EXISTS** (4.9 GB GGUF) | `[ORIGINAL OBSERVATION]` Present in `ollama list` (ID `1769703a2677`). `ollama show` confirmed 8.0B llama architecture. | Recorded: `sha256:c519cba1...` in `orca-core-combined-v2.json`. | Accuracy 72.8%, Jailbreak 70.0%, Domain 37.5%, Calibration 100% (6/6). | `NOT_PROMOTABLE` | `LEGACY_FINETUNED_MODEL` |
| **Legacy Aeternum** `ultra` | None (historical target was Llama-3.1-70B) | **NONE** (Never trained) | **DOES NOT EXIST** | `[ORIGINAL OBSERVATION]` Zero files in `~/.orca/registry/checkpoints/` and zero Ollama tags. | N/A | None. | `UNSELECTED_PROVISIONAL` | `ABSENT_UNPRODUCED` |
| **Native Genesis** (`PR #55/58`) | None (Original ORNEUR Transformer) | **NONE** (Never trained from scratch) | Inert code only; **NO CHECKPOINT** | `[ORIGINAL OBSERVATION]` All models in tests are fresh random initializations. Acceptance ledger is `0/95`. | N/A | None (Software integration test only). | `DESIGNED_ONLY` | `ORNEUR_NATIVE_PRETRAINED_MODEL` (Pending) |
| **Native Novus** | None (Original architecture planned) | **NONE** | **DOES NOT EXIST** | `[ORIGINAL OBSERVATION]` Zero code in repo. | N/A | None. | `UNSTARTED` | `ORNEUR_NATIVE_PRETRAINED_MODEL` (Pending) |
| **Native Aeternum** | None (Original architecture planned) | **NONE** | **DOES NOT EXIST** | `[ORIGINAL OBSERVATION]` Zero code in repo. | N/A | None. | `UNSTARTED` | `ORNEUR_NATIVE_PRETRAINED_MODEL` (Pending) |

---

## 3. Detailed Forensic Findings

### 3.1 Live Artifact Verification (`[ORIGINAL OBSERVATION]`)
Execution of `ollama list` on the local system yielded:
```
NAME                            ID              SIZE      MODIFIED     
orca-core-combined-v2:latest    1769703a2677    4.9 GB    6 weeks ago     
orca-core-combined:latest       24e5f55c01e3    4.9 GB    6 weeks ago     
nomic-embed-text:latest         0a109f422b47    274 MB    2 months ago    
orca-nano-v7:latest             dca5de8d5e6a    4.7 GB    2 months ago    
orca-nano:latest                2ab5910cb763    4.7 GB    2 months ago    
orca-nano-v4:latest             2ab5910cb763    4.7 GB    2 months ago    
```
- Direct execution of `ollama show orca-nano-v7` proved the model has 7.6B parameters, `qwen2` architecture, 32,768 context length, and 3,584 embedding dimension.
- Direct execution of `ollama show orca-core-combined-v2` proved the model has 8.0B parameters, `llama` architecture, 131,072 context length, and 4,096 embedding dimension.
- `orca-nano` and `orca-nano-v4` point to the identical image ID (`2ab5910cb763`).

### 3.2 Verification of Historical Evaluation Numbers
In `~/.orca/registry/evaluations/novus-combined-v2-full-eval.json`:
- `eval_accuracy`: **72.8%**
- `jailbreak_block_rate`: **70.0%** (Threshold required: 92.0%)
- `bias_flag_rate`: **12.5%** (Threshold max: 20.0%)
- `domain_eval`: **37.5%** (Threshold required: 75.0%)
- `pass_fail_status`: **`NOT_PROMOTABLE`**
- `failure_reasons`:
  - `jailbreak_block_rate 70.0 is below required minimum 92.0`
  - `domain_eval 37.5 is below required minimum 75.0`

These evaluations reflect **small-sample internal heuristics** (specifically 72 total examples in `orca-novus-combined-safety-calibration-v2`). They provide evidence of fine-tuning behavior, but do not substantiate any frontier intelligence or production readiness claim.

### 3.3 Aeternum Architecture Target Reconciliation
In Phase 0/1, Aeternum was described as a fine-tuned `Llama-3.1-70B-Instruct` model. In commit `fef1be0` (2026-09-12, "Phase 16 closure: correct Aeternum architecture per owner review"), this was officially altered in `orca/registry/model_spec.py`:
- `base_model = None`
- `base_model_status = "UNSELECTED_PROVISIONAL"`
- `parameter_class = "~14B"`
- `provisional_parameter_hypothesis`: explicitly notes that `~14B` is a research starting point hypothesis, pending empirical capability evaluation.
- `require_base_model("aeternum")` was designed to raise `ValueError` rather than fall back to stale 70B defaults.
This audit confirms that the transition from 70B to ~14B was an **explicit, documented architectural decision**, not unrecorded drift.

---

## 4. Separation of Lineages: Fine-Tuning vs Native Pretraining

$$\begin{aligned}
\mathbf{LEGACY\_FINETUNED\_MODELS} &\neq \mathbf{ORNEUR\_NATIVE\_PRETRAINED\_MODELS} \\
\text{Qwen2.5 / Llama-3.1 Base} &\longleftrightarrow \text{Scratch Pretraining from Random Init}
\end{aligned}$$

1. **What ORNEUR Has Genuinely Achieved:**
   - Successful parameter fine-tuning of 7B and 8B open-weights base models using QLoRA and DPO.
   - Genuine recovery and verification of 4 fine-tuned GGUF artifacts running locally in Ollama.
   - Honest internal evaluation recording failures (`NOT_PROMOTABLE`) rather than fabricating passes.
2. **What ORNEUR Has Not Yet Achieved:**
   - Native from-scratch pretraining of any model.
   - Verification of dataset pipelines, streaming tokenization, or distributed training clusters.
   - Any trained artifact for Aeternum.
   - Any external benchmark score (MMLU, GSM8K, MATH, HumanEval) on native models.

---

## 5. Forensic Verdict

$$\mathbf{HISTORICAL\_TRAINING\_EVIDENCE\_VERDICT = VERIFIED\_LEGACY\_FINETUNING\_ONLY}$$
$$\mathbf{NATIVE\_PRETRAINING\_STATUS = UNSTARTED\_ABSENT}$$

PR #60's documentation is **accurate, forensic, and substantiated by primary local evidence**. The legacy fine-tuned models are genuine, but must remain strictly distinguished from the unstarted native pretraining programme.
