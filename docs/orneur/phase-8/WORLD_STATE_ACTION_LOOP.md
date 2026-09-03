# WorldState Action Loop (Phase 8 spec §20-23)

## Before action: consult WorldState

`AgentRuntime.execute()` builds (or accepts a caller-provided) `WorldState`
before the action loop starts. `orca.deliberation.worldstate_ops.unavailable_model_ids()`
(unchanged from Phase 7.1) demonstrates the exact "consult WorldState
before acting" pattern this phase reuses conceptually for tool-level
decisions (see `orca.agent.eval_harness`'s scenario 20).

## After action: typed Observation -> WorldState.apply

`AgentRuntime._to_observation()` converts every `ToolResult` into a typed
`Observation` (never a bare string): `action_id`, `source` (the tool_id),
`facts`, `status` (`OK`/`ERROR`/`DEDUPED`), `evidence_refs`, `error`,
`trust_class`, `world_state_changes`. `_apply_observation()` is the ONLY
function that mutates WorldState from an agent action, and it goes
through the SAME typed `WorldStateOp.ADD_OBSERVATION` operation Phase 7.1
introduced (`orca.deliberation.worldstate_ops.apply_update`) -- every fact
carries `source_ref=f"tool:{tool_id}:{action_id}"`, never asserted without
provenance (spec §22).

## Observation trust classes (spec §23)

`ObservationTrustClass`: `SYSTEM_VERIFIED` (filesystem/subprocess results
-- what every current tool in `orca.agent.tool_registry` produces),
`EXTERNAL_API` (HTTP/search responses), `USER_STATEMENT`,
`MODEL_INTERPRETATION`. All four are distinguished explicitly and never
collapsed -- `Observation.trust_class` is set per-source, not defaulted
silently for external/model-derived facts.

## Model text cannot directly mutate WorldState (spec §22)

There is no code path where a model's raw output string is written into
`WorldState.known_facts`/`variables` directly -- only
`orca.deliberation.worldstate_ops.apply_update()`, called from
`AgentRuntime._apply_observation()` with a tool-derived `Observation`,
ever touches WorldState from the Agent Runtime. `MissingProvenanceError`
(Phase 7.1, unchanged) still guards every write.

## Decision-changing observation (spec §60's required scenario)

`orca.agent.eval_harness.run_all()`'s scenario 20 reuses Phase 7.1's own
proven WorldState-driven-routing-decision mechanism directly
(`unavailable_model_ids`) -- Phase 8 does not duplicate that
demonstration, it composes with it.
