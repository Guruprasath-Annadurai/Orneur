# Agent Runtime Budgets (Phase 8 spec §45-48)

Extends Phase 7.2's dimension-aware `SocietyBudgetLedger` (unchanged
design) with two new purposes, both drawing from dimensions that existed
in `orca.cognitive.contracts.BudgetDimension` since Phase 3 but had zero
real consumers until this phase (confirmed in `CURRENT_AGENT_RUNTIME.md`'s
audit):

| Purpose | Dimension | Consumer |
|---|---|---|
| `tool_execution` | `TOOL_CALLS` | `AgentRuntime.execute()`, reserved before every tool invocation |
| `agent_delegation` | `AGENT_CALLS` | `orca.agent.delegation.run_delegation()`, 1 unit per delegation |

## Reservation before execution (spec §13/§46)

`AgentRuntime.execute()` calls `self.ledger.reserve("tool_execution", 1)`
BEFORE `AgentToolRegistry.invoke()` -- proven directly with a counting
tool under `max_tool_calls=1`:
`test_budget_exhaustion_before_tool_call_prevents_execution` shows exactly
1 execution happens, never more.

## Dimensions stay distinct (spec §48)

A plan with zero remaining `TOOL_CALLS` cannot execute another tool merely
because `MODEL_CALLS` remain -- `tool_execution`'s cap is sized (and, per
the same "sole consumer in scope" fix applied to `verification`/`retrieval`
in Phase 7.2, widened to the REMAINING `TOOL_CALLS` capacity) independently
of any `MODEL_CALLS` state. No cross-dimensional reallocation is possible
(`SocietyBudgetLedger.reallocate()`, Phase 7.2, unchanged, still refuses
moves between purposes of different dimensions).

## Subagent budget flows from the parent (spec §47)

`orca.agent.delegation.build_child_runtime()` refuses (never clamps) a
`DelegationRequest.budget_subset` that exceeds the parent's REMAINING
capacity per dimension -- no independent fresh allocation. On delegation,
exactly 1 unit of the PARENT's `AGENT_CALLS` is consumed (unchanged from
Phase 7.1's "consume, don't refund on completed work" discipline);
unused RESERVATIONS (not completed work) are still released via the
existing `SocietyBudgetLedger.release_reservation()` mechanism, unchanged.
