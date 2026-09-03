# Agent Runtime Architecture (Phase 8)

## Canonical authority chain (spec §2)

```
Model  ->  Agent Runtime  ->  Capability Engine  ->  Policy Engine  ->  Tool Adapter
```

A model may REQUEST an action; only `orca.agent.policy.evaluate_policy()`
(fully deterministic, no model call) may authorize it. Court ACCEPT,
Society routing, and Memory recall never authorize anything -- this was
true before Phase 8 (Phase 6/7 both state it explicitly) and remains true
here: none of those subsystems' outputs are consulted anywhere in
`orca.agent.runtime.AgentRuntime._authorize()`.

## The loop (spec §1, §13)

```
ActionRequest -> capability check -> policy check -> budget reservation
-> execution -> result validation -> Observation -> WorldState update
-> (on failure) bounded local replan -> next action / STOP
```

Implemented in `orca.agent.runtime.AgentRuntime.execute()`. Never
model->tool direct: `AgentRuntime` is the ONLY caller of
`AgentToolRegistry.invoke()` in this new package.

## Package layout (`orca/agent/`)

- `contracts.py` -- all typed dataclasses (spec §4): `AgentGoal/Plan/Task/
  Action`, `ActionRequest/Authorization/Result`, `Observation`, `ToolSpec/
  Invocation/Result`, `Capability/CapabilityRequirement/CapabilityDecision`,
  `AgentRun/AgentTrace`, `DelegationRequest/Result`, `ExecutionStopReason`.
- `tool_registry.py` -- `AgentToolRegistry`, wrapping EXISTING sound
  primitives (`orca.tools`) with `ToolSpec` security metadata.
- `capability.py` -- `check_capabilities()`: a pure membership check.
- `policy.py` -- `evaluate_policy()`: the sole authorization boundary.
- `runtime.py` -- `AgentRuntime`: the execution loop.
- `delegation.py` -- bounded subagent delegation with non-escalation
  invariants.
- `eval_harness.py` / `latency_bench.py` -- deterministic evaluation and
  performance measurement.

## Relationship to the EXISTING `AgentLoop`/`OrcaUltra` (spec §3, §18-19)

`orca/agent/` is a NEW, additive package -- `AgentLoop`/`OrcaUltra` are
NOT torn out or redesigned (see `CURRENT_AGENT_RUNTIME.md`'s audit). The
one touchpoint added is opt-in: `AgentLoop(..., route_tool_reasoning_via_society=True)`
resolves its tool-reasoning brain through Model Society's `TOOL_REASONER`
role instead of implicitly reusing the session's general-chat brain --
default (`False`) behavior is byte-for-byte unchanged from before this
phase, verified directly (`tests/test_agentloop_tool_reasoner_migration.py`).

## Honest scope notes

- **No LLM-driven planning is implemented this phase.** `AgentRuntime.execute()`
  takes an `AgentPlan` (a `list[AgentTask]`/`list[AgentAction]`) as input
  -- it does not itself call a model to decompose a goal into tasks. This
  is a genuine, disclosed gap: Phase 8 builds the AUTHORIZATION/EXECUTION/
  OBSERVATION/WORLDSTATE/REPLAN machinery real production requests would
  need, but the goal->plan decomposition step (which WOULD be a
  `TOOL_REASONER`-routed model call) is not wired into this new runtime --
  only into the pre-existing `AgentLoop._plan()` (see above).
- **Truth Fabric / Cognitive Court / Memory integration are documented
  hook points, not deeply wired this phase** -- `AgentRuntime` does not
  itself call `TruthFabric`/`CognitiveCourt`/`FailureMemory`/
  `ProceduralMemory`. A caller that wants a high-risk plan reviewed by
  Court, or wants advisory failure-memory context before planning, does
  so BEFORE constructing the `AgentPlan` it passes to `AgentRuntime.execute()`
  -- exactly the same "compose, don't embed" pattern Court itself uses for
  Truth Fabric (Court consumes a `TruthResult` the caller already computed,
  never re-derives it). See `WORLD_STATE_ACTION_LOOP.md`/`SECURITY.md` for
  what IS wired (WorldState, capability/policy) versus what remains a
  documented integration point.
