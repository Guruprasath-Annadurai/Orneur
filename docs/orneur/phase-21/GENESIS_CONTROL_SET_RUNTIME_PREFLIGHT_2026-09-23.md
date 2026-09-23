# Genesis Control Set Runtime Preflight — Phase 21B.4.16 (evidence closed in 21B.4.16.1)

**CPU / metadata / API-only. No GPU, no inference, no weight download, no
benchmark, no engine startup.**

Source evidence: `docs/orneur/phase-21/evidence/GENESIS_CONTROL_SET_PRIMARY_SOURCES_2026-09-23.json`,
the three per-control admission evidence files, and the three
`*_RUNTIME_PREFLIGHT_EVIDENCE_CLOSURE_2026-09-23.json` files added in
Phase 21B.4.16.1 to close weight-layout, tokenizer/chat-template, and
topology-math evidence gaps identified by independent audit.

## Purpose

Per Phase 21B.4.16 §1, the locked Genesis frontier methodology requires
EXACTLY THREE control models — Qwen3-8B, Mistral-Nemo-Instruct-2407,
Phi-4 — as a mandatory lower baseline. This document records what is
currently known about their future production-serving runtime paths,
without launching any engine or spending any compute.

## Identity re-verification summary

| Control | Registered pin | Current upstream HEAD | Drift |
|---|---|---|---|
| Qwen3-8B | `b968826d9c46dd6066d109eabc6255188de91218` | same | NO |
| Mistral-Nemo-Instruct-2407 | `04d8a90549d23fc6bd7f642064003592df51e9b3` | same | NO |
| Phi-4 | `2db69c1c3e91a05d2c64a3185acfbaf36f744e25` | same | NO |

All three registered pins are exactly the current upstream `main` HEAD
at the time of this phase's live re-verification — no silent drift, no
repinning performed or needed.

## License re-verification summary

| Control | License | Actual LICENSE file in repo | README prose declaration | Status |
|---|---|---|---|---|
| Qwen3-8B | Apache-2.0 | YES (persisted, hashed) | n/a (standalone file exists) | CLEAR |
| Mistral-Nemo-Instruct-2407 | Apache-2.0 | **NO** (both LICENSE and LICENSE.md checked, both 404) | **YES** — README line 29: "Released under the **Apache 2 License**" | CLEAR* |
| Phi-4 | MIT | YES (persisted, hashed) | n/a (standalone file exists) | CLEAR |

\* Mistral-Nemo-Instruct-2407 has no standalone `LICENSE`/`LICENSE.md`
file at the pinned revision. However, the pinned repository's own README
declares Apache-2.0 in **two** independent first-party places: the YAML
frontmatter metadata tag (`license: apache-2.0`, line 13) **and** explicit
prose text (line 29). Phase 21B.4.16.1 corrects the prior phase's
"metadata tag only" wording, which understated this evidence. The
absence of a standalone full-license-text file remains an accurate
evidentiary-*format* fact (ORNEUR cannot hash a repo-local full-text
copy the way it did for the other two controls) but this was never, and
is not, a license-*identity* ambiguity — Apache-2.0's canonical text is
a fixed, universally known standard document.

## Architecture / config identity

| Control | Architecture | Native context (config.json) | Weight (BF16), exact bytes | Shards |
|---|---|---|---|---|
| Qwen3-8B | `Qwen3ForCausalLM` | 40,960 | 16.4 GB (16,381,516,776 bytes exact) | 5 |
| Mistral-Nemo-Instruct-2407 | `MistralForCausalLM` | 131,072 | 24.5 GB (24,495,604,224 bytes exact, dual on-disk format) | 5 (HF) / 1 (consolidated) |
| Phi-4 | `Phi3ForCausalLM` | 16,384 | 29.3 GB (29,319,042,992 bytes exact) | 6 |

All three architecture classes are confirmed live from `config.json` at
the pinned revision, matching the registry exactly. Exact byte totals
are freshly derived this phase (21B.4.16.1) from HF tree-API per-shard
file listings at the pinned revision — not from `parameter_count × 2`
arithmetic — for all three controls; see each control's
`*_RUNTIME_PREFLIGHT_EVIDENCE_CLOSURE_2026-09-23.json` for the full
per-shard breakdown and reproduction methodology.

## Runtime support

| Control | vLLM official recipe | Recipe scope | Parsers documented | vLLM supported_models.md | SGLang |
|---|---|---|---|---|---|
| Qwen3-8B | YES (`recipes.vllm.ai/Qwen/Qwen3-8B`, min vLLM 0.8.5+) | CPU (Intel Xeon 6) only — no GPU section | `--reasoning-parser qwen3 --tool-call-parser hermes` | `Qwen/Qwen3-8B` named explicitly | not confirmed this phase |
| Mistral-Nemo-Instruct-2407 | NO dedicated page (404) | `library_name: vllm` HF tag signals vLLM as the intended path | none documented | `MistralForCausalLM` row confirmed; this exact model NOT named by example | not confirmed this phase |
| Phi-4 | NO dedicated page (404) | — | none documented | `microsoft/Phi-4` named explicitly | not confirmed this phase |

Only Qwen3-8B has a dedicated, model-specific official recipe, and that
recipe is CPU-scoped (Xeon), not GPU-scoped — it does not itself prove
a GPU serving path, only that a documented CPU path exists with named
parser flags. Neither Mistral-Nemo nor Phi-4 has a dedicated recipe.
Phase 21B.4.16.1 strengthens both weak "mainstream architecture"
statements with a cited primary source: vLLM's own official
`supported_models.md` (fetched from the `vllm-project/vllm` repository's
`main` branch HEAD) names `microsoft/Phi-4` explicitly as an Example HF
Model for `Phi3ForCausalLM`, and confirms the `MistralForCausalLM`
architecture row (though without naming Mistral-Nemo-Instruct-2407
specifically) — see
`docs/orneur/phase-21/evidence/GENESIS_CONTROL_SET_VLLM_SUPPORTED_MODELS_PRIMARY_SOURCE_2026-09-23.md`.
"Not researched" is converted to "researched and confirmed" for Phi-4,
not silently upgraded to "unsupported" or downgraded without evidence
for Mistral-Nemo.

## Future engine decision (per control)

| Control | Primary | Fallback | Basis |
|---|---|---|---|
| Qwen3-8B | vLLM | native Transformers | dedicated recipe with named parser flags; existing ORNEUR vLLM harness experience |
| Mistral-Nemo-Instruct-2407 | vLLM | native Transformers | `library_name: vllm` structural HF tag; existing ORNEUR vLLM harness experience |
| Phi-4 | vLLM | native Transformers | mainstream vLLM-supported architecture; existing ORNEUR vLLM harness experience |

None is `ENGINE_SELECTION_INCONCLUSIVE` — each has at least one concrete,
evidence-backed signal favoring vLLM, and no evidence favors SGLang
specifically for any of the three this phase. SGLang is not ruled out
in principle; it is simply unconfirmed for these three controls with
the research performed this phase.

## Future topology (theoretical/documented, never claimed qualified)

**Phase 21B.4.16.1 correction:** two topology statements in the original
Phase 21B.4.16 version of this table were wrong and are corrected here.
A GPU marketed as "24GB" does not provide more raw bytes than its
marketed capacity, and runtime/KV-cache allocations require additional
space beyond the raw weight floor regardless — so "little/no headroom"
and "tight headroom" both incorrectly implied a possible fit where none
exists.

| Control | Raw weight fit, 1x 24GB-class GPU | Minimum plausible native-precision topology | Safer qualification topology |
|---|---|---|---|
| Qwen3-8B | **YES** (16.4 GB fits within 24GB raw capacity) | THEORETICAL: 1x 24GB-class GPU, headroom remains for KV cache | DOCUMENTED (CPU, Xeon 6) / THEORETICAL (GPU) |
| Mistral-Nemo-Instruct-2407 | **NO** (24.5 GB exceeds 24GB raw capacity — corrected from "BORDERLINE, little/no headroom") | THEORETICAL: larger single card (80GB+) or a multi-GPU topology explicitly supported by the chosen runtime | THEORETICAL: 1x 80GB+-class GPU |
| Phi-4 | **NO** (29.3 GB exceeds 24GB raw capacity — corrected from "tight headroom", which wrongly implied a possible fit) | THEORETICAL: 2x 24GB-class GPU (aggregate memory only — TP2 support for Phi3ForCausalLM on vLLM is **not confirmed**, not inferred merely because two GPUs have enough combined memory) or 1x 80GB+-class GPU | THEORETICAL: 1x 80GB+-class GPU (avoids relying on unconfirmed TP2 support) |

No topology here is LIVE-PROVEN. A weight-fit calculation is not
runtime proof, and raw weight fit is distinct from production-serving
qualification — none of these figures constitute a qualification claim
for any control.

## Zero-owner-cash execution feasibility

No GPU execution was performed to determine any of the following, and
no promotional credits, account balance, or prior-phase credit state is
assumed:

| Control | Classification |
|---|---|
| Qwen3-8B | POTENTIALLY_AVAILABLE |
| Mistral-Nemo-Instruct-2407 | POTENTIALLY_AVAILABLE |
| Phi-4 | POTENTIALLY_AVAILABLE |

All three are classified `POTENTIALLY_AVAILABLE` rather than
`AVAILABLE_NOW` because a live billing/credit check (the kind performed
immediately before any actual GPU allocation, per
`GENESIS_ZERO_CASH_GPU_EXECUTION_CONTROL_SPEC_2026-09-23.md`) has not
been performed for these controls specifically. The standing run-level
acceptance invariant for any future execution remains:
`billed_after_usd - billed_before_usd == owner_billed_delta_usd`, and
`owner_billed_delta_usd == 0` — unchanged and unweakened by this phase.

## Evaluation-adapter compatibility (preflight only, no execution)

All three controls expose:
- A chat-completions-shaped request format compatible with an
  OpenAI-compatible serving path once actually served (vLLM's standard
  `/v1/chat/completions`).
- System/user/assistant role support (standard for all three
  architecture families).
- A tokenizer chat template, now directly confirmed for **all three**
  controls at the pinned revision (Phase 21B.4.16.1 closure): Qwen3-8B
  (`enable_thinking` hybrid-mode branch, 4,168-char template), Phi-4
  (`<|im_start|>role<|im_sep|>content<|im_end|>` format, 462-char
  template), and Mistral-Nemo-Instruct-2407 (tokenizer_config.json
  independently fetched and found to contain a populated `chat_template`
  field, in addition to — not instead of — the separate Mistral-native
  `params.json`/`tekken.json` path implied by the `mistral-common` tag).
- Reasoning-content handling relevant only to Qwen3-8B (hybrid thinking
  mode); not applicable to Mistral-Nemo or Phi-4.

No task execution occurred. This section exists solely to flag future
adapter-compatibility risk before any GPU money is spent, per phase
instruction.

## No capability claims

This document makes zero capability, ranking, or frontier-comparison
claims about any control, and none of the three is compared to any
other control or to any Genesis deployable candidate. All capability
remains UNEXECUTED / UNPROVEN UNDER GENESIS PROTOCOL.

## Runtime-preflight-status closure (Phase 21B.4.16.1)

Per the phase-locked rule, `runtime_preflight_status = READY` requires:
resolved identity, clear license, a reproducible pinned artifact, actual
weight-layout evidence, a known chat/template/tokenizer path, at least
one evidence-supported future runtime path, and no unresolved blocker.
All three controls now satisfy every one of these criteria as of this
phase's evidence closure:

| Control | Identity | License | Weight-layout evidence | Chat/tokenizer path | Runtime path | Blocker | `runtime_preflight_status` |
|---|---|---|---|---|---|---|---|
| Qwen3-8B | RESOLVED | CLEAR | COMPLETE (exact bytes) | COMPLETE | vLLM (dedicated recipe) | NONE | READY |
| Mistral-Nemo-Instruct-2407 | RESOLVED | CLEAR | COMPLETE (exact bytes, prior phase) | COMPLETE | vLLM (`library_name` tag + architecture-class confirmation) | NONE | READY |
| Phi-4 | RESOLVED | CLEAR | COMPLETE (exact bytes) | COMPLETE | vLLM (architecture-class confirmation, model named explicitly) | NONE | READY |

`control_admission_status` remains `ADMITTED` for all three, and
`runtime_qualification_status` remains `NOT_TESTED` for all three —
`READY` preflight status is not, and must never be conflated with, a
runtime qualification claim.
