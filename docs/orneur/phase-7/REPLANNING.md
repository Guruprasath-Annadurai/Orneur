# First Real Bounded Replan Execution (Phase 7 spec §31-33)

Phase 6 had `ReasoningPlan.completion_conditions` as a trigger CONTRACT with
no running loop. Phase 7 adds `orca.deliberation.replanning`, the first
real loop.

## Scope: one trigger wired to a live consumer this phase

`ReplanTrigger` declares eight named triggers
(`HYPOTHESIS_FALSIFIED`, `CRITICAL_EVIDENCE_CONTRADICTION`,
`TOOL_RUNTIME_FAILURE`, `MODEL_UNAVAILABLE`, `WORLD_STATE_CHANGE`,
`BUDGET_CHANGE`, `COMPLETION_CONDITION_FAILED`, `COURT_REVISE`), matching
spec §31's list. Only `COURT_REVISE` has a live implementation this phase
(`revise_plan_for_court_verdict()`) -- called when `CognitiveCourt`
returns `CourtVerdictState.REVISE`. The other seven triggers are declared
but not yet wired to a caller that fires them; an honest, disclosed
foundation (matching the "contract exists, not yet consumed everywhere"
pattern already used for `WorldState` in Phase 6).

## Local revision, not full regeneration (spec §32)

`revise_plan_for_court_verdict()` copies the plan's `goal`/`subproblems`
unchanged and only flips `requires_falsification=True` /
`requires_court=True` -- adding a bounded second falsification round, not
regenerating the whole plan
(`tests/test_deliberation_worldstate_replanning.py::test_replan_is_a_local_revision_not_a_full_regeneration`).

## Bounded (spec §31)

`MAX_REPLANS = 2`. `ReplanState.can_replan()` must be checked before
calling `revise_plan_for_court_verdict()`; the function itself raises
`ReplanBudgetExhaustedError` if called past the cap -- no recursive/
unbounded replan loop is possible
(`test_replan_is_bounded_by_max_replans`).

## Plan versioning (spec §33)

`ReasoningPlan` gained `version`, `parent_version`, `revision_reason`,
`created_at`. Every replan increments `version` and records
`parent_version` -- prior plan metadata is never discarded, only
superseded, matching the same "never silently delete" discipline Phase 6
used for falsified hypotheses.

## Not wired into `CognitiveKernel` this phase

`CognitiveCourt` itself does not call `revise_plan_for_court_verdict()` --
Court returns its verdict and stop_reason exactly as it did in Phase 6;
the Kernel-level REVISE→replan→re-run-Court loop is NOT implemented this
phase (Court remains single-round). This is an honest, disclosed scope
boundary: the replanning MECHANISM is real and tested in isolation, but no
production code path currently drives it end-to-end. See
`PHASE_7_CLOSURE.md`'s "Remaining Phase-7 blockers."
