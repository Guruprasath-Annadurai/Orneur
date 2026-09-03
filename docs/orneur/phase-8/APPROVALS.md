# Human Approval Foundation (Phase 8 spec §28-29)

Approval CONTRACTS only this phase -- no full Godmode/elevated-privilege
system (explicitly out of scope, Phase 10).

## What exists

`PolicyDecisionState.REQUIRE_APPROVAL` is a real, distinct outcome from
`ALLOW`/`DENY`. When `evaluate_policy()` returns it,
`AgentRuntime.execute()`:

- Marks the task `BLOCKED` (never `FAILED` -- it's pending, not lost).
- Sets `AgentRun.status = BLOCKED` and
  `stop_reason = ExecutionStopReason.APPROVAL_REQUIRED`.
- **Never executes the tool.** Proven directly with a destructive tool
  whose function sets a `called` flag --
  `tests/test_agent_runtime.py::test_destructive_action_requires_approval_and_never_executes`
  asserts `executed["called"] is False`.

## What does NOT exist yet (disclosed, Phase 10 scope)

A structured `ApprovalRequest`/`Approval` record (action, resource, risk,
scope, expiry, approver identity) and an actual approval-granting flow are
NOT implemented this phase -- `BLOCKED` is a terminal state for THIS run;
resuming after a human approves is future work. This is an honest,
disclosed foundation, matching spec §29's own "implement approval
contracts only... future Phase 10 capability leases can build on this."

## Approval cannot be faked (spec §28)

No code path in `orca/agent/` ever sets
`PolicyDecisionState.ALLOW`/`ActionAuthorization.authorized=True` from a
model's output, a Court verdict, a memory recall, or retrieved content --
`evaluate_policy()` imports none of those subsystems (verified: no
`orca.deliberation`/`orca.society`/`orca.memory` import in
`orca/agent/policy.py`).
