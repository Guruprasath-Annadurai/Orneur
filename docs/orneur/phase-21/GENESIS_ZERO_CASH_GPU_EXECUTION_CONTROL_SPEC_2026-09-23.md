# Genesis Zero-Cash GPU Execution Control Specification — Phase 21B.4.15

**Prospective only. No code in this phase implements this control. No
GPU is authorized by this document.**

This generalizes and supersedes the candidate-specific guardrail notes
in `GLM_5_3_FLASH_FUTURE_ZERO_CASH_GPU_GUARDRAIL_2026-09-23.md` (which
remains as the historical incident-driven record for that specific
phase) into a standing requirement for ANY future ORNEUR GPU execution
under a zero-owner-cash constraint, including the future Qwen3.8-27B
production-serving qualification run this phase preflights but does not
launch.

## Why this exists

Phase 21B.4.13's GLM-5.3-Flash GPU execution invocation #2 stayed within
its authorized wall-clock ceiling (55 minutes; actual run 38 minutes)
but exceeded the account's available credit balance ($30.00) partway
through, because the harness enforced ONLY a wall-clock ceiling and
never checked live monetary state. The result: `owner_billed_delta_usd`
became $3.52 — a real violation of the zero-owner-cash acceptance gate.
Root cause, recorded in `GLM_5_3_FLASH_COMPUTE_COST_INCIDENT_2026-09-23.md`:
**ORNEUR COMPUTE-COST GUARDRAIL DEFECT** — not a model defect, not a
Modal defect.

**Wall-clock ceilings alone are insufficient.** Any future GPU
qualification run — Qwen3.8-27B included — must never rely only on:

- a $0 account spend limit
- a wall-clock timeout
- an assumed remaining promotional-credit balance

## Required control (all of the following, before ANY future GPU authorization)

### Before allocation

1. **Fresh billing evidence immediately before launch.** A live billing
   query (e.g. `modal billing summary --json` or the equivalent for
   whatever provider is used) executed in the same session, immediately
   before GPU allocation — never a stale or remembered figure from an
   earlier phase or an earlier point in the same session.
2. **`owner_billed_delta_usd == 0` acceptance invariant confirmed at
   this fresh check** — `billed_before_usd` must be exactly `$0.00`.
3. **Known remaining credit**, read from the live billing state where
   the provider exposes it, or from the most recent authoritative
   owner-provided figure cross-checked against live `metered_cost`/
   `credits` fields (as was done for the Phase 21B.4.13 billing gate).
4. **Estimated worst-case job cost**, computed from the provider's
   published per-GPU-second/hour rate × the requested topology ×
   the wall-clock ceiling being requested (i.e. the cost IF the job ran
   the full ceiling, not the expected/optimistic cost).
5. **Safety reserve**: the estimated worst-case job cost must fit
   comfortably under (known remaining credit − a reserve margin), never
   planned against the full remaining balance. A job must never be
   authorized when its own worst-case cost could plausibly exhaust the
   entire known credit balance on its own, exactly the condition that
   produced the GLM incident.

### During allocation

6. **Live credit/billing polling where technically available.** The
   harness's wait/readiness loop must poll live billing state at a
   bounded interval (not only wall-clock time), computing an observed
   burn rate from consecutive samples.
7. **Proactive termination before credit exhaustion.** If projected
   remaining runway (known remaining credit − reserve − current
   metered cost, divided by observed burn rate) drops below a safety
   threshold (enough time for one more polling interval plus a clean
   shutdown), the harness must proactively terminate the job — exactly
   mirroring the existing wall-clock soft-deadline pattern, but
   triggered by the monetary signal, independently of whether the
   wall-clock ceiling has also been reached.
8. **Wall-clock hard ceiling** remains required in addition to (not
   instead of) the monetary guard — both must be enforced, not either/or.

### After allocation

9. **Cleanup verification**: GPU process terminated, resources released,
   `nvidia-smi` (or equivalent) confirms return to idle baseline, no
   lingering phase-created cloud resources (apps/containers/volumes).
10. **No automatic retry that could duplicate spend.** A failed,
    deferred, or financially-rejected run must never automatically
    trigger a second GPU allocation. Any subsequent attempt requires a
    fresh, explicit authorization turn (matching the established pattern
    across the Mistral, GLM, and this phase's own governance).
11. **Explicit owner authorization immediately before launch** — not
    inherited from an earlier phase's authorization, and not implied by
    a preflight/research phase (such as this one) having completed.

## Provider telemetry limitation (record, do not pretend enforcement exists)

If the compute provider exposes no sufficiently reliable LIVE cost
telemetry (e.g. a billing API with meaningful polling latency, or one
that only settles cost well after the fact), that limitation must be
recorded explicitly in the execution's evidence, and the harness must
compensate with a MORE conservative safety reserve and a SHORTER polling
interval — never by treating an unenforceable monetary guardrail as if
it were hard enforcement. Modal's own $0 account spend limit was shown
by the GLM incident to prevent only NEW chargeable actions once credits
are exhausted, not to retroactively prevent an in-flight job's
already-metered usage from resolving into real billed cost — this
specific limitation must be re-stated in any future Modal-based
execution's control documentation, not silently assumed fixed.

## Applicability

This control is a prerequisite for authorizing GPU compute on:

- Qwen3.8-27B's future production-serving qualification (this phase's
  preflight spec: `GENESIS_QWEN3_8_27B_PRODUCTION_SERVING_QUALIFICATION_SPEC_2026-09-23.md`)
- Any future re-attempt at GLM-5.3-Flash's formal zero-cash
  requalification
- Any future Qwen3.8-Flash-Next runtime smoke, if/when its license
  blocker resolves
- Any other future ORNEUR zero-owner-cash GPU execution

No GPU work is launched by this document. It is a binding prerequisite
specification, not an execution.
