# Model Society Evaluation (Phase 7 spec §58-61)

## Deterministic harness

`orca/society/eval_harness.py` -- run directly with
`.venv/bin/python -m orca.society.eval_harness`. No fabricated
model-quality gains (spec §58, §60's explicit caution against inventing
"broad capability ratings from 2 examples").

**Real result: 12/12 passed (1.000).**

| Scenario | Result |
|---|---|
| Simple fast request routes without error | PASS |
| Structured extraction role routes | PASS |
| Experimental Novus disallowed in production | PASS |
| Experimental Novus explicitly allowed in evaluation | PASS |
| Aeternum absent -- never a routing candidate | PASS |
| Legacy Genesis mapping selectable for fast roles | PASS |
| Entitlement-constrained request respects the constraint | PASS |
| Same-model Constructor/Falsifier disclosed honestly | PASS |
| Disagreement triggers escalation, not silent pass | PASS |
| Budget exhaustion stops optional work | PASS |
| Replan behavior produces a new bounded plan version | PASS |
| WorldState is request-scoped (fresh id per call) | PASS |

## Scenarios covered live, not duplicated here

Role fallback under a live model outage, unhealthy/open-circuit deployment
behavior, live role-injection during an actual call, and cancellation
through a live Court run all genuinely need either a live model call or
real Gateway state to measure -- covered instead by
`tests/test_gateway_model_gateway.py`, `tests/test_gateway_warmup_health.py`,
`tests/test_deliberation_security.py`/`tests/test_society_security.py`,
and `tests/test_deliberation_cancellation.py` respectively (see
`orca.society.eval_harness.HarnessResult.covered_elsewhere` for the exact
mapping, returned by the harness itself, not hand-maintained separately).

## A real, disclosed environment fragility found during this phase's own development

While developing and testing the router, real routing decisions
transiently flipped (Novus spuriously rejected as `DEPLOYMENT_UNHEALTHY`)
because `tests/test_gateway_*.py` write a real `ModelDeployment` record
into this machine's actual `~/.orca` without isolating `ORCA_HOME` --
a pre-existing test-hygiene gap in those files, not introduced this phase.
Fixed for Model Society's OWN test hermeticity by making
`orca.society.router.route()`'s checkpoint/deployment lookups injectable
(`tests/test_society_router.py` now passes fake lookups and remains
correct even when a stray real deployment record is present on disk --
verified directly). The underlying `test_gateway_*.py` non-isolation is
flagged as a follow-on task, not fixed in this phase (out of Model
Society's own code).

## Falsifier regression (spec §61)

`tests/test_twin_objection_kind_validation.py` is the versioned regression
case for Phase 6's finding (undocumented `objection_kind` value
"repetition"). It does not chase the one literal output -- it tests the
general schema-enforcement function (`_validate_objection_kind`) against
the full declared taxonomy, an empty string, the exact historical bad
value, and an adversarial injected string, so any future undocumented
value is caught the same way.

## Baseline comparison (spec §55's own caution carried forward)

There is no pre-Phase-7 "model routing quality" baseline to compare
against, because Model Society did not exist -- the honest comparison
point is Court's own end-to-end latency (see PERFORMANCE in
`PHASE_7_CLOSURE.md`), which shows no meaningful regression from adding
the Society routing layer (routing decision p50 ≈0.15ms against a
~18-second live Court round).
