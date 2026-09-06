# Budget Execution (Phase 7.1 spec §20-24; dimension-corrected Phase 7.2 spec §2-13)

Phase 7's `SocietyBudgetLedger` enforced Constructor/Falsifier spending
only. Phase 7.1 added `verification`/`replanning` but computed EVERY
purpose's cap as a percentage of `budget.max_model_calls` alone -- a
latent mismatch for `retrieval`/`counter_evidence`, which actually consume
the separate `RETRIEVAL_CALLS` dimension (see `BUDGET_DIMENSION_AUDIT.md`).
Phase 7.2 makes `SocietyBudgetLedger` dimension-aware and wires
`retrieval`/`counter_evidence` to real enforcement.

## Enforced purposes and their real dimension

| Purpose | Dimension | Enforced since |
|---|---|---|
| `constructor` | `MODEL_CALLS` | Phase 7 |
| `falsifier` | `MODEL_CALLS` | Phase 7 |
| `verification` | `MODEL_CALLS` | Phase 7.1 |
| `replanning` | `MODEL_CALLS` | Phase 7.1 |
| `retrieval` | `RETRIEVAL_CALLS` | **Phase 7.2** |
| `counter_evidence` | `RETRIEVAL_CALLS` | **Phase 7.2** |
| `optional_second_model` | `MODEL_CALLS` | not enforced -- no live call site exists (Court only ever uses Constructor+Falsifier, per Phase 6's bounded single-round design) |

`SocietyBudgetLedger.reserve(purpose, amount)` now looks up the purpose's
real `BudgetDimension` (`_PURPOSE_TO_DIMENSION`) and calls
`orca.cognitive.budget.consume()` against THAT dimension specifically --
`retrieval`/`counter_evidence` reservations consume
`budget.consumed_retrieval_calls`, never `consumed_model_calls`. Verified
directly:
`tests/test_retrieval_counter_evidence_budget.py::test_counter_evidence_runs_and_consumes_retrieval_calls_dimension_not_model_calls`
(succeeds with zero `MODEL_CALLS` capacity, consumes exactly 1
`RETRIEVAL_CALLS` unit).

## Retrieval enforcement (spec §7-9)

`TruthFabric.assess_evidence()` builds ONE `SocietyBudgetLedger` for its
own `retrieval` purpose, passed as `retrieval_ledger` into `_retrieve()`
for BOTH the initial retrieval call and every corrective round -- never an
independent fresh allocation per round or per multi-hop sub-query (spec
§9). `_reserve_retrieval_or_raise()` reserves BEFORE the actual
`doc_store.retrieve()`/search call runs, never after -- proven directly by
a doc_store whose `.retrieve()` raises `AssertionError` if ever actually
called, under a zero-capacity budget
(`tests/test_retrieval_counter_evidence_budget.py::test_retrieval_reservation_happens_before_the_retrieve_call_not_after`).
Existing hard bound `MAX_TOTAL_RETRIEVAL_QUERIES` is preserved unchanged
alongside the budget check -- both are enforced (spec §8).

## Counter-evidence enforcement (spec §10)

`find_counter_evidence()` now accepts an optional `retrieval_ledger` and
reserves against its `"counter_evidence"` purpose (still `RETRIEVAL_CALLS`
-- this function has NO model/judge step at all, verified by reading its
body; `BUDGET_DIMENSION_AUDIT.md` corrects Phase 7.1's assumption that one
existed). On reservation failure, returns `CounterEvidenceStatus.BUDGET_EXHAUSTED`
-- never `RAN` when the operation didn't actually run
(`tests/test_retrieval_counter_evidence_budget.py::test_counter_evidence_reserves_before_searching_and_reports_budget_exhausted_not_ran`).

## No cross-dimensional reallocation (spec §15)

`SocietyBudgetLedger.reallocate()` now refuses any move between purposes
of different dimensions (`ValueError`) -- unused `RETRIEVAL_CALLS`
capacity can never be converted into `MODEL_CALLS` capacity. `retrieval`
↔ `counter_evidence` (both `RETRIEVAL_CALLS`) remains a legitimate move;
`retrieval` → `falsifier` (crossing dimensions) is refused, tested
directly
(`tests/test_society_budget_ledger.py::test_reallocation_refuses_cross_dimension_moves`).

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

## Budget invariants (Phase 7.2 spec §16)

Property-tested directly in `tests/test_budget_invariants.py`: reserved
capacity never exceeds the parent dimension's real cap (within small
per-purpose rounding), no double-release, no double-consume from a single
reservation, remaining never goes negative, a cancelled unused reservation
returns exactly its own capacity (no more, no less), reallocation
redistributes without creating capacity, and a partial multi-resource
failure (retrieval reservation succeeds, verification reservation fails)
never lets the failed dimension's consumption exceed its real cap while
correctly retaining the already-done retrieval work's charge (not
refunded, since that work already happened).

## Security: budget manipulation resistance (Phase 7.2 spec §25-26)

`tests/test_budget_manipulation_security.py` proves: negative/oversized
`CognitiveBudget` limits are rejected at construction; `consume()` rejects
negative amounts; `release()` floors at zero (never negative consumption);
replaying a release on the same reservation object multiple times cannot
manufacture phantom capacity; an attacker-widened PURPOSE cap cannot
bypass the PARENT `CognitiveBudget`'s real dimension cap; reallocation
cannot manufacture capacity beyond the parent pool; and `RoutingRequest`
has no field that could set an unlimited/overridden budget ceiling at
all.
