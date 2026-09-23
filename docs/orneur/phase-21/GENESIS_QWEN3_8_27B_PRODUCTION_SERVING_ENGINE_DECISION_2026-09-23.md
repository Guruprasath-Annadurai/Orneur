# Qwen3.8-27B Production-Serving Engine Decision — Phase 21B.4.15

**CPU/documentation-only. No GPU allocated to produce this decision.**

Source evidence: `docs/orneur/phase-21/evidence/QWEN3_8_27B_CURRENT_SERVING_PRIMARY_SOURCES_2026-09-23.json`,
`docs/orneur/phase-21/evidence/QWEN3_8_27B_RUNTIME_SUPPORT_MATRIX_2026-09-23.json`.

## Candidates considered

vLLM vs SGLang, per phase instruction. TokenSpeed is named by Qwen's own
README as a third recommended engine but is excluded from serious
comparison here: its evidence base in the current primary sources is a
single override-syntax snippet, with no dedicated recipe, no measured
numbers, and no resolvable container image lookup performed this phase
— insufficient to compare on the criteria below.

## Comparison

| Criterion | vLLM | SGLang |
|---|---|---|
| Official Qwen support | Explicit, via Qwen's own README Quickstart list | Explicit, via Qwen's own README Quickstart list |
| Dedicated recipe evidence | **Full dedicated recipe page** (recipes.vllm.ai) with multiple measured launch-command variants (RTX5090 NVFP4, 2xRTX5090 NVFP4, GB300 FP8 TP4, Ascend w8a8/native-FP8, DFlash2 speculative) | **No dedicated recipe page found.** Evidence limited to one official long-context override snippet in Qwen's README |
| Model architecture compatibility (Qwen3_5ForConditionalGeneration) | Confirmed via the recipe's own measured, working launch commands | Confirmed only indirectly, via the README's long-context override syntax targeting this exact model |
| OpenAI-compatible API | Yes, documented | Implied by the README's general framework list, not independently confirmed this phase with a concrete SGLang API example |
| Reasoning parsing | `--reasoning-parser qwen3`, explicitly documented as "not optional in practice" | Not documented in the retrieved sources this phase |
| Tool calling | `--enable-auto-tool-choice --tool-call-parser qwen3_xml` (general) or `qwen3_coder` (Ascend variant), explicitly documented | Not documented in the retrieved sources this phase |
| Multimodal support | Recipe explicitly scopes itself to text-only and states multimodal is unverified by it | Not addressed in retrieved sources |
| Reproducibility (image pinning) | Resolved a stable, versioned, non-nightly release: `v0.30.0-cu129`, linux/amd64 digest `sha256:58fdb6bb123a81aa53f46fa4652ad8cc87e817bd1077c9832c6258ef12c1c688` | Resolved a stable, versioned, non-nightly release: `v0.5.20`, linux/amd64 digest `sha256:b27fce60bc5494c118c4910702812bcfa8cee67abcdd1ff8b0902f21647552f4` |
| Container pinning quality | Equal — both resolved to genuine stable tags with digests, CPU-only, no GPU required to resolve | Equal — see left |
| H200 compatibility | Recipe demonstrates Hopper-class topologies indirectly (GB300 FP8 TP4 example; no direct H100/H200 example, but the architecture and engine are Hopper-and-newer-class per general vLLM support) | No H100/H200-specific example found in retrieved sources |
| Memory behavior | Recipe gives concrete, measured KV-pool-size numbers across multiple precisions/topologies (e.g. 377,456 KV tokens at FP8 TP2, 262K context) | No measured memory numbers found in retrieved sources |
| Operational simplicity for ORNEUR's existing infra | ORNEUR's Mistral Small 4 and GLM-5.3-Flash phases already built, tested, and validated a real `vllm serve` harness pattern (Modal ephemeral GPU function, entrypoint clearing, readiness polling via `/v1/models`, generation smoke via `/v1/chat/completions`) — directly reusable | No existing ORNEUR SGLang harness exists; would require net-new harness design and validation |
| Evidence quality for strict qualification | High — dense, specific, measured | Low — thin, generic |

## Decision

**PRIMARY FUTURE QUALIFICATION ENGINE: vLLM**

**FALLBACK ENGINE: SGLang** (only if a future vLLM-specific blocker for
this architecture surfaces during CPU-only preflight or GPU execution;
SGLang's own official support is real but its current evidence base is
too thin to serve as a strict-qualification primary path today).

## Rationale

This is not a vague preference ranking. Every criterion where the two
engines differ favors vLLM specifically because of **evidence density**,
not because SGLang is unsupported or inferior in principle:

1. vLLM has a dedicated, Qwen-authored-or-endorsed recipe page with
   multiple measured launch configurations for this exact architecture.
   SGLang's evidence is a single generic override snippet reused across
   three different frameworks in the README — it proves SGLang is
   *officially listed*, not that a specific, verified launch
   configuration exists for Qwen3.8-27B the way vLLM's does.
2. ORNEUR already has a working, tested `vllm serve` harness pattern
   from the Mistral Small 4 and GLM-5.3-Flash phases (Modal ephemeral
   GPU function + entrypoint clearing + `/v1/models`/`/v1/chat/completions`
   readiness/generation smoke). Reusing this pattern for Qwen3.8-27B is a
   narrow, low-risk extension; building an equivalent SGLang harness from
   scratch is new surface area this phase has no evidence base to design
   safely against (no confirmed SGLang reasoning-parser or tool-call-parser
   flags, no measured SGLang memory numbers for this model).
3. Reasoning-parser and tool-call-parser support — both material to
   ORNEUR's eventual agent/tool ecosystem integration — are explicitly
   documented for vLLM (`qwen3` / `qwen3_xml`) and undocumented for
   SGLang in the current evidence base.

This is not `ENGINE_SELECTION_INCONCLUSIVE` — the evidence clearly
favors vLLM on every comparable criterion, and no criterion favors
SGLang. It is also not a claim that SGLang is worse in an absolute
sense; only that its *currently available official evidence* for this
specific model is materially thinner than vLLM's, which is what a
strict, evidence-based qualification decision must weigh.

## What would change this decision

- A dedicated SGLang recipe page or an official Qwen-published SGLang
  launch-command set with reasoning/tool-call parser flags and measured
  memory numbers for Qwen3.8-27B, matching vLLM's evidence density.
- A concrete vLLM-specific blocker discovered during a future CPU-only
  preflight against the resolved `v0.30.0-cu129` image (e.g. the
  architecture registry not actually recognizing `Qwen3_5ForConditionalGeneration`
  in that exact build).

Neither has occurred as of this phase. No GPU work is authorized to
investigate either further in this phase.
