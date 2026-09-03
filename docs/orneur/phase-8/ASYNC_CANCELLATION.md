# Async Runtime + Cancellation (Phase 8.1 spec §23-36)

## Genuine async entry point (spec §23)

`AgentRuntime.execute_async()` is the real implementation; `execute()` is
a thin synchronous wrapper (`asyncio.run(self.execute_async(...))`) --
NOT a duplicated loop (avoiding the two-implementations-drift risk spec
§5 of Phase 8.1 warns about for planners, applied here too). No nested-
event-loop hack: `execute()` is only valid from OUTSIDE a running event
loop, exactly Python's own `asyncio.run()` rule; an async caller already
inside an event loop calls `await execute_async()` directly.

## Cancellation vs. deadline -- kept distinct (spec §25)

- `ExecutionStopReason.TIMEOUT` / `AgentRunStatus.FAILED`: the runtime's
  own deadline (`deadline_s`) was exceeded -- checked once per loop
  iteration, never confused with an external cancel.
- `ExecutionStopReason.CANCELLED` / `AgentRunStatus.CANCELLED`: the
  CALLER explicitly cancelled the `asyncio.Task` running `execute_async()`
  (`task.cancel()`). Proven never to cross-contaminate:
  `tests/test_agent_cancellation.py::test_deadline_and_cancellation_are_distinct_stop_reasons`.

## Cancellation propagation (spec §24, §26-27)

- **Through tool execution**: `AgentToolRegistry.invoke_async()` awaits a
  genuinely-async tool directly (interruptible at its own internal
  `await` points) or runs a sync tool via `asyncio.to_thread()`.
  **Honest semantics (spec §26)**: cancelling the awaiting Task interrupts
  the AWAIT, but Python cannot forcibly kill an OS thread already running
  synchronous code -- a cancelled sync tool's thread keeps running to
  completion in the background; its result is simply discarded. This is
  documented, not glossed over, and matches real CPython
  `asyncio.to_thread` behavior exactly.
- **Through planning**: `AgentPlanner.compile_plan()`'s `await
  gateway_json_call(...)` is a normal awaited coroutine -- cancelling the
  Task running `compile_plan()` raises `CancelledError` there naturally,
  proven directly:
  `tests/test_agent_planning_cancellation.py::test_cancel_during_planning_never_produces_a_plan`.
  The budget reservation made for the (never-completed) attempt is real,
  accounted consumption for an attempt that was genuinely made -- not a
  leak (spec §29's "budget accounting correct").
- **Through subagents**: `orca.agent.delegation.run_delegation_async()`
  awaits `child_runtime.execute_async()` directly in the parent's own
  task -- a parent cancellation reaches the child's execution loop the
  same way any awaited coroutine receives cancellation, no separate
  relay mechanism (spec §27, §31). The child's OWN
  `execute_async()` catches `CancelledError` internally and returns a
  structured `AgentRunStatus.CANCELLED` result (the same graceful-return
  design used everywhere in this runtime) rather than re-raising --
  proven:
  `tests/test_agent_subagent_cancellation.py::test_parent_cancellation_cancels_active_child_task`.
- **Through Truth Fabric / Court**: both are called via `await` inside
  `execute_async()`'s own try/except; `CancelledError` from either is
  caught the same way as a tool-call cancellation.

## Reservation release on cancellation (spec §28)

Every reservation made immediately before a now-cancelled operation is
released via `SocietyBudgetLedger.release_reservation()` -- tested
directly for tool execution
(`test_unused_reservation_is_released_on_cancellation`, asserting
`consumed_tool_calls == 0`) and for subagent delegation (the child's own
internal release, verified via the parent's clean `AGENT_CALLS` state in
`test_parent_cancellation_cancels_active_child_task`). Already-consumed
(completed) work is never refunded -- unchanged from Phase 7's
established discipline.

## Partial success + cancellation (spec §33)

A/B completed, C cancelled: A/B's `task_id`s remain in
`run.completed_task_ids`, never erased -- proven:
`test_partial_completion_is_preserved_when_a_later_action_is_cancelled`.

## WorldState consistency under cancellation (spec §34-35)

A cancelled action NEVER produces a success fact
(`test_cancelled_tool_never_emits_a_success_fact`) -- `_apply_observation()`
is only called for a completed `Observation`, which is only constructed
AFTER a tool call actually returns. A cancelled `asyncio.to_thread()`
sync call whose underlying thread may still be running externally (the
honest semantics above) is a real, disclosed
`OUTCOME_UNKNOWN`-class scenario for IRREVERSIBLE/EXTERNAL_SIDE_EFFECT
tools specifically -- not built out as a distinct structured state this
phase (all four of Phase 8's built-in tools are either read-only or
locally-reversible; the race spec §35 describes matters most for
EXTERNAL_SIDE_EFFECT tools, none of which exist in this phase's tool
registry -- disclosed as a real, not-yet-encountered gap rather than
speculatively implemented against no real tool).
