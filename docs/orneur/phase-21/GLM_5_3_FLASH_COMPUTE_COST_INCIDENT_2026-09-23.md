# GLM-5.3-Flash Compute-Cost Incident — Phase 21B.4.13 GPU execution invocation #2

**Classification: ORNEUR COMPUTE-COST GUARDRAIL DEFECT.**

Not a model defect. Not a Modal defect. Not a vLLM defect.

## What happened

GPU execution invocation #2 (the corrected model-load-detection harness,
`scripts/phase21b_4_13_glm_gpu_run2.py`) launched a 4×H200 (TP=4) job to
serve GLM-5.3-Flash. The job:

- Stayed within the owner-authorized 55-minute wall-clock hard ceiling
  (`timeout=3300` at the Modal function level) — total wall time was
  2282.28 seconds (~38 minutes), and within the harness's own internal
  49-minute soft readiness deadline.
- Completed successfully: server reached ready state, `GET /v1/models`
  returned 200, `POST /v1/chat/completions` returned 200 with a valid
  non-empty decoded generation, cleanup completed cleanly.
- **Exceeded the owner's available promotional/free Modal credit balance
  partway through the run.** The credit pool available to this Modal
  workspace was exactly $30.00. Weight download alone took 1264 seconds
  (~21 minutes) for the 306 GiB FP8 checkpoint across 4× H200 GPUs, and
  cumulative metered cost crossed $30.00 before the run finished. The
  excess — $3.52 — was billed to the owner as real cost
  (`owner_billed_delta_usd = 3.52`), violating the pre-declared
  `owner_billed_delta_usd == 0` invariant.

## Root cause

**The execution budget enforced wall-clock duration but did not enforce
remaining promotional-credit runway in real time.**

The harness tracked only `time.time()` against a fixed second-count
ceiling. It never polled `modal billing summary` (or any equivalent
live cost signal) during the wait loop, and had no mechanism to compare
projected remaining cost against remaining credit balance. A 4×H200 job
whose cost-per-minute (~$0.30-0.42/min observed across this phase,
varying with concurrent metered activity) multiplied by its actual
runtime could — and did — exceed the credit ceiling well before the
time ceiling was reached, because the two ceilings are independent
quantities and only one was being enforced.

The account's Modal Workspace spend limit is configured to $0, which is
the mechanism that keeps runs from spending real money in the general
case — but it does not retroactively prevent already-authorized
billable GPU-second usage, already metered during a run in progress,
from converting into owner-billed cost once the credit pool underneath
it is exhausted. The $0 spend limit blocks *new* chargeable actions
once credits are gone; it does not roll back or refuse to bill for
GPU-seconds a running job has already consumed while credits were still
available moment-to-moment. By the time credits ran out mid-run, the
job was already mid-flight consuming GPU-seconds that had to be
accounted for somehow, and the accounting resolved as real billed cost
for the shortfall.

## What this incident is not

- **Not a model defect.** GLM-5.3-Flash's runtime behavior was correct
  in every observed respect.
- **Not a Modal defect.** Modal billed exactly what was metered, exactly
  as its billing model is documented to work; the $0 spend limit did
  what it is designed to do (block new spend once credits and any
  further allowance are gone), not something broader.
- **Not evidence the zero-owner-cash rule is impractical.** The rule
  itself (`owner_billed_delta_usd == 0`) remains correct and is
  preserved unweakened — see
  `GLM_5_3_FLASH_TECHNICAL_RUNTIME_RESULT_2026-09-22.json`'s
  `formal_runtime_qualification: NOT_ACCEPTED`. This incident is a gap
  in the harness's own guardrail design, not a reason to relax the rule
  the guardrail exists to enforce.

## Required future invariant

GPU jobs operating under ZERO_OWNER_CASH mode must use **BOTH**:

1. A wall-clock ceiling (as already implemented).
2. A live monetary-credit ceiling, polled during the run and enforced
   independently of the wall-clock ceiling.

A future zero-cash job must not rely solely on duration. See
`GLM_5_3_FLASH_FUTURE_ZERO_CASH_GPU_GUARDRAIL_2026-09-23.md` for the
specific control design required before any further GPU compute is
authorized under this constraint.

## Scope of this record

This is a prospective, documentation-only finding for Phase 21B.4.13.1.
No code was changed in this phase to implement the future guardrail —
that remains a separately authorized future step. No GPU compute was
launched in this phase. This incident record exists solely to preserve
an honest root-cause account and to bind the required future control
before any subsequent zero-cash GPU authorization is granted.
