# Phase 11 — WorldState Projection

`orca/simulation/worldstate_projection.py::project_worldstate()`.

## Guarantee

The parent `WorldState` is `copy.deepcopy()`-ed before any
`WorldStateUpdate` is applied — the SAME real, typed
`orca.deliberation.worldstate_ops.apply_update()` machinery Phase 7
built, applied to the COPY only. The function signature never returns a
reference to the caller's original object; `WorldStateProjection` is a
distinct dataclass wrapping the projected copy alongside
`parent_world_state_id`, `source_action_id`, and `assumption_ids` (spec
§33).

Verified directly: `parent.known_facts`/`parent.world_state_id` are
provably unchanged after `project_worldstate()` runs, and the returned
projection's `world_state_id` is a distinct, freshly-generated ID.

## Visual distinction, not just structural

Every projected fact is prefixed `"SIMULATED:"` (e.g.
`"SIMULATED:UPDATE:customer/123->verified [source=simulation:act-1:peffect-...]"`)
so a projected `WorldState`'s `known_facts` list can never be visually
mistaken for a real observation's, even if a caller mishandles
provenance downstream — belt-and-suspenders on top of the `Provenance`
enum tag already carried on each `PredictedEffect`.

## Never mutates the live WorldState

There is no code path in `orca/simulation/` that calls `apply_update()`
against a live, in-flight `AgentRuntime` `WorldState` — projection is
always a separate, throwaway artifact consulted for decision-making
(the `SimulationResult`/`PredictedEffect` list), never written back into
the real world state until a genuine post-execution `Observation`
arrives (spec §6, §15).
