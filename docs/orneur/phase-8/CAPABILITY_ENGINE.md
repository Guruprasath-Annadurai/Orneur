# Capability Engine (Phase 8 spec §10-11)

Nine capabilities (`orca.agent.contracts.Capability`): `FILE_READ`,
`FILE_WRITE`, `NETWORK_READ`, `NETWORK_WRITE`, `TOOL_EXECUTION`,
`SUBAGENT_DELEGATION`, `SECRET_USE`, `EXTERNAL_MESSAGE`,
`PROCESS_EXECUTION`. No Godmode/wildcard capability exists.

## Capability is necessary, not sufficient (spec §11)

`check_capabilities()` (`orca/agent/capability.py`) is a pure set-membership
check -- `granted ⊇ tool_spec.required_capabilities`. Having `FILE_WRITE`
does not authorize "write anywhere": `orca.agent.policy.evaluate_policy()`
runs AFTER the capability check and separately evaluates the goal's
`allowed_action_classes`, the tool's `risk_class` against the goal's
declared `risk`, and (spec §40) the resolved side-effect class -- proven
directly:
`tests/test_agent_security.py::test_capability_check_cannot_be_bypassed_by_a_higher_policy_score`.

## No escalation path

A capability set is fixed for the lifetime of an `AgentRuntime` instance
-- nothing in `orca/agent/` ever adds to `self.capabilities` after
construction. Delegation (spec §31) enforces
`child_capabilities ⊆ parent_capabilities` at construction time in
`orca.agent.delegation.build_child_runtime()`, raising
`CapabilityEscalationError` rather than clamping silently.
