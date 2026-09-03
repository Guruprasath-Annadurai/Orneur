"""
The Phase 12 pipeline orchestrator (spec §57, §81): a repeatable,
explicitly-invoked sequence -- collect -> verify -> triage -> dedupe ->
sanitize -> candidate -> review -> freeze -> train-metadata. NOT a
background daemon (spec §58: "Do NOT create always-on auto-training
daemon"); every stage here is a plain function call a caller (a CLI
command, a script, a test) must explicitly invoke.
"""
from __future__ import annotations

from dataclasses import dataclass, field

from orca.learning.audit import AUDIT
from orca.learning.contracts import (
    CandidateReviewState,
    CurriculumCandidate,
    FailureDisposition,
    FailureEvent,
    PrivacyClass,
    ReviewDecision,
    ReviewQueueEntry,
    TrainingDestination,
    VerificationState,
    apply_review_decision,
)
from orca.learning.dedupe import dedupe_against
from orca.learning.provenance import LineageGraph
from orca.learning.sanitize import sanitize_for_candidate
from orca.learning.security import (
    DataPoisoningAttemptDetected,
    TenantExfiltrationBlocked,
    enforce_tenant_boundary,
    scan_for_poisoning_attempt,
)
from orca.learning.triage import triage


class UnverifiedTrainingAdmissionBlocked(Exception):
    pass


@dataclass
class PipelineRunReport:
    events_in: int = 0
    verified: int = 0
    dismissed: int = 0
    triaged: dict = field(default_factory=dict)          # disposition -> count
    candidates_created: int = 0
    candidates_deduped_out: int = 0
    candidates_sanitization_rejected: int = 0
    candidates_poisoning_flagged: int = 0
    lineage: LineageGraph = field(default_factory=LineageGraph)


def verify_event(event: FailureEvent, is_reproducible_and_confirmed: bool) -> FailureEvent:
    """
    Spec §7: not every apparent failure is real. This is the single place
    a FailureEvent's verification_state transitions away from UNVERIFIED --
    callers pass in the real evidence-based confirmation result (e.g. a
    reproduction run, a second independent Truth Fabric check), never a
    model's own self-assessment.
    """
    event.verification_state = VerificationState.VERIFIED if is_reproducible_and_confirmed else event.verification_state
    return event


def make_candidate_from_event(event: FailureEvent, task_type: str, input_summary: str, expected_behavior: str) -> CurriculumCandidate:
    """
    Only ever called for a VERIFIED event whose triage disposition was
    TRAINING_CANDIDATE or EVAL_CANDIDATE -- enforced explicitly here as a
    defense-in-depth check (spec §7, §90's UNVERIFIED_FAILURE_TRAINING_ADMISSION),
    even though the pipeline's own control flow (see run_pipeline below)
    should never call this otherwise.
    """
    if event.verification_state != VerificationState.VERIFIED:
        AUDIT.record("UNVERIFIED_FAILURE_TRAINING_ADMISSION")
        raise UnverifiedTrainingAdmissionBlocked(
            f"FailureEvent {event.failure_id} is not VERIFIED (state={event.verification_state.value}) -- cannot become a curriculum candidate."
        )
    destination = (
        TrainingDestination.TENANT_LOCAL_TRAINING
        if event.privacy_class == PrivacyClass.TENANT_PRIVATE
        else TrainingDestination.GLOBAL_TRAINING_ELIGIBLE
        if event.privacy_class == PrivacyClass.PUBLIC
        else TrainingDestination.TENANT_EVAL_ONLY
    )
    candidate = CurriculumCandidate(
        failure_ids=[event.failure_id],
        task_type=task_type,
        input_summary=input_summary,
        expected_behavior=expected_behavior,
        evidence_refs=[event.evidence_reference] if event.evidence_reference else [],
        privacy_class=event.privacy_class,
        security_class=event.security_class,
        training_destination=destination,
        source_lineage=[f"failure:{event.failure_id}"] + ([f"tenant:{event.tenant_id}"] if event.tenant_id else []),
    )
    return candidate


def run_pipeline(
    events: list[FailureEvent],
    task_type_of,
    input_summary_of,
    expected_behavior_of,
    existing_candidates: list[CurriculumCandidate] | None = None,
) -> tuple[list[CurriculumCandidate], PipelineRunReport]:
    """
    `task_type_of`/`input_summary_of`/`expected_behavior_of` are callables
    (FailureEvent) -> str -- the caller supplies these because deriving
    them requires reaching back into the OWNING subsystem's real record
    (e.g. the actual Truth claim text), which this generic pipeline
    function deliberately does not know how to do for every source system.
    """
    report = PipelineRunReport(events_in=len(events))
    existing_candidates = list(existing_candidates or [])
    produced: list[CurriculumCandidate] = []

    for event in events:
        report.lineage.add("FailureEvent", event.failure_id)
        if event.verification_state == VerificationState.VERIFIED:
            report.verified += 1
        if event.verification_state == VerificationState.DISMISSED:
            report.dismissed += 1

        result = triage(event)
        report.triaged[result.disposition.value] = report.triaged.get(result.disposition.value, 0) + 1

        if result.disposition not in (FailureDisposition.TRAINING_CANDIDATE, FailureDisposition.EVAL_CANDIDATE):
            continue
        if event.verification_state != VerificationState.VERIFIED:
            continue

        candidate = make_candidate_from_event(
            event,
            task_type=task_type_of(event),
            input_summary=input_summary_of(event),
            expected_behavior=expected_behavior_of(event),
        )

        poisoning_hits = scan_for_poisoning_attempt(candidate.input_summary + " " + candidate.expected_behavior)
        if poisoning_hits:
            report.candidates_poisoning_flagged += 1
            candidate.review_state = CandidateReviewState.NEEDS_MORE_EVIDENCE

        sanitized = sanitize_for_candidate(candidate.input_summary)
        if sanitized.rejected:
            report.candidates_sanitization_rejected += 1
            AUDIT.record("SECRET_IN_CURRICULUM")
            continue
        candidate.input_summary = sanitized.clean_text

        dedupe_report = dedupe_against(candidate, existing_candidates + produced)
        if dedupe_report.exact_duplicate_of:
            report.candidates_deduped_out += 1
            continue

        try:
            enforce_tenant_boundary(candidate, event.tenant_id, candidate.training_destination)
        except TenantExfiltrationBlocked:
            AUDIT.record("TENANT_DATA_GLOBAL_TRAINING_LEAK")
            continue

        report.lineage.add("CurriculumCandidate", candidate.candidate_id, parent_refs=[event.failure_id])
        produced.append(candidate)
        event.status = event.status.__class__.CANDIDATE_CREATED

    report.candidates_created = len(produced)
    return produced, report


def revoke_source_and_invalidate(candidate: CurriculumCandidate) -> CurriculumCandidate:
    """
    Spec §70-71: if the original source is deleted/revoked, the derived
    candidate/dataset must follow documented policy -- tombstone it rather
    than leaving a hidden training copy silently eligible. This does not
    delete the candidate RECORD (that would erase the audit trail spec §61
    requires); it moves the candidate to REJECTED/DISALLOWED so it can
    never again be picked up by review or compilation.
    """
    candidate.review_state = CandidateReviewState.REJECTED
    candidate.training_destination = TrainingDestination.DISALLOWED
    return candidate


def review_candidate(candidate: CurriculumCandidate, decision: ReviewDecision, reviewer: str, rationale: str = "") -> CurriculumCandidate:
    """The ONLY function that moves a candidate out of DRAFT. `reviewer`
    must never be a model identity (enforced inside apply_review_decision,
    spec §69)."""
    entry = ReviewQueueEntry(candidate_id=candidate.candidate_id, decision=decision, reviewer=reviewer, rationale=rationale)
    return apply_review_decision(entry, candidate)
