# Phase 11.1 — Async Simulation & Cancellation

`orca/simulation/plan_chamber.py::simulate_plan_async()`.

## Real async entry point, not a wrapper illusion

`simulate_plan_async()` is the REAL implementation; `simulate_plan()` is
a thin `asyncio.run(...)` wrapper — the exact pattern
`orca.agent.runtime.AgentRuntime.execute_async()`/`execute()` already
established in Phase 8.1. No nested-event-loop hacks.

## Cooperative cancellation checkpoint

`await asyncio.sleep(0)` runs BEFORE each action in the ordered list — a
real `task.cancel()` genuinely interrupts here. Verified with real
`asyncio.create_task()` + `task.cancel()`: cancelling between action A
and action B leaves A's real, already-computed result untouched in
`per_action`/`action_order`, and B/C never start.

## Honest limitation, not a silent gap (spec §33)

The per-action filesystem work itself
(`orca.simulation.filesystem_sim.apply_action_to_sandbox`) is
synchronous, real disk I/O. Python cannot abort a blocking syscall
mid-flight — an action that has already STARTED always finishes.
Cancellation takes effect BEFORE the next action begins, never
mid-write. This is stated directly in the function's docstring, not
discovered as a surprise by a caller.

## Cancellation vs. timeout stay distinct

`simulate_plan_async()` only ever sets `block_reasons`/`aggregate_verdict`
via the explicit cancellation path when `asyncio.CancelledError` is
caught or an injected `cancellation_check()` returns True — never
conflated with a deadline/timeout mechanism (which is out of this
specific function's scope; a caller wanting a hard deadline wraps this
call in `asyncio.wait_for()`, and a `TimeoutError` from that is
distinguishable from this function's own `CANCELLED`-shaped result).

## No orphan tasks

Verified directly: after `task.cancel()` + `await task`,
`asyncio.all_tasks()` contains no other pending task — the temp sandbox
context manager's `finally` block always runs (even on cancellation),
so no dangling temp directory or background work survives.

## Budget: reserved per action attempted, not per plan upfront

`_reserve_action_budget()` reserves exactly ONE `simulation_operations`
unit per action ACTUALLY started — never a single large reservation for
the whole plan taken upfront. This means there is nothing to "release"
for actions that never began (spec §32): unused capacity was never
taken from the ledger in the first place. Already-consumed reservations
for actions that did run remain consumed — no double-release, no
double-charge.
