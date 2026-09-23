# Qwen3.8-27B Production-Serving Engine Decision — Phase 21B.4.15 (corrected Phase 21B.4.15.1)

**CPU/documentation-only. No GPU allocated to produce this decision.**

Source evidence: `docs/orneur/phase-21/evidence/QWEN3_8_27B_CURRENT_SERVING_PRIMARY_SOURCES_2026-09-23.json`,
`docs/orneur/phase-21/evidence/QWEN3_8_27B_RUNTIME_SUPPORT_MATRIX_2026-09-23.json`.

**Phase 21B.4.15.1 correction notice:** independent audit found that
Phase 21B.4.15's original version of this document understated SGLang's
official evidence — it missed a dedicated, extensively measured
official SGLang Cookbook page for this exact model
(`docs.sglang.io/cookbook/autoregressive/Qwen/Qwen3.8-27B`, linked
directly from the Qwen README itself), and as a result several rows
below and the original rationale incorrectly characterized SGLang's
evidence as "thin" or "undocumented." This document is rewritten in
full with the corrected evidence. **The decision (vLLM primary, SGLang
fallback) is UNCHANGED, but the reasoning behind it is now based on
real, evidence-backed differentiators rather than an evidence-density
claim that was not actually true.**

## Candidates considered

vLLM vs SGLang, per phase instruction. TokenSpeed is named by Qwen's own
README as a third recommended engine but is excluded from serious
comparison here: its evidence base in the current primary sources is a
single override-syntax snippet, with no dedicated recipe, no measured
numbers, and no resolvable container image lookup performed this phase
— insufficient to compare on the criteria below.

## Comparison (corrected)

| Criterion | vLLM | SGLang |
|---|---|---|
| Official Qwen support | Explicit, via Qwen's own README Quickstart list, linking to a dedicated recipe | Explicit, via Qwen's own README Quickstart list, linking to a dedicated cookbook |
| Dedicated recipe evidence | Full dedicated recipe page (recipes.vllm.ai) with multiple measured launch-command variants (RTX5090 NVFP4, 2xRTX5090 NVFP4, GB300 FP8 TP4, Ascend w8a8/native-FP8, DFlash2 speculative) | **Full dedicated cookbook page** (docs.sglang.io) — 202 measured cells across H200/RTX PRO 6000/RTX 5090/DGX Spark and multiple precisions, each scored on the full 1319-question GSM8K, measured on SGLang v0.5.19. **Correction: this evidence base is comparable to, and in measured-cell breadth exceeds, vLLM's.** |
| Model architecture compatibility (Qwen3_5ForConditionalGeneration) | Confirmed via the recipe's own measured, working launch commands; a Phase 21B.4.15.1 CPU-only preflight attempt against the resolved image was inconclusive (unrelated torchvision/torch mismatch blocked the check, no GPU/weights involved) | Confirmed via the cookbook's own measured, GSM8K-scored recipes for this exact model — direct, model-specific evidence |
| OpenAI-compatible API | Yes, documented | Yes, documented (`http://<host>:30000/v1`), plus an Anthropic-compatible `/v1/messages` endpoint (noted by SGLang's own docs as outside Anthropic's tested scope for non-Claude models when used with Claude Code) |
| Reasoning parsing | `--reasoning-parser qwen3`, explicitly documented as "not optional in practice" | `--reasoning-parser qwen3`, **explicitly standard in every cookbook recipe** (correction: this was previously recorded as undocumented for SGLang, which was inaccurate) |
| Tool calling | `--tool-call-parser qwen3_xml` (NVFP4-variant-repo examples) / `qwen3_coder` (Ascend examples) — **PRIMARY_SOURCE_CONFIGURATION_DIVERGENCE, unresolved this phase** | `--tool-call-parser qwen3_coder`, **explicitly standard in every cookbook recipe with a documented chat-template-based rationale** (correction: this was previously recorded as undocumented for SGLang, which was inaccurate) |
| Multimodal support | Recipe explicitly scopes itself to text-only and states multimodal is unverified by it | Cookbook explicitly states the vision tower is live on its recipes ("SGLang serves it through the Qwen3-VL path") — SGLang's own stated multimodal scope is broader than vLLM's recipe claims for itself, though neither is included in ORNEUR's required qualification evidence this phase (§13 of the phase spec) |
| Reproducibility (image pinning) | Resolved a stable, versioned, non-nightly release: `v0.30.0-cu129`, linux/amd64 digest `sha256:58fdb6bb123a81aa53f46fa4652ad8cc87e817bd1077c9832c6258ef12c1c688` | Resolved a stable, versioned, non-nightly release: `v0.5.20`, linux/amd64 digest `sha256:b27fce60bc5494c118c4910702812bcfa8cee67abcdd1ff8b0902f21647552f4` (the cookbook's own 202 measured cells are pinned specifically to v0.5.19, one patch version earlier) |
| Container pinning quality | Equal — both resolved to genuine stable tags with digests, CPU-only, no GPU required to resolve | Equal — see left |
| H200 compatibility | Recipe demonstrates Hopper-class topologies indirectly (GB300 FP8 TP4 example; no direct H100/H200 example) | **Explicit, direct H200 support** — the cookbook's own hardware matrix names H200 as one of four supported single-GPU cards, with H200-specific notes (BF16/FP8 only, no FP4 tensor cores; 32768-token prefill chunks; ~6.5 min load time for 18 BF16 shards from NVMe). **Correction: this is materially stronger direct H200 evidence than vLLM's.** |
| Memory behavior | Recipe gives concrete, measured KV-pool-size numbers across multiple precisions/topologies (e.g. 377,456 KV tokens at FP8 TP2, 262K context) | Cookbook gives a documented GDN-state/KV-pool sizing formula (`--mamba-full-memory-ratio`) plus a calculator, and 202 measured cells' worth of concrete throughput/accuracy data | 
| Operational simplicity for ORNEUR's existing infra | ORNEUR's Mistral Small 4 and GLM-5.3-Flash phases already built, tested, and validated a real `vllm serve` harness pattern (Modal ephemeral GPU function, entrypoint clearing, readiness polling via `/v1/models`, generation smoke via `/v1/chat/completions`) — directly reusable | No existing ORNEUR SGLang harness exists; would require net-new harness design, testing, and validation before a first GPU attempt |
| Evidence quality for strict qualification | High — dense, specific, measured | **Also high** (correction) — dense, specific, measured, comparable to vLLM's |

## Decision

**PRIMARY FUTURE QUALIFICATION ENGINE: vLLM**

**FALLBACK ENGINE: SGLang** — now explicitly acknowledged as a strong,
comparably-evidenced fallback (not a weak one), reserved because of
ORNEUR's own implementation-risk profile, not because its official
support or documentation is inferior.

## Rationale (corrected — real differentiators only)

The original Phase 21B.4.15 rationale claimed vLLM won on "evidence
density," which the corrected comparison above shows was not actually
true — SGLang's official evidence for this exact model is comparably
rich, with genuinely stronger direct H200 confirmation and equally
explicit parser flags. The decision to keep vLLM as primary is
unchanged, but now rests on the differentiators that are actually real:

1. **ORNEUR already has a working, tested `vllm serve` harness
   pattern** from the Mistral Small 4 and GLM-5.3-Flash phases (Modal
   ephemeral GPU function + entrypoint clearing +
   `/v1/models`/`/v1/chat/completions` readiness/generation smoke,
   including the corrected failure-detection logic from the GLM
   Phase 21B.4.13.2 quarantine). Reusing this pattern for Qwen3.8-27B is
   a narrow, low-risk extension of code ORNEUR has already built,
   debugged, and validated end-to-end (including through a real
   financial-guardrail incident and its correction). Building an
   equivalent SGLang harness from scratch — new server-readiness
   detection, new endpoint conventions (SGLang's default port is 30000,
   not vLLM's 8000; SGLang additionally exposes an Anthropic-compatible
   endpoint ORNEUR does not need for this qualification), new failure
   modes — is net-new surface area with no prior ORNEUR validation
   history behind it.
2. **Lower implementation risk for ORNEUR's immediate qualification
   path.** This is explicitly a risk-management differentiator, not an
   evidence-quality one: given two comparably well-documented official
   engines, the one ORNEUR has already operated successfully in
   production-adjacent conditions (Mistral Small 4's accepted
   qualification, GLM-5.3-Flash's technical-success-but-financially-
   rejected run) is the lower-risk choice for a *first* Qwen3.8-27B
   production-serving qualification attempt.
3. **vLLM's evidence includes detailed memory/topology/quantization/
   long-context information in a form (measured KV-pool token counts
   per topology) that maps directly onto ORNEUR's existing manifest
   schema fields** (`weight_storage_envelope`, `theoretical_gpu_count_80gb_class`)
   from prior phases, reducing translation risk between "what the
   recipe measured" and "what ORNEUR's evidence schema expects."

This is not `ENGINE_SELECTION_INCONCLUSIVE` — a decision is reached —
but it is explicitly NOT a claim that SGLang lacks capabilities its
official documentation actually demonstrates. SGLang's tool-call parser
recommendation (`qwen3_coder`, with a specific, technically justified
rationale) is in fact evidence that should inform the still-unresolved
vLLM tool-call-parser divergence (see below), not evidence to be
discounted because vLLM was chosen as primary.

## Unresolved: tool-call-parser divergence

vLLM's own recipe uses `qwen3_xml` for its NVFP4-quantized-variant
examples but `qwen3_coder` for its Ascend examples. SGLang's cookbook
uses `qwen3_coder` universally for this model family, with an explicit
technical justification (this checkpoint's chat template emits an
inner `<function=.../><parameter=...>` block nested in
`<tool_call></tool_call>`, which is exactly what `qwen3_coder` decodes;
the Hermes-style parser reads a different, incompatible bare-JSON
payload). This is recorded as `PRIMARY_SOURCE_CONFIGURATION_DIVERGENCE`.
A Phase 21B.4.15.1 CPU-only preflight attempted to resolve it by
inspecting vLLM's own tool-parser registry inside the resolved image;
the attempt was **inconclusive** (the expected module path,
`vllm.entrypoints.openai.tool_parsers`, does not exist in vLLM
v0.30.0+cu129 — the API surface has been reorganized and the correct
current path was not determined this phase). Given SGLang's explicit,
checkpoint-specific rationale for `qwen3_coder`, and that
`qwen3_coder` is ALSO what vLLM's own Ascend examples use, `qwen3_coder`
is the more evidence-supported choice — but this is not frozen as
final. Per phase instruction, the future qualification run must use
whichever parser configuration passes a corrected CPU-only preflight
(finding the right registry-inspection path for the resolved vLLM
version) or, failing that, is confirmed live during the actual GPU
qualification run itself — see the updated qualification spec's
explicit non-freezing of this choice.

## What would change this decision

- A concrete vLLM-specific blocker discovered during a corrected
  CPU-only preflight or during GPU execution (e.g. the architecture
  registry genuinely not recognizing `Qwen3_5ForConditionalGeneration`
  in the resolved build, once the torchvision/torch mismatch blocking
  Phase 21B.4.15.1's check is fixed).
- A successful ORNEUR SGLang harness validation in a future phase,
  which would remove the "no prior operational history" differentiator
  entirely and could justify re-opening the primary/fallback choice.

Neither has occurred as of this phase. No GPU work is authorized to
investigate either further in this phase.
