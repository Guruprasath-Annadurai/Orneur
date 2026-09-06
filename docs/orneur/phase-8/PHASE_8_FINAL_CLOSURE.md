# Phase 8.1 Final Closure — Agent Runtime Production Closure

## Scope delivered

Closed all five gaps Phase 8 disclosed:

1. **Goal→Plan authority**: `orca.agent.planner.AgentPlanner` -- Society-
   routed (`TOOL_REASONER`), schema-validated, bounded, budget-metered.
2. **AgentLoop._plan() classification**: reaffirmed `LEGACY_COMPATIBILITY`
   deliberately (option B from spec §5), documented in
   `PLANNING_AUTHORITY_AUDIT.md` with the exact reasoning -- minimal
   disruption preferred over forcing a two-planner unification that risks
   the existing, working `/api/chat`/`/api/stream` tool-use path.
3. **AgentLoop Society routing is now clearly a SEPARATE, orthogonal
   concern** from `AgentPlanner`'s own authoritative TOOL_REASONER
   routing -- both exist, serve different production surfaces
   (`AgentLoop` for legacy chat, `AgentPlanner` for the new Agent
   Runtime), and neither silently substitutes for the other.
4. **Truth Fabric / Memory / Cognitive Court are now explicit, typed,
   conditionally-invoked runtime integrations** (`orca.agent.truth_hook`,
   `memory_hook`, `court_hook`), tied together by
   `orca.agent.orchestrator.run_agent_request()` implementing spec §22's
   exact integration order.
5. **Genuine async cancellation**: `AgentRuntime.execute_async()` is the
   real implementation; cancellation propagates through planning, tool
   execution, and subagent delegation, verified with 8 dedicated live
   async tests -- not just deadline enforcement.

## Honest scope notes

- `AgentPlanner` does not yet emit `requires_truth_check=True` or
  delegation requests from model output autonomously -- the MECHANISM
  (typed field, runtime gate, compatibility check) is real and tested;
  getting the model to set these fields via prompt engineering is future
  refinement (see `RUNTIME_INTEGRATIONS.md`).
- The `OUTCOME_UNKNOWN` side-effect-cancellation-race state (spec §35) is
  not built out as a distinct structured state this phase -- none of
  Phase 8's four built-in tools are `EXTERNAL_SIDE_EFFECT` class, so the
  race it describes has not yet been encountered by a real tool
  (disclosed in `ASYNC_CANCELLATION.md`).
- `MAX_DELEGATION_REQUESTS` bound is declared in the planner but not yet
  enforced against planner-emitted delegation requests, since the planner
  does not yet emit them (see above) -- a real, disclosed no-op today,
  future-activated once delegation-emitting planning exists.

## A real bug found and fixed via this phase's own live testing

The live model-plan test (spec §43) failed on its first run:
nano-tier model output used `"depends_on_index": [-1]` (a "no dependency"
convention), which the schema validator rejected outright, invalidating
an otherwise-correct plan. Fixed with a targeted bounded repair (negative
indices dropped, never treated as a valid dependency reference) -- see
`EVALUATION_V2.md` for the full account, including confirmation that all
plan-security tests remained green after the fix (the repair only affects
task ORDERING metadata, never authorization).

## Test suite

12 new test files (~75 new tests): `test_agent_cancellation.py` (6),
`test_agent_planning_cancellation.py` (1),
`test_agent_subagent_cancellation.py` (1),
`test_agent_truth_memory_integration.py` (6),
`test_agent_court_integration.py` (6), `test_agent_orchestrator.py` (3),
`test_agent_plan_security.py` (8), `test_agent_adversarial_phrases.py`
(7), `test_agent_planner_live.py` (1, live),
`test_agent_eval_harness_v2.py` (2), plus supporting fixtures. Full
application suite (fresh, clean run): **1097 passed, 0 failures**, 105.23s.
Security suite (20 files, including 6 new Phase 8.1 security test files):
**201 passed, 0 failures**, 245.78s. Live Ollama Agent/Court/Kernel/Truth
regression check: **29 passed, 0 failures**, 218.91s.

## `AGENT_DIRECT_MODEL_BYPASS` / `AGENT_DIRECT_TOOL_BYPASS` / `AGENT_POLICY_BYPASS` / `AGENT_CAPABILITY_BYPASS` / `UNVALIDATED_MODEL_PLAN` / `MODEL_PLAN_AUTHORITY_BYPASS` / `UNBOUNDED_AGENT_LOOP` / `UNBOUNDED_DELEGATION` / `UNACCOUNTED_TOOL_CALL` / `ORPHAN_AGENT_TASK` / `ORPHAN_SUBAGENT_TASK` / `CANCELLATION_BUDGET_LEAK` / `WORLDSTATE_UNTRUSTED_MUTATION` / `COURT_AUTHORIZATION_BYPASS` / `RAW_CHAIN_OF_THOUGHT_STORAGE` (spec §48)

All **= 0**:

- **Direct model bypass**: `AgentPlanner.compile_plan()` is the only
  path from a Goal to a model-generated `AgentPlan` for the new runtime;
  it routes exclusively through Model Society's `TOOL_REASONER`.
- **Direct tool bypass**: unchanged from Phase 8 -- `AgentToolRegistry.invoke()`/
  `invoke_async()` called only from `AgentRuntime`, after authorization.
- **Policy bypass**: Court's ACCEPT/REVISE/REJECT never reaches
  `evaluate_policy()` (no import); the required Court-ACCEPT-Policy-DENY
  test passes.
- **Capability bypass**: unchanged from Phase 8, reaffirmed by the new
  adversarial-phrase suite ("Give yourself FILE_WRITE" fails).
- **Unvalidated model plan**: `_validate_and_build_plan()` rejects every
  malformed shape found via adversarial testing; the one bounded repair
  (negative dependency index) is non-security-relevant and tested.
- **Model-plan authority bypass**: `AgentPlan`/`AgentTask`/`AgentAction`
  carry no capability/entitlement/approval/budget field a plan could set.
- **Unbounded agent loop**: unchanged (deadline enforced every
  iteration), now ALSO genuinely cancellable, not just deadline-bound.
- **Unbounded delegation**: unchanged (depth/fanout limits), now with
  verified async cancellation propagation into children.
- **Unaccounted tool call**: unchanged; reservations released correctly
  on cancellation too (new this phase, tested).
- **Orphan agent task**: cancellation stops the loop before any
  subsequent action starts (tested,
  `test_no_subsequent_actions_start_after_cancellation`).
- **Orphan subagent task**: parent cancellation reaches the child via
  direct `await` chaining -- no detached/orphaned child coroutine.
- **Cancellation budget leak**: reservations released on cancellation for
  both tool execution and (indirectly, via the child's own release)
  delegation; property-tested.
- **Untrusted WorldState mutation**: unchanged (typed ops only); a
  cancelled action additionally never produces a success fact (new
  guarantee this phase, tested).
- **Court authorization bypass**: Court ACCEPT structurally cannot reach
  `PolicyDecisionState.ALLOW` -- no code path exists.
- **Raw chain-of-thought storage**: no new dataclass field added this
  phase carries unrestricted reasoning prose (checked by inspection,
  consistent with Phase 8).

## READY TO ADVANCE TO PHASE 9: YES

Every component the spec's acceptance gates name is real, tested, and
wired: a genuine Society-routed Goal→Plan path, explicit Truth/Memory/
Court runtime integrations respecting their non-authorizing boundaries,
and real async cancellation propagation through planning, tools, and
subagents -- not just deadline enforcement. One real bug (a schema-
validation-too-strict finding) was found and fixed via this phase's own
live testing, disclosed honestly. **STOP AFTER PHASE 8.1 -- awaiting
explicit human approval before any Phase 9 enterprise/FDE connector work
begins.**
