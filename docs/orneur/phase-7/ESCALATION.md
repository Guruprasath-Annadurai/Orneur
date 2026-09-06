# Escalation Engine (Phase 7 spec §21-23)

`orca.society.escalation.decide_escalation()` -- resolves to a CAPABILITY
REQUIREMENT tier (`FAST` → `BALANCED` → `BALANCED_VERIFICATION` →
`DEEP_REASONING`), never a hardcoded model name (spec §22). If no eligible
model satisfies the resolved requirement, the caller's own routing call
will honestly return `NO_ELIGIBLE_CANDIDATE`/abstain -- Aeternum is never
fabricated to fill the gap
(`tests/test_society_security.py::test_escalation_target_is_never_a_hardcoded_future_model_name`).

## Escalation triggers (real structured signals only, spec §21)

`risk_level in (HIGH, CRITICAL)`, `critical_contradiction`,
`falsifier_objection_unresolved`, `calibration_inadequate`,
`evidence_insufficient`, `disagreement.severity in (MODERATE, HIGH)`.
Explicitly NOT triggered by answer length or any other non-signal
(`tests/test_society_plan_disagreement_escalation.py::test_escalation_never_triggers_merely_because_answer_is_long`).

## De-escalation (spec §23)

When `risk_level == LOW` and there is no meaningful disagreement, and the
current tier is above `FAST`, `decide_escalation()` recommends stepping
DOWN one tier -- preferring the cheapest sufficiently capable candidate
rather than defaulting to a stronger tier "just in case."

## `role_model_unavailable` → honest abstention

If the role's model is genuinely unavailable, `decide_escalation()`
returns `ABSTAIN_NO_CAPABLE_MODEL` immediately, before any
escalate/de-escalate logic runs -- never silently substitutes a different
model or fabricates Aeternum.
