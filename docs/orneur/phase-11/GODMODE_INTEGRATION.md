# Phase 11 — Godmode Integration

## Two disciplines, both enforced structurally

1. **Simulation never consumes a one-use lease.**
   `chamber.py::_check_lease_compatibility()` calls the READ-ONLY
   `orca.godmode.resolution.resolve_lease()` — never
   `resolve_and_consume_lease()`. Verified directly:
   `tests/test_simulation_e2e.py`'s Godmode end-to-end test confirms
   `uses_remaining == 1` (unchanged) immediately after a successful
   simulation.

2. **The lease is revalidated AND consumed only immediately before real
   execution.** `orca/simulation/godmode_integration.py::revalidate_and_consume_before_execution()`
   is the ONE call site that actually spends a use — it calls
   `resolve_and_consume_lease()` fresh, so a lease revoked, expired,
   exhausted, or blocked by an activated kill switch AFTER simulation
   but BEFORE this call is denied here, regardless of what the
   (never-consuming) simulation found. Verified:
   `test_lease_revoked_between_simulation_and_execution_denies`,
   `test_kill_switch_activated_after_simulation_pass_denies_execution`.

## Which `CapabilityDomain` for which path

- `CapabilityDomain.AGENT` naming a `Capability` enum value (e.g.
  `"FILE_WRITE"`, `"PROCESS_EXECUTION"`) — the lease AgentRuntime's
  GENERIC elevation path (`orca.godmode.capability.compute_effective_capabilities()`)
  actually resolves. This is the lease type to use when the elevated
  action executes through `AgentRuntime` itself.
- `CapabilityDomain.FILE`/`CapabilityDomain.CONNECTOR` — leases for the
  DEDICATED `orca.godmode.file_elevation.elevated_write_file()` /
  `orca.godmode.connector_elevation.evaluate_connector_policy_with_elevation()`
  paths, used when a tool implementation calls those functions directly,
  bypassing the generic Capability Engine.

`SimulationRequest.capability_domain` (explicit, default `"FILE"`) tells
the Chamber's compatibility check which of these applies — never
inferred from the tool id's spelling (a real gap found and fixed this
phase; see SIMULATION_CONTRACTS.md).

## Staleness (spec §49-51)

`check_simulation_staleness()` compares a resource's `StateFingerprint`
captured at simulation time against its current state right before
execution. Fingerprinting-unavailable resources (most connector types)
are honestly reported as undeterminable — never silently assumed fresh.
Verified with a real file: unchanged content -> not stale; changed
content -> stale, with both hash values shown.
