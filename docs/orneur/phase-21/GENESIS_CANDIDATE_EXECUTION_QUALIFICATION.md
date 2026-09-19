# Genesis Candidate Execution Qualification (Stage 0)

**Phase 21B.4.10, hardened 21B.4.10.1.** This document summarizes the
Stage-0 identity/license/runtime eligibility qualification performed
against the machine-readable registry
[`GENESIS_CANDIDATE_EXECUTION_REGISTRY.json`](GENESIS_CANDIDATE_EXECUTION_REGISTRY.json)
(schema `genesis-candidate-execution-registry-v2`: `orca/eval/candidate_registry.py`,
tests: `tests/test_candidate_registry.py`). **No candidate is declared
frontier-class, benchmark-qualified, or Genesis-selected here.**

**Phase 21B.4.10.1 correction**: deployable candidates' single
conflated `stage0_status` field is replaced by four separate fields
(`identity_status`, `license_status`, `runtime_qualification_status`,
`runtime_smoke_eligibility`) so that "runtime not yet qualified"
(exactly what a runtime smoke test exists to resolve) is never confused
with "not eligible to attempt a smoke test." `runtime_smoke_eligibility:
ELIGIBLE` means only that a future, separately authorized phase MAY
attempt to LOAD that candidate — nothing more; controls retain the
simpler `stage0_status` field (`ELIGIBLE_FOR_RUNTIME_SMOKE`), since they
never suffer this conflation.

## What Stage 0 actually checked

For every deployable candidate, control, and frontier reference, using
ONLY small metadata retrieved live from the Hugging Face Hub API
(`GET /api/models/{repo}` — no weight shards were downloaded):

- **Identity**: exact immutable revision (a real commit SHA, never
  `main`/`latest`/a floating tag — enforced structurally by
  `orca/eval/candidate_registry.py`'s schema validator, exactly the same
  discipline `orca.eval.runner.CandidateConfig.__post_init__` already
  enforces for real evaluation runs).
- **License**: the repository's own `cardData.license` / license tag
  (a primary source), never inferred from a blog post or secondary
  commentary.
- **Architecture & parameters**: total parameters (the weight-storage
  driver — never active parameters, per the standing
  `GENESIS_FRONTIER_COMPUTE_MATRIX.md` warning), parameter dtype
  breakdown (revealing, for two candidates, that an OFFICIAL FP8
  checkpoint already exists — see below), and the model's
  `architectures` class name.

## Summary table — deployable candidates (hardened fields, Phase 21B.4.10.1)

| Candidate | Revision (short) | License | Total params | Official FP8 checkpoint? | Identity | License status | Runtime qual. | Smoke eligibility |
|---|---|---|---|---|---|---|---|---|
| Qwen3.8-27B | `1d4bf0f2` | apache-2.0 | 27.78B | No (BF16 only) | RESOLVED | CLEAR | UNQUALIFIED | **ELIGIBLE** |
| Qwen3.8-Flash-Next | `de4b8e4d` | other (qwen-community-1.0) | 180.0B | No (BF16 only) | RESOLVED | LICENSE_REVIEW_REQUIRED | UNQUALIFIED | **BLOCKED** |
| Mistral Small 4 | `a11f36be` | apache-2.0 | 119.4B | **Yes** | RESOLVED | CLEAR | UNQUALIFIED | **ELIGIBLE** |
| GLM-5.3-Flash | `eb9eb208` | mit | 321.3B | **Yes** | RESOLVED | CLEAR | UNQUALIFIED | **ELIGIBLE** |

## Summary table — controls and frontier references

| Candidate | Class | Revision (short) | License | Total params | Status |
|---|---|---|---|---|---|
| Qwen3-8B (control) | Control | `b968826d` | apache-2.0 | 8.19B | `ELIGIBLE_FOR_RUNTIME_SMOKE` |
| Mistral-Nemo-Instruct-2407 (control) | Control | `04d8a905` | apache-2.0 | 12.25B | `ELIGIBLE_FOR_RUNTIME_SMOKE` |
| Phi-4 (control) | Control | `2db69c1c` | mit | 14.66B | `ELIGIBLE_FOR_RUNTIME_SMOKE` |
| DeepSeek V4.1-Flash | Reference | `dba1be0a` | mit | ~763B (Phase 21B.4.8) | `REFERENCE_EXECUTION_DEFERRED` |
| GLM-5.3 (flagship) | Reference | `aca966e4` | other | ~743B (Phase 21B.4.8) | `REFERENCE_EXECUTION_DEFERRED` |
| Mistral Large 3 | Reference | `d40f4a01` | apache-2.0 | ~675B (Phase 21B.4.8) | `REFERENCE_EXECUTION_DEFERRED` |
| MiniMax M3 | Reference | `f0e1c1e0` | other (custom, terms review pending) | ~428B (Phase 21B.4.8) | `REFERENCE_EXECUTION_DEFERRED` |
| Qwen3.8-Max | Reference (mutable API) | N/A (managed API) | N/A | N/A | `REFERENCE_EXECUTION_DEFERRED` |
| Kimi K3 | Reference | `f831ab66` | other | ~2.8T (Phase 21B.4.8) | `REFERENCE_EXECUTION_DEFERRED` |

Full SHAs, per-dtype parameter breakdowns, and every other Stage-0
field are in the registry JSON — this table is a summary, not the
source of truth.

## Key findings this phase

1. **Two deployable candidates ship official FP8 checkpoints.** Mistral
   Small 4 (`quant_method=fp8`, vision tower/projector/lm_head excluded
   from quantization) and GLM-5.3-Flash (`quant_method=fp8`, a much
   larger exclusion list reflecting its more complex MoE architecture)
   are NOT published as BF16-native models that would need converting —
   their actual weight-storage footprint is already the FP8 figure in
   `GENESIS_FRONTIER_COMPUTE_MATRIX.md`/`GENESIS_FRONTIER_COST_PLAN.md`,
   not a hypothetical post-hoc quantization.
2. **Qwen3.8-Flash-Next's license remains `LICENSE_REVIEW_REQUIRED`** —
   Hugging Face's own tag is the generic `other`, consistent with the
   `qwen-community-1.0` custom-license finding from Phase 21B.4.8.1.
   Ambiguity was not converted to `GRANTED`.
3. **Mistral Small 4 and GLM-5.3-Flash both use brand-new, custom
   architecture classes** (`Mistral3ForConditionalGeneration`,
   `Glm5NextForConditionalGeneration`) not previously qualified against
   any runtime in this project — see `GENESIS_RUNTIME_COMPATIBILITY_MATRIX.md`.
   Qwen3.8-27B and Qwen3.8-Flash-Next use `Qwen3_5ForConditionalGeneration`
   and `Qwen4ExpForConditionalGeneration` respectively — also unqualified.
4. **All three controls** use mainstream, long-established architecture
   classes (`Qwen3ForCausalLM`, `MistralForCausalLM`, `Phi3ForCausalLM`)
   plausibly already compatible with the Phase 21B.4.8.1/.2-qualified
   vLLM 0.6.3.post1, though this was not independently re-confirmed live
   this phase (owner spec §14: no GPU/runtime work this phase beyond
   what is CPU-only-verifiable, and none of this required a live check).
5. **No frontier reference was called.** All six remain
   `REFERENCE_EXECUTION_DEFERRED` — five are open-weight but
   compute-prohibitive to self-host (per `GENESIS_FRONTIER_COMPUTE_MATRIX.md`);
   Qwen3.8-Max is a mutable managed-API product with no pinned identity,
   correctly excluded from ever claiming one.

## What this phase does NOT establish

- Whether any candidate actually LOADS on Modal (no GPU was started).
- Whether vLLM/SGLang/Transformers actually supports any of the four
  novel architecture classes above (`GENESIS_RUNTIME_COMPATIBILITY_MATRIX.md`
  records the open question, not an answer).
- Any capability, benchmark, or frontier-class judgment about any
  candidate.
- A locked cost figure for any candidate's runtime smoke test
  (`GENESIS_ZERO_CASH_EXECUTION_PLAN.md` restates every Phase
  21B.4.9.2 cost figure as `PRELIMINARY / NOT EXECUTION-AUTHORIZED`,
  unchanged).

## Candidate ordering for a future runtime-smoke phase (infrastructure evidence, not capability ranking)

Per owner spec §21: if a future phase attempts runtime smoke tests, the
smallest/cheapest topology that still tests a REAL deployable candidate
is a reasonable resource-scheduling order — **this is infrastructure
sequencing, not a capability judgment, and no intelligence ranking is
inferred from it**. **Corrected, Phase 21B.4.10.1**: the registry
records Qwen3.8-27B's official repository as BF16-only (no official
INT4 checkpoint was observed) — the prior version of this ordering
incorrectly assumed an L4 INT4 smoke was the lowest-risk first real
load, which would introduce TWO untested variables at once (runtime
compatibility AND an unqualified post-hoc quantization path). The
corrected preferred sequence for Qwen3.8-27B specifically:

**A.** Metadata/config/tokenizer/runtime-parser compatibility check
using no full weights where possible (config.json parsing, tokenizer
loading, checking whether the installed/target runtime recognizes the
`Qwen3_5ForConditionalGeneration` architecture class at all) — this
resolves real information with zero GPU cost and zero weight download.

**B.** If (A) succeeds: the candidate's OWN OFFICIAL pinned BF16
checkpoint on an 80GB-class GPU (A100-80GB/H100/H200, or the current
supported equivalent with sufficient practical headroom) — never a
custom/ad-hoc INT4 quantization path, which this candidate's official
repository does not itself provide.

Only after (A) and (B) both succeed would an ad-hoc quantization route
be evaluated as a SEPARATE, explicitly-labeled experiment — never
substituted as the "first real load" itself. **This phase does not
launch (A) or (B)** — this is the corrected plan for a future phase to
execute.

Full candidate-ordering table:

1. Qwen3.8-27B — Stage A (metadata-only) then Stage B (official BF16 on
   an 80GB-class GPU) per the correction above; smallest deployable
   candidate by total parameters.
2. Mistral Small 4 (2-3 GPU theoretical floor, official FP8 checkpoint
   simplifies the precision question — this candidate's own official
   checkpoint IS FP8, unlike Qwen3.8-27B, so testing its actual
   published artifact is not an ad-hoc quantization route).
3. GLM-5.3-Flash (its official FP8 checkpoint likewise avoids ad-hoc
   quantization; its 2×80GB INT4 theoretical floor has essentially zero
   headroom and is NOT the recommended first configuration — see
   `GENESIS_COMPUTE_TOPOLOGY_QUALIFICATION_PLAN.md`'s FP8-first
   recommendation for this candidate).
4. Qwen3.8-Flash-Next — currently `runtime_smoke_eligibility: BLOCKED`
   (license review required); excluded from this ordering until that
   resolves. It must not be excluded from eventual runtime-smoke
   consideration merely because its runtime remains unqualified — only
   the license status blocks it right now.

Controls (Qwen3-8B, Mistral-Nemo-Instruct-2407, Phi-4) remain
`CONTROL / SMALL BASELINE` throughout — they are never promoted to
candidate-finalist status regardless of how cheaply or successfully they
smoke-test.
