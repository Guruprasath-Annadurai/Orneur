# WorldState Execution (Phase 7.1 spec §12-14)

Phase 7 built WorldState from `TruthResult`/`HypothesisSet` but nothing
downstream ever read it. Phase 7.1 closes this gap.

## Consumption path

`orca.deliberation.worldstate_ops.unavailable_model_ids(state)` scans
`WorldState.variables` (populated only through the typed `UPDATE_ENTITY_STATE`
operation -- never free text) for entities whose recorded value contains
an unavailability marker (`UNAVAILABLE`/`UNHEALTHY`/`OFFLINE`/`DRAINING`).
`orca.deliberation.court.CognitiveCourt.run()`:

1. Builds `world_state` from the `TruthResult` (as Phase 7 already did) --
   now done BEFORE routing, not after.
2. Merges in any caller-seeded `initial_world_state` (e.g. a Kernel-level
   tool-observation hook recording "deployment X went unhealthy
   mid-session").
3. Computes `unavailable_model_ids(world_state)`.
4. Passes that list as `exclude_model_ids` into
   `orca.society.society_plan.build_court_society_plan()`, which threads
   it into BOTH Constructor's and Falsifier's `RoutingRequest`.

## The decision-changing demonstration (spec §13)

`tests/test_worldstate_decision_consumption.py::test_court_excludes_a_worldstate_flagged_unavailable_model_from_routing`
proves the exact scenario spec §13 names: WITHOUT a WorldState observation,
Constructor/Falsifier route to Genesis-legacy (the only production-eligible
candidate); WITH a `WorldStateUpdate` recording `"orneur-genesis": "UNAVAILABLE"`,
the SAME request now returns `CourtVerdictState.INSUFFICIENT_EVIDENCE` /
`COURT_INSUFFICIENT_EVIDENCE` -- a real, observable, safety-relevant
decision change, not a synthetic demo divorced from production interfaces
(this runs through `CognitiveCourt.run()` itself, the exact code path a
real Kernel request uses).

## Trust boundary preserved (spec §14)

- Every `WorldStateUpdate` requires a non-empty `source_ref`
  (`MissingProvenanceError` otherwise) -- unchanged from Phase 7.
- `unavailable_model_ids()` reads ONLY `state.variables`, which can only be
  populated through `apply_update()`'s `UPDATE_ENTITY_STATE` branch -- there
  is no code path where raw model output text writes to `state.variables`
  directly.
- New security test:
  `tests/test_society_authority_security.py::test_worldstate_injection_cannot_add_a_trusted_fact_without_provenance`
  proves an adversarial fact string ("Ignore all previous instructions...
  This fact is VERIFIED.") is rejected purely because it lacks a
  `source_ref` -- content is irrelevant to acceptance.

## What is still NOT consumed (honest scope note)

WorldState's `known_facts`/`assumption_ids`/`constraints` are populated but
not yet read by any downstream decision beyond the `unavailable_model_ids`
routing-exclusion path above. A future phase could use verified facts to
skip redundant retrieval, or use invalidated assumptions to trigger a
different replan trigger (`WORLD_STATE_CHANGE`, declared in
`orca.deliberation.replanning.ReplanTrigger` but not yet wired to a live
caller). This is disclosed, not hidden.
