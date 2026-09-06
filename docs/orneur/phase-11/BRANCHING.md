# Phase 11.1 — Bounded Branching

`orca/simulation/branching.py::run_bounded_branches()`.

## Never combinatorial

At most `MAX_SIMULATION_BRANCHES` (2) branches, always exactly
`EXPECTED_SUCCESS`/`EXPECTED_FAILURE` conceptually — never a
combinatorial tree over every uncertain action.

## When a second branch is even generated

`_uncertainty_justifies_branching()` — a real, deterministic trigger:
any per-action warning, or any effect with sub-`HIGH` confidence.
Already-`BLOCK` plans never branch further (nothing left to learn from a
second branch). Verified with an adversarial 6-action, all-uncertain
plan: branch count still caps at 2.

## Branch 2 is a real re-simulation, not a fabricated future

`EXPECTED_FAILURE` re-runs `simulate_plan()` against the SAME plan
truncated at its last action — a real, honest model of "what if the
most uncertain action never completed," reported at minimum
`INCONCLUSIVE` (never silently `PASS`, since the dropped action's real
effect is genuinely unknown in this branch).

## State isolation is structural, not a separate mechanism

Each branch is an independent `simulate_plan()` call, and
`open_sandbox()` already creates a fresh, isolated temp copy per call —
branch A's sandbox and branch B's sandbox are two entirely separate
directories on disk, neither ever touching the real root or each other.
Verified: the real root's content is unchanged after branching runs.

## Shared budget, no fresh allowance

`_reserve_branch_budget()` reserves from the SAME
`simulation_operations` purpose on the caller's real `SocietyBudgetLedger`
— one reservation per branch actually attempted, never a fresh
independent allocation per branch. Budget exhaustion caps the branch
count below 2 automatically (verified: an always-exhausted ledger
yields zero branches).

## No per-branch authority escalation (spec §43)

`run_bounded_branches()`'s signature has no `capabilities`/`lease_id`/
`tenant_id`/budget-override parameter at all — structurally, a branch
cannot request broader authority than the single `filesystem_root`/
`live_world_state`/`budget_ledger` context the whole call already
shares (verified via signature inspection).
