# Phase 11.1 — Multi-Action Plan Simulation

`orca/simulation/plan_chamber.py::simulate_plan()` / `simulate_plan_async()`.

## Dependency ordering

Kahn's algorithm over `AgentTask.dependencies` (`_topological_order()`).
A dependency referencing an unknown `task_id`, or a cycle, raises
`PlanDependencyError` and the whole plan simulation resolves to `BLOCK`
— never silently falling back to list order. Independent tasks (equal
in-degree) are ordered deterministically (sorted by `task_id`), never
left to dict/set iteration order.

## Projected state chain (the critical invariant)

Every action in a plan simulation is applied to ONE SHARED sandbox
(`orca.simulation.filesystem_sim.open_sandbox()`), opened once for the
whole plan and applied to sequentially via
`apply_action_to_sandbox()` — action B's simulated starting state is
therefore genuinely action A's projected output, not the original live
root re-copied per action. Verified directly: action B's
`PredictedEffect.before_reference` hash is byte-identical to action A's
`predicted_after_reference` hash.

## MAX_SIMULATION_ACTIONS

Checked BEFORE any action is simulated (`_prepare()`). An oversized plan
is rejected outright (`BLOCK`, `partial=True`, `action_order=[]`) — never
silently truncated to the first N actions and reported as a full-plan
PASS.

## Failure propagation

If an action's real simulation resolves `BLOCK`, every task depending
on it (transitively) is marked `BLOCKED_BY_DEPENDENCY` and never
simulated as if the dependency had succeeded — verified with a
`delete`-on-a-missing-file action blocking its dependent.

## Aggregate verdict, blast radius, reversibility

- **Verdict**: deterministic precedence `BLOCK > INCONCLUSIVE > REVISE >
  PASS_WITH_WARNINGS > PASS` — no model voting.
- **Blast radius**: the worst individual effect's radius, ESCALATED from
  `SINGLE_OBJECT` to `MULTIPLE_OBJECTS` when more than one distinct
  resource is touched across the plan — never just the first action's
  radius.
- **Reversibility**: worst-of ranking (`REVERSIBLE < COMPENSATABLE <
  UNKNOWN < IRREVERSIBLE`) — a plan with 3 reversible actions and 1
  irreversible one is reported `IRREVERSIBLE` overall.

## Compensation chain

Built per-effect from `Reversibility`: `COMPENSATABLE` effects get a
proposed (never guaranteed) inverse-action `CompensationPlan`;
`IRREVERSIBLE` effects get an explicit "no compensating action exists"
record. Never called atomic rollback anywhere in code or docs.

## Real bugs found while building this

Both the sync `simulate_plan()`/async `simulate_plan_async()` share
`_simulate_one_action()`/`_finalize()`/`_prepare()` — factored out
specifically so the two entry points can never silently drift into two
different behaviors, a risk noted explicitly during design rather than
discovered as a bug afterward.
