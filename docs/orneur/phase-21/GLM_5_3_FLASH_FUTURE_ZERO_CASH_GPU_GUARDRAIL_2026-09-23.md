# Future Zero-Cash GPU Guardrail Requirement (prospective, not implemented this phase)

Required by the compute-cost incident recorded in
`GLM_5_3_FLASH_COMPUTE_COST_INCIDENT_2026-09-23.md`. This document
specifies the control that must exist **before** any future GPU
allocation is authorized under ZERO_OWNER_CASH mode. It is prospective
only — it does not retroactively accept the GLM-5.3-Flash GPU execution
invocation #2 run, and no code implementing this is written in Phase
21B.4.13.1 (CPU/docs-only).

## Before allocation

- `billed_cost` must equal 0 (confirmed live via `modal billing summary`,
  as already practiced).
- The promotional/free-credit balance must be known — not merely
  inferred from an owner screenshot's "approximately" figure, but
  cross-checked as an exact number where the billing API exposes one,
  or bounded conservatively where it does not.
- The expected GPU hourly rate must be known (e.g. via the provider's
  current published pricing, as already practiced this phase for
  Modal's H200 SXM rate).
- A minimum reserve must be maintained — the job must never be allowed
  to plan for spending the entire known credit balance; some margin
  must be held back to absorb rate estimation error, billing-metric
  lag, or an underestimated weight-download/load duration.

## During allocation

- **Poll billing/credit state periodically** during the wait loop (not
  only wall-clock time) — e.g. every N seconds, call the live billing
  endpoint and read current metered cost.
- **Calculate projected remaining runway**: given the current burn rate
  (metered-cost delta over the polling interval) and the known
  remaining credit balance minus the reserve, compute how many more
  seconds of GPU time can be safely consumed.
- **Gracefully terminate BEFORE promotional credits are exhausted** —
  if projected runway drops below a safety threshold (e.g. one more
  polling interval's worth of spend, plus the time needed for clean
  shutdown), the harness must proactively SIGTERM the server and exit
  cleanly, classifying the result as `DEFERRED_FOR_COMPUTE` if no
  technical defect was observed, exactly as the wall-clock ceiling
  already does — but triggered by the monetary signal, independently of
  whether the wall-clock ceiling has also been reached.

## Design shape (illustrative, not final code)

```
loop:
    if time.time() >= wall_clock_deadline:
        stop("wall-clock ceiling reached")
    if server_actually_exited():
        classify_concrete_failure()
        stop()
    if server_ready_via_v1_models():
        proceed_to_generation()
        stop()

    # the missing half, required going forward:
    current_metered = poll_billing_metered_cost()
    burn_rate = (current_metered - last_metered) / poll_interval
    projected_runway_seconds = (credit_balance - reserve - current_metered) / burn_rate
    if projected_runway_seconds < shutdown_buffer_seconds:
        stop("credit runway ceiling reached -- DEFERRED_FOR_COMPUTE if no technical defect observed")

    last_metered = current_metered
    sleep(poll_interval)
```

## Do not let the system run until `credit_remaining == 0`

The future system must stop **before** the financial boundary, with
margin — not at it, and never after it. The GLM-5.3-Flash incident
happened precisely because nothing stopped the job before the boundary;
the boundary itself (Modal's $0 spend limit) only prevents *new* spend
once credits are gone, it does not prevent an in-flight job's
already-metered GPU-seconds from resolving into owner-billed cost. The
guardrail's job is to never let the job get close enough to the
boundary for that distinction to matter.

## Explicitly out of scope for this document

- No retroactive reclassification of GLM-5.3-Flash's GPU execution
  invocation #2 as accepted. It remains `NOT_ACCEPTED` per
  `GLM_5_3_FLASH_TECHNICAL_RUNTIME_RESULT_2026-09-22.json`.
- No code implementing this control is added in Phase 21B.4.13.1.
- No weakening of the existing `owner_billed_delta_usd == 0` strict
  acceptance invariant in `orca/eval/runtime_qualification_manifest.py`
  — that invariant is orthogonal to this guardrail: the guardrail is
  meant to make it easier to actually achieve `== 0` in future GPU
  runs, not to change what counts as compliant.
