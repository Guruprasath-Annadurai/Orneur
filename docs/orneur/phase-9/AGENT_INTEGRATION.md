# Phase 9 — Agent Runtime Integration

## Tool visibility (spec §39)

`orca.connectors.agent_bridge.authorized_connector_tool_specs(registry, identity)`
returns `ToolSpec` entries ONLY for connector instances that are (a)
visible to the requesting tenant (`registry.list_for_tenant()`) AND (b)
currently healthy/routable (`registry.is_routable()`). An unhealthy or
other-tenant connector never appears in the returned dict at all -- not
merely denied at execution time. Verified directly in
`tests/test_connector_agent_bridge.py` with a two-tenant registry.

## ToolSpec derivation

`connector_tool_spec()` derives `SideEffectClass`/`Capability` from the
connector instance's OWN `structurally_rejects_write()` -- never from the
tool's name or description. A read-only connector always gets
`SideEffectClass.READ_ONLY` + `Capability.CONNECTOR_READ`; anything else
gets `SideEffectClass.EXTERNAL_SIDE_EFFECT` + `Capability.CONNECTOR_WRITE`.

## Two new capabilities

`orca.agent.contracts.Capability` gained `CONNECTOR_READ` and
`CONNECTOR_WRITE` (Phase 9) -- gating connector tool use at the
Capability Engine layer, on TOP OF (never instead of)
`orca.connectors.policy`'s own independent checks.

## Defense-in-depth callable

`make_connector_read_fn()` returns a plain callable for
`AgentToolRegistry.register()` that RE-RUNS `evaluate_connector_policy()`
and `registry.is_routable()` INSIDE the callable, even though
`AgentRuntime._authorize()` already ran `orca.agent.policy.evaluate_policy()`
before this callable was ever invoked. Proven: an identity that somehow
bypassed the outer check (constructed directly, bypassing AgentRuntime)
is still rejected with `TenantIsolationError` when the callable itself
runs (`tests/test_connector_agent_bridge.py::test_make_connector_read_fn_rechecks_tenant_even_if_caller_bypassed_earlier_checks`).

## Full end-to-end verification

`tests/test_connector_agent_runtime_e2e.py` runs the REAL chain:
`AgentGoal -> AgentPlan -> AgentRuntime -> Capability -> Policy ->
connector adapter -> real DocStore -> Observation -> WorldState`,
confirming `AgentRunStatus.COMPLETED` with the retrieved fact present in
`world_state.known_facts`; a capability-denied variant confirms the run
never completes without `Capability.CONNECTOR_READ` granted; and a
cancellation variant confirms `execute_async()` returns a structured
`AgentRunStatus.CANCELLED` (never raises) when cancelled mid-connector-read.
