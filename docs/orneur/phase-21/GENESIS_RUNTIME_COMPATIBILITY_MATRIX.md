# Genesis Runtime Compatibility Matrix

**Phase 21B.4.10.** The Phase 21B.4.8.1/.2 live Modal qualification
proved vLLM 0.6.3.post1 can run a *compatible* model (`facebook/opt-125m`)
on a real L4 GPU — it did **not** prove vLLM 0.6.3.post1 supports every
September-2026 frontier architecture. This document records, for every
deployable candidate, what its OWN architecture requires, separately
from what ORNEUR has actually qualified.

## Currently qualified ORNEUR runtime

| Component | Version | Qualified against | Evidence |
|---|---|---|---|
| Backend | vLLM | `0.6.3.post1` | Real load + generation on Modal L4, Phase 21B.4.8.1 (after fixing a `transformers` pin incompatibility) |
| Transformers | pinned alongside vLLM | `4.45.2` | Same live qualification run |
| GPU / CUDA / precision | Modal L4, CUDA available, BF16 confirmed, FP8 dtype constructible | — | Phase 21B.4.8 live qualification |
| Sandbox (untrusted code) | `DockerSandboxBackend` | — | Qualified since Phase 21B.4.7A; Modal Sandbox (legacy + V2) permanently `NOT_QUALIFIED` |

**This is the ONLY runtime configuration this project has live-tested.**
Everything below is CANDIDATE-REQUIRED, not ORNEUR-confirmed.

## Per-candidate runtime requirement vs. currently-qualified runtime

| Candidate | Architecture class | `CANDIDATE_RUNTIME_REQUIREMENT` | vs. `CURRENTLY QUALIFIED ORNEUR RUNTIME` | Status |
|---|---|---|---|---|
| Qwen3.8-27B | `Qwen3_5ForConditionalGeneration` | A "3.5" generation Qwen class name distinct from the classic `Qwen3ForCausalLM` the controls use (below) — likely requires a Transformers/vLLM release newer than the qualified `4.45.2`/`0.6.3.post1` pair, and its `image-text-to-text` pipeline tag suggests a multimodal-capable checkpoint, which may carry its own vision-tower runtime requirements | NOT independently re-verified this phase | `RUNTIME_UPGRADE_QUALIFICATION_REQUIRED` |
| Qwen3.8-Flash-Next | `Qwen4ExpForConditionalGeneration` | A brand-new "Qwen4" experimental/expert-routing class — near-certainly postdates the qualified vLLM version; its sparse-MoE + n-gram-embedding + MTP-layer architecture (per `GENESIS_FRONTIER_MODEL_LANDSCAPE_2026_09.md`) likely needs custom kernel/routing support not present in `0.6.3.post1` | NOT independently re-verified this phase | `RUNTIME_UPGRADE_QUALIFICATION_REQUIRED` |
| Mistral Small 4 | `Mistral3ForConditionalGeneration` | A "Mistral3" conditional-generation class distinct from the classic `MistralForCausalLM` the Nemo control uses — its official FP8 checkpoint (confirmed live, `quant_method=fp8`) requires FP8-aware weight loading, which `0.6.3.post1`'s qualified path (BF16 dtype, per Phase 21B.4.8.1) has not been tested against; also multimodal (vision tower present) | NOT independently re-verified this phase | `RUNTIME_UPGRADE_QUALIFICATION_REQUIRED` |
| GLM-5.3-Flash | `Glm5NextForConditionalGeneration` | The most architecturally distinct of the four (its `quantization_config.modules_to_not_convert` list names dozens of custom module types — `hc_attn_base`, `hc_ffn_scale`, gated/hyper-connection components, custom conv1d projections — indicating a genuinely novel attention/routing design, not a routine transformer variant); its official FP8 checkpoint likewise requires FP8-aware loading | NOT independently re-verified this phase | `RUNTIME_UPGRADE_QUALIFICATION_REQUIRED` |
| Qwen3-8B (control) | `Qwen3ForCausalLM` | Mainstream, long-established class; plausibly already supported by the qualified `4.45.2`/`0.6.3.post1` pair | Not independently re-confirmed live this phase | `LIKELY_COMPATIBLE — NOT CONFIRMED` |
| Mistral-Nemo-Instruct-2407 (control) | `MistralForCausalLM` | Mainstream, long-established class | Not independently re-confirmed live this phase | `LIKELY_COMPATIBLE — NOT CONFIRMED` |
| Phi-4 (control) | `Phi3ForCausalLM` | Mainstream, long-established class | Not independently re-confirmed live this phase | `LIKELY_COMPATIBLE — NOT CONFIRMED` |

## Fields not resolved this phase (per candidate, tracked for the next runtime-qualification phase)

For every deployable candidate, the following remain explicitly
unresolved (recorded honestly as open questions, never guessed):

- Exact minimum supported Transformers version
- Exact minimum supported vLLM version (or whether SGLang is the better
  fit, given the custom architectures involved)
- `trust_remote_code` requirement (custom architecture classes commonly
  need this; not confirmed for any of the four)
- Tensor-parallel support (required for all four given their >1-GPU
  theoretical floors, per `GENESIS_COMPUTE_TOPOLOGY_QUALIFICATION_PLAN.md`)
- Expert-parallel support (relevant to the two MoE-style candidates,
  Qwen3.8-Flash-Next and GLM-5.3-Flash)
- Quantization-format runtime support (FP8-aware loading specifically,
  for Mistral Small 4 and GLM-5.3-Flash's official checkpoints)
- Multimodal runtime requirements (vision encoder loading/inference
  path) where applicable
- Reasoning-parser requirements, if any of the four expose an explicit
  reasoning/thinking mode requiring special output parsing

## What this phase explicitly does NOT do

Per owner spec §14: **"If candidate requires a newer runtime, do NOT
call it incompatible. Mark `RUNTIME_UPGRADE_QUALIFICATION_REQUIRED`."**
No candidate above is marked incompatible — every `RUNTIME_UPGRADE_
QUALIFICATION_REQUIRED` status is an open question requiring live
research/testing in a future phase, not a rejection. No GPU/runtime
upgrade was executed this phase (no CPU-only-verifiable check was
identified that would resolve any of these fields without either
downloading weights or starting a GPU, both prohibited this phase).
