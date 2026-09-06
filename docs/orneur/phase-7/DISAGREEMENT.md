# Disagreement as Signal (Phase 7 spec §19-20)

`orca.society.disagreement.compute_disagreement(TwinResult) -> DisagreementSignal`.
Derived ENTIRELY from `TwinResult`'s own structured fields
(`disputed_claim_ids`, `unsupported_assumption_ids`, `counter_evidence_ids`)
-- never by scanning claim/objection TEXT.

## Bounded categories (spec §20)

`CLAIM_CONFLICT`, `ASSUMPTION_CONFLICT`, `EVIDENCE_INTERPRETATION_CONFLICT`,
`CAUSAL_CONFLICT`, `TEMPORAL_CONFLICT`, `RISK_CONFLICT`,
`NO_MEANINGFUL_DISAGREEMENT`. This phase's `compute_disagreement()`
populates `CLAIM_CONFLICT`, `ASSUMPTION_CONFLICT`, and
`EVIDENCE_INTERPRETATION_CONFLICT` from real Twin output;
`CAUSAL_CONFLICT`/`TEMPORAL_CONFLICT`/`RISK_CONFLICT` are declared in the
enum for future Causal Graph / multi-role disagreement work but have no
current producer -- honestly undriven, not fabricated.

## Never majority vote

`DisagreementSignal` carries no vote-count, winner, or consensus field at
all -- checked structurally
(`tests/test_society_plan_disagreement_escalation.py::test_disagreement_never_resolved_by_majority_vote`).
Disagreement is a SIGNAL consumed by `orca.society.escalation`, never
resolved by counting.

## Severity → escalation

`NONE` (no disagreement) / `LOW` (single conflict type) / `MODERATE`
(multiple types) / `HIGH` (disputed claims AND confirmed counter-evidence).
`orca.society.escalation.decide_escalation()` only escalates model tier on
`MODERATE`/`HIGH` -- a `LOW`-severity single disputed claim is already
handled by Court's own deterministic `REVISE` verdict and the Phase 7
bounded replan loop (`orca.deliberation.replanning`), not by an additional
Society-level tier escalation. This is a real design choice, not an
oversight: escalating model tier for every single disagreement would
violate spec §21's "do not escalate merely because [a minor signal]
exists."
