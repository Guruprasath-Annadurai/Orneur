# Model Society (Phase 7)

## Core principle (spec §2)

Model identity is not cognitive role. Model size is not cognitive role. A
`RoutingRequest` names a `CognitiveRole` (what work is needed); `route()`
resolves that to an actual eligible checkpoint using evidence-backed
`ModelCapabilityProfile` data. No caller ever asks for `"nano"` or
`"ultra"` directly in the Society-routed path -- `orca.society.router`
translates the selected `model_id` back to the legacy tier string only at
the very last step, for the actual `gateway_json_call` (see
`model_id_to_tier()`), because that call still speaks the pre-existing
tier vocabulary (a disclosed, unmigrated boundary -- see
`CURRENT_MODEL_ROUTING.md`).

## Two-phase routing (spec §12-13)

1. **Hard filters** (`orca/society/router.py::_build_candidate`): lifecycle
   disqualification, entitlement, artifact availability
   (`CheckpointRecord.is_routable()`), context-window sufficiency,
   caller-side exclusion, and best-effort deployment health/circuit state.
   A candidate that fails ANY of these is dropped before scoring ever
   runs -- no score can resurrect it.
2. **Soft ranking** (`_score`): role suitability (evidence-backed capability
   score), safety status, calibration, lifecycle maturity, cost preference
   -- explicit weights (`W_ROLE_SUITABILITY=0.50`, `W_SAFETY=0.20`,
   `W_CALIBRATION=0.15`, `W_LIFECYCLE_MATURITY=0.10`, `W_COST=0.05`),
   applied only to survivors of step 1.

Not a trained neural router (spec §14 explicitly forbids fabricating one)
-- every weight and rule above is Python, readable, and directly tested.

## Current reality: very little real differentiation evidence exists yet

With only two profiled families (Genesis-legacy, Novus) and neither in
formal `PRODUCTION`, most routing decisions today are decided by hard
filters (lifecycle/entitlement) rather than close scoring competitions.
Where BOTH families are eligible (EVALUATION-priority requests with
`allow_experimental=True`), Novus's real measured `VERIFIER` capability
(72.8% accuracy, evaluation_id=`novus-combined-v2-full-eval`) correctly
outranks Genesis's `UNMEASURED` score of 0.0 for that role -- proof the
evidence-weighting mechanism works, not proof of a rich multi-model
society (there isn't one yet). This is disclosed honestly, not inflated.

## Same-model role overlap (spec §18)

`orca.society.society_plan.build_court_society_plan()` does NOT exclude
Constructor's selected model from Falsifier's candidate pool -- forcing
cosmetic diversity is explicitly forbidden. In production (Novus
disallowed), Constructor and Falsifier both resolve to Genesis-legacy, and
`SocietyPlan.same_model_role_overlap=True` reports this honestly
(`tests/test_society_plan_disagreement_escalation.py::test_same_model_role_overlap_is_explicit_when_only_one_eligible_model_exists`).
No independent-model-intelligence claim is made anywhere in this phase's
code or docs.
