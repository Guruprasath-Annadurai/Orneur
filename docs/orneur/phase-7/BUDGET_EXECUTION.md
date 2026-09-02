# Budget Execution (Phase 7.1 spec §20-24)

Phase 7's `SocietyBudgetLedger` enforced Constructor/Falsifier spending
only. Phase 7.1 connects two more purposes to real production operations.

## Newly enforced purposes

- **`verification`**: `TruthFabric.verify_answer()` now builds its own
  `SocietyBudgetLedger` (scoped to that call, drawing from the SAME shared
  `budget.max_model_calls`/`consumed_model_calls` pool Court's ledger also
  draws from) and reserves 1 unit per claim-extraction/per-claim-verification
  step, raising `TruthBudgetExhaustedError` (wrapping
  `CognitiveBudgetExhaustedError`) if exhausted -- never silently skipping
  verification and returning as if it ran.
- **`replanning`**: `CognitiveKernel`'s Court-loop reserves 1
  `replanning` unit (against the SAME shared `plan.budget`) before EVERY
  REVISE-triggered re-run of Court -- if the reservation fails, the Kernel
  abstains (`DELIBERATION_BUDGET_EXHAUSTED`) instead of re-running Court
  anyway.

## What is still NOT wired (honest disclosure, spec §20's own caution against decorative allocations)

`retrieval` and `counter_evidence` purposes are **not** wired to real
enforcement this phase. Truth Fabric's actual retrieval/counter-evidence
calls (`orca.truth.counter_evidence.find_counter_evidence`, the corrective
retrieval loop) consume the SEPARATE `BudgetDimension.RETRIEVAL_CALLS`
dimension of `CognitiveBudget` -- a different pool than the
`MODEL_CALLS`-only pool `SocietyBudgetLedger` currently models. Wiring
these purposes into the existing ledger design without a RETRIEVAL_CALLS-
aware ledger would be a mismatched, non-enforcing allocation (exactly what
spec §20 warns against) -- disclosed here rather than forced. A future
phase's ledger redesign (a second dimension-aware ledger, or a unified
multi-dimension ledger) would close this properly.

`optional_second_model` has no live call site at all (Court only ever
uses Constructor+Falsifier, one model call each, per Phase 6's bounded
single-round design) -- nothing to wire yet.

## One traceable bounded hierarchy (spec §21)

All THREE currently-enforced purposes (`constructor`, `falsifier` from
Court; `verification` from Truth Fabric; `replanning` from the Kernel)
draw their caps from calling `allocate_budget()` against the SAME
underlying `CognitiveBudget` object reference (`plan.budget`, passed
unchanged from Kernel → Court → Truth Fabric). Each subsystem constructs
its OWN `SocietyBudgetLedger` VIEW (a purpose-scoped cap calculator) rather
than sharing one Python object instance end-to-end -- this means
PER-PURPOSE "spent" bookkeeping does not persist across subsystem
boundaries within one request (a Truth Fabric-local ledger doesn't know
how much Court's ledger already spent on "constructor"). What DOES persist
and IS shared, and is the property that actually matters for safety, is
the underlying `CognitiveBudget.consumed_model_calls`/`max_model_calls`
fields themselves -- every `SocietyBudgetLedger.reserve()` call ultimately
calls `orca.cognitive.budget.consume()` against that ONE shared object, so
exhausting the request's real `MODEL_CALLS` budget in one subsystem
correctly causes `CognitiveBudgetExhaustedError` in the next subsystem
too, verified directly
(`tests/test_budget_execution_integration.py::test_verify_answer_raises_when_verification_budget_exhausted`).
This is disclosed as a real, bounded limitation -- not the fully unified
single-ledger-object design spec §21 describes in its ideal form, but the
actual overspend-prevention property it cares about IS present and tested.

## Reservation before expensive work (spec §22)

Every enforced purpose reserves BEFORE the model call/Court re-run starts
-- never discovered as insufficient only after the fact. Tested directly
in `tests/test_society_budget_ledger.py` (Phase 7) and
`tests/test_budget_execution_integration.py` (Phase 7.1).

## Release on cancellation/failure (spec §23)

`SocietyBudgetLedger.release_reservation()` (Phase 7, unchanged) gives back
both the purpose's sub-cap and the parent `CognitiveBudget`'s consumption.
`CognitiveCourt.run()` calls this on timeout (unchanged from Phase 7).

## Reallocation cannot create budget (spec §24, §47)

`reallocate()` raises `ValueError` if asked to move more than is actually
unspent from the source purpose -- proven directly under an adversarial
framing:
`tests/test_society_authority_security.py::test_budget_reallocation_cannot_exceed_parent_budget`.
