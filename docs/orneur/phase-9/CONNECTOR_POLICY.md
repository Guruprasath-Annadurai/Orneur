# Phase 9 — Connector Policy Engine

`orca.connectors.policy.evaluate_connector_policy()` is fully
deterministic -- no model call -- mirroring `orca.agent.policy`'s own
discipline exactly. Checked in this fixed order:

1. **Tenant match** -- mismatch is DENY, unconditionally, never
   REQUIRE_APPROVAL (spec §7's critical invariant).
2. **Capability enabled** -- the requested `ConnectorCapabilityKind` must
   be in `instance.enabled_capabilities`, else DENY.
3. **Structural write rejection** -- a WRITE request against an instance
   where `structurally_rejects_write()` is True is DENY, regardless of
   what `enabled_capabilities` claims (defense in depth against a
   misconfigured instance record).
4. **Sensitivity gate** -- a WRITE or DELETE against SENSITIVE data
   always returns REQUIRE_APPROVAL, never bypassed by a permissive
   remote-provider scope (spec §42).
5. Otherwise ALLOW.

## Two independent policy layers for agent-driven connector use

When a connector is exposed to `AgentRuntime` via
`orca.connectors.agent_bridge`, TWO separate policy engines run on every
call: `orca.agent.policy.evaluate_policy()` (generic agent-runtime
authorization, checked by `AgentRuntime._authorize()` before the tool
function is even invoked) and `orca.connectors.policy.evaluate_connector_policy()`
(re-run INSIDE the tool callable itself, in
`agent_bridge.make_connector_read_fn()`). Neither is ever treated as
sufficient on its own -- proven directly in
`tests/test_connector_agent_bridge.py::test_make_connector_read_fn_rechecks_tenant_even_if_caller_bypassed_earlier_checks`.

## Cross-connector data flow

`orca.connectors.security.authorize_cross_connector_flow()` authorizes a
write to a DIFFERENT connector based ONLY on the destination connector's
own configured `destination_allows_sensitivity` set -- never on the
source content's text. This directly defeats the canonical "malicious
document instructs the agent to post confidential data to Slack channel
X" attack: the instruction text has zero effect on the authorization
decision (spec §46-47).
