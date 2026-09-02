# WorldState — Made Operational (Phase 7 spec §28-30)

Phase 6 introduced the `WorldState` contract with no populator/consumer.
Phase 7 adds both, through bounded typed operations only.

## Typed operations (spec §30) — `orca/deliberation/worldstate_ops.py`

`ADD_FACT`, `SUPERSEDE_FACT`, `ADD_OBSERVATION`, `INVALIDATE_ASSUMPTION`,
`UPDATE_ENTITY_STATE`. `apply_update()` is the ONLY function that mutates a
`WorldState` in this codebase -- there is no code path where arbitrary
model text writes to `WorldState` fields directly.

## Provenance is required, not optional (spec §29)

Every `WorldStateUpdate` requires a non-empty `source_ref`
(`MissingProvenanceError` is raised otherwise) -- checked structurally in
`tests/test_deliberation_worldstate_replanning.py::test_add_fact_requires_provenance`.
`known_facts` entries embed their source inline (`"<fact> [source=<ref>]"`)
so provenance survives even a plain string read, and `update_log` records
every operation as a short label (`"ADD_FACT:evidence:ev-1"`) -- never raw
reasoning prose.

## Population (spec §28) — `orca/deliberation/worldstate_build.py`

`build_world_state(objective, truth_result=None, hypotheses=None)` builds
a fresh, REQUEST-SCOPED `WorldState` (a new `world_state_id` every call --
`tests/test_deliberation_worldstate_replanning.py::test_build_world_state_is_request_scoped_not_global`
proves this directly) from:
- Truth Fabric's own supported claims (`TruthResult.claims` +
  `claim_supports`), each tagged with its evidence id as `source_ref`.
- The active `HypothesisSet`, one `UPDATE_ENTITY_STATE` op per hypothesis.

**Not built**: a WorkingMemory/SemanticMemory-sourced population path.
Memory integration into WorldState is deliberately NOT added this phase --
see `PHASE_7_CLOSURE.md`'s honest scope notes. `CognitiveCourt.run()`
calls `build_world_state()` unconditionally and attaches the result to
`CourtCase.world_state` for every Court invocation (spec §28: "where
complex deliberation requires it" -- Court invocations are, by
construction, the complex-deliberation case).

## No persistent global world model (spec §28)

Nothing in this codebase stores a `WorldState` across requests. Each
`CognitiveCourt.run()` call creates one, uses it, and discards it when the
call returns.
