"""
Signal adapters (the "collect" stage of spec §1's flow): convert real,
already-existing subsystem outputs into a typed FailureEvent, WITHOUT
copying raw private content -- only references and short structured
summaries (spec §4, §12).

Per docs/orneur/phase-12/LEARNING_SIGNAL_AUDIT.md, this module implements
adapters for the sources classified TRAINING_ELIGIBLE or EVAL_ONLY with a
concrete, inspectable structure available today: Truth Fabric contradictions
and unsupported claims, Simulation Chamber RealityDiff mismatches, and
Cognitive Court Constructor/Falsifier disagreement. Sources classified
NOT_TRAINING_ELIGIBLE, SECURITY_SENSITIVE-only, or requiring product
surfaces that do not exist yet (e.g. a user-correction UI) are audited but
intentionally have no adapter here yet -- adding one is a schema-compatible,
additive change, not a redesign, when that surface exists.
"""
from __future__ import annotations

from orca.learning.contracts import (
    FailureEvent,
    FailureType,
    PrivacyClass,
    ReproducibilityState,
    RootCauseClass,
    SecurityClass,
    VerificationState,
)


def from_truth_contradiction(contradiction, tenant_id: str | None = None) -> FailureEvent:
    """`contradiction` is an orca.truth.contracts.Contradiction. We store
    only its claim/evidence IDs as references -- never the full evidence
    text."""
    claim_ref = getattr(contradiction, "claim_id", "") or getattr(contradiction, "claim_a_id", "")
    evidence_ref = ",".join(getattr(contradiction, "evidence_ids", []) or [])
    return FailureEvent(
        source_system="truth_fabric",
        failure_type=FailureType.CONTRADICTION,
        tenant_id=tenant_id,
        input_reference=claim_ref,
        output_reference="",
        evidence_reference=evidence_ref,
        severity="MEDIUM",
        confidence=0.7,
        privacy_class=PrivacyClass.INTERNAL,
        reproducibility=ReproducibilityState.UNKNOWN,
        root_cause=RootCauseClass.RETRIEVAL_FAILURE,
        verification_state=VerificationState.UNVERIFIED,
    )


def from_unsupported_claim(claim_id: str, evidence_state: str, tenant_id: str | None = None) -> FailureEvent:
    return FailureEvent(
        source_system="truth_fabric",
        failure_type=FailureType.UNSUPPORTED_CLAIM,
        tenant_id=tenant_id,
        input_reference=claim_id,
        evidence_reference=evidence_state,
        severity="MEDIUM",
        confidence=0.6,
        root_cause=RootCauseClass.MODEL_FAILURE,
        verification_state=VerificationState.UNVERIFIED,
    )


def from_reality_diff(reality_diff, simulation_id: str, tenant_id: str | None = None) -> FailureEvent:
    """`reality_diff` is an orca.simulation.contracts.RealityDiff. This is
    exactly spec §38's 'RealityDiff mismatches may produce candidates' --
    the event itself is EVAL_ONLY-leaning by construction (root_cause left
    UNKNOWN, forcing explicit human/policy root-cause classification before
    any curriculum targeting, per spec §38's 'do not automatically train on
    raw mismatch')."""
    severity = getattr(reality_diff, "severity", "LOW")
    return FailureEvent(
        source_system="simulation_chamber",
        failure_type=FailureType.SIMULATION_MISMATCH,
        tenant_id=tenant_id,
        task_trace_id=simulation_id,
        input_reference=getattr(reality_diff, "action_id", ""),
        evidence_reference=getattr(reality_diff, "diff_id", ""),
        severity=severity,
        confidence=0.6,
        root_cause=RootCauseClass.UNKNOWN,       # deliberately unresolved -- spec §38
        verification_state=VerificationState.UNVERIFIED,
    )


def from_court_disagreement(case, verdict, tenant_id: str | None = None) -> FailureEvent:
    """`case`/`verdict` are orca.deliberation.contracts.CourtCase/CourtVerdict.
    Spec §39: only becomes curriculum when evidence/arbiter indicates a
    better answer or it is explicit adversarial unresolved -- this adapter
    only records the disagreement as an EVAL-leaning signal; the
    training-worthiness judgment happens later in triage/review, never
    here from a majority vote."""
    return FailureEvent(
        source_system="cognitive_court",
        failure_type=FailureType.COURT_DISAGREEMENT,
        tenant_id=tenant_id,
        task_trace_id=case.case_id,
        input_reference=case.objective[:200],   # bounded excerpt, not the full case
        evidence_reference=verdict.verdict_id,
        severity="MEDIUM" if verdict.unresolved_claim_ids else "LOW",
        confidence=verdict.confidence if verdict.confidence is not None else 0.5,
        root_cause=RootCauseClass.MODEL_FAILURE,
        verification_state=VerificationState.UNVERIFIED,
    )


def from_falsifier_miss(case_id: str, missed_contradiction_ref: str, tenant_id: str | None = None) -> FailureEvent:
    return FailureEvent(
        source_system="cognitive_court",
        failure_type=FailureType.FALSIFIER_MISS,
        tenant_id=tenant_id,
        task_trace_id=case_id,
        evidence_reference=missed_contradiction_ref,
        severity="MEDIUM",
        confidence=0.6,
        root_cause=RootCauseClass.MODEL_FAILURE,
        role="FALSIFIER",
        verification_state=VerificationState.UNVERIFIED,
    )


def from_connector_failure(connector_id: str, failure_summary: str, tenant_id: str | None = None) -> FailureEvent:
    return FailureEvent(
        source_system="connector_fabric",
        failure_type=FailureType.TOOL_EXECUTION_ERROR,
        tenant_id=tenant_id,
        input_reference=connector_id,
        evidence_reference=failure_summary[:200],
        severity="LOW",
        confidence=0.5,
        privacy_class=PrivacyClass.TENANT_PRIVATE,   # spec §13/§64: connector content defaults tenant-private
        root_cause=RootCauseClass.TOOL_FAILURE,
        verification_state=VerificationState.UNVERIFIED,
    )


def from_policy_denial(action_id: str, policy_reason: str, tenant_id: str | None = None) -> FailureEvent:
    """Spec §43: policy-denied actions should typically become safety
    regression cases, not 'teach the model how to succeed.'"""
    return FailureEvent(
        source_system="agent_runtime",
        failure_type=FailureType.POLICY_VIOLATION_ATTEMPT,
        tenant_id=tenant_id,
        input_reference=action_id,
        evidence_reference=policy_reason[:200],
        severity="HIGH",
        confidence=0.9,
        security_class=SecurityClass.SECURITY_SENSITIVE,
        root_cause=RootCauseClass.POLICY_FAILURE,
        verification_state=VerificationState.VERIFIED,   # a real policy denial is a fact, not a claim needing verification
    )


def from_jailbreak_probe_result(probe_id: str, passed: bool, tenant_id: str | None = None) -> FailureEvent | None:
    """Only emits an event on FAILURE (probe defeated the model) -- a
    passing probe is not a failure signal."""
    if passed:
        return None
    return FailureEvent(
        source_system="redteam_probes",
        failure_type=FailureType.JAILBREAK_FAILURE,
        tenant_id=tenant_id,
        input_reference=probe_id,
        severity="CRITICAL",
        confidence=0.95,
        security_class=SecurityClass.SECURITY_SENSITIVE,
        root_cause=RootCauseClass.MODEL_FAILURE,
        verification_state=VerificationState.VERIFIED,
    )
