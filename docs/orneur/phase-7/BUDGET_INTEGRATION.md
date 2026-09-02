# Cognitive Budget Market — Made Operational (Phase 7 spec §24-27)

Phase 6 explicitly disclosed the Budget Market allocator as **policy-only**:
"`CognitiveCourt` does not yet consume [the allocator's percentages] to
gate actual per-dimension spending; it spends a fixed, small, hard-bounded
amount regardless" (`docs/orneur/phase-6/COGNITIVE_BUDGET_MARKET.md`).
Phase 7 closes this gap with `orca.society.budget_ledger.SocietyBudgetLedger`.

## How it works

1. `orca.deliberation.budget_market.allocate_budget()` (Phase 6, unchanged)
   produces a `BudgetAllocation` -- percentages across `retrieval`,
   `reasoning`, `falsification`, `verification`, `counter_evidence`,
   `simulation`, `agents`.
2. `SocietyBudgetLedger.__post_init__` converts those percentages into REAL
   integer call caps per purpose (`constructor`, `falsifier`,
   `verification`, `counter_evidence`, `retrieval`, `optional_second_model`,
   `replanning`), scaled against `budget.max_model_calls` -- the SAME
   `CognitiveBudget` every other Kernel dimension already uses, not a
   second, parallel accounting authority. `constructor`/`falsifier` always
   get at least 1 call each (Court's mandatory single round cannot run
   with zero).
3. `CognitiveCourt.run()` calls `ledger.reserve("constructor", 1)` and
   `ledger.reserve("falsifier", 1)` **before** launching either model call
   (spec §25) -- never discovering insufficient budget only after a call
   already started.
4. On timeout/failure, `ledger.release_reservation()` gives back both the
   purpose's sub-cap AND the parent `CognitiveBudget`'s consumption (via
   the new `orca.cognitive.budget.release()`, added this phase as the
   symmetric counterpart to the existing `consume()`).

## Reallocation (spec §26)

`SocietyBudgetLedger.reallocate(from_purpose, to_purpose, amount, reason)`
moves only UNSPENT capacity, and every move is recorded as a
`ReallocationRecord` (`from`/`to`/`amount`/`reason`) -- never a silent,
untracked shuffle. Bounded: raises `ValueError` if asked to move more than
is actually unspent.

## Exhaustion (spec §27)

When a purpose's cap (or the parent `CognitiveBudget`'s `MODEL_CALLS`
dimension) is exhausted, `reserve()` raises the SAME
`CognitiveBudgetExhaustedError` every other Kernel budget check raises --
optional role calls (verification, counter-evidence, a second model) stop;
Court's own two mandatory reservations (constructor+falsifier) are
attempted first and produce `DELIBERATION_BUDGET_EXHAUSTED` honestly if
even those can't be met.

## What remains true from Phase 6 (not changed)

The allocator itself (`allocate_budget()`) is unchanged -- still a
deterministic, tested percentage policy. Phase 7 adds the enforcement
layer on top; it does not touch the allocation math.
