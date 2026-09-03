# Agent Delegation (Phase 8 spec §30-34)

`orca.agent.delegation.build_child_runtime()`/`run_delegation()`.

## The required invariant (spec §31), enforced structurally

```
child_capabilities ⊆ parent_capabilities
child_budget      <= parent delegated budget (per dimension)
child_scope       <= parent scope
```

`build_child_runtime()` raises (never clamps silently) if a
`DelegationRequest` asks for more than the parent has:
`CapabilityEscalationError` (capability superset attempt),
`BudgetEscalationError` (a requested dimension amount exceeds the
parent's REMAINING capacity in that dimension), `DelegationDepthExceededError`
(`depth > MAX_DELEGATION_DEPTH = 3`), `DelegationFanoutExceededError`
(`active_subagent_count >= MAX_CONCURRENT_SUBAGENTS = 4`). All four
property-tested directly in `tests/test_agent_delegation.py`.

## Budget flows from the parent, never independently (spec §47)

`run_delegation()` consumes exactly 1 unit of the PARENT's `AGENT_CALLS`
dimension for the delegation itself (via
`orca.cognitive.budget.consume`, the same shared authority every other
Phase 7/7.1/7.2 budget consumer uses) -- a second delegation attempt once
the parent's `AGENT_CALLS` is exhausted returns `AgentRunStatus.BLOCKED`,
never silently proceeds.

## Subagent result is never automatically trusted (spec §34)

`DelegationResult.trusted` starts `False` unless the caller explicitly
opts out of schema validation (`require_schema_validation=False`) AND the
child run actually `COMPLETED` -- a caller handling a higher-risk
delegation is expected to apply its own schema validation/Truth
verification/Court review on top before treating `DelegationResult.result`
as trusted, matching spec §34's explicit instruction.

## Depth and fanout are conservative starting bounds (spec §32-33)

`MAX_DELEGATION_DEPTH = 3` and `MAX_CONCURRENT_SUBAGENTS = 4` are the
Phase 8 starting values -- no agent->agent->agent recursion beyond depth
3, no unrestricted swarm. `active_subagent_count` is caller-tracked and
passed in explicitly (this module does not itself maintain a global
counter across concurrent runtimes -- that bookkeeping belongs to whatever
orchestrates multiple `AgentRuntime` instances, a disclosed scope
boundary matching "start conservatively").
