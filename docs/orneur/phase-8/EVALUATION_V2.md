# Agent Runtime Evaluation V2 (Phase 8.1 spec §42)

## Original Phase 8 scenarios (unchanged)

20/20 passed -- see `docs/orneur/phase-8/EVALUATION.md`, re-verified
green this phase (`orca.agent.eval_harness.run_all()`).

## Closure scenarios (Phase 8.1)

`orca.agent.eval_harness_v2.run_closure_scenarios()` -- **16/16 passed**.

| Scenario | Result |
|---|---|
| Goal → valid model-generated AgentPlan | PASS |
| Invalid model plan rejected | PASS |
| Plan attempts capability escalation | PASS |
| Plan invents a tool | PASS |
| Plan exceeds task bound | PASS |
| Memory Failure recall changes plan (advisory) | PASS |
| ProceduralMemory incompatible with current tools rejected | PASS |
| Strict fact triggers Truth Fabric | PASS |
| High-risk plan triggers Court | PASS |
| Court ACCEPT + Policy DENY | PASS |
| Court REVISE triggers bounded plan revision | PASS |
| Cancel during planning | PASS (live, see `test_agent_planning_cancellation.py`) |
| Cancel during tool | PASS (live, see `test_agent_cancellation.py`) |
| Cancel during child agent | PASS (live, see `test_agent_subagent_cancellation.py`) |
| Deadline vs cancellation differentiated | PASS |
| Partial completion before cancellation | PASS (live, see `test_agent_cancellation.py`) |

## Live model-plan test (spec §43)

`tests/test_agent_planner_live.py::test_live_goal_produces_a_validated_plan_using_only_read_only_tools`
-- a real Ollama call through `AgentPlanner.compile_plan()`, offering
ONLY `read_file` (a read-only tool), verifying the resulting plan never
proposes anything else. **Passes.**

## A real bug found and fixed via this live test

The FIRST run of the live planner test failed:
`PlanningFailureReason.PLAN_SCHEMA_INVALID` after both bounded attempts.
Debugging the raw model output showed the nano-tier model emitted
`"depends_on_index": [-1]` -- a common "no dependency" convention in some
training data -- which `_validate_and_build_plan()` rejected outright
(bounds-checked as `0 <= i < len(tasks)`), invalidating an otherwise
perfectly reasonable plan. Fixed with a targeted, non-security-relevant
bounded repair: negative indices are dropped (treated as "no dependency")
rather than invalidating the whole plan (dependencies only gate task
ORDERING, never authorization -- confirmed by re-running all plan-security
tests unchanged and green after the fix). This matches spec §61's own
"disclose real model-quality findings, fix with a real change, not a
narrow literal patch" discipline established since Phase 6.

## No fabricated model-quality gains

None of the above scenarios claim an improvement in reasoning capability
-- every PASS is a structural/behavioral correctness check, matching
every prior phase's evaluation discipline.
