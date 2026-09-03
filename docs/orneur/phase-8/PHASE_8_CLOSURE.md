# Phase 8 Closure — Agentic Runtime + World State Action Loop

## Scope delivered

First production Agent Runtime (`orca/agent/`): typed contracts
(`AgentGoal/Plan/Task/Action`, `ActionRequest/Authorization/Result`,
`Observation`, `ToolSpec/Invocation/Result`, `Capability/
CapabilityDecision`, `AgentRun/AgentTrace`, `DelegationRequest/Result`,
`ExecutionStopReason`); a canonical `ToolRegistry` wrapping the EXISTING,
already-secured tool primitives with real security metadata; a
`Capability Engine` (pure membership check); a `Policy Engine`
(deterministic, the sole authorization boundary); an `AgentRuntime`
execution loop implementing PLAN→AUTHORIZE→EXECUTE→OBSERVE→UPDATE
WORLDSTATE→VERIFY→REPLAN→STOP with real budget reservation, bounded
retries, idempotency, and approval-required blocking; bounded subagent
delegation with property-tested capability/budget non-escalation, depth,
and fanout limits; an opt-in TOOL_REASONER Society-routing touchpoint for
the existing `AgentLoop`; a 20-scenario deterministic evaluation harness;
and a performance benchmark.

**Explicitly not built**, per the spec's own exclusions: enterprise
connectors (Phase 9), Godmode/elevated-capability leases (Phase 10), the
Simulation Chamber (Phase 11), a full LLM-driven goal→plan decomposition
engine for the NEW `AgentRuntime` (the existing `AgentLoop._plan()`
remains the model-driven planning path; `AgentRuntime.execute()` takes an
already-built `AgentPlan`).

## Honest scope notes

- **`AgentRuntime` does not itself do LLM-driven planning.** It is the
  AUTHORIZATION/EXECUTION/OBSERVATION/WORLDSTATE/REPLAN machinery; a
  caller (or a future phase) supplies the `AgentPlan`. This is a
  deliberate, disclosed boundary -- building a full model-driven planner
  on top of a not-yet-proven authorization layer would have meant
  authorizing actions from an unproven planner, backwards from the
  intended build order.
- **Truth Fabric / Cognitive Court / Memory are documented integration
  points, not deeply wired into `AgentRuntime` itself this phase** -- a
  caller composes them BEFORE constructing the plan/goal it passes in,
  the same "compose, don't embed" pattern Court itself uses for Truth
  Fabric. See `ARCHITECTURE.md`.
- **Cancellation is proven via deadline enforcement, not `asyncio`
  cancellation propagation** -- `AgentRuntime.execute()` is synchronous.
  Genuine async cancellation testing is deferred to whatever future
  integration point calls into an async `AgentRuntime`.
- **Delegation fanout tracking is caller-supplied** (`active_subagent_count`
  is a parameter, not internally maintained across concurrent runtimes) --
  a real, disclosed scope boundary for "start conservatively" (spec §33).
- **Ultra's own model calls remain `LEGACY_COMPATIBILITY`**, unchanged
  from Phase 7's classification -- same architectural reason (one `Brain`
  object per pipeline run, not per-role), consistent with spec §19's "do
  not grant new Ultra capabilities... remains a product pipeline."

## Two real bugs found and fixed during this phase's own testing

1. **Task-completion accounting after a local replan** -- the original
   failed task stayed `FAILED` forever even after a substitute task
   completed the work, so a fully-successful run (via its replan)
   reported `PARTIAL` instead of `COMPLETED`. Fixed: a superseded task is
   marked `SKIPPED`; the final completion check iterates the CURRENT task
   map (including replan-added tasks), not the stale original plan.
2. **`tool_execution` purpose cap prematurely exhausting** -- the exact
   same percentage-of-pool-cap bug class found twice in Phase 7.2
   (`verification`, `retrieval`). Fixed with the same "widen to remaining
   capacity for the sole in-scope consumer" pattern.

Both found via TDD (the test that exercises the real scenario failed
first, was root-caused, then fixed) -- not discovered later.

## Test suite

11 new test files (~90 new tests): `test_agent_runtime.py` (11),
`test_agent_delegation.py` (10), `test_agent_security.py` (9),
`test_agent_secret_and_trace_security.py` (3),
`test_agentloop_tool_reasoner_migration.py` (3),
`test_agent_eval_harness.py` (1), `test_agent_runtime_fast_path.py` (3),
plus supporting fixtures. Full application suite (fresh, clean run):
**1057 passed, 0 failures**, 224.30s. Security suite (18 files, including
four new Phase 8 security test files): **180 passed, 0 failures**, 382.38s.
Live Ollama Court/Kernel regression check (to confirm the
`SocietyBudgetLedger` extension didn't disturb the existing Court/Truth
Fabric budget paths): **4 passed, 0 failures**.

## `AGENT_DIRECT_MODEL_BYPASS` / `AGENT_DIRECT_TOOL_BYPASS` / `AGENT_POLICY_BYPASS` / `AGENT_CAPABILITY_BYPASS` / `UNBOUNDED_AGENT_LOOP` / `UNBOUNDED_DELEGATION` / `UNACCOUNTED_TOOL_CALL` / `WORLDSTATE_UNTRUSTED_MUTATION` / `APPROVAL_BYPASS` / `RAW_CHAIN_OF_THOUGHT_STORAGE` (spec §73)

All **= 0**:

- **Direct model bypass**: `evaluate_policy()`/`check_capabilities()` make
  no model call; `AgentRuntime._authorize()` never asks a model to decide
  authorization.
- **Direct tool bypass**: `AgentToolRegistry.invoke()` is called ONLY from
  `AgentRuntime.execute()`, after `_authorize()` returns `authorized=True`
  -- no other code path in `orca/agent/` calls a tool function directly.
- **Policy bypass**: capability check runs before, and independently of,
  policy evaluation; neither can be skipped by the other (tested).
- **Capability bypass**: `check_capabilities()` is a pure membership
  check with no override; delegation's non-escalation is enforced at
  construction time, not execution time (fail before start, not after).
- **Unbounded agent loop**: `deadline_s` enforced every iteration; a
  20-slow-task plan under a 0.3s deadline runs a bounded subset, never
  all 20 (tested).
- **Unbounded delegation**: `MAX_DELEGATION_DEPTH=3`,
  `MAX_CONCURRENT_SUBAGENTS=4`, both enforced with a dedicated exception
  type each, tested.
- **Unaccounted tool call**: every tool invocation reserves
  `tool_execution`/`TOOL_CALLS` before executing; a budget-exhausted
  request never executes the tool (tested with a real counting function).
- **Untrusted WorldState mutation**: only `_apply_observation()` writes
  WorldState from an agent action, exclusively through the typed,
  provenance-required `apply_update()` (Phase 7.1, unchanged).
- **Approval bypass**: `DESTRUCTIVE` actions always require approval and
  are proven to never execute (a `called` flag stays `False`).
- **Raw chain-of-thought storage**: no dataclass in `orca/agent/contracts.py`
  carries an unrestricted reasoning-prose field, checked by inspection and
  directly for `AgentTrace`.

## READY TO ADVANCE TO PHASE 9: YES

Every component the spec's acceptance gates name is real, tested, and
either fully wired (capability/policy/budget/WorldState/delegation) or
delivered as an honestly-disclosed foundation (LLM-driven planning for the
new runtime, deep Truth/Court/Memory embedding, async cancellation).
Two real bugs were found and fixed during this phase's own TDD process,
not discovered later. **STOP AFTER PHASE 8 -- awaiting explicit human
approval before any Phase 9 enterprise/FDE connector work begins.**
