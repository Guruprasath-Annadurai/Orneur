# Genesis Control Set Runtime Preflight — Phase 21B.4.16

**CPU / metadata / API-only. No GPU, no inference, no weight download, no
benchmark, no engine startup.**

Source evidence: `docs/orneur/phase-21/evidence/GENESIS_CONTROL_SET_PRIMARY_SOURCES_2026-09-23.json`
and the three per-control admission evidence files.

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

| Control | License | Actual LICENSE file in repo | Status |
|---|---|---|---|
| Qwen3-8B | Apache-2.0 | YES (persisted, hashed) | CLEAR |
| Mistral-Nemo-Instruct-2407 | Apache-2.0 | **NO** (metadata tag only) | CLEAR* |
| Phi-4 | MIT | YES (persisted, hashed) | CLEAR |

\* Mistral-Nemo-Instruct-2407 has no standalone `LICENSE`/`LICENSE.md`
file at the pinned revision (both checked, both HTTP 404) — the only
evidence is the repository's own `cardData.license: apache-2.0` HF API
field. This is recorded as an honest evidentiary gap. Apache-2.0 is a
well-known, unambiguous standard license, so this gap does not itself
create license ambiguity, but it means ORNEUR cannot hash a repo-local
full-text copy the way it did for the other two controls.

## Architecture / config identity

| Control | Architecture | Native context (config.json) | Weight (BF16) |
|---|---|---|---|
| Qwen3-8B | `Qwen3ForCausalLM` | 40,960 | 16.4 GB |
| Mistral-Nemo-Instruct-2407 | `MistralForCausalLM` | 131,072 | 24.5 GB (dual on-disk format) |
| Phi-4 | `Phi3ForCausalLM` | 16,384 | 29.3 GB |

All three architecture classes are confirmed live from `config.json` at
the pinned revision, matching the registry exactly.

## Runtime support

| Control | vLLM official recipe | Recipe scope | Parsers documented | SGLang |
|---|---|---|---|---|
| Qwen3-8B | YES (`recipes.vllm.ai/Qwen/Qwen3-8B`) | CPU (Intel Xeon 6) only — no GPU section | `--reasoning-parser qwen3 --tool-call-parser hermes` | not confirmed this phase |
| Mistral-Nemo-Instruct-2407 | NO dedicated page (404) | `library_name: vllm` HF tag signals vLLM as the intended path | none documented | not confirmed this phase |
| Phi-4 | NO dedicated page (404) | mainstream, long-supported architecture | none documented | not confirmed this phase |

Only Qwen3-8B has a dedicated, model-specific official recipe, and that
recipe is CPU-scoped (Xeon), not GPU-scoped — it does not itself prove
a GPU serving path, only that a documented CPU path exists with named
parser flags. Neither Mistral-Nemo nor Phi-4 has a dedicated recipe;
both rely on being mainstream, long-established architecture classes
within vLLM's general model support, which is a weaker (but still
reasonable) form of evidence than a dedicated recipe.

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

| Control | Minimum plausible native-precision topology | Safer qualification topology |
|---|---|---|
| Qwen3-8B | THEORETICAL: 1x 24GB-class GPU, substantial headroom | DOCUMENTED (CPU, Xeon 6) / THEORETICAL (GPU) |
| Mistral-Nemo-Instruct-2407 | THEORETICAL: 1x 24GB-class GPU, BORDERLINE (little/no headroom) | THEORETICAL: 1x 80GB+-class GPU |
| Phi-4 | THEORETICAL: 1x 24GB-class GPU, tight headroom | THEORETICAL: 2x 24GB-class GPU (TP2) or 1x 80GB+-class GPU |

No topology here is LIVE-PROVEN. A weight-fit calculation is not
runtime proof — none of these figures constitute a qualification claim.

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
- A tokenizer chat template (Qwen3-8B and Phi-4 confirmed directly;
  Mistral-Nemo's canonical path likely runs through the `mistral-common`
  package rather than a plain `chat_template.jinja`, per its repository
  tag — not independently deep-verified this phase).
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
