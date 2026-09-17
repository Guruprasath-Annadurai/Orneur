# Phase 21B.4 -- Foundation Baseline Shootout Runbook

**This document specifies a FUTURE procedure. It does not execute
anything, and no part of it has been run.** No GPU was activated, no
compute was provisioned, and no model was evaluated in the production
of this document (Phase 21B.3 explicitly forbids all of that). This
runbook exists so that IF the owner later issues an explicit
`APPROVED -- BEGIN PHASE 21B.4 GENESIS FOUNDATION BASELINE SHOOTOUT ON
<RESOURCE>` gate, the procedure is already fully specified and does not
need to be designed under time pressure.

## Purpose

Empirically compare the foundation-model finalists named in
`GENESIS_FOUNDATION_SHORTLIST_2026.md` against the identical
`genesis-eval-v1` suite (`orca/eval/genesis_suite.py`,
`EvaluationSuiteManifest` digest-pinned), BEFORE any Genesis training
decision is finalized. This shootout evaluates the UNTOUCHED base
models -- no fine-tuning happens in this phase either; that is Phase
21C's job, still separately locked.

## Candidates (from the shortlist, unchanged)

1. **Primary**: `Qwen/Qwen3-8B` (verified Apache-2.0, revision
   `946bc9ac74a6c1f8cf012497c503a119b2fcf2eb` per the `unsloth/Qwen3-8B`
   mirror, as of 2026-09-17 -- re-verify at execution time, since
   upstream revisions can change).
2. **Second**: `mistralai/Mistral-Nemo-Instruct-2407` (verified
   Apache-2.0, revision `04d8a90549d23fc6bd7f642064003592df51e9b3`).
3. **Optional third**: `microsoft/Phi-4` (verified MIT, revision
   `2db69c1c3e91a05d2c64a3185acfbaf36f744e25`) or `microsoft/Phi-4-mini-instruct`
   (verified MIT, revision `cfbefacb99257ffa30c83adab238a50856ac3083`).

All revisions must be RE-VERIFIED live (not assumed from this document)
immediately before execution -- upstream repositories can and do publish
new revisions under the same tag.

## No-apples-to-oranges configuration contract

Every candidate run must record and hold constant, unless a candidate
genuinely cannot support a setting (in which case the deviation itself
must be recorded, not silently normalized away):

| Field | Requirement |
|---|---|
| candidate | exact HF repo id |
| exact_revision | exact commit SHA, re-verified at run time |
| quantization | identical across candidates where feasible (e.g. all 4-bit, or all bf16) -- record if one candidate required a different quantization for a technical reason |
| inference_config | identical decoding parameters (see below) |
| temperature | identical, e.g. 0.0 for deterministic-scoring categories (3, 4, 5, 7, 9, 10, 11, 12, 14, 15, 16, 17), a fixed non-zero value (documented) for LLM-judge categories if used |
| seed | fixed and recorded where the inference backend supports one (not all do -- record if unsupported) |
| context | identical max-context setting across candidates |
| system_instruction | IDENTICAL system prompt text across all candidates (the same Genesis system prompt used in `scripts/build_genesis_v3_dataset.py`'s `SYSTEM_PROMPT`, or a shootout-specific variant -- but the SAME one for every candidate) |
| tool_availability | identical -- either no tools available to any candidate, or the identical tool set/schema to every candidate |
| hardware | recorded per run (GPU model, VRAM, host RAM) -- need not be identical across candidates if using different providers, but must be recorded so cost/latency comparisons are honestly attributable |
| eval_suite_digest | `EvaluationSuiteManifest("genesis-eval", "v1").content_digest` + `.scoring_contract_digest`, confirmed to match `orca.eval.genesis_suite.compute_suite_digests(all_tasks())` immediately before the run -- if suite v1 has been frozen by an earlier baseline, verify the manifest is loaded, not silently re-derived, and matches exactly |
| result_manifest | one structured result file per candidate per suite version, containing every field in "Result manifest schema" below |
| latency_capture | per-task wall-clock generation time, recorded in the result manifest |
| failure_capture | any task where generation itself failed (timeout, API error, malformed output) recorded explicitly as a failure, never silently dropped from the denominator |

## Result manifest schema (per candidate run)

```json
{
  "run_id": "<deterministic id, e.g. sha256(candidate+revision+suite_digest+timestamp)[:16]>",
  "candidate": "<HF repo id>",
  "exact_revision": "<commit sha, re-verified at run time>",
  "quantization": "<e.g. 4bit-nf4, bf16>",
  "inference_config": {"temperature": 0.0, "top_p": 1.0, "max_new_tokens": 512},
  "seed": "<int or null if unsupported>",
  "context_window_used": "<int>",
  "system_instruction": "<exact text used>",
  "tool_availability": "<none | schema reference>",
  "hardware": {"gpu": "...", "vram_gb": 0, "host_ram_gb": 0},
  "eval_suite_id": "genesis-eval",
  "eval_suite_version": "v1",
  "eval_suite_content_digest": "<from EvaluationSuiteManifest>",
  "eval_suite_scoring_contract_digest": "<from EvaluationSuiteManifest>",
  "per_task_results": [
    {"task_id": "cat04-001", "category": 4, "passed": true, "latency_ms": 0, "raw_response_ref": "<pointer, not inline dump>", "scorer_output": {}}
  ],
  "per_category_summary": {"1": {"passed": 0, "total": 0}, "...": {}},
  "failures": [{"task_id": "...", "reason": "timeout|error|malformed_output"}],
  "started_at": "<ISO8601>",
  "completed_at": "<ISO8601>"
}
```

Per-category deltas (candidate vs. base-model baseline, and candidate vs.
candidate) are computed FROM this manifest, never hand-computed or
eyeballed -- see `GENESIS_PRETRAINING_QUALIFICATION.md`'s regression
policy for how deltas feed into a promotion decision once thresholds are
calibrated.

## Compute plan (estimates only, no invented pricing)

| Candidate | Min VRAM (INFERENCE) | Preferred VRAM | Host RAM | Storage | Likely quantization | QLoRA feasibility | Baseline-eval duration class | Training-duration class |
|---|---|---|---|---|---|---|---|---|
| Qwen3-8B (dense, 8.2B) | ~6-8GB (4-bit inference) | 16GB+ | 16GB+ | ~16GB (fp16 weights) | 4-bit NF4 (QLoRA) or bf16 (inference-only) | HIGH (Unsloth-documented QLoRA support, same class as the currently-implemented Qwen2.5-3B path) | LOW (90 tasks, single dense 8B model -- minutes to low tens of minutes on a single consumer/cloud GPU) | LOW-MEDIUM (comparable order of magnitude to the existing Qwen2.5-3B QLoRA runbook, scaled up for the larger model) |
| Mistral-Nemo-12B (dense) | ~8-10GB (4-bit) | 24GB+ | 16GB+ | ~24GB (fp16 weights) | 4-bit NF4 or bf16 | MEDIUM (Unsloth mirror exists, but no prior project-specific training code) | LOW | MEDIUM (larger model, new tokenizer/template validation needed first) |
| Phi-4 (dense, 14B) | ~10-12GB (4-bit) | 24GB+ | 16GB+ | ~28GB (fp16 weights) | 4-bit NF4 or bf16 | MEDIUM (Unsloth mirror exists, no prior project training code) | LOW | MEDIUM |
| Phi-4-mini (~3.8B) | ~3-4GB (4-bit) | 8GB+ | 8GB+ | ~8GB (fp16 weights) | 4-bit NF4 or bf16 | MEDIUM-HIGH (small, but new template family) | VERY LOW | LOW |

All VRAM/RAM/storage figures above are INFERENCE, this document's own
order-of-magnitude estimates extrapolated from parameter count and the
already-documented Qwen2.5-3B QLoRA profile in
`PHASE21C_GENESIS_TRAINING_RUNBOOK.md` -- not vendor-published numbers,
not measured, and explicitly not to be treated as a commitment. Baseline
evaluation (running 90 inference calls per candidate, no training)
should complete in well under an hour per candidate on any GPU meeting
the "preferred VRAM" figure; exact duration depends on hardware, batch
size, and whether generation is streamed or batched.

## Candidate execution environments (not activated)

ORNEUR owns run identity, configuration, manifests, evaluation, and
checkpoint lineage regardless of WHERE compute runs -- the provider is
merely compute, per spec section 35. Legitimate future options, none
activated:

- **Kaggle**: free-tier GPU (T4/P100 class), session time limits, no
  persistent storage between sessions without explicit save/upload.
- **Google Colab**: similar free/paid-tier GPU access, session time
  limits.
- **Race Engineering**: the compute-provider identity already recorded
  as a valid `compute_provider` value in `TrainingRunManifest`
  (`orca/registry/training_run.py`) from prior phases -- specific
  hardware/pricing not re-verified this closure.
- **Modal**: serverless GPU compute, pay-per-second, no invented
  pricing here -- would need live pricing lookup at execution time.
- Any other resource the owner separately authorizes.

No pricing numbers are stated as fact in this document -- any of the
above would need a live, current price check immediately before
provisioning, not a number carried over from this document's authoring
date.

## What must happen before this runbook can actually execute

1. An explicit owner gate: `APPROVED -- BEGIN PHASE 21B.4 GENESIS
   FOUNDATION BASELINE SHOOTOUT ON <RESOURCE>`.
2. Re-verification of every candidate's exact revision SHA and license
   (upstream can change between this document's authoring and
   execution).
3. Provisioning of the named `<RESOURCE>` (not done by this document).
4. Confirmation that `genesis-eval-v1`'s `EvaluationSuiteManifest` is
   loaded from its persisted, version-pinned form (frozen if a prior
   baseline already exists) rather than re-derived ad hoc.

None of the above has happened. This document is the specification
only.
