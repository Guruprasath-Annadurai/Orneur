"""
Deterministic failure triage engine (spec §10): FailureEvent -> FailureDisposition.

Spec §10 is explicit: "Do not let an LLM alone decide that a failure
belongs in training." This is a pure, deterministic rule table over the
FailureEvent's own typed fields -- no model call anywhere in this module.
"""
from __future__ import annotations

from orca.learning.contracts import (
    FailureDisposition,
    FailureEvent,
    FailureType,
    NON_TRAINING_ROOT_CAUSES,
    RootCauseClass,
    SecurityClass,
    TriageResult,
    VerificationState,
)

_SECURITY_FAILURE_TYPES = frozenset({
    FailureType.JAILBREAK_FAILURE,
    FailureType.POLICY_VIOLATION_ATTEMPT,
})


def triage(event: FailureEvent) -> TriageResult:
    reasons: list[str] = []

    # Rule 1 (spec §7): a failure that isn't VERIFIED is never a training
    # candidate outright -- CONTESTED goes to human review, UNVERIFIED
    # needs more evidence, DISMISSED is dropped.
    if event.verification_state == VerificationState.DISMISSED:
        reasons.append("verification_state=DISMISSED")
        return TriageResult(failure_id=event.failure_id, disposition=FailureDisposition.DISMISS, reasons=reasons)

    if event.verification_state == VerificationState.CONTESTED:
        reasons.append("verification_state=CONTESTED -- requires explicit human/policy review (spec §7)")
        return TriageResult(failure_id=event.failure_id, disposition=FailureDisposition.HUMAN_REVIEW, reasons=reasons)

    if event.verification_state == VerificationState.UNVERIFIED:
        reasons.append("verification_state=UNVERIFIED -- not yet eligible for training/eval candidacy")
        return TriageResult(failure_id=event.failure_id, disposition=FailureDisposition.HUMAN_REVIEW, reasons=reasons)

    # From here, verification_state == VERIFIED.

    # Rule 2 (spec §37): security-relevant failure types become security
    # regressions by default, never ordinary capability training.
    if event.failure_type in _SECURITY_FAILURE_TYPES or event.security_class == SecurityClass.SECURITY_SENSITIVE:
        reasons.append(f"failure_type={event.failure_type.value} or security_class={event.security_class.value} -- security regression, not capability training")
        return TriageResult(failure_id=event.failure_id, disposition=FailureDisposition.SECURITY_REGRESSION, reasons=reasons)

    # Rule 3 (spec §8-9): infrastructure/runtime/test root causes are never
    # model-training candidates -- the canonical Phase 11.2 Gateway example.
    if event.root_cause in NON_TRAINING_ROOT_CAUSES:
        reasons.append(f"root_cause={event.root_cause.value} -- infrastructure/runtime/test failures are RUNTIME_BUG, not a cognition failure")
        return TriageResult(failure_id=event.failure_id, disposition=FailureDisposition.RUNTIME_BUG, reasons=reasons)

    if event.root_cause == RootCauseClass.DATA_FAILURE:
        reasons.append("root_cause=DATA_FAILURE")
        return TriageResult(failure_id=event.failure_id, disposition=FailureDisposition.DATA_QUALITY_ISSUE, reasons=reasons)

    if event.root_cause == RootCauseClass.UNKNOWN:
        reasons.append("root_cause=UNKNOWN -- cannot triage without root-cause classification")
        return TriageResult(failure_id=event.failure_id, disposition=FailureDisposition.HUMAN_REVIEW, reasons=reasons)

    # Rule 4 (spec §35): every verified, model-attributable failure becomes
    # an eval candidate first -- training-eligibility is a *further*,
    # separate decision made later by the curriculum/review layer, never
    # skipped straight to TRAINING_CANDIDATE by triage alone.
    reasons.append(f"verification_state=VERIFIED, root_cause={event.root_cause.value} -- eligible for eval-candidate path (spec §35: failure-to-eval before failure-to-training)")
    return TriageResult(failure_id=event.failure_id, disposition=FailureDisposition.EVAL_CANDIDATE, reasons=reasons)
