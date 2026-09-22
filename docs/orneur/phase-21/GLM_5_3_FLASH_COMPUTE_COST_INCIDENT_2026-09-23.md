# GLM-5.3-Flash Compute-Cost Incident — Phase 21B.4.13 GPU execution invocation #2

**Classification: ORNEUR COMPUTE-COST GUARDRAIL DEFECT.**

Not a model defect. Not a Modal defect. Not a vLLM defect.

*Phase 21B.4.13.2 wording correction: two passages below originally
stated general claims about how Modal's $0 spend limit is designed to
behave, without a primary Modal source confirming that behavior. They
have been rewritten to state only what was directly observed in this
execution. The root-cause classification itself (ORNEUR COMPUTE-COST
GUARDRAIL DEFECT) is unchanged.*

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

The account's Modal Workspace spend limit is configured to $0. **Observed
in this execution:** despite that configured limit, the run's metered
cost ($33.52) exceeded the available credit balance ($30.00) and the
shortfall ($3.52) was billed to the owner (`billed_cost` moved from
$0.00 to $3.52, confirmed live via `modal billing summary` before and
after the run). No current primary Modal documentation was consulted to
confirm the general mechanics of how a $0 spend limit interacts with an
already-in-flight job's metered-but-not-yet-settled usage once credits
are exhausted — the paragraph above described a plausible mechanism,
not a documented one, and is corrected here. **The incident evidence is
consistent with** the $0 spend limit not preventing this specific
already-metered overage from resolving as owner-billed cost, in this
one observed instance; it should not be read as an established general
claim about Modal's billing semantics.

## What this incident is not

- **Not a model defect.** GLM-5.3-Flash's runtime behavior was correct
  in every observed respect.
- **Not a Modal defect.** Observed in this execution: Modal billed
  exactly what was metered ($33.52 metered, $30.00 credits applied,
  $3.52 billed — the arithmetic is exact and consistent). No claim is
  made here about whether this is Modal's intended or documented
  billing behavior in general; only the exact observed numbers for
  this one run are asserted as fact.
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
