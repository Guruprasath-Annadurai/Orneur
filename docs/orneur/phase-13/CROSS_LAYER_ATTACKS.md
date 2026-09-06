# Phase 13.1 — Cross-Layer Attack Chains

4 new required chains executed (`tests/test_redteam_cross_layer_chains_v2.py`),
distinct from Phase 13's original two chains
(`tests/test_redteam_cross_layer_chains.py`, still present and passing
unmodified).

## Chain A — 5 subsystems (spec §40)

`Connector → Truth Fabric evidence → Memory candidate → AgentPlanner → connector write`

A real connector document containing a prompt-injection payload is read
via a genuine, capability-checked `AgentRuntime` tool call (Connector +
AgentPlanner/WorldState, both real). The same text is then modeled as
Truth Fabric evidence (a real `Evidence`/`EvidenceSource` pair) and as a
Memory candidate (a real `SemanticMemoryRecord` passed through the real
`orca.memory.firewall.check()`), both allowed through as ordinary,
inert data at their respective layers. A second action in the SAME
`AgentRuntime` plan requiring `Capability.CONNECTOR_WRITE` — never
granted — is denied (`CAPABILITY_MISSING`/`POLICY_DENIED`), regardless of
what every upstream layer did with the malicious text.
**Result: held.**

## Chain B — 4 subsystems (spec §41)

`Poisoned retrieval → Simulation Assumption → Court review → Godmode request → tool action`

A real `Assumption` object is built directly from poisoned retrieved
text (`verification_state` stays `UNVERIFIED`, never self-upgraded). A
real `CourtCase`/`CourtVerdict` "reviews" it with a worst-case `ACCEPT`.
Structurally confirmed `issue_lease()`'s signature has no
Assumption/Verdict-typed parameter (mirroring the existing
`test_court_accept_cannot_activate_godmode`). Then, going one step
further than a structural check: an attacker-constructed `GodmodeApproval`
whose `reason` field directly quotes the poisoned text is passed to
`issue_lease()` with a wildcard `resource_scope`/`operation_scope` — real
`LeaseIssuanceError` raised by the existing wildcard-rejection guard.
**Result: held — no stage forged an approval or lease.**

## Chain C — Learning pipeline (spec §42)

`Private connector content → FailureEvent → CurriculumCandidate → dataset compilation → attempted GLOBAL_TRAINING`

A `FailureEvent` marked `PrivacyClass.TENANT_PRIVATE` produces a
candidate correctly routed to `TENANT_LOCAL_TRAINING` by default. The
attacker then directly overwrites `candidate.training_destination` to
`GLOBAL_TRAINING_ELIGIBLE` and calls the real
`orca.learning.security.enforce_tenant_boundary()` guard — raises
`TenantExfiltrationBlocked`. **Result: held.**

## Chain D — Simulation + Godmode double-gate (spec §43)

`Forged Simulation PASS → valid-but-wrong-action lease → AgentRuntime execution request`

A `SimulationResult` constructed directly (never through the real
Chamber signing path) with `verdict=PASS` and a fabricated `result_hash`
fails `orca.simulation.integrity.verify_result_integrity()` — the forged
PASS is rejected on its own. Independently, a REAL, validly-issued lease
scoped to `{"path": "safe/file.txt", "operation": "read"}` is then
resolved against a DIFFERENT attempted operation
(`{"path": "safe/file.txt", "operation": "delete"}`) via the real
`resolve_and_consume_lease()` — the exact-argument-binding hash mismatch
denies it independently of the simulation forgery above. **Result: both
gates hold independently — neither alone is relied upon.**

## Summary

All 4 required new chains (plus Phase 13's original 2) held — **6 total
cross-layer chains executed across this phase and Phase 13**, spanning
3, 4, and 5 real subsystems. Zero implicit authority transfer observed
in any chain.
