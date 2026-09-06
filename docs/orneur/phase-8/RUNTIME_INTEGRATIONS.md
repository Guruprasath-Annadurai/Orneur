# Runtime Integrations — Truth Fabric / Memory / Cognitive Court (Phase 8.1 spec §12-22)

Phase 8 disclosed these as "caller-side composition points, not explicit
runtime integrations." Phase 8.1 makes each an EXPLICIT, typed,
conditionally-invoked integration, tied together by
`orca.agent.orchestrator.run_agent_request()`.

## Truth Fabric runtime hook (spec §12-14)

`AgentAction.requires_truth_check: bool` is a typed field the PLANNER (or
a caller) sets explicitly -- never inferred by the runtime itself.
`AgentRuntime(..., truth_checker=...)` accepts an async callback; when an
action has `requires_truth_check=True`, the runtime awaits
`truth_checker(action)` BEFORE budget reservation/execution. `False`
(insufficient evidence) never executes on a guess -- the action fails with
`ExecutionStopReason.UNRESOLVED_WORLD_STATE`, eligible for the SAME
bounded local-replan mechanism tool failures use.
`orca.agent.truth_hook.truth_check_sufficient()` is the real
implementation, calling `TruthFabric.assess_evidence()` directly -- no
second evidence stack. Kept explicitly distinct from OPERATIONAL
verification (a tool read-back/status check, spec §14) -- those remain
`Observation`-level facts from the tool itself, never routed through
Truth Fabric.

## Memory Continuum runtime hook (spec §15-18)

`orca.agent.memory_hook.recall_advisory_context()` queries
`FailureMemory`/`ProceduralMemory` through the EXACT SAME
`MemoryQuery` → `orca.memory.retrieval.recall()` →
`orca.memory.firewall.filter_recall()` path Phase 5/5.1 established --
never a raw string query, never a Firewall bypass. Advisory only (spec
§16): the returned text is passed to `AgentPlanner.compile_plan()`'s
`memory_context` parameter, which only ever appears in the MODEL PROMPT --
it has no code path into `Capability`/`Policy`/`WorldState`/`TruthResult`
at all.

`orca.agent.memory_hook.procedural_record_is_compatible()` implements
spec §18's compatibility gate: a recalled procedure's steps must
reference currently-allowed tool ids, or it is rejected -- never executed
blindly against a stale tool set.

## Cognitive Court runtime hook (spec §19-21)

`orca.agent.court_hook.should_request_court_review()` -- real, structured
triggers only (HIGH/CRITICAL risk, an unresolved contradiction,
AUDIT_GRADE evidence requirement, or a DESTRUCTIVE-class allowed action).
`request_court_review()` runs ONE bounded Court round (Phase 6/7,
unchanged), consuming the SAME shared `CognitiveBudget` -- no fresh
deliberation allocation (spec §21). **Court ACCEPT never authorizes** --
proven structurally (`orca.agent.court_hook` has no import of
`orca.agent.policy`/`orca.agent.capability` at all) and behaviorally (the
required test: Court ACCEPT + Policy DENY → action does not execute,
`tests/test_agent_court_integration.py::test_court_accept_plus_policy_deny_means_action_does_not_execute`).

## The full integration order (spec §22)

`orca.agent.orchestrator.run_agent_request()`:

```
AgentGoal -> Memory recall (if use_memory) -> Court review (if triggered)
-> AgentPlanner.compile_plan() -> AgentRuntime.execute_async()
```

Every heavy stage is CONDITIONAL: a low-risk, non-destructive goal skips
Court entirely (proven:
`tests/test_agent_orchestrator.py::test_simple_safe_goal_skips_court_review`);
`use_memory=False` skips Memory entirely; `truth_checker=None` means no
action ever pays the Truth Fabric cost. Simple, safe requests really do
skip the heavy stages, not just "in theory."

## Honest scope note

`AgentPlanner` does not itself emit `requires_truth_check=True` or
delegation requests from model output this phase -- these are caller/
future-work-set fields on the plan's actions. The MECHANISM (the runtime
gate, the typed field, the compatibility check) is real and tested; the
model LEARNING to set these fields autonomously via prompt engineering is
future refinement, not required by this phase's acceptance gates (which
require the mechanism to exist and be tested, not that the model uses it
unprompted).
