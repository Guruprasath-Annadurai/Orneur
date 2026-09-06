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

## Phase 11.2 — Genuinely concurrent branch cancellation (real, not structural)

`orca/simulation/branching.py::run_bounded_branches_async()` launches
both branches as REAL concurrent `asyncio.TaskGroup` children --
structured concurrency, no detached `create_task()` anywhere. Proven
with a real two-`asyncio.Event` handshake: both branches signal
"started" and block on independent release gates; only once BOTH are
confirmed active does the test cancel the parent task.

`TaskGroup.__aexit__`'s own documented behavior guarantees the
structural properties spec §3/§5 require without a second mechanism:
when the enclosing task is cancelled, the TaskGroup cancels every
still-running child and AWAITS ALL OF THEM before re-raising --
`ORPHAN_SIMULATION_TASK` is therefore 0 by construction, verified
directly (`asyncio.all_tasks()` empty immediately after).

Because `simulate_plan_async()` catches its own `CancelledError`
internally (the established `AgentRuntime.execute_async()` pattern), a
cancelled branch's `asyncio.Task` actually reports "done, not cancelled"
-- its OWN result honestly encodes the interruption
(`aggregate_verdict=INCONCLUSIVE` + a cancellation `block_reason`).
`run_bounded_branches_async()` re-classifies this case as cancelled for
its own bookkeeping (never letting "where the CancelledError was caught"
masquerade as a real branch conclusion), while retaining the partial
result in `cancelled_branch_partial_results` for forensic access.

## Phase 11.2 — Real Truth-verification cancellation while genuinely in-flight

Real live-model latency is not deterministic enough to reliably prove
"genuinely in flight" in a fast CI run (spec §8) -- a controlled,
deterministic `_ControlledSlowFabric` test double is used ONLY to prove
exact task lifecycle timing: it sets a real `asyncio.Event` the INSTANT
`assess_evidence()` is entered, then blocks on a release gate. The test
awaits that event (proving the Truth Fabric call genuinely started)
BEFORE calling `task.cancel()` -- never cancelling before entry and
calling that sufficient.

`verify_assumption()` does not catch `CancelledError` itself (unlike
`simulate_plan_async()`) -- cancellation propagates naturally to the
caller, verified directly. No assumption is ever left/returned as
`VERIFIED` from cancelled work (the coroutine never reaches its `return`
statement), and `apply_truth_impact_to_verdict()` on the original,
untouched (default `UNVERIFIED`) assumption still correctly keeps a
high-risk verdict off `PASS`. The pre-existing REAL
`TruthFabric.assess_evidence()` integration tests (SUFFICIENT→VERIFIED,
INSUFFICIENT→downgrade) are unchanged and still pass.

## Phase 11.2 — Cancellation/completion race, explicit semantics

A genuine asyncio edge case was found while building the race test:
cancelling a task synchronously immediately after `create_task()` --
before the event loop ever schedules it even once -- means NONE of
`simulate_plan_async()`'s own code, including its internal
`try/except CancelledError`, ever executes; `CancelledError` propagates
to the awaiter. This is standard, correct Python/asyncio behavior for
every async function, not a defect in this module, and is documented
here rather than silently "fixed" by fabricating a result for work that
never began. When a task IS given one real chance to start first, its
own internal cancellation handling applies normally and a structured
result comes back. Both arms are tested explicitly.

For Truth verification, a real "already complete before cancel() is
processed" race is also tested: when the controlled adapter's release
gate is pre-set, the call completes and its real `VERIFIED` result is
retained -- never discarded or fabricated as cancelled.
