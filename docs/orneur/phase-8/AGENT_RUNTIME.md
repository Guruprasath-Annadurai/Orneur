# Agent Runtime (Phase 8)

## AgentRun / AgentGoal / AgentPlan / AgentTask / AgentAction (spec §5-7)

`AgentRun` carries `run_id`, `goal`, `scope`, `owner`, `plan_id`,
`world_state_id`, `capabilities`, `deadline_s`, `status`
(`CREATED/PLANNING/RUNNING/WAITING/REPLANNING/COMPLETED/FAILED/CANCELLED/
BLOCKED/PARTIAL`), timestamps, and honest completion tracking
(`completed_task_ids`/`blocked_task_ids`). `AgentGoal` is structured, never
a bare string: `objective`, `success_criteria`, `constraints`, `risk`,
`evidence_requirement`, `scope`, `allowed_action_classes` (a
`frozenset[SideEffectClass]` -- the actual mechanism the Policy Engine
checks a resolved action's side-effect class against).

`AgentTask` carries `dependencies` and `completion_criteria`;
`AgentRuntime.execute()` refuses to run a task whose dependencies aren't
yet `COMPLETED`/`SKIPPED`, marking it `BLOCKED` instead (tested:
`test_partial_multi_task_success_is_reported_honestly`).

## Retries (spec §26)

Bounded (`_MAX_ACTION_RETRIES = 1`) and classified: only exception class
names in `_TRANSIENT_ERROR_CLASSES = {TimeoutError, ConnectionError,
TimeoutExpired}` are retried. A `PermissionError` (or any other class) is
never retried, tested directly
(`test_permission_denied_is_never_blindly_retried`).

## Idempotency (spec §27)

A non-idempotent tool (`ToolSpec.idempotent=False`, e.g. `write_file`) is
tracked per-run by `(tool_id, sorted(arguments))` -- a repeat action with
the same key within one run is deduplicated (`Observation.status="DEDUPED"`)
rather than re-executed. `read_file`/`web_search`/`shell` are declared
`idempotent=True` and may re-run freely.

## Failure semantics (spec §51)

`ExecutionStopReason` is a bounded enum:
`GOAL_ACHIEVED/TOOL_ERROR/POLICY_DENIED/CAPABILITY_MISSING/
APPROVAL_REQUIRED/BUDGET_EXHAUSTED/TIMEOUT/CANCELLED/NO_VALID_PLAN/
UNRESOLVED_WORLD_STATE/DEPENDENCY_FAILED/MAX_REPLANS_EXCEEDED` -- never
collapsed into a generic failure. `CAPABILITY_MISSING` is checked and
reported BEFORE the more generic `POLICY_DENIED` when both are true, so
the more specific, actionable reason is never masked.

## Partial success (spec §52)

`AgentRunStatus.PARTIAL`/`BLOCKED` are real, distinct outcomes from
`COMPLETED` -- a run with any failed/blocked task never reports
`COMPLETED` (`all_completed` is computed over every task in the CURRENT
task map, including tasks added by a replan, not the stale original
plan's task list -- a real bug found and fixed during this phase's own
testing, see `EVALUATION.md`).
