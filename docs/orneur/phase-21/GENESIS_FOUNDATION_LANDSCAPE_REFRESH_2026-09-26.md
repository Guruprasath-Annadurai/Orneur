# Genesis Foundation Landscape Refresh — 2026-09-26

**Verdict:** `FOUNDATION_LANDSCAPE_REFRESHED_NO_FOUNDATION_SELECTED`. No foundation is selected, no training or GPU is authorized, Phase 21C is not authorized.

The Qwen3-8B / Mistral-Nemo / Phi-4 pool was a **control pool** for runtime qualification. It does not automatically remain the Genesis candidate pool. This refresh re-derives the candidate pool from live primary sources and admits models only through gates A–J.

## 1. Evidence and method

- Collected read-only at `2026-09-26T14:46:55+00:00` by `scripts/orneur_foundation_landscape_collect.py` (public Hugging Face API, `config.json`, `LICENSE` texts, chat templates, transformers-main model directory listing, vLLM supported-models docs, PyPI). Raw record: `docs/orneur/phase-21/evidence/GENESIS_FOUNDATION_LANDSCAPE_RAW_HF_METADATA_2026-09-26.json`.
- **No weights downloaded, no GPU, no provider inference, no training.** Nothing below was executed on a model: every 'feasible' statement is documentation-level or a formula estimate and is labelled by *basis*.
- Latest package versions observed on PyPI: `{"accelerate": "1.15.0", "bitsandbytes": "0.50.2", "peft": "0.21.0", "transformers": "5.17.0", "trl": "1.14.0", "vllm": "0.30.0"}`.
- Parameter counts come from the safetensors metadata at the pinned revision. Active parameters for MoE models are **name-derived or vendor claims**, marked as such, and never used as verified fact.
- Vendor benchmark claims were deliberately **not** collected: this refresh admits candidates for ORNEUR's own frozen eval; it does not rank capability.
- The previous landscape (`GENESIS_FRONTIER_MODEL_LANDSCAPE_2026_09.md`) is unchanged. Where it and this file disagree, this file reflects the newer live collection and the previous file is historical.

## 2. Admission gates (a model enters the Genesis Capability Eval only if A–J all PASS)

- **A_license** — License is permissive (Apache-2.0 or MIT) and ungated; custom, revenue-threshold, MaaS-clause or manually gated terms fail until legally cleared.
- **B_revision_pinned** — An exact 40-hex revision is available to pin.
- **C_architecture_documented** — config.json is retrievable and the architecture has a native implementation in transformers main or the vLLM supported-models docs.
- **D_tokenizer_template** — A tokenizer and a chat template are shipped and were probed.
- **E_peft_qlora_feasible** — PEFT/QLoRA is feasible ON PAPER: dense, natively implemented, BF16-stored, <=40B parameters. MoE and natively-quantised checkpoints are UNVERIFIED; >40B fails. Basis is INFERRED_NOT_EXECUTED, so a PASS here means 'expected', never 'proven trainable' (see trainability_proven).
- **F_training_cost_vs_budget** — A 5M-token QLoRA pilot costs <=10% of the low end of the planning budget and the estimated QLoRA memory fits 80GB.
- **G_inference_path** — A vLLM-listed or transformers-native inference path exists.
- **H_artifacts_verifiable** — Immutable revision plus safetensors metadata at that revision.
- **I_no_proprietary_only_stack** — An open serving/training stack exists.
- **J_ecosystem_maturity** — Architecture is native in transformers main AND listed in the vLLM docs.

Status semantics: `PASS` documented evidence satisfies the gate; `FAIL` evidence violates it; `UNVERIFIED` no adequate evidence and is treated as *not passed*. Basis: `PRIMARY_SOURCE`, `DERIVED_FROM_PRIMARY_SOURCE`, `DERIVED_ESTIMATE`, `INFERRED_NOT_EXECUTED`, `NOT_VERIFIED`. A gate marked `INFERRED_NOT_EXECUTED` is exactly what the future capability/trainability probe must confirm.

## 3. Classification

- **GENESIS_EVAL_ADMITTED** (15)
- **TEACHER_REFERENCE** (6)
- **FUTURE_REASON_CANDIDATE** (9)
- **FUTURE_FRONTIER_ARCHITECTURE_REFERENCE** (3)
- **BASELINE_ONLY_CONTROL** (3)
- **NOT_ADMITTED** (8)

Classes are assigned by rules in `orca/eval/foundation_landscape.py`, not by recency, size or popularity. Giant MoE models are **not** forced into the current budget: they are teacher/reference or architecture-reference material.

**Terminology (corrected in the audit-corrections phase).** `GENESIS_EVAL_ADMITTED` (formerly `GENESIS_TRAINABLE_NOW`) means *admitted for evaluation* by documented gates. It does **not** mean proven trainable: every record carries `trainability_proven=false` and `trainability_evidence_ref=null` until Stage-0/Stage-3 evidence exists. `BASELINE_ONLY_CONTROL` models are never admitted (`admitted_to_capability_eval=false`) even when they would pass the gates; they are regression baselines only.

## 4. All investigated models (gate string = A B C D E F G H I J; P=PASS F=FAIL ?=UNVERIFIED)

| Model | Class | Admitted | Gates | Total params (B) | Active (B, attributed claim) | Context: config / vendor-supported | License | Revision |
|---|---|---|---|---|---|---|---|---|
| `HuggingFaceTB/SmolLM3-3B` | GENESIS_EVAL_ADMITTED | yes | `PPPPPPPPPP` | 3.08 | dense | 65536 / 65536 (MATCH) | apache-2.0 | `a07cc9a04f16` |
| `LiquidAI/LFM2.5-2.6B` | NOT_ADMITTED | no | `FPPPPPPPPP` | 2.7 | dense | 131072 / 131072 (MATCH) | other | `654f9463ce32` |
| `Qwen/Qwen3-8B` | BASELINE_ONLY_CONTROL | no | `PPPPPPPPPP` | 8.19 | dense | 40960 / 32768 (DIFFERS) | apache-2.0 | `b968826d9c46` |
| `Qwen/Qwen3.5-27B` | GENESIS_EVAL_ADMITTED | yes | `PPPPPPPPPP` | 27.78 | dense | 262144 / 262144 (MATCH) | apache-2.0 | `fc05daec18b0` |
| `Qwen/Qwen3.5-35B-A3B` | FUTURE_REASON_CANDIDATE | no | `PPPP?PPPPP` | 35.95 | 3.0 (VENDOR_MODEL_CARD_CLAIM) | 262144 / 262144 (MATCH) | apache-2.0 | `59d61f3ce65a` |
| `Qwen/Qwen3.5-4B` | GENESIS_EVAL_ADMITTED | yes | `PPPPPPPPPP` | 4.66 | dense | 262144 / 262144 (MATCH) | apache-2.0 | `851bf6e806ef` |
| `Qwen/Qwen3.5-9B` | GENESIS_EVAL_ADMITTED | yes | `PPPPPPPPPP` | 9.65 | dense | 262144 / 262144 (MATCH) | apache-2.0 | `c20223623576` |
| `Qwen/Qwen3.6-27B` | GENESIS_EVAL_ADMITTED | yes | `PPPPPPPPPP` | 27.78 | dense | 262144 / 262144 (MATCH) | apache-2.0 | `6a9e13bd6fc8` |
| `Qwen/Qwen3.6-35B-A3B` | FUTURE_REASON_CANDIDATE | no | `PPPP?PPPPP` | 35.95 | 3.0 (VENDOR_MODEL_CARD_CLAIM) | 262144 / 262144 (MATCH) | apache-2.0 | `995ad96eacd9` |
| `Qwen/Qwen3.8-2.4T-A95B` | FUTURE_FRONTIER_ARCHITECTURE_REFERENCE | no | `FPPPFFPPP?` | 2446.18 | 95.0 (VENDOR_MODEL_CARD_CLAIM) | 262144 / 262144 (MATCH) | other | `207bd685a7e3` |
| `Qwen/Qwen3.8-27B` | GENESIS_EVAL_ADMITTED | yes | `PPPPPPPPPP` | 27.78 | dense | 262144 / 262144 (MATCH) | apache-2.0 | `1d4bf0f2ff60` |
| `Qwen/Qwen3.8-Flash-Next` | FUTURE_FRONTIER_ARCHITECTURE_REFERENCE | no | `FPPPFFPPP?` | 180.0 | 6.0 (VENDOR_MODEL_CARD_CLAIM) | 262144 / 262144 (MATCH) | other | `de4b8e4d43b9` |
| `allenai/Olmo-3-7B-Instruct` | GENESIS_EVAL_ADMITTED | yes | `PPPPPPPPPP` | 7.3 | dense | 65536 / None (VENDOR_CLAIM_NOT_CAPTURED) | apache-2.0 | `6e5971d9eba4` |
| `deepseek-ai/DeepSeek-R1-0528-Qwen3-8B` | NOT_ADMITTED | no | `PPPPPPPPPP` | 8.19 | dense | 131072 / None (VENDOR_CLAIM_NOT_CAPTURED) | mit | `6e8885a6ff5c` |
| `deepseek-ai/DeepSeek-V4-Pro-0813` | TEACHER_REFERENCE | no | `PPP?FFPPPP` | 1650.5 | MoE (active not recorded) | 1048576 / None (VENDOR_CLAIM_NOT_CAPTURED) | mit | `72e1d3230f6c` |
| `deepseek-ai/DeepSeek-V4.1-Flash` | TEACHER_REFERENCE | no | `PP??FFFP??` | 763.21 | MoE (active not recorded) | 1048576 / 1048576 (MATCH) | mit | `dba1be0a40aa` |
| `google/gemma-4-12B` | FUTURE_REASON_CANDIDATE | no | `PPP?PPPPPP` | 11.96 | dense | 262144 / 262144 (MATCH) | apache-2.0 | `023679ed352d` |
| `google/gemma-4-12B-it` | GENESIS_EVAL_ADMITTED | yes | `PPPPPPPPPP` | 11.96 | dense | 262144 / 262144 (MATCH) | apache-2.0 | `707f0a3b8a3c` |
| `google/gemma-4-26B-A4B-it` | FUTURE_REASON_CANDIDATE | no | `PPPP?PPPPP` | 25.81 | 3.8 (VENDOR_MODEL_CARD_CLAIM) | 262144 / 262144 (MATCH) | apache-2.0 | `4d7ae4984b7d` |
| `google/gemma-4-31B-it` | GENESIS_EVAL_ADMITTED | yes | `PPPPPPPPPP` | 31.27 | dense | 262144 / 262144 (MATCH) | apache-2.0 | `842da3794eaa` |
| `google/gemma-4-E4B-it` | GENESIS_EVAL_ADMITTED | yes | `PPPPPPPPPP` | 8.0 | dense | 131072 / 131072 (MATCH) | apache-2.0 | `ee0ef6023621` |
| `ibm-granite/granite-4.2-30b` | GENESIS_EVAL_ADMITTED | yes | `PPPPPPPPPP` | 29.28 | dense | 131072 / 131072 (MATCH) | apache-2.0 | `9e668ce1c538` |
| `ibm-granite/granite-4.2-3b` | GENESIS_EVAL_ADMITTED | yes | `PPPPPPPPPP` | 3.66 | dense | 131072 / 131072 (MATCH) | apache-2.0 | `e459acceac81` |
| `ibm-granite/granite-4.2-8b` | GENESIS_EVAL_ADMITTED | yes | `PPPPPPPPPP` | 8.79 | dense | 131072 / 131072 (MATCH) | apache-2.0 | `f8de16cdcdbc` |
| `meta-llama/Llama-3.3-70B-Instruct` | NOT_ADMITTED | no | `FP??FFFP??` | 70.55 | dense | None / 131072 (CONFIG_NOT_AVAILABLE) | llama3.3 | `6f6073b42301` |
| `meta-llama/Llama-4-Scout-17B-16E-Instruct` | NOT_ADMITTED | no | `FP??FFFP??` | 108.64 | dense | None / None (CONFIG_NOT_AVAILABLE) | other | `92f3b1597a19` |
| `microsoft/Fara1.5-9B` | NOT_ADMITTED | no | `PPPPPPPPPP` | 9.41 | dense | 262144 / 262144 (MATCH) | mit | `1a93677cd89d` |
| `microsoft/MagenticBrain` | NOT_ADMITTED | no | `PPPPPPPPPP` | 14.77 | dense | 40960 / 32768 (DIFFERS) | mit | `db8eb9340a90` |
| `microsoft/Phi-4-mini-instruct` | GENESIS_EVAL_ADMITTED | yes | `PPPPPPPPPP` | 3.84 | dense | 131072 / 131072 (MATCH) | mit | `cfbefacb9925` |
| `microsoft/phi-4` | BASELINE_ONLY_CONTROL | no | `PPPPPPPPPP` | 14.66 | dense | 16384 / 16384 (MATCH) | mit | `2db69c1c3e91` |
| `mistralai/Ministral-3-14B-Base-2512` | FUTURE_REASON_CANDIDATE | no | `PPP?PPPPPP` | 13.95 | dense | 262144 / 262144 (MATCH) | apache-2.0 | `5b0ceedbb42d` |
| `mistralai/Ministral-3-14B-Instruct-2512` | FUTURE_REASON_CANDIDATE | no | `PPPP?PPPPP` | 13.95 | dense | 262144 / 262144 (MATCH) | apache-2.0 | `29439f81c2be` |
| `mistralai/Ministral-3-14B-Reasoning-2512` | GENESIS_EVAL_ADMITTED | yes | `PPPPPPPPPP` | 13.95 | dense | 262144 / 262144 (MATCH) | apache-2.0 | `51f9210f3cd2` |
| `mistralai/Ministral-3-8B-Instruct-2512` | FUTURE_REASON_CANDIDATE | no | `PPPP?PPPPP` | 8.92 | dense | 262144 / 262144 (MATCH) | apache-2.0 | `5b26027e7b19` |
| `mistralai/Mistral-Large-3-675B-Instruct-2512` | TEACHER_REFERENCE | no | `PP?P??F???` | None | 41.0 (VENDOR_MODEL_CARD_CLAIM) | None / 262144 (CONFIG_NOT_AVAILABLE) | apache-2.0 | `383ffea2c7d6` |
| `mistralai/Mistral-Nemo-Instruct-2407` | BASELINE_ONLY_CONTROL | no | `PPPPPPPPPP` | 12.25 | dense | 131072 / 131072 (MATCH) | apache-2.0 | `04d8a90549d2` |
| `mistralai/Mistral-Small-4-119B-2603` | TEACHER_REFERENCE | no | `PPPPFFPPPP` | 119.4 | 6.5 (VENDOR_MODEL_CARD_CLAIM) | 1048576 / 262144 (DIFFERS) | apache-2.0 | `a11f36bebf70` |
| `nvidia/NVIDIA-Nemotron-3-Nano-30B-A3B-BF16` | NOT_ADMITTED | no | `FPPP?PPPPP` | 31.58 | 3.0 (NAME_DERIVED) | 262144 / 1048576 (DIFFERS) | other | `bf77c3174f68` |
| `nvidia/NVIDIA-Nemotron-3.5-Lightning-30B-A3B-Base-BF16` | NOT_ADMITTED | no | `FPP??PPPPP` | 31.58 | 3.0 (NAME_DERIVED) | 262144 / 1048576 (DIFFERS) | other | `434456c9a675` |
| `openai/gpt-oss-120b` | TEACHER_REFERENCE | no | `PPPPFFPPPP` | 116.83 | 5.1 (VENDOR_MODEL_CARD_CLAIM) | 131072 / None (VENDOR_CLAIM_NOT_CAPTURED) | apache-2.0 | `b5c939de8f75` |
| `openai/gpt-oss-20b` | FUTURE_REASON_CANDIDATE | no | `PPPP?PPPPP` | 20.91 | 3.6 (VENDOR_MODEL_CARD_CLAIM) | 131072 / None (VENDOR_CLAIM_NOT_CAPTURED) | apache-2.0 | `6cee5e81ee83` |
| `zai-org/GLM-4.7-Flash` | FUTURE_REASON_CANDIDATE | no | `PPPP?PPPPP` | 31.22 | 3.0 (NAME_DERIVED) | 202752 / None (VENDOR_CLAIM_NOT_CAPTURED) | mit | `7dd20894a642` |
| `zai-org/GLM-5.3` | FUTURE_FRONTIER_ARCHITECTURE_REFERENCE | no | `FPPPFFPPPP` | 753.33 | MoE (active not recorded) | 1048576 / None (VENDOR_CLAIM_NOT_CAPTURED) | other | `aca966e4e027` |
| `zai-org/GLM-5.3-Flash` | TEACHER_REFERENCE | no | `PPPPFFPPP?` | 321.32 | 18.0 (VENDOR_MODEL_CARD_CLAIM) | 1048576 / None (VENDOR_CLAIM_NOT_CAPTURED) | mit | `eb9eb208eb0d` |

## 5. Per-candidate admission / exclusion reasons and records

### GENESIS_EVAL_ADMITTED

#### `HuggingFaceTB/SmolLM3-3B`

- Exact revision: `a07cc9a04f16550a088caea529712d1d335b0ac1`; license: `apache-2.0` (name `None`, gated `False`)
- Architecture: `['SmolLM3ForCausalLM']` / `smollm3`; total parameters 3.08B; active dense (DENSE)
- Context: config `max_position_embeddings`=65536; vendor-supported=65536 (SHORTHAND_K1024_ASSUMED; extended 131072); source `VENDOR_MODEL_CARD_CLAIM`; config-vs-vendor: **MATCH**; vendor text: "Trained on 64k context and supports up to 128k tokens using YARN extrapolation"
- Active parameters: None — source `DENSE`, verified=False
- Admission meaning: admitted for evaluation only; PEFT/QLoRA training is not proven until Stage-0/Stage-3 evidence exists (trainability_proven=False)
- Multimodality: text; tool-calling template: True; reasoning/thinking template: True
- Structured output: NOT_MODEL_NATIVE_EVIDENCE: enforced at system level by the ORNEUR Contract Engine; serving-stack constrained decoding not verified this phase
- Quantization: vendor variants observed none recorded; runtime 4-bit INFERRED_NOT_EXECUTED
- ESTIMATES (not measurements): QLoRA VRAM 5.5–10.2 GB; USD 0.082–0.137 per 1M training tokens; 5M-token pilot USD 0.41–0.69
- **Class reason:** passes all admission gates A-J on documented evidence: admitted for evaluation only; trainability is NOT proven
- Gates not passed: none
- Known caveats: 3.1B; 64k native context; full-attention only.
- Primary sources: https://huggingface.co/HuggingFaceTB/SmolLM3-3B, https://huggingface.co/api/models/HuggingFaceTB/SmolLM3-3B, https://huggingface.co/HuggingFaceTB/SmolLM3-3B/blob/main/config.json

#### `Qwen/Qwen3.5-27B`

- Exact revision: `fc05daec18b0a78c049392ed2e771dde82bdf654`; license: `apache-2.0` (name `None`, gated `False`)
- Architecture: `['Qwen3_5ForConditionalGeneration']` / `qwen3_5`; total parameters 27.78B; active dense (DENSE)
- Context: config `max_position_embeddings`=262144; vendor-supported=262144 (EXACT; extended 1010000); source `VENDOR_MODEL_CARD_CLAIM`; config-vs-vendor: **MATCH**; vendor text: "262,144 natively and extensible up to 1,010,000 tokens"
- Active parameters: None — source `DENSE`, verified=False
- Admission meaning: admitted for evaluation only; PEFT/QLoRA training is not proven until Stage-0/Stage-3 evidence exists (trainability_proven=False)
- Multimodality: text+image; tool-calling template: True; reasoning/thinking template: True
- Structured output: NOT_MODEL_NATIVE_EVIDENCE: enforced at system level by the ORNEUR Contract Engine; serving-stack constrained decoding not verified this phase
- Quantization: vendor variants observed none recorded; runtime 4-bit INFERRED_NOT_EXECUTED
- ESTIMATES (not measurements): QLoRA VRAM 17.9–27.4 GB; USD 0.74–1.233 per 1M training tokens; 5M-token pilot USD 3.7–6.17
- **Class reason:** passes all admission gates A-J on documented evidence: admitted for evaluation only; trainability is NOT proven
- Gates not passed: none
- Known caveats: Hybrid full/linear attention; superseded within family by newer 27B releases but not excluded for that reason.
- Primary sources: https://huggingface.co/Qwen/Qwen3.5-27B, https://huggingface.co/api/models/Qwen/Qwen3.5-27B, https://huggingface.co/Qwen/Qwen3.5-27B/blob/main/config.json

#### `Qwen/Qwen3.5-4B`

- Exact revision: `851bf6e806efd8d0a36b00ddf55e13ccb7b8cd0a`; license: `apache-2.0` (name `None`, gated `False`)
- Architecture: `['Qwen3_5ForConditionalGeneration']` / `qwen3_5`; total parameters 4.66B; active dense (DENSE)
- Context: config `max_position_embeddings`=262144; vendor-supported=262144 (EXACT; extended 1010000); source `VENDOR_MODEL_CARD_CLAIM`; config-vs-vendor: **MATCH**; vendor text: "262,144 natively and extensible up to 1,010,000 tokens"
- Active parameters: None — source `DENSE`, verified=False
- Admission meaning: admitted for evaluation only; PEFT/QLoRA training is not proven until Stage-0/Stage-3 evidence exists (trainability_proven=False)
- Multimodality: text+image; tool-calling template: True; reasoning/thinking template: True
- Structured output: NOT_MODEL_NATIVE_EVIDENCE: enforced at system level by the ORNEUR Contract Engine; serving-stack constrained decoding not verified this phase
- Quantization: vendor variants observed none recorded; runtime 4-bit INFERRED_NOT_EXECUTED
- ESTIMATES (not measurements): QLoRA VRAM 6.3–11.3 GB; USD 0.124–0.207 per 1M training tokens; 5M-token pilot USD 0.62–1.03
- **Class reason:** passes all admission gates A-J on documented evidence: admitted for evaluation only; trainability is NOT proven
- Gates not passed: none
- Known caveats: Hybrid full/linear attention (Gated-DeltaNet-style layers per config.layer_types): QLoRA/serving depend on specialised kernels; unverified by ORNEUR.
- Primary sources: https://huggingface.co/Qwen/Qwen3.5-4B, https://huggingface.co/api/models/Qwen/Qwen3.5-4B, https://huggingface.co/Qwen/Qwen3.5-4B/blob/main/config.json

#### `Qwen/Qwen3.5-9B`

- Exact revision: `c202236235762e1c871ad0ccb60c8ee5ba337b9a`; license: `apache-2.0` (name `None`, gated `False`)
- Architecture: `['Qwen3_5ForConditionalGeneration']` / `qwen3_5`; total parameters 9.65B; active dense (DENSE)
- Context: config `max_position_embeddings`=262144; vendor-supported=262144 (EXACT; extended 1010000); source `VENDOR_MODEL_CARD_CLAIM`; config-vs-vendor: **MATCH**; vendor text: "262,144 natively and extensible up to 1,010,000 tokens"
- Active parameters: None — source `DENSE`, verified=False
- Admission meaning: admitted for evaluation only; PEFT/QLoRA training is not proven until Stage-0/Stage-3 evidence exists (trainability_proven=False)
- Multimodality: text+image; tool-calling template: True; reasoning/thinking template: True
- Structured output: NOT_MODEL_NATIVE_EVIDENCE: enforced at system level by the ORNEUR Contract Engine; serving-stack constrained decoding not verified this phase
- Quantization: vendor variants observed none recorded; runtime 4-bit INFERRED_NOT_EXECUTED
- ESTIMATES (not measurements): QLoRA VRAM 8.8–14.8 GB; USD 0.257–0.428 per 1M training tokens; 5M-token pilot USD 1.29–2.14
- **Class reason:** passes all admission gates A-J on documented evidence: admitted for evaluation only; trainability is NOT proven
- Gates not passed: none
- Known caveats: Hybrid full/linear attention: QLoRA/serving depend on specialised kernels; unverified by ORNEUR.
- Primary sources: https://huggingface.co/Qwen/Qwen3.5-9B, https://huggingface.co/api/models/Qwen/Qwen3.5-9B, https://huggingface.co/Qwen/Qwen3.5-9B/blob/main/config.json

#### `Qwen/Qwen3.6-27B`

- Exact revision: `6a9e13bd6fc8f0983b9b99948120bc37f49c13e9`; license: `apache-2.0` (name `None`, gated `False`)
- Architecture: `['Qwen3_5ForConditionalGeneration']` / `qwen3_5`; total parameters 27.78B; active dense (DENSE)
- Context: config `max_position_embeddings`=262144; vendor-supported=262144 (EXACT; extended 1010000); source `VENDOR_MODEL_CARD_CLAIM`; config-vs-vendor: **MATCH**; vendor text: "262,144 natively and extensible up to 1,010,000 tokens"
- Active parameters: None — source `DENSE`, verified=False
- Admission meaning: admitted for evaluation only; PEFT/QLoRA training is not proven until Stage-0/Stage-3 evidence exists (trainability_proven=False)
- Multimodality: text+image; tool-calling template: True; reasoning/thinking template: True
- Structured output: NOT_MODEL_NATIVE_EVIDENCE: enforced at system level by the ORNEUR Contract Engine; serving-stack constrained decoding not verified this phase
- Quantization: vendor variants observed ['Qwen/Qwen3.6-27B-FP8']; runtime 4-bit INFERRED_NOT_EXECUTED
- ESTIMATES (not measurements): QLoRA VRAM 17.9–27.4 GB; USD 0.74–1.233 per 1M training tokens; 5M-token pilot USD 3.7–6.17
- **Class reason:** passes all admission gates A-J on documented evidence: admitted for evaluation only; trainability is NOT proven
- Gates not passed: none
- Known caveats: Hybrid full/linear attention; same architecture class as Qwen3.8-27B.
- Primary sources: https://huggingface.co/Qwen/Qwen3.6-27B, https://huggingface.co/api/models/Qwen/Qwen3.6-27B, https://huggingface.co/Qwen/Qwen3.6-27B/blob/main/config.json

#### `Qwen/Qwen3.8-27B`

- Exact revision: `1d4bf0f2ff6012fd82039f2fa52739d0dd7c60c0`; license: `apache-2.0` (name `None`, gated `False`)
- Architecture: `['Qwen3_5ForConditionalGeneration']` / `qwen3_5`; total parameters 27.78B; active dense (DENSE)
- Context: config `max_position_embeddings`=262144; vendor-supported=262144 (EXACT; extended 1000000); source `VENDOR_MODEL_CARD_CLAIM`; config-vs-vendor: **MATCH**; vendor text: "262,144 natively and extensible up to 1,000,000 tokens"
- Active parameters: None — source `DENSE`, verified=False
- Admission meaning: admitted for evaluation only; PEFT/QLoRA training is not proven until Stage-0/Stage-3 evidence exists (trainability_proven=False)
- Multimodality: text+image; tool-calling template: True; reasoning/thinking template: True
- Structured output: NOT_MODEL_NATIVE_EVIDENCE: enforced at system level by the ORNEUR Contract Engine; serving-stack constrained decoding not verified this phase
- Quantization: vendor variants observed ['Qwen/Qwen3.8-27B-FP8', 'nvidia/Qwen3.8-27B-NVFP4 (third-party)']; runtime 4-bit INFERRED_NOT_EXECUTED
- ESTIMATES (not measurements): QLoRA VRAM 17.9–27.4 GB; USD 0.74–1.233 per 1M training tokens; 5M-token pilot USD 3.7–6.17
- **Class reason:** passes all admission gates A-J on documented evidence: admitted for evaluation only; trainability is NOT proven
- Gates not passed: none
- Known caveats: Released 2026-08-05: young ecosystem; hybrid full/linear attention kernels; largest dense candidate that still fits a single 80GB GPU for QLoRA on paper.
- Primary sources: https://huggingface.co/Qwen/Qwen3.8-27B, https://huggingface.co/api/models/Qwen/Qwen3.8-27B, https://huggingface.co/Qwen/Qwen3.8-27B/blob/main/config.json

#### `allenai/Olmo-3-7B-Instruct`

- Exact revision: `6e5971d9eba42665f5bd5a0fcf047f299ce1dccc`; license: `apache-2.0` (name `None`, gated `False`)
- Architecture: `['Olmo3ForCausalLM']` / `olmo3`; total parameters 7.3B; active dense (DENSE)
- Context: config `max_position_embeddings`=65536; vendor-supported=None (None; extended None); source `NOT_CAPTURED_FROM_MODEL_CARD`; config-vs-vendor: **VENDOR_CLAIM_NOT_CAPTURED**
- Active parameters: None — source `DENSE`, verified=False
- Admission meaning: admitted for evaluation only; PEFT/QLoRA training is not proven until Stage-0/Stage-3 evidence exists (trainability_proven=False)
- Multimodality: text; tool-calling template: True; reasoning/thinking template: False
- Structured output: NOT_MODEL_NATIVE_EVIDENCE: enforced at system level by the ORNEUR Contract Engine; serving-stack constrained decoding not verified this phase
- Quantization: vendor variants observed none recorded; runtime 4-bit INFERRED_NOT_EXECUTED
- ESTIMATES (not measurements): QLoRA VRAM 7.7–13.1 GB; USD 0.194–0.324 per 1M training tokens; 5M-token pilot USD 0.97–1.62
- **Class reason:** passes all admission gates A-J on documented evidence: admitted for evaluation only; trainability is NOT proven
- Gates not passed: none
- Known caveats: Fully-open lineage (data/training documented by vendor, not re-verified); 65k context; released 2025-10 (older than other candidates).
- Primary sources: https://huggingface.co/allenai/Olmo-3-7B-Instruct, https://huggingface.co/api/models/allenai/Olmo-3-7B-Instruct, https://huggingface.co/allenai/Olmo-3-7B-Instruct/blob/main/config.json

#### `google/gemma-4-12B-it`

- Exact revision: `707f0a3b8a3c7ad586ed01e27eafbad8a27dd0f7`; license: `apache-2.0` (name `None`, gated `False`)
- Architecture: `['Gemma4UnifiedForConditionalGeneration']` / `gemma4_unified`; total parameters 11.96B; active dense (DENSE)
- Context: config `max_position_embeddings`=262144; vendor-supported=262144 (SHORTHAND_K1024_ASSUMED; extended None); source `VENDOR_MODEL_CARD_TABLE_COLUMN_INFERRED`; config-vs-vendor: **MATCH**; vendor text: "256K tokens (family table, column inferred from parameter row)"
- Active parameters: None — source `DENSE`, verified=False
- Admission meaning: admitted for evaluation only; PEFT/QLoRA training is not proven until Stage-0/Stage-3 evidence exists (trainability_proven=False)
- Multimodality: any-to-any (pipeline tag); tool-calling template: True; reasoning/thinking template: True
- Structured output: NOT_MODEL_NATIVE_EVIDENCE: enforced at system level by the ORNEUR Contract Engine; serving-stack constrained decoding not verified this phase
- Quantization: vendor variants observed ['google/gemma-4-12B-it-qat-w4a16-ct', 'google/gemma-4-12B-it-qat-q4_0-gguf']; runtime 4-bit INFERRED_NOT_EXECUTED
- ESTIMATES (not measurements): QLoRA VRAM 10.0–16.4 GB; USD 0.318–0.531 per 1M training tokens; 5M-token pilot USD 1.59–2.66
- **Class reason:** passes all admission gates A-J on documented evidence: admitted for evaluation only; trainability is NOT proven
- Gates not passed: none
- Known caveats: Architecture Gemma4Unified: vLLM docs list it without a LoRA-support mark; repo has no LICENSE file (Apache-2.0 from card metadata).
- Primary sources: https://huggingface.co/google/gemma-4-12B-it, https://huggingface.co/api/models/google/gemma-4-12B-it, https://huggingface.co/google/gemma-4-12B-it/blob/main/config.json

#### `google/gemma-4-31B-it`

- Exact revision: `842da3794eaa0b77d5f08bae87a17459d91ff475`; license: `apache-2.0` (name `None`, gated `False`)
- Architecture: `['Gemma4ForConditionalGeneration']` / `gemma4`; total parameters 31.27B; active dense (DENSE)
- Context: config `max_position_embeddings`=262144; vendor-supported=262144 (SHORTHAND_K1024_ASSUMED; extended None); source `VENDOR_MODEL_CARD_TABLE_COLUMN_INFERRED`; config-vs-vendor: **MATCH**; vendor text: "256K tokens (family table, column inferred from parameter row)"
- Active parameters: None — source `DENSE`, verified=False
- Admission meaning: admitted for evaluation only; PEFT/QLoRA training is not proven until Stage-0/Stage-3 evidence exists (trainability_proven=False)
- Multimodality: text+image; tool-calling template: True; reasoning/thinking template: True
- Structured output: NOT_MODEL_NATIVE_EVIDENCE: enforced at system level by the ORNEUR Contract Engine; serving-stack constrained decoding not verified this phase
- Quantization: vendor variants observed ['google/gemma-4-31B-it-qat-w4a16-ct']; runtime 4-bit INFERRED_NOT_EXECUTED
- ESTIMATES (not measurements): QLoRA VRAM 19.6–29.9 GB; USD 0.833–1.388 per 1M training tokens; 5M-token pilot USD 4.17–6.94
- **Class reason:** passes all admission gates A-J on documented evidence: admitted for evaluation only; trainability is NOT proven
- Gates not passed: none
- Known caveats: 31.3B dense: QLoRA fits one 80GB GPU on paper; no LICENSE file in repo.
- Primary sources: https://huggingface.co/google/gemma-4-31B-it, https://huggingface.co/api/models/google/gemma-4-31B-it, https://huggingface.co/google/gemma-4-31B-it/blob/main/config.json

#### `google/gemma-4-E4B-it`

- Exact revision: `ee0ef6023621cff504d758262d4e04895a5af4a2`; license: `apache-2.0` (name `None`, gated `False`)
- Architecture: `['Gemma4ForConditionalGeneration']` / `gemma4`; total parameters 8.0B; active dense (DENSE)
- Context: config `max_position_embeddings`=131072; vendor-supported=131072 (SHORTHAND_K1024_ASSUMED; extended None); source `VENDOR_MODEL_CARD_TABLE_COLUMN_INFERRED`; config-vs-vendor: **MATCH**; vendor text: "128K tokens (family table, column inferred from parameter row)"
- Active parameters: None — source `DENSE`, verified=False
- Admission meaning: admitted for evaluation only; PEFT/QLoRA training is not proven until Stage-0/Stage-3 evidence exists (trainability_proven=False)
- Multimodality: text+image+audio (per vLLM listing T+I+V+A); tool-calling template: True; reasoning/thinking template: True
- Structured output: NOT_MODEL_NATIVE_EVIDENCE: enforced at system level by the ORNEUR Contract Engine; serving-stack constrained decoding not verified this phase
- Quantization: vendor variants observed ['google/gemma-4-E4B-it-qat-w4a16-ct']; runtime 4-bit INFERRED_NOT_EXECUTED
- ESTIMATES (not measurements): QLoRA VRAM 8.0–13.6 GB; USD 0.213–0.355 per 1M training tokens; 5M-token pilot USD 1.06–1.77
- **Class reason:** passes all admission gates A-J on documented evidence: admitted for evaluation only; trainability is NOT proven
- Gates not passed: none
- Known caveats: 8.0B stored parameters include per-layer embeddings; 'E4B' effective size is a vendor label (not verified here). | Repo has no LICENSE file; Apache-2.0 comes from model-card metadata only.
- Primary sources: https://huggingface.co/google/gemma-4-E4B-it, https://huggingface.co/api/models/google/gemma-4-E4B-it, https://huggingface.co/google/gemma-4-E4B-it/blob/main/config.json

#### `ibm-granite/granite-4.2-30b`

- Exact revision: `9e668ce1c538387ef24d3644e9b0606647762636`; license: `apache-2.0` (name `None`, gated `False`)
- Architecture: `['GraniteForCausalLM']` / `granite`; total parameters 29.28B; active dense (DENSE)
- Context: config `max_position_embeddings`=131072; vendor-supported=131072 (SHORTHAND_K1024_ASSUMED; extended 524288); source `VENDOR_MODEL_CARD_CLAIM`; config-vs-vendor: **MATCH**; vendor text: "Natively Supports 128K (Long-context extension to 512K)"
- Active parameters: None — source `DENSE`, verified=False
- Admission meaning: admitted for evaluation only; PEFT/QLoRA training is not proven until Stage-0/Stage-3 evidence exists (trainability_proven=False)
- Multimodality: text; tool-calling template: True; reasoning/thinking template: True
- Structured output: NOT_MODEL_NATIVE_EVIDENCE: enforced at system level by the ORNEUR Contract Engine; serving-stack constrained decoding not verified this phase
- Quantization: vendor variants observed ['FP8', 'MXFP4', 'NVFP4', 'GGUF']; runtime 4-bit INFERRED_NOT_EXECUTED
- ESTIMATES (not measurements): QLoRA VRAM 18.6–28.5 GB; USD 0.78–1.299 per 1M training tokens; 5M-token pilot USD 3.9–6.49
- **Class reason:** passes all admission gates A-J on documented evidence: admitted for evaluation only; trainability is NOT proven
- Gates not passed: none
- Known caveats: 29.3B dense; QLoRA fits one 80GB GPU on paper.
- Primary sources: https://huggingface.co/ibm-granite/granite-4.2-30b, https://huggingface.co/api/models/ibm-granite/granite-4.2-30b, https://huggingface.co/ibm-granite/granite-4.2-30b/blob/main/config.json

#### `ibm-granite/granite-4.2-3b`

- Exact revision: `e459acceac81e5fe67c07d9cfc72329a332e7eb1`; license: `apache-2.0` (name `None`, gated `False`)
- Architecture: `['GraniteForCausalLM']` / `granite`; total parameters 3.66B; active dense (DENSE)
- Context: config `max_position_embeddings`=131072; vendor-supported=131072 (SHORTHAND_K1024_ASSUMED; extended 524288); source `VENDOR_MODEL_CARD_CLAIM`; config-vs-vendor: **MATCH**; vendor text: "Natively Supports 128K (Long-context extension to 512K)"
- Active parameters: None — source `DENSE`, verified=False
- Admission meaning: admitted for evaluation only; PEFT/QLoRA training is not proven until Stage-0/Stage-3 evidence exists (trainability_proven=False)
- Multimodality: text; tool-calling template: True; reasoning/thinking template: True
- Structured output: NOT_MODEL_NATIVE_EVIDENCE: enforced at system level by the ORNEUR Contract Engine; serving-stack constrained decoding not verified this phase
- Quantization: vendor variants observed ['FP8', 'MXFP4', 'NVFP4', 'GGUF']; runtime 4-bit INFERRED_NOT_EXECUTED
- ESTIMATES (not measurements): QLoRA VRAM 5.8–10.6 GB; USD 0.097–0.162 per 1M training tokens; 5M-token pilot USD 0.48–0.81
- **Class reason:** passes all admission gates A-J on documented evidence: admitted for evaluation only; trainability is NOT proven
- Gates not passed: none
- Known caveats: Config declares GraniteForCausalLM (dense); vLLM docs list Granite 3.x model names for this class: 4.2 serving is unverified.
- Primary sources: https://huggingface.co/ibm-granite/granite-4.2-3b, https://huggingface.co/api/models/ibm-granite/granite-4.2-3b, https://huggingface.co/ibm-granite/granite-4.2-3b/blob/main/config.json

#### `ibm-granite/granite-4.2-8b`

- Exact revision: `f8de16cdcdbc6c779ca517604e050d82cc119e44`; license: `apache-2.0` (name `None`, gated `False`)
- Architecture: `['GraniteForCausalLM']` / `granite`; total parameters 8.79B; active dense (DENSE)
- Context: config `max_position_embeddings`=131072; vendor-supported=131072 (SHORTHAND_K1024_ASSUMED; extended 524288); source `VENDOR_MODEL_CARD_CLAIM`; config-vs-vendor: **MATCH**; vendor text: "Natively Supports 128K (Long-context extension to 512K)"
- Active parameters: None — source `DENSE`, verified=False
- Admission meaning: admitted for evaluation only; PEFT/QLoRA training is not proven until Stage-0/Stage-3 evidence exists (trainability_proven=False)
- Multimodality: text; tool-calling template: True; reasoning/thinking template: True
- Structured output: NOT_MODEL_NATIVE_EVIDENCE: enforced at system level by the ORNEUR Contract Engine; serving-stack constrained decoding not verified this phase
- Quantization: vendor variants observed ['FP8', 'MXFP4', 'NVFP4', 'GGUF']; runtime 4-bit INFERRED_NOT_EXECUTED
- ESTIMATES (not measurements): QLoRA VRAM 8.4–14.2 GB; USD 0.234–0.39 per 1M training tokens; 5M-token pilot USD 1.17–1.95
- **Class reason:** passes all admission gates A-J on documented evidence: admitted for evaluation only; trainability is NOT proven
- Gates not passed: none
- Known caveats: As above: GraniteForCausalLM dense; 4.2 serving unverified.
- Primary sources: https://huggingface.co/ibm-granite/granite-4.2-8b, https://huggingface.co/api/models/ibm-granite/granite-4.2-8b, https://huggingface.co/ibm-granite/granite-4.2-8b/blob/main/config.json

#### `microsoft/Phi-4-mini-instruct`

- Exact revision: `cfbefacb99257ffa30c83adab238a50856ac3083`; license: `mit` (name `None`, gated `False`)
- Architecture: `['Phi3ForCausalLM']` / `phi3`; total parameters 3.84B; active dense (DENSE)
- Context: config `max_position_embeddings`=131072; vendor-supported=131072 (SHORTHAND_K1024_ASSUMED; extended None); source `VENDOR_MODEL_CARD_CLAIM`; config-vs-vendor: **MATCH**; vendor text: "128K tokens"
- Active parameters: None — source `DENSE`, verified=False
- Admission meaning: admitted for evaluation only; PEFT/QLoRA training is not proven until Stage-0/Stage-3 evidence exists (trainability_proven=False)
- Multimodality: text; tool-calling template: True; reasoning/thinking template: False
- Structured output: NOT_MODEL_NATIVE_EVIDENCE: enforced at system level by the ORNEUR Contract Engine; serving-stack constrained decoding not verified this phase
- Quantization: vendor variants observed none recorded; runtime 4-bit INFERRED_NOT_EXECUTED
- ESTIMATES (not measurements): QLoRA VRAM 5.9–10.7 GB; USD 0.102–0.17 per 1M training tokens; 5M-token pilot USD 0.51–0.85
- **Class reason:** passes all admission gates A-J on documented evidence: admitted for evaluation only; trainability is NOT proven
- Gates not passed: none
- Known caveats: 3.8B, 128k context; Phi-4 (14B) control had a 16k context limit.
- Primary sources: https://huggingface.co/microsoft/Phi-4-mini-instruct, https://huggingface.co/api/models/microsoft/Phi-4-mini-instruct, https://huggingface.co/microsoft/Phi-4-mini-instruct/blob/main/config.json

#### `mistralai/Ministral-3-14B-Reasoning-2512`

- Exact revision: `51f9210f3cd20f3452a80d5819d15dc61cc50630`; license: `apache-2.0` (name `None`, gated `False`)
- Architecture: `['Mistral3ForConditionalGeneration']` / `mistral3`; total parameters 13.95B; active dense (DENSE)
- Context: config `max_position_embeddings`=262144; vendor-supported=262144 (SHORTHAND_K1024_ASSUMED; extended None); source `VENDOR_MODEL_CARD_CLAIM`; config-vs-vendor: **MATCH**; vendor text: "Supports a 256k context window"
- Active parameters: None — source `DENSE`, verified=False
- Admission meaning: admitted for evaluation only; PEFT/QLoRA training is not proven until Stage-0/Stage-3 evidence exists (trainability_proven=False)
- Multimodality: text+image; tool-calling template: True; reasoning/thinking template: True
- Structured output: NOT_MODEL_NATIVE_EVIDENCE: enforced at system level by the ORNEUR Contract Engine; serving-stack constrained decoding not verified this phase
- Quantization: vendor variants observed none recorded; runtime 4-bit INFERRED_NOT_EXECUTED
- ESTIMATES (not measurements): QLoRA VRAM 11.0–17.8 GB; USD 0.371–0.619 per 1M training tokens; 5M-token pilot USD 1.85–3.09
- **Class reason:** passes all admission gates A-J on documented evidence: admitted for evaluation only; trainability is NOT proven
- Gates not passed: none
- Known caveats: Reasoning post-trained variant; same mistral-common/tekken caveat.
- Primary sources: https://huggingface.co/mistralai/Ministral-3-14B-Reasoning-2512, https://huggingface.co/api/models/mistralai/Ministral-3-14B-Reasoning-2512, https://huggingface.co/mistralai/Ministral-3-14B-Reasoning-2512/blob/main/config.json

### TEACHER_REFERENCE

#### `deepseek-ai/DeepSeek-V4-Pro-0813`

- Exact revision: `72e1d3230f6c080a530b0a1d46f8eb4602340597`; license: `mit` (name `None`, gated `False`)
- Architecture: `['DeepseekV4ForCausalLM']` / `deepseek_v4`; total parameters 1650.5B; active not recorded (NOT_RECORDED)
- Context: config `max_position_embeddings`=1048576; vendor-supported=None (None; extended None); source `NOT_CAPTURED_FROM_MODEL_CARD`; config-vs-vendor: **VENDOR_CLAIM_NOT_CAPTURED**
- Active parameters: None — source `NOT_RECORDED`, verified=False
- Admission meaning: admitted for evaluation only; PEFT/QLoRA training is not proven until Stage-0/Stage-3 evidence exists (trainability_proven=False)
- Multimodality: text; tool-calling template: None; reasoning/thinking template: None
- Structured output: NOT_MODEL_NATIVE_EVIDENCE: enforced at system level by the ORNEUR Contract Engine; serving-stack constrained decoding not verified this phase
- Quantization: vendor variants observed none recorded; runtime 4-bit INFERRED_NOT_EXECUTED
- ESTIMATES (not measurements): QLoRA VRAM 829.2–1163.3 GB; USD 43.947–73.244 per 1M training tokens; 5M-token pilot USD 219.74–366.22
- **Class reason:** too large for the first-stage budget; studied as reference, not admitted as a base
- Gates not passed: D_tokenizer_template=UNVERIFIED (no chat template found); E_peft_qlora_feasible=FAIL (1650.5B exceeds single-GPU QLoRA envelope for the first-stage budget); F_training_cost_vs_budget=FAIL (5M-token pilot ~USD 219.74-366.22 (<= 10% of USD 111); est. QLoRA VRAM 829.2-1163.3 GB vs 80 GB)
- Known caveats: 1.65T stored parameters (mostly int8); 1M context; transformers has deepseek_v4; teacher/reference only.
- Primary sources: https://huggingface.co/deepseek-ai/DeepSeek-V4-Pro-0813, https://huggingface.co/api/models/deepseek-ai/DeepSeek-V4-Pro-0813, https://huggingface.co/deepseek-ai/DeepSeek-V4-Pro-0813/blob/main/config.json

#### `deepseek-ai/DeepSeek-V4.1-Flash`

- Exact revision: `dba1be0a40aa45a94ad051997016db3960a90277`; license: `mit` (name `None`, gated `False`)
- Architecture: `['DeepseekV41ForCausalLM']` / `deepseek_v41`; total parameters 763.21B; active not recorded (NOT_RECORDED)
- Context: config `max_position_embeddings`=1048576; vendor-supported=1048576 (SHORTHAND_K1024_ASSUMED; extended None); source `VENDOR_MODEL_CARD_CLAIM`; config-vs-vendor: **MATCH**; vendor text: "`context_window` 1M tokens"
- Active parameters: None — source `NOT_RECORDED`, verified=False; note: vendor table lists '8B / 16B' (input/output path per earlier landscape doc); column attribution not verified
- Admission meaning: admitted for evaluation only; PEFT/QLoRA training is not proven until Stage-0/Stage-3 evidence exists (trainability_proven=False)
- Multimodality: text+image; tool-calling template: None; reasoning/thinking template: None
- Structured output: NOT_MODEL_NATIVE_EVIDENCE: enforced at system level by the ORNEUR Contract Engine; serving-stack constrained decoding not verified this phase
- Quantization: vendor variants observed none recorded; runtime 4-bit INFERRED_NOT_EXECUTED
- ESTIMATES (not measurements): QLoRA VRAM 385.6–542.2 GB; USD 20.321–33.869 per 1M training tokens; 5M-token pilot USD 101.61–169.34
- **Class reason:** too large for the first-stage budget; studied as reference, not admitted as a base
- Gates not passed: C_architecture_documented=UNVERIFIED (config.json present (DeepseekV41ForCausalLM) but no native transformers/vLLM implementation found at collection time); D_tokenizer_template=UNVERIFIED (no chat template found); E_peft_qlora_feasible=FAIL (763.21B exceeds single-GPU QLoRA envelope for the first-stage budget); F_training_cost_vs_budget=FAIL (5M-token pilot ~USD 101.61-169.34 (<= 10% of USD 111); est. QLoRA VRAM 385.6-542.2 GB vs 80 GB); G_inference_path=FAIL (no transformers-native or vLLM-listed inference path found); I_no_proprietary_only_stack=UNVERIFIED (no open serving stack identified); J_ecosystem_maturity=UNVERIFIED (transformers-native=False, vLLM-listed=False)
- Known caveats: 763B stored parameters; architecture deepseek_v41 is not in transformers main or the vLLM supported-models docs at collection time: reference only.
- Primary sources: https://huggingface.co/deepseek-ai/DeepSeek-V4.1-Flash, https://huggingface.co/api/models/deepseek-ai/DeepSeek-V4.1-Flash, https://huggingface.co/deepseek-ai/DeepSeek-V4.1-Flash/blob/main/config.json

#### `mistralai/Mistral-Large-3-675B-Instruct-2512`

- Exact revision: `383ffea2c7d60dfd44ca960e8e691709d4fdb9cd`; license: `apache-2.0` (name `None`, gated `False`)
- Architecture: `None` / `None`; total parameters NoneB; active 41.0 (VENDOR_MODEL_CARD_CLAIM)
- Context: config `max_position_embeddings`=None; vendor-supported=262144 (SHORTHAND_K1024_ASSUMED; extended None); source `VENDOR_MODEL_CARD_CLAIM`; config-vs-vendor: **CONFIG_NOT_AVAILABLE**; vendor text: "Supports a 256k context window"
- Active parameters: 41.0 — source `VENDOR_MODEL_CARD_CLAIM`, verified=False; note: the same card also states 39B active for the language model alone
- Admission meaning: admitted for evaluation only; PEFT/QLoRA training is not proven until Stage-0/Stage-3 evidence exists (trainability_proven=False)
- Multimodality: text; tool-calling template: True; reasoning/thinking template: True
- Structured output: NOT_MODEL_NATIVE_EVIDENCE: enforced at system level by the ORNEUR Contract Engine; serving-stack constrained decoding not verified this phase
- Quantization: vendor variants observed none recorded; runtime 4-bit INFERRED_NOT_EXECUTED
- **Class reason:** too large for the first-stage budget; studied as reference, not admitted as a base
- Gates not passed: C_architecture_documented=UNVERIFIED (no config.json retrievable); E_peft_qlora_feasible=UNVERIFIED (no parameter total); F_training_cost_vs_budget=UNVERIFIED (no parameter total); G_inference_path=FAIL (no transformers-native or vLLM-listed inference path found); H_artifacts_verifiable=UNVERIFIED (no safetensors metadata at the pinned revision); I_no_proprietary_only_stack=UNVERIFIED (no open serving stack identified); J_ecosystem_maturity=UNVERIFIED (transformers-native=False, vLLM-listed=False)
- Known caveats: Native Mistral format only (no safetensors metadata/config.json via the HF API): artifact verification partial.
- Primary sources: https://huggingface.co/mistralai/Mistral-Large-3-675B-Instruct-2512, https://huggingface.co/api/models/mistralai/Mistral-Large-3-675B-Instruct-2512, https://huggingface.co/mistralai/Mistral-Large-3-675B-Instruct-2512/blob/main/config.json

#### `mistralai/Mistral-Small-4-119B-2603`

- Exact revision: `a11f36bebf709121056b1dbcc943d1c6afbe494d`; license: `apache-2.0` (name `None`, gated `False`)
- Architecture: `['Mistral3ForConditionalGeneration']` / `mistral3`; total parameters 119.4B; active 6.5 (VENDOR_MODEL_CARD_CLAIM)
- Context: config `max_position_embeddings`=1048576; vendor-supported=262144 (SHORTHAND_K1024_ASSUMED; extended None); source `VENDOR_MODEL_CARD_CLAIM`; config-vs-vendor: **DIFFERS**; vendor text: "256k context length"
- Active parameters: 6.5 — source `VENDOR_MODEL_CARD_CLAIM`, verified=False
- Admission meaning: admitted for evaluation only; PEFT/QLoRA training is not proven until Stage-0/Stage-3 evidence exists (trainability_proven=False)
- Multimodality: text+image; tool-calling template: True; reasoning/thinking template: True
- Structured output: NOT_MODEL_NATIVE_EVIDENCE: enforced at system level by the ORNEUR Contract Engine; serving-stack constrained decoding not verified this phase
- Quantization: vendor variants observed none recorded; runtime 4-bit INFERRED_NOT_EXECUTED
- ESTIMATES (not measurements): QLoRA VRAM 63.7–91.6 GB; USD 0.173–0.288 per 1M training tokens; 5M-token pilot USD 0.86–1.44
- **Class reason:** too large for the first-stage budget; studied as reference, not admitted as a base
- Gates not passed: E_peft_qlora_feasible=FAIL (119.4B exceeds single-GPU QLoRA envelope for the first-stage budget); F_training_cost_vs_budget=FAIL (5M-token pilot ~USD 0.86-1.44 (<= 10% of USD 111); est. QLoRA VRAM 63.7-91.6 GB vs 80 GB)
- Known caveats: 119B (FP8 weights, 128 experts): teacher/reference only; provider or large-GPU serving needed.
- Primary sources: https://huggingface.co/mistralai/Mistral-Small-4-119B-2603, https://huggingface.co/api/models/mistralai/Mistral-Small-4-119B-2603, https://huggingface.co/mistralai/Mistral-Small-4-119B-2603/blob/main/config.json

#### `openai/gpt-oss-120b`

- Exact revision: `b5c939de8f754692c1647ca79fbf85e8c1e70f8a`; license: `apache-2.0` (name `None`, gated `False`)
- Architecture: `['GptOssForCausalLM']` / `gpt_oss`; total parameters 116.83B; active 5.1 (VENDOR_MODEL_CARD_CLAIM)
- Context: config `max_position_embeddings`=131072; vendor-supported=None (None; extended None); source `NOT_CAPTURED_FROM_MODEL_CARD`; config-vs-vendor: **VENDOR_CLAIM_NOT_CAPTURED**
- Active parameters: 5.1 — source `VENDOR_MODEL_CARD_CLAIM`, verified=False
- Admission meaning: admitted for evaluation only; PEFT/QLoRA training is not proven until Stage-0/Stage-3 evidence exists (trainability_proven=False)
- Multimodality: text; tool-calling template: True; reasoning/thinking template: True
- Structured output: NOT_MODEL_NATIVE_EVIDENCE: enforced at system level by the ORNEUR Contract Engine; serving-stack constrained decoding not verified this phase
- Quantization: vendor variants observed none recorded; runtime 4-bit INFERRED_NOT_EXECUTED
- ESTIMATES (not measurements): QLoRA VRAM 62.4–89.8 GB; USD 0.136–0.226 per 1M training tokens; 5M-token pilot USD 0.68–1.13
- **Class reason:** too large for the first-stage budget; studied as reference, not admitted as a base
- Gates not passed: E_peft_qlora_feasible=FAIL (116.83B exceeds single-GPU QLoRA envelope for the first-stage budget); F_training_cost_vs_budget=FAIL (5M-token pilot ~USD 0.68-1.13 (<= 10% of USD 111); est. QLoRA VRAM 62.4-89.8 GB vs 80 GB)
- Known caveats: 116.8B stored parameters (MXFP4 experts): teacher/reference; hostable on one 80GB-class GPU per vendor claim (not verified here).
- Primary sources: https://huggingface.co/openai/gpt-oss-120b, https://huggingface.co/api/models/openai/gpt-oss-120b, https://huggingface.co/openai/gpt-oss-120b/blob/main/config.json

#### `zai-org/GLM-5.3-Flash`

- Exact revision: `eb9eb208eb0d988989d07a6a12d0fdeb5f52574a`; license: `mit` (name `None`, gated `False`)
- Architecture: `['Glm5NextForConditionalGeneration']` / `glm5_next`; total parameters 321.32B; active 18.0 (VENDOR_MODEL_CARD_CLAIM)
- Context: config `max_position_embeddings`=1048576; vendor-supported=None (None; extended None); source `NOT_CAPTURED_FROM_MODEL_CARD`; config-vs-vendor: **VENDOR_CLAIM_NOT_CAPTURED**
- Active parameters: 18.0 — source `VENDOR_MODEL_CARD_CLAIM`, verified=False
- Admission meaning: admitted for evaluation only; PEFT/QLoRA training is not proven until Stage-0/Stage-3 evidence exists (trainability_proven=False)
- Multimodality: text+image; tool-calling template: True; reasoning/thinking template: True
- Structured output: NOT_MODEL_NATIVE_EVIDENCE: enforced at system level by the ORNEUR Contract Engine; serving-stack constrained decoding not verified this phase
- Quantization: vendor variants observed ['nvidia/GLM-5.3-Flash-NVFP4 (third-party)']; runtime 4-bit INFERRED_NOT_EXECUTED
- ESTIMATES (not measurements): QLoRA VRAM 164.7–232.9 GB; USD 0.479–0.799 per 1M training tokens; 5M-token pilot USD 2.4–4.0
- **Class reason:** too large for the first-stage budget; studied as reference, not admitted as a base
- Gates not passed: E_peft_qlora_feasible=FAIL (321.32B exceeds single-GPU QLoRA envelope for the first-stage budget); F_training_cost_vs_budget=FAIL (5M-token pilot ~USD 2.4-4.0 (<= 10% of USD 111); est. QLoRA VRAM 164.7-232.9 GB vs 80 GB); J_ecosystem_maturity=UNVERIFIED (transformers-native=True, vLLM-listed=False)
- Known caveats: 321B stored parameters, MIT; architecture glm5_next in transformers main but not in vLLM docs at collection time.
- Primary sources: https://huggingface.co/zai-org/GLM-5.3-Flash, https://huggingface.co/api/models/zai-org/GLM-5.3-Flash, https://huggingface.co/zai-org/GLM-5.3-Flash/blob/main/config.json

### FUTURE_REASON_CANDIDATE

#### `Qwen/Qwen3.5-35B-A3B`

- Exact revision: `59d61f3ce65a6d9863b86d2e96597125219dc754`; license: `apache-2.0` (name `None`, gated `False`)
- Architecture: `['Qwen3_5MoeForConditionalGeneration']` / `qwen3_5_moe`; total parameters 35.95B; active 3.0 (VENDOR_MODEL_CARD_CLAIM)
- Context: config `max_position_embeddings`=262144; vendor-supported=262144 (EXACT; extended 1010000); source `VENDOR_MODEL_CARD_CLAIM`; config-vs-vendor: **MATCH**; vendor text: "262,144 natively and extensible up to 1,010,000 tokens"
- Active parameters: 3.0 — source `VENDOR_MODEL_CARD_CLAIM`, verified=False
- Admission meaning: admitted for evaluation only; PEFT/QLoRA training is not proven until Stage-0/Stage-3 evidence exists (trainability_proven=False)
- Multimodality: text+image; tool-calling template: True; reasoning/thinking template: True
- Structured output: NOT_MODEL_NATIVE_EVIDENCE: enforced at system level by the ORNEUR Contract Engine; serving-stack constrained decoding not verified this phase
- Quantization: vendor variants observed none recorded; runtime 4-bit INFERRED_NOT_EXECUTED
- ESTIMATES (not measurements): QLoRA VRAM 22.0–33.2 GB; USD 0.08–0.133 per 1M training tokens; 5M-token pilot USD 0.4–0.67
- **Class reason:** fits the size envelope but gate(s) not passed: E_peft_qlora_feasible=UNVERIFIED
- Gates not passed: E_peft_qlora_feasible=UNVERIFIED (MoE: adapter/QLoRA support over fused or quantised experts is not verified)
- Known caveats: MoE (256 experts, 8 active): QLoRA over fused experts not verified.
- Primary sources: https://huggingface.co/Qwen/Qwen3.5-35B-A3B, https://huggingface.co/api/models/Qwen/Qwen3.5-35B-A3B, https://huggingface.co/Qwen/Qwen3.5-35B-A3B/blob/main/config.json

#### `Qwen/Qwen3.6-35B-A3B`

- Exact revision: `995ad96eacd98c81ed38be0c5b274b04031597b0`; license: `apache-2.0` (name `None`, gated `False`)
- Architecture: `['Qwen3_5MoeForConditionalGeneration']` / `qwen3_5_moe`; total parameters 35.95B; active 3.0 (VENDOR_MODEL_CARD_CLAIM)
- Context: config `max_position_embeddings`=262144; vendor-supported=262144 (EXACT; extended 1010000); source `VENDOR_MODEL_CARD_CLAIM`; config-vs-vendor: **MATCH**; vendor text: "262,144 natively and extensible up to 1,010,000 tokens"
- Active parameters: 3.0 — source `VENDOR_MODEL_CARD_CLAIM`, verified=False
- Admission meaning: admitted for evaluation only; PEFT/QLoRA training is not proven until Stage-0/Stage-3 evidence exists (trainability_proven=False)
- Multimodality: text+image; tool-calling template: True; reasoning/thinking template: True
- Structured output: NOT_MODEL_NATIVE_EVIDENCE: enforced at system level by the ORNEUR Contract Engine; serving-stack constrained decoding not verified this phase
- Quantization: vendor variants observed none recorded; runtime 4-bit INFERRED_NOT_EXECUTED
- ESTIMATES (not measurements): QLoRA VRAM 22.0–33.2 GB; USD 0.08–0.133 per 1M training tokens; 5M-token pilot USD 0.4–0.67
- **Class reason:** fits the size envelope but gate(s) not passed: E_peft_qlora_feasible=UNVERIFIED
- Gates not passed: E_peft_qlora_feasible=UNVERIFIED (MoE: adapter/QLoRA support over fused or quantised experts is not verified)
- Known caveats: MoE (256 experts, 8 active): QLoRA over fused experts not verified; attractive FAST-serving profile if trainable.
- Primary sources: https://huggingface.co/Qwen/Qwen3.6-35B-A3B, https://huggingface.co/api/models/Qwen/Qwen3.6-35B-A3B, https://huggingface.co/Qwen/Qwen3.6-35B-A3B/blob/main/config.json

#### `google/gemma-4-12B`

- Exact revision: `023679ed352de9bb66cc873c9009ce3482585c08`; license: `apache-2.0` (name `None`, gated `False`)
- Architecture: `['Gemma4UnifiedForConditionalGeneration']` / `gemma4_unified`; total parameters 11.96B; active dense (DENSE)
- Context: config `max_position_embeddings`=262144; vendor-supported=262144 (SHORTHAND_K1024_ASSUMED; extended None); source `VENDOR_MODEL_CARD_TABLE_COLUMN_INFERRED`; config-vs-vendor: **MATCH**; vendor text: "256K tokens (family table, column inferred from parameter row)"
- Active parameters: None — source `DENSE`, verified=False
- Admission meaning: admitted for evaluation only; PEFT/QLoRA training is not proven until Stage-0/Stage-3 evidence exists (trainability_proven=False)
- Multimodality: any-to-any (pipeline tag); tool-calling template: None; reasoning/thinking template: None
- Structured output: NOT_MODEL_NATIVE_EVIDENCE: enforced at system level by the ORNEUR Contract Engine; serving-stack constrained decoding not verified this phase
- Quantization: vendor variants observed none recorded; runtime 4-bit INFERRED_NOT_EXECUTED
- ESTIMATES (not measurements): QLoRA VRAM 10.0–16.4 GB; USD 0.318–0.531 per 1M training tokens; 5M-token pilot USD 1.59–2.66
- **Class reason:** fits the size envelope but gate(s) not passed: D_tokenizer_template=UNVERIFIED
- Gates not passed: D_tokenizer_template=UNVERIFIED (no chat template found)
- Known caveats: Pretrained (non-'it') variant of the 12B; Gemma4Unified architecture; no LICENSE file in repo.
- Primary sources: https://huggingface.co/google/gemma-4-12B, https://huggingface.co/api/models/google/gemma-4-12B, https://huggingface.co/google/gemma-4-12B/blob/main/config.json

#### `google/gemma-4-26B-A4B-it`

- Exact revision: `4d7ae4984b7db7de8f8457170b3f1a419ee76d52`; license: `apache-2.0` (name `None`, gated `False`)
- Architecture: `['Gemma4ForConditionalGeneration']` / `gemma4`; total parameters 25.81B; active 3.8 (VENDOR_MODEL_CARD_CLAIM)
- Context: config `max_position_embeddings`=262144; vendor-supported=262144 (SHORTHAND_K1024_ASSUMED; extended None); source `VENDOR_MODEL_CARD_CLAIM`; config-vs-vendor: **MATCH**; vendor text: "256K tokens"
- Active parameters: 3.8 — source `VENDOR_MODEL_CARD_CLAIM`, verified=False; note: model name says A4B; card table says 3.8B active and 25.2B total (safetensors total is 25.8B)
- Admission meaning: admitted for evaluation only; PEFT/QLoRA training is not proven until Stage-0/Stage-3 evidence exists (trainability_proven=False)
- Multimodality: text+image; tool-calling template: True; reasoning/thinking template: True
- Structured output: NOT_MODEL_NATIVE_EVIDENCE: enforced at system level by the ORNEUR Contract Engine; serving-stack constrained decoding not verified this phase
- Quantization: vendor variants observed none recorded; runtime 4-bit INFERRED_NOT_EXECUTED
- ESTIMATES (not measurements): QLoRA VRAM 16.9–26.1 GB; USD 0.101–0.169 per 1M training tokens; 5M-token pilot USD 0.51–0.85
- **Class reason:** fits the size envelope but gate(s) not passed: E_peft_qlora_feasible=UNVERIFIED
- Gates not passed: E_peft_qlora_feasible=UNVERIFIED (MoE: adapter/QLoRA support over fused or quantised experts is not verified)
- Known caveats: MoE (128 experts): QLoRA over experts not verified; no LICENSE file in repo.
- Primary sources: https://huggingface.co/google/gemma-4-26B-A4B-it, https://huggingface.co/api/models/google/gemma-4-26B-A4B-it, https://huggingface.co/google/gemma-4-26B-A4B-it/blob/main/config.json

#### `mistralai/Ministral-3-14B-Base-2512`

- Exact revision: `5b0ceedbb42dff466ae60b258ba296f32da51384`; license: `apache-2.0` (name `None`, gated `False`)
- Architecture: `['Mistral3ForConditionalGeneration']` / `mistral3`; total parameters 13.95B; active dense (DENSE)
- Context: config `max_position_embeddings`=262144; vendor-supported=262144 (SHORTHAND_K1024_ASSUMED; extended None); source `VENDOR_MODEL_CARD_CLAIM`; config-vs-vendor: **MATCH**; vendor text: "Supports a 256k context window"
- Active parameters: None — source `DENSE`, verified=False
- Admission meaning: admitted for evaluation only; PEFT/QLoRA training is not proven until Stage-0/Stage-3 evidence exists (trainability_proven=False)
- Multimodality: text+image; tool-calling template: None; reasoning/thinking template: None
- Structured output: NOT_MODEL_NATIVE_EVIDENCE: enforced at system level by the ORNEUR Contract Engine; serving-stack constrained decoding not verified this phase
- Quantization: vendor variants observed none recorded; runtime 4-bit INFERRED_NOT_EXECUTED
- ESTIMATES (not measurements): QLoRA VRAM 11.0–17.8 GB; USD 0.371–0.619 per 1M training tokens; 5M-token pilot USD 1.85–3.09
- **Class reason:** fits the size envelope but gate(s) not passed: D_tokenizer_template=UNVERIFIED
- Gates not passed: D_tokenizer_template=UNVERIFIED (no chat template found)
- Known caveats: Base checkpoint: needs full instruction/format SFT; same mistral-common/tekken caveat.
- Primary sources: https://huggingface.co/mistralai/Ministral-3-14B-Base-2512, https://huggingface.co/api/models/mistralai/Ministral-3-14B-Base-2512, https://huggingface.co/mistralai/Ministral-3-14B-Base-2512/blob/main/config.json

#### `mistralai/Ministral-3-14B-Instruct-2512`

- Exact revision: `29439f81c2be264d8d393273f99e7db9c0961120`; license: `apache-2.0` (name `None`, gated `False`)
- Architecture: `['Mistral3ForConditionalGeneration']` / `mistral3`; total parameters 13.95B; active dense (DENSE)
- Context: config `max_position_embeddings`=262144; vendor-supported=262144 (SHORTHAND_K1024_ASSUMED; extended None); source `VENDOR_MODEL_CARD_CLAIM`; config-vs-vendor: **MATCH**; vendor text: "Supports a 256k context window"
- Active parameters: None — source `DENSE`, verified=False
- Admission meaning: admitted for evaluation only; PEFT/QLoRA training is not proven until Stage-0/Stage-3 evidence exists (trainability_proven=False)
- Multimodality: text+image; tool-calling template: True; reasoning/thinking template: False
- Structured output: NOT_MODEL_NATIVE_EVIDENCE: enforced at system level by the ORNEUR Contract Engine; serving-stack constrained decoding not verified this phase
- Quantization: vendor variants observed ['BF16 variant', 'GGUF']; runtime 4-bit INFERRED_NOT_EXECUTED
- ESTIMATES (not measurements): QLoRA VRAM 11.0–17.8 GB; USD 0.371–0.619 per 1M training tokens; 5M-token pilot USD 1.85–3.09
- **Class reason:** fits the size envelope but gate(s) not passed: E_peft_qlora_feasible=UNVERIFIED
- Gates not passed: E_peft_qlora_feasible=UNVERIFIED (checkpoint ships natively quantised (FP8/INT8) weights: a dequantise-then-QLoRA path is not verified)
- Known caveats: Same mistral-common/tekken caveat as the Mistral-Nemo control.
- Primary sources: https://huggingface.co/mistralai/Ministral-3-14B-Instruct-2512, https://huggingface.co/api/models/mistralai/Ministral-3-14B-Instruct-2512, https://huggingface.co/mistralai/Ministral-3-14B-Instruct-2512/blob/main/config.json

#### `mistralai/Ministral-3-8B-Instruct-2512`

- Exact revision: `5b26027e7b19eeb4b7352e1fed3926375dd2cb4d`; license: `apache-2.0` (name `None`, gated `False`)
- Architecture: `['Mistral3ForConditionalGeneration']` / `mistral3`; total parameters 8.92B; active dense (DENSE)
- Context: config `max_position_embeddings`=262144; vendor-supported=262144 (SHORTHAND_K1024_ASSUMED; extended None); source `VENDOR_MODEL_CARD_CLAIM`; config-vs-vendor: **MATCH**; vendor text: "Supports a 256k context window"
- Active parameters: None — source `DENSE`, verified=False
- Admission meaning: admitted for evaluation only; PEFT/QLoRA training is not proven until Stage-0/Stage-3 evidence exists (trainability_proven=False)
- Multimodality: text+image; tool-calling template: True; reasoning/thinking template: False
- Structured output: NOT_MODEL_NATIVE_EVIDENCE: enforced at system level by the ORNEUR Contract Engine; serving-stack constrained decoding not verified this phase
- Quantization: vendor variants observed ['native F8_E4M3 weights', 'GGUF']; runtime 4-bit INFERRED_NOT_EXECUTED
- ESTIMATES (not measurements): QLoRA VRAM 8.5–14.2 GB; USD 0.238–0.396 per 1M training tokens; 5M-token pilot USD 1.19–1.98
- **Class reason:** fits the size envelope but gate(s) not passed: E_peft_qlora_feasible=UNVERIFIED
- Gates not passed: E_peft_qlora_feasible=UNVERIFIED (checkpoint ships natively quantised (FP8/INT8) weights: a dequantise-then-QLoRA path is not verified)
- Known caveats: Ships FP8 weights only for the instruct 8B: QLoRA requires a dequantised path (unverified). | Mistral tokenizer path (tekken.json + mistral-common) caused the Mistral-Nemo control failure; tokenizer/template behaviour must be re-qualified.
- Primary sources: https://huggingface.co/mistralai/Ministral-3-8B-Instruct-2512, https://huggingface.co/api/models/mistralai/Ministral-3-8B-Instruct-2512, https://huggingface.co/mistralai/Ministral-3-8B-Instruct-2512/blob/main/config.json

#### `openai/gpt-oss-20b`

- Exact revision: `6cee5e81ee83917806bbde320786a8fb61efebee`; license: `apache-2.0` (name `None`, gated `False`)
- Architecture: `['GptOssForCausalLM']` / `gpt_oss`; total parameters 20.91B; active 3.6 (VENDOR_MODEL_CARD_CLAIM)
- Context: config `max_position_embeddings`=131072; vendor-supported=None (None; extended None); source `NOT_CAPTURED_FROM_MODEL_CARD`; config-vs-vendor: **VENDOR_CLAIM_NOT_CAPTURED**
- Active parameters: 3.6 — source `VENDOR_MODEL_CARD_CLAIM`, verified=False
- Admission meaning: admitted for evaluation only; PEFT/QLoRA training is not proven until Stage-0/Stage-3 evidence exists (trainability_proven=False)
- Multimodality: text; tool-calling template: True; reasoning/thinking template: True
- Structured output: NOT_MODEL_NATIVE_EVIDENCE: enforced at system level by the ORNEUR Contract Engine; serving-stack constrained decoding not verified this phase
- Quantization: vendor variants observed ['native MXFP4 experts']; runtime 4-bit INFERRED_NOT_EXECUTED
- ESTIMATES (not measurements): QLoRA VRAM 14.5–22.6 GB; USD 0.096–0.16 per 1M training tokens; 5M-token pilot USD 0.48–0.8
- **Class reason:** fits the size envelope but gate(s) not passed: E_peft_qlora_feasible=UNVERIFIED
- Gates not passed: E_peft_qlora_feasible=UNVERIFIED (MoE: adapter/QLoRA support over fused or quantised experts is not verified)
- Known caveats: MoE with MXFP4 expert weights: QLoRA/PEFT over quantised experts unverified.
- Primary sources: https://huggingface.co/openai/gpt-oss-20b, https://huggingface.co/api/models/openai/gpt-oss-20b, https://huggingface.co/openai/gpt-oss-20b/blob/main/config.json

#### `zai-org/GLM-4.7-Flash`

- Exact revision: `7dd20894a642a0aa287e9827cb1a1f7f91386b67`; license: `mit` (name `None`, gated `False`)
- Architecture: `['Glm4MoeLiteForCausalLM']` / `glm4_moe_lite`; total parameters 31.22B; active 3.0 (NAME_DERIVED)
- Context: config `max_position_embeddings`=202752; vendor-supported=None (None; extended None); source `NOT_CAPTURED_FROM_MODEL_CARD`; config-vs-vendor: **VENDOR_CLAIM_NOT_CAPTURED**
- Active parameters: 3.0 — source `NAME_DERIVED`, verified=False; note: card only names the model '30B-A3B'; no explicit active count
- Admission meaning: admitted for evaluation only; PEFT/QLoRA training is not proven until Stage-0/Stage-3 evidence exists (trainability_proven=False)
- Multimodality: text; tool-calling template: True; reasoning/thinking template: True
- Structured output: NOT_MODEL_NATIVE_EVIDENCE: enforced at system level by the ORNEUR Contract Engine; serving-stack constrained decoding not verified this phase
- Quantization: vendor variants observed none recorded; runtime 4-bit INFERRED_NOT_EXECUTED
- ESTIMATES (not measurements): QLoRA VRAM 19.6–29.9 GB; USD 0.08–0.133 per 1M training tokens; 5M-token pilot USD 0.4–0.67
- **Class reason:** fits the size envelope but gate(s) not passed: E_peft_qlora_feasible=UNVERIFIED
- Gates not passed: E_peft_qlora_feasible=UNVERIFIED (MoE: adapter/QLoRA support over fused or quantised experts is not verified)
- Known caveats: MoE 31.2B (64 experts): QLoRA over experts unverified.
- Primary sources: https://huggingface.co/zai-org/GLM-4.7-Flash, https://huggingface.co/api/models/zai-org/GLM-4.7-Flash, https://huggingface.co/zai-org/GLM-4.7-Flash/blob/main/config.json

### FUTURE_FRONTIER_ARCHITECTURE_REFERENCE

#### `Qwen/Qwen3.8-2.4T-A95B`

- Exact revision: `207bd685a7e3696cfaff12ded7c6a7ea0f88c996`; license: `other` (name `qwen3.8-max`, gated `False`)
- Architecture: `['Qwen3_5MoeForCausalLM']` / `qwen3_5_moe_text`; total parameters 2446.18B; active 95.0 (VENDOR_MODEL_CARD_CLAIM)
- Context: config `max_position_embeddings`=262144; vendor-supported=262144 (EXACT; extended 1010000); source `VENDOR_MODEL_CARD_CLAIM`; config-vs-vendor: **MATCH**; vendor text: "262,144 natively and extensible up to 1,010,000 tokens"
- Active parameters: 95.0 — source `VENDOR_MODEL_CARD_CLAIM`, verified=False
- Admission meaning: admitted for evaluation only; PEFT/QLoRA training is not proven until Stage-0/Stage-3 evidence exists (trainability_proven=False)
- Multimodality: text; tool-calling template: True; reasoning/thinking template: True
- Structured output: NOT_MODEL_NATIVE_EVIDENCE: enforced at system level by the ORNEUR Contract Engine; serving-stack constrained decoding not verified this phase
- Quantization: vendor variants observed none recorded; runtime 4-bit INFERRED_NOT_EXECUTED
- ESTIMATES (not measurements): QLoRA VRAM 1227.1–1720.3 GB; USD 2.529–4.216 per 1M training tokens; 5M-token pilot USD 12.64–21.08
- **Class reason:** too large for the first-stage budget; studied as reference, not admitted as a base
- Gates not passed: A_license=FAIL (license tag 'other' / name 'qwen3.8-max', gated=False: custom or gated terms; not admitted without legal review); E_peft_qlora_feasible=FAIL (2446.18B exceeds single-GPU QLoRA envelope for the first-stage budget); F_training_cost_vs_budget=FAIL (5M-token pilot ~USD 12.64-21.08 (<= 10% of USD 111); est. QLoRA VRAM 1227.1-1720.3 GB vs 80 GB); J_ecosystem_maturity=UNVERIFIED (transformers-native=True, vLLM-listed=False)
- Known caveats: 2.4T parameters: reference only. License (qwen3.8-max) needs a separate license for AI-assistant/MaaS businesses above US$50M revenue; terms not fully legal-reviewed.
- Primary sources: https://huggingface.co/Qwen/Qwen3.8-2.4T-A95B, https://huggingface.co/api/models/Qwen/Qwen3.8-2.4T-A95B, https://huggingface.co/Qwen/Qwen3.8-2.4T-A95B/blob/main/config.json

#### `Qwen/Qwen3.8-Flash-Next`

- Exact revision: `de4b8e4d43b917e7706784d8bb445c9af86a3540`; license: `other` (name `qwen-community-1.0`, gated `False`)
- Architecture: `['Qwen4ExpForConditionalGeneration']` / `qwen4_exp`; total parameters 180.0B; active 6.0 (VENDOR_MODEL_CARD_CLAIM)
- Context: config `max_position_embeddings`=262144; vendor-supported=262144 (EXACT; extended 1000000); source `VENDOR_MODEL_CARD_CLAIM`; config-vs-vendor: **MATCH**; vendor text: "262,144 natively and extensible up to 1,000,000 tokens"
- Active parameters: 6.0 — source `VENDOR_MODEL_CARD_CLAIM`, verified=False; note: card: 125B + 51B n-gram embedding + 4B MTP (= 180B stored, matching the safetensors total)
- Admission meaning: admitted for evaluation only; PEFT/QLoRA training is not proven until Stage-0/Stage-3 evidence exists (trainability_proven=False)
- Multimodality: text+image; tool-calling template: True; reasoning/thinking template: True
- Structured output: NOT_MODEL_NATIVE_EVIDENCE: enforced at system level by the ORNEUR Contract Engine; serving-stack constrained decoding not verified this phase
- Quantization: vendor variants observed none recorded; runtime 4-bit INFERRED_NOT_EXECUTED
- ESTIMATES (not measurements): QLoRA VRAM 94.0–134.0 GB; USD 0.16–0.266 per 1M training tokens; 5M-token pilot USD 0.8–1.33
- **Class reason:** too large for the first-stage budget; studied as reference, not admitted as a base
- Gates not passed: A_license=FAIL (license tag 'other' / name 'qwen-community-1.0', gated=False: custom or gated terms; not admitted without legal review); E_peft_qlora_feasible=FAIL (180.0B exceeds single-GPU QLoRA envelope for the first-stage budget); F_training_cost_vs_budget=FAIL (5M-token pilot ~USD 0.8-1.33 (<= 10% of USD 111); est. QLoRA VRAM 94.0-134.0 GB vs 80 GB); J_ecosystem_maturity=UNVERIFIED (transformers-native=True, vLLM-listed=False)
- Known caveats: License (qwen-community-1.0) requires a separate license from Qwen for any 'Model as a Service or AI Work Assistant business': incompatible with ORNEUR's intended business until legally cleared. Architecture (qwen4_exp) studied only.
- Primary sources: https://huggingface.co/Qwen/Qwen3.8-Flash-Next, https://huggingface.co/api/models/Qwen/Qwen3.8-Flash-Next, https://huggingface.co/Qwen/Qwen3.8-Flash-Next/blob/main/config.json

#### `zai-org/GLM-5.3`

- Exact revision: `aca966e4e02791568aa6a4ced368624b3d897f42`; license: `other` (name `glm-5.3`, gated `False`)
- Architecture: `['GlmMoeDsaForCausalLM']` / `glm_moe_dsa`; total parameters 753.33B; active not recorded (NOT_RECORDED)
- Context: config `max_position_embeddings`=1048576; vendor-supported=None (None; extended None); source `NOT_CAPTURED_FROM_MODEL_CARD`; config-vs-vendor: **VENDOR_CLAIM_NOT_CAPTURED**
- Active parameters: None — source `NOT_RECORDED`, verified=False
- Admission meaning: admitted for evaluation only; PEFT/QLoRA training is not proven until Stage-0/Stage-3 evidence exists (trainability_proven=False)
- Multimodality: text; tool-calling template: True; reasoning/thinking template: True
- Structured output: NOT_MODEL_NATIVE_EVIDENCE: enforced at system level by the ORNEUR Contract Engine; serving-stack constrained decoding not verified this phase
- Quantization: vendor variants observed none recorded; runtime 4-bit INFERRED_NOT_EXECUTED
- ESTIMATES (not measurements): QLoRA VRAM 380.7–535.3 GB; USD 20.058–33.431 per 1M training tokens; 5M-token pilot USD 100.29–167.15
- **Class reason:** too large for the first-stage budget; studied as reference, not admitted as a base
- Gates not passed: A_license=FAIL (license tag 'other' / name 'glm-5.3', gated=False: custom or gated terms; not admitted without legal review); E_peft_qlora_feasible=FAIL (753.33B exceeds single-GPU QLoRA envelope for the first-stage budget); F_training_cost_vs_budget=FAIL (5M-token pilot ~USD 100.29-167.16 (<= 10% of USD 111); est. QLoRA VRAM 380.7-535.3 GB vs 80 GB)
- Known caveats: Custom GLM-5.3 License (MaaS clause above US$10B revenue): architecture reference only; unaudited by counsel.
- Primary sources: https://huggingface.co/zai-org/GLM-5.3, https://huggingface.co/api/models/zai-org/GLM-5.3, https://huggingface.co/zai-org/GLM-5.3/blob/main/config.json

### BASELINE_ONLY_CONTROL

#### `Qwen/Qwen3-8B`

- Exact revision: `b968826d9c46dd6066d109eabc6255188de91218`; license: `apache-2.0` (name `None`, gated `False`)
- Architecture: `['Qwen3ForCausalLM']` / `qwen3`; total parameters 8.19B; active dense (DENSE)
- Context: config `max_position_embeddings`=40960; vendor-supported=32768 (EXACT; extended 131072); source `VENDOR_MODEL_CARD_CLAIM`; config-vs-vendor: **DIFFERS**; vendor text: "32,768 natively and 131,072 tokens with YaRN"
- Active parameters: None — source `DENSE`, verified=False
- Admission meaning: admitted for evaluation only; PEFT/QLoRA training is not proven until Stage-0/Stage-3 evidence exists (trainability_proven=False)
- Multimodality: text; tool-calling template: True; reasoning/thinking template: True
- Structured output: NOT_MODEL_NATIVE_EVIDENCE: enforced at system level by the ORNEUR Contract Engine; serving-stack constrained decoding not verified this phase
- Quantization: vendor variants observed none recorded; runtime 4-bit INFERRED_NOT_EXECUTED
- ESTIMATES (not measurements): QLoRA VRAM 8.1–13.7 GB; USD 0.218–0.363 per 1M training tokens; 5M-token pilot USD 1.09–1.81
- **Class reason:** Phase 21B.4.20 control; never admitted as a candidate; may serve only as a regression baseline
- Gates not passed: none
- Known caveats: Phase 21B.4.20 control: RUNTIME_QUALIFIED=false in ORNEUR's raw-model harness (smoke B FAIL); kept only as a regression baseline, not carried forward automatically.
- Primary sources: https://huggingface.co/Qwen/Qwen3-8B, https://huggingface.co/api/models/Qwen/Qwen3-8B, https://huggingface.co/Qwen/Qwen3-8B/blob/main/config.json

#### `microsoft/phi-4`

- Exact revision: `2db69c1c3e91a05d2c64a3185acfbaf36f744e25`; license: `mit` (name `None`, gated `False`)
- Architecture: `['Phi3ForCausalLM']` / `phi3`; total parameters 14.66B; active dense (DENSE)
- Context: config `max_position_embeddings`=16384; vendor-supported=16384 (SHORTHAND_K1024_ASSUMED; extended None); source `VENDOR_MODEL_CARD_CLAIM`; config-vs-vendor: **MATCH**; vendor text: "16K tokens"
- Active parameters: None — source `DENSE`, verified=False
- Admission meaning: admitted for evaluation only; PEFT/QLoRA training is not proven until Stage-0/Stage-3 evidence exists (trainability_proven=False)
- Multimodality: text; tool-calling template: False; reasoning/thinking template: False
- Structured output: NOT_MODEL_NATIVE_EVIDENCE: enforced at system level by the ORNEUR Contract Engine; serving-stack constrained decoding not verified this phase
- Quantization: vendor variants observed none recorded; runtime 4-bit INFERRED_NOT_EXECUTED
- ESTIMATES (not measurements): QLoRA VRAM 11.3–18.3 GB; USD 0.39–0.651 per 1M training tokens; 5M-token pilot USD 1.95–3.25
- **Class reason:** Phase 21B.4.20 control; never admitted as a candidate; may serve only as a regression baseline
- Gates not passed: none
- Known caveats: Phase 21B.4.20 control: PASS/FAIL/FAIL; 16k context limit; baseline only.
- Primary sources: https://huggingface.co/microsoft/phi-4, https://huggingface.co/api/models/microsoft/phi-4, https://huggingface.co/microsoft/phi-4/blob/main/config.json

#### `mistralai/Mistral-Nemo-Instruct-2407`

- Exact revision: `04d8a90549d23fc6bd7f642064003592df51e9b3`; license: `apache-2.0` (name `None`, gated `False`)
- Architecture: `['MistralForCausalLM']` / `mistral`; total parameters 12.25B; active dense (DENSE)
- Context: config `max_position_embeddings`=131072; vendor-supported=131072 (SHORTHAND_K1024_ASSUMED; extended None); source `VENDOR_MODEL_CARD_CLAIM`; config-vs-vendor: **MATCH**; vendor text: "Trained with a 128k context window"
- Active parameters: None — source `DENSE`, verified=False
- Admission meaning: admitted for evaluation only; PEFT/QLoRA training is not proven until Stage-0/Stage-3 evidence exists (trainability_proven=False)
- Multimodality: text; tool-calling template: True; reasoning/thinking template: False
- Structured output: NOT_MODEL_NATIVE_EVIDENCE: enforced at system level by the ORNEUR Contract Engine; serving-stack constrained decoding not verified this phase
- Quantization: vendor variants observed none recorded; runtime 4-bit INFERRED_NOT_EXECUTED
- ESTIMATES (not measurements): QLoRA VRAM 10.1–16.6 GB; USD 0.326–0.544 per 1M training tokens; 5M-token pilot USD 1.63–2.72
- **Class reason:** Phase 21B.4.20 control; never admitted as a candidate; may serve only as a regression baseline
- Gates not passed: none
- Known caveats: Phase 21B.4.20 control: FAIL/FAIL/FAIL under native-tokenizer candidate; needs mistral-common tokenizer path; baseline only.
- Primary sources: https://huggingface.co/mistralai/Mistral-Nemo-Instruct-2407, https://huggingface.co/api/models/mistralai/Mistral-Nemo-Instruct-2407, https://huggingface.co/mistralai/Mistral-Nemo-Instruct-2407/blob/main/config.json

### NOT_ADMITTED

#### `LiquidAI/LFM2.5-2.6B`

- Exact revision: `654f9463ce32b05d0429d76fe1f580b27d4c1ac0`; license: `other` (name `lfm1.0`, gated `False`)
- Architecture: `['Lfm2ForCausalLM']` / `lfm2`; total parameters 2.7B; active dense (DENSE)
- Context: config `max_position_embeddings`=131072; vendor-supported=131072 (EXACT; extended None); source `VENDOR_MODEL_CARD_CLAIM`; config-vs-vendor: **MATCH**; vendor text: "Context length: 131,072 tokens"
- Active parameters: None — source `DENSE`, verified=False
- Admission meaning: admitted for evaluation only; PEFT/QLoRA training is not proven until Stage-0/Stage-3 evidence exists (trainability_proven=False)
- Multimodality: text; tool-calling template: True; reasoning/thinking template: True
- Structured output: NOT_MODEL_NATIVE_EVIDENCE: enforced at system level by the ORNEUR Contract Engine; serving-stack constrained decoding not verified this phase
- Quantization: vendor variants observed none recorded; runtime 4-bit INFERRED_NOT_EXECUTED
- ESTIMATES (not measurements): QLoRA VRAM 5.3–9.9 GB; USD 0.072–0.12 per 1M training tokens; 5M-token pilot USD 0.36–0.6
- **Class reason:** fails the license gate: license tag 'other' / name 'lfm1.0', gated=False: custom or gated terms; not admitted without legal review
- Gates not passed: A_license=FAIL (license tag 'other' / name 'lfm1.0', gated=False: custom or gated terms; not admitted without legal review)
- Known caveats: LFM1.0 licence: commercial use licensed only below a US$10M annual-revenue threshold: not permissive.
- Primary sources: https://huggingface.co/LiquidAI/LFM2.5-2.6B, https://huggingface.co/api/models/LiquidAI/LFM2.5-2.6B, https://huggingface.co/LiquidAI/LFM2.5-2.6B/blob/main/config.json

#### `deepseek-ai/DeepSeek-R1-0528-Qwen3-8B`

- Exact revision: `6e8885a6ff5c1dc5201574c8fd700323f23c25fa`; license: `mit` (name `None`, gated `False`)
- Architecture: `['Qwen3ForCausalLM']` / `qwen3`; total parameters 8.19B; active dense (DENSE)
- Context: config `max_position_embeddings`=131072; vendor-supported=None (None; extended None); source `NOT_CAPTURED_FROM_MODEL_CARD`; config-vs-vendor: **VENDOR_CLAIM_NOT_CAPTURED**
- Active parameters: None — source `DENSE`, verified=False
- Admission meaning: admitted for evaluation only; PEFT/QLoRA training is not proven until Stage-0/Stage-3 evidence exists (trainability_proven=False)
- Multimodality: text; tool-calling template: False; reasoning/thinking template: True
- Structured output: NOT_MODEL_NATIVE_EVIDENCE: enforced at system level by the ORNEUR Contract Engine; serving-stack constrained decoding not verified this phase
- Quantization: vendor variants observed none recorded; runtime 4-bit INFERRED_NOT_EXECUTED
- ESTIMATES (not measurements): QLoRA VRAM 8.1–13.7 GB; USD 0.218–0.363 per 1M training tokens; 5M-token pilot USD 1.09–1.81
- **Class reason:** fine-tuned derivative of another candidate architecture: recorded to avoid double counting, not a separate foundation
- Gates not passed: none
- Known caveats: MIT-licensed distillation onto the Qwen3-8B architecture; inherits the Qwen3-8B control caveats.
- Primary sources: https://huggingface.co/deepseek-ai/DeepSeek-R1-0528-Qwen3-8B, https://huggingface.co/api/models/deepseek-ai/DeepSeek-R1-0528-Qwen3-8B, https://huggingface.co/deepseek-ai/DeepSeek-R1-0528-Qwen3-8B/blob/main/config.json

#### `meta-llama/Llama-3.3-70B-Instruct`

- Exact revision: `6f6073b423013f6a7d4d9f39144961bfbfbc386b`; license: `llama3.3` (name `None`, gated `manual`)
- Architecture: `None` / `None`; total parameters 70.55B; active dense (DENSE)
- Context: config `max_position_embeddings`=None; vendor-supported=131072 (SHORTHAND_K1024_ASSUMED; extended None); source `VENDOR_MODEL_CARD_CLAIM`; config-vs-vendor: **CONFIG_NOT_AVAILABLE**; vendor text: "128k (model-family table)"
- Active parameters: None — source `DENSE`, verified=False
- Admission meaning: admitted for evaluation only; PEFT/QLoRA training is not proven until Stage-0/Stage-3 evidence exists (trainability_proven=False)
- Multimodality: text; tool-calling template: None; reasoning/thinking template: None
- Structured output: NOT_MODEL_NATIVE_EVIDENCE: enforced at system level by the ORNEUR Contract Engine; serving-stack constrained decoding not verified this phase
- Quantization: vendor variants observed none recorded; runtime 4-bit INFERRED_NOT_EXECUTED
- ESTIMATES (not measurements): QLoRA VRAM 39.3–57.4 GB; USD 1.878–3.131 per 1M training tokens; 5M-token pilot USD 9.39–15.65
- **Class reason:** fails the license gate: license tag 'llama3.3' / name 'None', gated=manual: custom or gated terms; not admitted without legal review
- Gates not passed: A_license=FAIL (license tag 'llama3.3' / name 'None', gated=manual: custom or gated terms; not admitted without legal review); C_architecture_documented=UNVERIFIED (no config.json retrievable); D_tokenizer_template=UNVERIFIED (no chat template found); E_peft_qlora_feasible=FAIL (70.55B exceeds single-GPU QLoRA envelope for the first-stage budget); F_training_cost_vs_budget=FAIL (5M-token pilot ~USD 9.39-15.65 (<= 10% of USD 111); est. QLoRA VRAM 39.3-57.4 GB vs 80 GB); G_inference_path=FAIL (no transformers-native or vLLM-listed inference path found); I_no_proprietary_only_stack=UNVERIFIED (no open serving stack identified); J_ecosystem_maturity=UNVERIFIED (transformers-native=False, vLLM-listed=False)
- Known caveats: Manually gated repo + custom community licence; 70B exceeds the first-stage budget in any case.
- Primary sources: https://huggingface.co/meta-llama/Llama-3.3-70B-Instruct, https://huggingface.co/api/models/meta-llama/Llama-3.3-70B-Instruct, https://huggingface.co/meta-llama/Llama-3.3-70B-Instruct/blob/main/config.json

#### `meta-llama/Llama-4-Scout-17B-16E-Instruct`

- Exact revision: `92f3b1597a195b523d8d9e5700e57e4fbb8f20d3`; license: `other` (name `llama4`, gated `manual`)
- Architecture: `None` / `None`; total parameters 108.64B; active dense (DENSE)
- Context: config `max_position_embeddings`=None; vendor-supported=None (None; extended None); source `NOT_CAPTURED_FROM_MODEL_CARD`; config-vs-vendor: **CONFIG_NOT_AVAILABLE**
- Active parameters: None — source `DENSE`, verified=False
- Admission meaning: admitted for evaluation only; PEFT/QLoRA training is not proven until Stage-0/Stage-3 evidence exists (trainability_proven=False)
- Multimodality: text+image; tool-calling template: None; reasoning/thinking template: None
- Structured output: NOT_MODEL_NATIVE_EVIDENCE: enforced at system level by the ORNEUR Contract Engine; serving-stack constrained decoding not verified this phase
- Quantization: vendor variants observed none recorded; runtime 4-bit INFERRED_NOT_EXECUTED
- ESTIMATES (not measurements): QLoRA VRAM 58.3–84.0 GB; USD 2.893–4.821 per 1M training tokens; 5M-token pilot USD 14.46–24.1
- **Class reason:** fails the license gate: license tag 'other' / name 'llama4', gated=manual: custom or gated terms; not admitted without legal review
- Gates not passed: A_license=FAIL (license tag 'other' / name 'llama4', gated=manual: custom or gated terms; not admitted without legal review); C_architecture_documented=UNVERIFIED (no config.json retrievable); D_tokenizer_template=UNVERIFIED (no chat template found); E_peft_qlora_feasible=FAIL (108.64B exceeds single-GPU QLoRA envelope for the first-stage budget); F_training_cost_vs_budget=FAIL (5M-token pilot ~USD 14.46-24.11 (<= 10% of USD 111); est. QLoRA VRAM 58.3-84.0 GB vs 80 GB); G_inference_path=FAIL (no transformers-native or vLLM-listed inference path found); I_no_proprietary_only_stack=UNVERIFIED (no open serving stack identified); J_ecosystem_maturity=UNVERIFIED (transformers-native=False, vLLM-listed=False)
- Known caveats: Manually gated repo + custom Llama 4 licence; 109B total parameters.
- Primary sources: https://huggingface.co/meta-llama/Llama-4-Scout-17B-16E-Instruct, https://huggingface.co/api/models/meta-llama/Llama-4-Scout-17B-16E-Instruct, https://huggingface.co/meta-llama/Llama-4-Scout-17B-16E-Instruct/blob/main/config.json

#### `microsoft/Fara1.5-9B`

- Exact revision: `1a93677cd89d5601bc2ed759791e981f3a520032`; license: `mit` (name `None`, gated `False`)
- Architecture: `['Qwen3_5ForConditionalGeneration']` / `qwen3_5`; total parameters 9.41B; active dense (DENSE)
- Context: config `max_position_embeddings`=262144; vendor-supported=262144 (EXACT; extended None); source `VENDOR_MODEL_CARD_CLAIM`; config-vs-vendor: **MATCH**; vendor text: "262,144 tokens"
- Active parameters: None — source `DENSE`, verified=False
- Admission meaning: admitted for evaluation only; PEFT/QLoRA training is not proven until Stage-0/Stage-3 evidence exists (trainability_proven=False)
- Multimodality: text+image; tool-calling template: True; reasoning/thinking template: True
- Structured output: NOT_MODEL_NATIVE_EVIDENCE: enforced at system level by the ORNEUR Contract Engine; serving-stack constrained decoding not verified this phase
- Quantization: vendor variants observed none recorded; runtime 4-bit INFERRED_NOT_EXECUTED
- ESTIMATES (not measurements): QLoRA VRAM 8.7–14.6 GB; USD 0.251–0.418 per 1M training tokens; 5M-token pilot USD 1.25–2.09
- **Class reason:** fine-tuned derivative of another candidate architecture: recorded to avoid double counting, not a separate foundation
- Gates not passed: none
- Known caveats: Task-specialised (computer-use) derivative of Qwen3.5-9B: not a general foundation candidate; recorded to avoid double counting.
- Primary sources: https://huggingface.co/microsoft/Fara1.5-9B, https://huggingface.co/api/models/microsoft/Fara1.5-9B, https://huggingface.co/microsoft/Fara1.5-9B/blob/main/config.json

#### `microsoft/MagenticBrain`

- Exact revision: `db8eb9340a90eaa4424dd13067373d1f9e8887f7`; license: `mit` (name `None`, gated `False`)
- Architecture: `['Qwen3ForCausalLM']` / `qwen3`; total parameters 14.77B; active dense (DENSE)
- Context: config `max_position_embeddings`=40960; vendor-supported=32768 (EXACT; extended None); source `VENDOR_MODEL_CARD_CLAIM`; config-vs-vendor: **DIFFERS**; vendor text: "32,768 tokens"
- Active parameters: None — source `DENSE`, verified=False
- Admission meaning: admitted for evaluation only; PEFT/QLoRA training is not proven until Stage-0/Stage-3 evidence exists (trainability_proven=False)
- Multimodality: text; tool-calling template: True; reasoning/thinking template: True
- Structured output: NOT_MODEL_NATIVE_EVIDENCE: enforced at system level by the ORNEUR Contract Engine; serving-stack constrained decoding not verified this phase
- Quantization: vendor variants observed none recorded; runtime 4-bit INFERRED_NOT_EXECUTED
- ESTIMATES (not measurements): QLoRA VRAM 11.4–18.3 GB; USD 0.393–0.655 per 1M training tokens; 5M-token pilot USD 1.97–3.28
- **Class reason:** fine-tuned derivative of another candidate architecture: recorded to avoid double counting, not a separate foundation
- Gates not passed: none
- Known caveats: Task-specialised derivative on the Qwen3 architecture, F32 weights; not a general foundation candidate.
- Primary sources: https://huggingface.co/microsoft/MagenticBrain, https://huggingface.co/api/models/microsoft/MagenticBrain, https://huggingface.co/microsoft/MagenticBrain/blob/main/config.json

#### `nvidia/NVIDIA-Nemotron-3-Nano-30B-A3B-BF16`

- Exact revision: `bf77c3174f68ad409e1c2aa60daeb46e32d1c606`; license: `other` (name `nvidia-nemotron-open-model-license`, gated `False`)
- Architecture: `['NemotronHForCausalLM']` / `nemotron_h`; total parameters 31.58B; active 3.0 (NAME_DERIVED)
- Context: config `max_position_embeddings`=262144; vendor-supported=1048576 (SHORTHAND_K1024_ASSUMED; extended None); source `VENDOR_MODEL_CARD_CLAIM`; config-vs-vendor: **DIFFERS**; vendor text: "supports up to a 1M context size, although the default context size in the Hugging Face configuration is 256k"
- Active parameters: 3.0 — source `NAME_DERIVED`, verified=False; note: from the 'A3B' model name; card gives experts-per-token, not an active count
- Admission meaning: admitted for evaluation only; PEFT/QLoRA training is not proven until Stage-0/Stage-3 evidence exists (trainability_proven=False)
- Multimodality: text; tool-calling template: True; reasoning/thinking template: True
- Structured output: NOT_MODEL_NATIVE_EVIDENCE: enforced at system level by the ORNEUR Contract Engine; serving-stack constrained decoding not verified this phase
- Quantization: vendor variants observed none recorded; runtime 4-bit INFERRED_NOT_EXECUTED
- ESTIMATES (not measurements): QLoRA VRAM 19.8–30.1 GB; USD 0.08–0.133 per 1M training tokens; 5M-token pilot USD 0.4–0.67
- **Class reason:** fails the license gate: license tag 'other' / name 'nvidia-nemotron-open-model-license', gated=False: custom or gated terms; not admitted without legal review
- Gates not passed: A_license=FAIL (license tag 'other' / name 'nvidia-nemotron-open-model-license', gated=False: custom or gated terms; not admitted without legal review); E_peft_qlora_feasible=UNVERIFIED (MoE: adapter/QLoRA support over fused or quantised experts is not verified)
- Known caveats: Hybrid Mamba/attention MoE (nemotron_h): valuable for architecture diversity; NVIDIA custom open-model license not legally reviewed.
- Primary sources: https://huggingface.co/nvidia/NVIDIA-Nemotron-3-Nano-30B-A3B-BF16, https://huggingface.co/api/models/nvidia/NVIDIA-Nemotron-3-Nano-30B-A3B-BF16, https://huggingface.co/nvidia/NVIDIA-Nemotron-3-Nano-30B-A3B-BF16/blob/main/config.json

#### `nvidia/NVIDIA-Nemotron-3.5-Lightning-30B-A3B-Base-BF16`

- Exact revision: `434456c9a6753f29d24e23c95d622aaf17111b3b`; license: `other` (name `openmdw-1.1`, gated `False`)
- Architecture: `['NemotronHForCausalLM']` / `nemotron_h`; total parameters 31.58B; active 3.0 (NAME_DERIVED)
- Context: config `max_position_embeddings`=262144; vendor-supported=1048576 (SHORTHAND_K1024_ASSUMED; extended None); source `VENDOR_MODEL_CARD_CLAIM`; config-vs-vendor: **DIFFERS**; vendor text: "supports up to 1M context length"
- Active parameters: 3.0 — source `NAME_DERIVED`, verified=False; note: from the 'A3B' model name
- Admission meaning: admitted for evaluation only; PEFT/QLoRA training is not proven until Stage-0/Stage-3 evidence exists (trainability_proven=False)
- Multimodality: text; tool-calling template: None; reasoning/thinking template: None
- Structured output: NOT_MODEL_NATIVE_EVIDENCE: enforced at system level by the ORNEUR Contract Engine; serving-stack constrained decoding not verified this phase
- Quantization: vendor variants observed none recorded; runtime 4-bit INFERRED_NOT_EXECUTED
- ESTIMATES (not measurements): QLoRA VRAM 19.8–30.1 GB; USD 0.08–0.133 per 1M training tokens; 5M-token pilot USD 0.4–0.67
- **Class reason:** fails the license gate: license tag 'other' / name 'openmdw-1.1', gated=False: custom or gated terms; not admitted without legal review
- Gates not passed: A_license=FAIL (license tag 'other' / name 'openmdw-1.1', gated=False: custom or gated terms; not admitted without legal review); D_tokenizer_template=UNVERIFIED (no chat template found); E_peft_qlora_feasible=UNVERIFIED (MoE: adapter/QLoRA support over fused or quantised experts is not verified)
- Known caveats: Base checkpoint under openmdw-1.1 (card metadata): license text not reviewed this phase.
- Primary sources: https://huggingface.co/nvidia/NVIDIA-Nemotron-3.5-Lightning-30B-A3B-Base-BF16, https://huggingface.co/api/models/nvidia/NVIDIA-Nemotron-3.5-Lightning-30B-A3B-Base-BF16, https://huggingface.co/nvidia/NVIDIA-Nemotron-3.5-Lightning-30B-A3B-Base-BF16/blob/main/config.json

## 6. Shortlists (no ranking, no selection)

**Eval-admitted pool (admitted to the Genesis Capability Eval by gates alone; NOT proven trainable):** `HuggingFaceTB/SmolLM3-3B`, `Qwen/Qwen3.5-27B`, `Qwen/Qwen3.5-4B`, `Qwen/Qwen3.5-9B`, `Qwen/Qwen3.6-27B`, `Qwen/Qwen3.8-27B`, `allenai/Olmo-3-7B-Instruct`, `google/gemma-4-12B-it`, `google/gemma-4-31B-it`, `google/gemma-4-E4B-it`, `ibm-granite/granite-4.2-30b`, `ibm-granite/granite-4.2-3b`, `ibm-granite/granite-4.2-8b`, `microsoft/Phi-4-mini-instruct`, `mistralai/Ministral-3-14B-Reasoning-2512`.

**Teacher / reference (studied, not a base):** `deepseek-ai/DeepSeek-V4-Pro-0813`, `deepseek-ai/DeepSeek-V4.1-Flash`, `mistralai/Mistral-Large-3-675B-Instruct-2512`, `mistralai/Mistral-Small-4-119B-2603`, `openai/gpt-oss-120b`, `zai-org/GLM-5.3-Flash`.

**Future reason candidates (blocked by an UNVERIFIED gate, mostly QLoRA-over-MoE or native-FP8 checkpoints):** `Qwen/Qwen3.5-35B-A3B`, `Qwen/Qwen3.6-35B-A3B`, `google/gemma-4-12B`, `google/gemma-4-26B-A4B-it`, `mistralai/Ministral-3-14B-Base-2512`, `mistralai/Ministral-3-14B-Instruct-2512`, `mistralai/Ministral-3-8B-Instruct-2512`, `openai/gpt-oss-20b`, `zai-org/GLM-4.7-Flash`.

**Future frontier architecture references:** `Qwen/Qwen3.8-2.4T-A95B`, `Qwen/Qwen3.8-Flash-Next`, `zai-org/GLM-5.3`.

**Baseline-only controls (not carried forward automatically):** `Qwen/Qwen3-8B`, `microsoft/phi-4`, `mistralai/Mistral-Nemo-Instruct-2407`. They may serve as regression baselines; their historical `RUNTIME_QUALIFIED=false` results are unchanged.

The pool is deliberately larger than can be sensibly trained. It is a *screening* pool: the capability eval design uses a staged funnel so that only a few models receive the expensive stages.

## 6a. Context and active-parameter semantics (audit correction)

Two different things were previously conflated. `config_max_position_embeddings` is what the shipped `config.json` says and is never overwritten. `vendor_supported_context_tokens` is what the vendor's model card states is supported; it is an attributed claim (`context_source`), quoted verbatim from the captured card text, not a measurement. K/M shorthand is converted with the K=1024 convention and flagged `SHORTHAND_K1024_ASSUMED`. Likewise `active_parameters_b` is an attributed claim (`VENDOR_MODEL_CARD_CLAIM`) or a name-derived value (`NAME_DERIVED`), never verified (`active_parameters_verified=false`).

Config-vs-vendor context **differs** for: `Qwen/Qwen3-8B` (config 40960, vendor 32768), `microsoft/MagenticBrain` (config 40960, vendor 32768), `mistralai/Mistral-Small-4-119B-2603` (config 1048576, vendor 262144), `nvidia/NVIDIA-Nemotron-3-Nano-30B-A3B-BF16` (config 262144, vendor 1048576), `nvidia/NVIDIA-Nemotron-3.5-Lightning-30B-A3B-Base-BF16` (config 262144, vendor 1048576).

`VENDOR_CLAIM_NOT_CAPTURED` (no vendor context claim was captured from the model card): `allenai/Olmo-3-7B-Instruct`, `deepseek-ai/DeepSeek-R1-0528-Qwen3-8B`, `deepseek-ai/DeepSeek-V4-Pro-0813`, `openai/gpt-oss-120b`, `openai/gpt-oss-20b`, `zai-org/GLM-4.7-Flash`, `zai-org/GLM-5.3`, `zai-org/GLM-5.3-Flash`.

`CONFIG_NOT_AVAILABLE` (no config.json retrievable (gated or native-format repo)): `meta-llama/Llama-3.3-70B-Instruct`, `meta-llama/Llama-4-Scout-17B-16E-Instruct`, `mistralai/Mistral-Large-3-675B-Instruct-2512`.

## 7. Owner budget reality (planning only — does not authorize spending)

- Approximate first-stage budget: INR 10,000 ≈ USD 111–118 (assumed INR 85–90/USD, not a live quote). H100 list rate used: USD 3.95/h (the program's persisted rate). Compute model: 6·N FLOPs/token at 15–25% of the public 989 TFLOPs bf16 peak; N is total parameters for dense models and *name-derived* active parameters for MoE. Real QLoRA overhead (dequantisation, gradient checkpointing, padding) makes actual cost higher; treat every figure as a lower-bound planning estimate.
- **This budget cannot pretrain or continue-pretrain a frontier model.** It can fund parameter-efficient adaptation (QLoRA/LoRA), small controlled SFT, small preference optimisation, and license-permitting distillation experiments.
- Three cost buckets are kept separate: **(1) initial adaptation cost** (the per-model estimates above, plus evals and failed runs; roughly 40–60% of a budget becomes training compute); **(2) production inference cost** (recurring; an always-on H100 at the persisted rate is ≈ USD 2,844/month, so scale-to-zero or small-GPU 4-bit serving is required regardless of base — small-GPU serving costs are NOT measured here); **(3) future full-pretraining / continued-pretraining research** (out of scope and out of budget; teacher/reference and architecture-reference models inform it only).
- Funding still requires an explicit owner decision: current promotional-credit headroom is below any training budget (per the Phase 21B.4.20 closeout).

## 8. Selection rule (pre-registered here; applies after the capability eval)

No model is selected in this phase. A future selection must use per-capability results from the frozen Genesis Capability Eval V1 and this pre-registered rule: (1) a model must clear every hard floor listed in GENESIS_CAPABILITY_EVAL_V1_DESIGN.md; (2) among survivors, drop any model Pareto-dominated on every capability category at equal or lower cost; (3) rank the remainder lexicographically by strict_contracts floor margin, then verification, then evidence_use, then trainability, then cost; (4) ties or irreconcilable trade-offs go to an explicit owner decision. Release date, parameter count and popularity are never inputs.

## 9. Remaining uncertainties

- Every PEFT/QLoRA statement for dense models is `INFERRED_NOT_EXECUTED`; the hybrid linear-attention Qwen3.5/3.6/3.8 family and the Gemma 4 family may need specialised kernels or newer library versions than a given host provides.
- Serving statements rely on the vLLM docs on `main` at collection time (vLLM PyPI latest observed above); the ORNEUR harness pins vLLM 0.29.0, so support must be re-qualified per model at the pinned version.
- Gemma 4 repositories carry no LICENSE file; the Apache-2.0 statement is model-card metadata only and should be confirmed against the vendor's terms page before any commitment.
- License review here is a mechanical screen of card metadata and selected LICENSE clauses, not legal advice. Custom licenses (Qwen community/max, GLM-5.3, NVIDIA, Llama, LFM) were screened only for headline restrictions.
- MoE active-parameter counts are name-derived or vendor claims and only affect the compute estimate.
- Frontier-scale teachers (DeepSeek V4.x, GLM-5.3-Flash, gpt-oss-120b, Mistral Large/Small 4) require provider or multi-GPU serving; teacher-output licensing for distillation was not legally reviewed.
- Release ordering shows a young ecosystem for the newest families; 'newest' was never used as a selection input.
- Task-specialised derivatives (Fara1.5, MagenticBrain, DeepSeek-R1-0528-Qwen3-8B) are recorded but not counted as foundations.

## 10. Authorizations

`training_authorized=false`, `gpu_authorized=false`, `provider_inference_authorized=false`, `phase_21c_authorized=false`, `foundation_selected=false`.
