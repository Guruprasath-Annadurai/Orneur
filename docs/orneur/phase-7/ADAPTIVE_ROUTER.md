# Adaptive Router (Phase 7 spec §11-16)

Deterministic, evidence-weighted -- not a trained neural router (spec §14
explicitly forbids fabricating one). See `MODEL_SOCIETY.md` for the
two-phase hard-filter/scoring design.

## Explicit scoring weights (`orca/society/router.py`)

```
W_ROLE_SUITABILITY = 0.50
W_SAFETY            = 0.20
W_CALIBRATION        = 0.15
W_LIFECYCLE_MATURITY = 0.10
W_COST               = 0.05
```

Sum to 1.0. Each is a plain Python constant, directly readable and
directly tested (`tests/test_society_router.py::test_evidence_evaluated_capability_wins_over_unmeasured`).

## Structured routing reasons (spec §16)

`RoutingReason` enum: `SELECTED`, `NOVUS_REJECTED_LIFECYCLE`,
`AETERNUM_ABSENT`, `LEGACY_GENESIS_SELECTED_FOR_FAST_ROLE`,
`CONTEXT_REQUIREMENT_UNMET`, `ENTITLEMENT_LIMIT`, `LOW_LATENCY_PREFERENCE`,
`VERIFICATION_QUALITY_PREFERRED`, `ARTIFACT_UNAVAILABLE`,
`DEPLOYMENT_UNHEALTHY`, `CIRCUIT_OPEN`, `LIFECYCLE_DISQUALIFIED`,
`EXCLUDED_BY_CALLER`, `NO_ELIGIBLE_CANDIDATE`, `ROLE_UNSUPPORTED`,
`COST_PREFERRED_SUFFICIENT_CANDIDATE` -- every `RoutingDecision` records
these for every rejected candidate, never a free-form justification.

## A disclosed, real gap: deployment-health enforcement is best-effort

`_deployment_health_ok()` only enforces `ModelDeployment.is_routable()` +
health when a deployment RECORD exists for that `model_id`. No deployment
records exist today for the legacy tier-based Ollama serving path (see
`CURRENT_MODEL_ROUTING.md`) -- so this check is a no-op for the common
case today. During Phase 7 development, a stray `ModelDeployment` record
left behind by `tests/test_gateway_*.py` (which do not isolate `ORCA_HOME`
for deployment records -- a pre-existing test-hygiene gap, not introduced
this phase) caused Novus to be transiently, spuriously rejected via
`DEPLOYMENT_UNHEALTHY` during this phase's own development. This is
flagged as a follow-on task (see "Remaining Phase-7 blockers" in
`PHASE_7_CLOSURE.md`), not fixed here since it is outside Model Society's
own code.

## Performance

`bench_routing_decision()` (100 reps, deterministic): see
`PHASE_7_CLOSURE.md`'s PERFORMANCE section for the actual measured p50.
Routing does real file I/O (`CheckpointRecord.load`, `list_deployments`)
per call, so it is slower than Phase 6's pure-Python
`compile_reasoning_plan()` (0.007ms) -- an honest, measured, disclosed
difference, not hidden.
