# Agent Planner (Phase 8.1 spec §3-11)

`orca.agent.planner.AgentPlanner.compile_plan()` -- the first production
Goal→Plan boundary for `AgentRuntime`.

## Model Society, not a hardcoded tier (spec §4)

`compile_plan()` resolves cognition via
`orca.society.router.resolve_tier_for_role(CognitiveRole.TOOL_REASONER)`
-- never `brain_for_tier_resolution()`/a literal tier string directly. The
returned `RoutingDecision` (exact checkpoint, capability evidence, degrade/
fallback state) is captured on `PlanningOutcome.routing_decision_id`/
`model_id`/`checkpoint_id` for audit. In production (no experimental
opt-in), this resolves to Genesis-legacy (`orca-nano-v7`), same as every
other Society-routed role -- Novus remains gated exactly as everywhere
else in this codebase.

## Schema validation (spec §6)

`_validate_and_build_plan()` rejects (returns `None`, never a partial
`AgentPlan`) on: non-dict/non-list top-level shapes, tasks/actions
exceeding bounds, a non-string task description, a dependency index out
of range, a `tool_id` not in the `allowed_tool_specs` dict passed in,
non-dict `arguments`. **One deliberate bounded repair** (spec §6's own
"reject or bounded-repair" choice): a negative `depends_on_index` (a
common "no dependency" sentinel some models emit instead of an empty
list) is dropped rather than invalidating the whole plan -- a real
finding from this phase's own live-Ollama test (see `EVALUATION_V2.md`).
Never security-relevant: dependencies only gate task ORDERING, never
authorization.

## Plan tool visibility (spec §8)

`compile_plan()`'s caller controls `allowed_tool_specs` -- ONLY those
tools are named in the prompt, and `_validate_and_build_plan()` rejects
any `tool_id` outside that dict, REGARDLESS of whether it happens to be a
real tool registered elsewhere in the system. Defense in depth: even if
this check were somehow bypassed, `AgentRuntime._authorize()`'s own
capability/policy check would independently reject an unauthorized tool.

## Bounds (spec §9)

`MAX_TASKS=12`, `MAX_ACTIONS=20`, `MAX_DEPENDENCIES_PER_TASK=5`,
`MAX_ESTIMATED_TOOL_CALLS=20`, `MAX_DELEGATION_REQUESTS=4` (declared;
delegation requests are not yet planner-emitted this phase -- see
`RUNTIME_INTEGRATIONS.md`'s honest scope note), `MAX_PLANNING_ATTEMPTS=2`.
An oversized plan is rejected outright, never truncated-and-executed.

## Planning budget (spec §10)

Each planning attempt reserves 1 `MODEL_CALLS` unit (via the SAME
dimension-aware `SocietyBudgetLedger` every other Society-routed call
uses) BEFORE invoking the reasoner -- `PlanningFailureReason.PLAN_BUDGET_EXHAUSTED`
if the reservation fails. Up to `MAX_PLANNING_ATTEMPTS=2` attempts are
made (each consuming its own unit) before giving up honestly.

## Planning failure (spec §11)

`PlanningFailureReason`: `NO_VALID_PLAN`, `PLAN_SCHEMA_INVALID`,
`PLAN_BUDGET_EXHAUSTED`, `NO_ELIGIBLE_REASONER` (Model Society found no
eligible candidate for `TOOL_REASONER` at all). None of these fall back to
unsafe free-form execution -- `PlanningOutcome.plan` stays `None`, and the
orchestrator (`orca.agent.orchestrator.run_agent_request`) never
constructs an `AgentRuntime` run in that case.

## Plan security (spec §7)

A model-generated plan cannot add capabilities, change entitlement,
increase budget, change scope, invent a privileged tool, or mark itself
approved -- `AgentGoal`/`AgentPlan`/`AgentTask`/`AgentAction` carry no such
fields at all (checked structurally,
`tests/test_agent_plan_security.py`), and `_validate_and_build_plan()`
never even receives the `goal` object (checked directly,
`test_scope_and_tenant_are_not_plan_controlled`).
