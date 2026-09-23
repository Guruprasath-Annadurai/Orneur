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
2. **Capture the fresh authoritative billed-cost baseline as observed —
   do not assume it is zero.** Record `billed_before_usd` exactly as
   the live billing query reports it (Phase 21B.4.15.2 correction: a
   prior, separately-recorded billing incident — e.g. GLM-5.3-Flash's
   Phase 21B.4.13 $3.52 violation — can leave the account's billed
   total permanently nonzero; that historical fact does not by itself
   block a later execution). The acceptance invariant this run must
   satisfy is `owner_billed_delta_usd == 0` (equivalently,
   `billed_after_usd == billed_before_usd`), never `billed_before_usd
   == 0`.
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

9. **Canonical post-run acceptance (Phase 21B.4.15.2):** capture
   `billed_after_usd` from a fresh live billing query and require
   `billed_after_usd == billed_before_usd` (equivalently,
   `owner_billed_delta_usd == 0`) — never `billed_after_usd == 0`. A
   nonzero shared baseline that did not increase is a PASS; any
   increase, however small, is a FAIL, regardless of what the baseline
   was.
9a. **Cleanup verification**: GPU process terminated, resources released,
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
it were hard enforcement.

**What was actually observed in the Phase 21B.4.13 GLM-5.3-Flash
incident (evidence-bounded, not a claim about Modal's internal
mechanism):**

- The configured Modal workspace spend limit was $0.
- Immediately before the successful GLM run, owner billed cost was
  $0.00 (confirmed live).
- Promotional/free credits were available on the account.
- The live job remained within its authorized wall-clock ceiling (55
  minutes authorized; actual run 38 minutes).
- After the run, cumulative metered cost exceeded the available credit
  balance.
- The owner billed delta was $3.52 — i.e. a real charge occurred despite
  the $0 spend limit being configured throughout.

**Therefore:** ORNEUR must not rely on a configured $0 spend limit,
by itself, as sufficient zero-cash protection for future long-running
GPU work — this is a fact directly supported by what was observed.

**What remains unverified:** the EXACT provider-side mechanism by which
this occurred — how Modal internally treats already-in-flight,
already-metered, pending, or newly-requested usage once a $0 spend
limit's headroom is exhausted — was not established from authoritative
Modal documentation, and this document does not claim to know it.
Observed behavior in this incident was consistent with the configured
spend limit not preventing this particular billed overage; the exact
provider-side mechanism was not established. Any future Modal-based
execution's control documentation should re-state this same
observed-fact/unverified-mechanism distinction rather than assert a
specific internal billing mechanism as fact.

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
