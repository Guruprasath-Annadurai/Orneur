# Planning Authority Audit (Phase 8.1 spec §2)

| Path | Classification | Notes |
|---|---|---|
| `orca.agent.planner.AgentPlanner.compile_plan()` (new this phase) | **AGENT_RUNTIME_AUTHORITATIVE** | The one production Goal→Plan path for the NEW `orca/agent/` runtime. Routes model cognition through `CognitiveRole.TOOL_REASONER` via Model Society; produces schema-validated `AgentPlan`; never authorizes. |
| `orca.brain.agent.AgentLoop._plan()` | **LEGACY_COMPATIBILITY** | The pre-existing, still-live production planner for `/api/chat`/`/api/stream`'s tool-use path. NOT migrated to be an adapter over `AgentPlanner` this phase (see §5's option B, chosen deliberately -- see `AGENT_PLANNER.md`'s "AgentLoop migration decision" for why option A was rejected). Its own `route_tool_reasoning_via_society` opt-in (Phase 8) is unchanged and orthogonal. |
| `OrcaUltra` planning (`_decompose`/`_execute`/`_synthesize`/`_grade`) | **ULTRA_LEGACY** | Unchanged since Phase 7/8 -- one `Brain` per pipeline run, explicitly out of scope for redesign (spec §19 from Phase 8, reaffirmed by Phase 8.1's own "do not grant new Ultra capabilities"). |
| `CognitiveKernel` operation planning (`self.plan(request)`) | **NON_AUTHORITATIVE for Agent Runtime** | A completely different concern -- deterministic Kernel request classification (intent/complexity/risk), not agent task/action planning. Never touches `orca.agent` at all (confirmed by Phase 8's own fast-path proof test). |
| `orca.deliberation.compiler.compile_reasoning_plan()` (`ReasoningPlan`) | **NON_AUTHORITATIVE for Agent Runtime** | Deliberation Fabric's own reasoning-mode compiler (Phase 6) -- a `ReasoningPlan` is an OPTIONAL INPUT `AgentPlanner.compile_plan()` may consult (spec §3's input list), never itself an `AgentPlan`. |
| `orca.society.society_plan.build_court_society_plan()` (`SocietyPlan`) | **NON_AUTHORITATIVE for Agent Runtime** | Court's own Constructor/Falsifier role assignment -- a different plan concept entirely, consulted by `AgentPlanner` only when it requests a Court review (spec §19-21), never conflated with an `AgentPlan`. |
| Manual/static `AgentPlan(...)` construction (all of Phase 8's own tests) | **TEST_ONLY** | `tests/test_agent_runtime.py`/`test_agent_delegation.py`/`test_agent_security.py`/`orca.agent.eval_harness` all construct `AgentPlan` directly, bypassing `AgentPlanner` -- correct and necessary for testing `AgentRuntime.execute()` in isolation from planning concerns. Continues to be a legitimate, supported way to drive `AgentRuntime` directly with a caller-supplied plan (spec §3 lists this as the standing "CALLER_SUPPLIED_PLAN" category, not a bypass). |
| Direct model-tool call inside `AgentLoop._execute_tools()` | **LEGACY_COMPATIBILITY (unauthorized, disclosed since Phase 8's own audit)** | Unchanged -- `AgentLoop` still calls `self.tools.call()` directly with no capability/policy layer. Explicitly NOT migrated to `orca.agent`'s Capability/Policy Engine this phase (would require redesigning `AgentLoop` itself, forbidden by "prefer minimal disruption to existing working behavior"). Disclosed as a standing gap in `RUNTIME_INTEGRATIONS.md`. |

## Required final value

**`UNEXPECTED_PLANNING_BYPASS = 0`** for AgentRuntime-authoritative
production paths. `AgentPlanner.compile_plan()` is the ONLY path that
produces an `AgentPlan` destined for `AgentRuntime.execute()` via a model
call; every other model-touching planner (`AgentLoop._plan()`, Ultra) is
either explicitly `LEGACY_COMPATIBILITY`/`ULTRA_LEGACY` (a different,
disclosed, unmigrated system) or `NON_AUTHORITATIVE` for the Agent Runtime
specifically (a different plan concept for a different subsystem). No
call site was found that silently bypasses `AgentPlanner` while claiming
to feed the Agent Runtime.
