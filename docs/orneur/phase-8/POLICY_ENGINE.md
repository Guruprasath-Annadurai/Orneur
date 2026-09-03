# Policy Engine (Phase 8 spec §12)

`orca.agent.policy.evaluate_policy()` -- fully deterministic, no model
call, the ONLY function in this codebase that may produce an
authorization-relevant `PolicyDecision`.

## Decision order

1. Capability check must already have passed (`capability_decision.granted`)
   -- if not, `DENY` immediately with the missing-capability reason.
2. If the resolved side-effect class differs from the tool's declared
   class, note the escalation and evaluate under the RESOLVED (actual,
   riskier) class from here on (spec §40).
3. `DESTRUCTIVE` actions ALWAYS require human approval
   (`_ALWAYS_REQUIRE_APPROVAL`), regardless of goal/capabilities --
   nothing can pre-approve a destructive action (spec §28-29).
4. If the effective side-effect class isn't in the goal's
   `allowed_action_classes`: `IRREVERSIBLE_WRITE`/`EXTERNAL_SIDE_EFFECT`
   degrade to `REQUIRE_APPROVAL` (a human can still choose to allow it);
   everything else is a hard `DENY`.
5. If the tool's `risk_class` is `HIGH`/`CRITICAL` but the goal's own
   declared `risk` isn't, `REQUIRE_APPROVAL`.
6. Otherwise `ALLOW`.

## Never asks a model (spec §12's explicit instruction)

`evaluate_policy()` takes only typed, already-computed inputs
(`AgentGoal`, `ToolSpec`, `CapabilityDecision`, an optional resolved
`SideEffectClass`) -- there is no LLM call, no prompt, anywhere in this
function or its call path. `PolicyDecisionState` is a 4-value bounded enum
(`ALLOW/DENY/REQUIRE_APPROVAL/ALLOW_WITH_RESTRICTIONS`) matching spec
§12's exact vocabulary.

## Approval cannot be forged (spec §28-29, §40)

- Court ACCEPT, Society routing output, and Memory recall are never
  consulted by `evaluate_policy()` at all -- there is no import of
  `orca.deliberation`/`orca.society`/`orca.memory` in `orca/agent/policy.py`.
- `ActionAuthorization` is constructed in exactly one place
  (`AgentRuntime._authorize()`), tested directly
  (`tests/test_agent_secret_and_trace_security.py::test_action_authorization_cannot_be_constructed_as_pre_approved_by_a_tool`).
- A model's own output text has no field to populate that would ever be
  read as authorization (`ActionRequest` carries no `authorized`/
  `approved` field, checked structurally).
