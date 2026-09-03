"""
Phase 12 typed contracts (spec §4-11, §19-20, §25, §46-48, §60, §74).

Every enum here is a closed, bounded set -- the spec explicitly forbids an
unbounded arbitrary label system (§5, §9). Extending a set is a deliberate
code change, never a free-form string field.

Raw private chain-of-thought is never a field on any of these contracts
(spec §4's "Do not store raw private chain-of-thought" and §61's audit
requirement). Only references (IDs, hashes, short evidence excerpts) are
carried -- never full transcripts, full documents, or full connector
payloads (spec §12).
"""
from __future__ import annotations

import uuid
from dataclasses import dataclass, field
from datetime import datetime, timezone
from enum import Enum


def _new_id(prefix: str) -> str:
    return f"{prefix}-{uuid.uuid4().hex[:12]}"


def _now_iso() -> str:
    return datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")


# --------------------------------------------------------------------------- learning signal audit (spec §3)


class SignalClassification(str, Enum):
    HIGH_VALUE_SIGNAL = "HIGH_VALUE_SIGNAL"
    LOW_VALUE_SIGNAL = "LOW_VALUE_SIGNAL"
    SECURITY_SENSITIVE = "SECURITY_SENSITIVE"
    PRIVACY_SENSITIVE = "PRIVACY_SENSITIVE"
    NOISY = "NOISY"
    DUPLICATE_PRONE = "DUPLICATE_PRONE"
    NOT_TRAINING_ELIGIBLE = "NOT_TRAINING_ELIGIBLE"
    EVAL_ONLY = "EVAL_ONLY"
    TRAINING_ELIGIBLE = "TRAINING_ELIGIBLE"


# --------------------------------------------------------------------------- FailureEvent (spec §4-9)


class FailureType(str, Enum):
    UNSUPPORTED_CLAIM = "UNSUPPORTED_CLAIM"
    WRONG_CITATION = "WRONG_CITATION"
    CONTRADICTION = "CONTRADICTION"
    STALE_FACT = "STALE_FACT"
    LOW_AUTHORITY_EVIDENCE = "LOW_AUTHORITY_EVIDENCE"
    MEMORY_CONFLICT = "MEMORY_CONFLICT"
    TOOL_SELECTION_ERROR = "TOOL_SELECTION_ERROR"
    TOOL_EXECUTION_ERROR = "TOOL_EXECUTION_ERROR"
    PLAN_FAILURE = "PLAN_FAILURE"
    POLICY_VIOLATION_ATTEMPT = "POLICY_VIOLATION_ATTEMPT"
    ROUTING_ERROR = "ROUTING_ERROR"
    SIMULATION_MISMATCH = "SIMULATION_MISMATCH"
    COURT_DISAGREEMENT = "COURT_DISAGREEMENT"
    FALSIFIER_MISS = "FALSIFIER_MISS"
    JAILBREAK_FAILURE = "JAILBREAK_FAILURE"
    BIAS_FAILURE = "BIAS_FAILURE"
    CALIBRATION_FAILURE = "CALIBRATION_FAILURE"
    DOMAIN_REASONING_FAILURE = "DOMAIN_REASONING_FAILURE"
    STRUCTURED_OUTPUT_FAILURE = "STRUCTURED_OUTPUT_FAILURE"


class VerificationState(str, Enum):
    UNVERIFIED = "UNVERIFIED"
    VERIFIED = "VERIFIED"
    CONTESTED = "CONTESTED"
    DISMISSED = "DISMISSED"


class ReproducibilityState(str, Enum):
    REPRODUCIBLE = "REPRODUCIBLE"
    INTERMITTENT = "INTERMITTENT"
    ENVIRONMENTAL = "ENVIRONMENTAL"
    NON_REPRODUCIBLE = "NON_REPRODUCIBLE"
    UNKNOWN = "UNKNOWN"


class RootCauseClass(str, Enum):
    MODEL_FAILURE = "MODEL_FAILURE"
    RETRIEVAL_FAILURE = "RETRIEVAL_FAILURE"
    MEMORY_FAILURE = "MEMORY_FAILURE"
    TOOL_FAILURE = "TOOL_FAILURE"
    POLICY_FAILURE = "POLICY_FAILURE"
    RUNTIME_FAILURE = "RUNTIME_FAILURE"
    DATA_FAILURE = "DATA_FAILURE"
    INFRASTRUCTURE_FAILURE = "INFRASTRUCTURE_FAILURE"
    TEST_FAILURE = "TEST_FAILURE"
    UNKNOWN = "UNKNOWN"


# Root causes that must NEVER become ordinary capability training data
# (spec §8-9: "Do not train a model to 'fix' environmental infrastructure
# failures as if they were cognition failures" -- the Phase 11.2 Gateway
# timeout investigation is the spec's own canonical example).
NON_TRAINING_ROOT_CAUSES = frozenset({
    RootCauseClass.RUNTIME_FAILURE,
    RootCauseClass.INFRASTRUCTURE_FAILURE,
    RootCauseClass.TEST_FAILURE,
})


class PrivacyClass(str, Enum):
    PUBLIC = "PUBLIC"
    INTERNAL = "INTERNAL"
    TENANT_PRIVATE = "TENANT_PRIVATE"
    RESTRICTED = "RESTRICTED"


class SecurityClass(str, Enum):
    NORMAL = "NORMAL"
    ADVERSARIAL_INPUT = "ADVERSARIAL_INPUT"
    SECURITY_SENSITIVE = "SECURITY_SENSITIVE"


class FailureEventStatus(str, Enum):
    OPEN = "OPEN"
    TRIAGED = "TRIAGED"
    CANDIDATE_CREATED = "CANDIDATE_CREATED"
    CLOSED = "CLOSED"


@dataclass
class FailureEvent:
    """
    Spec §4: at minimum failure_id, source_system, failure_type, timestamp,
    tenant/scope, model_id/checkpoint if applicable, role, task/request
    trace, input_reference, output_reference, evidence_reference, severity,
    confidence, privacy_class, security_class, reproducibility, status.

    `input_reference`/`output_reference`/`evidence_reference` are references
    (an ID, a hash, a short excerpt) -- never the full raw content. See
    orca/learning/provenance.py for how these resolve back to the real
    source record.
    """
    failure_id: str = field(default_factory=lambda: _new_id("fail"))
    source_system: str = ""                       # e.g. "truth_fabric", "simulation_chamber", "cognitive_court"
    failure_type: FailureType = FailureType.DOMAIN_REASONING_FAILURE
    timestamp: str = field(default_factory=_now_iso)
    tenant_id: str | None = None
    model_id: str | None = None
    checkpoint_id: str | None = None
    role: str | None = None                        # Model Society role, if applicable
    task_trace_id: str | None = None
    input_reference: str = ""
    output_reference: str = ""
    evidence_reference: str = ""
    severity: str = "LOW"                          # LOW | MEDIUM | HIGH | CRITICAL
    confidence: float = 0.5
    privacy_class: PrivacyClass = PrivacyClass.INTERNAL
    security_class: SecurityClass = SecurityClass.NORMAL
    reproducibility: ReproducibilityState = ReproducibilityState.UNKNOWN
    root_cause: RootCauseClass = RootCauseClass.UNKNOWN
    verification_state: VerificationState = VerificationState.UNVERIFIED
    status: FailureEventStatus = FailureEventStatus.OPEN
    provenance_refs: list[str] = field(default_factory=list)   # lineage pointers, see provenance.py


# --------------------------------------------------------------------------- Failure triage (spec §10)


class FailureDisposition(str, Enum):
    TRAINING_CANDIDATE = "TRAINING_CANDIDATE"
    EVAL_CANDIDATE = "EVAL_CANDIDATE"
    SECURITY_REGRESSION = "SECURITY_REGRESSION"
    RUNTIME_BUG = "RUNTIME_BUG"
    DATA_QUALITY_ISSUE = "DATA_QUALITY_ISSUE"
    HUMAN_REVIEW = "HUMAN_REVIEW"
    DISMISS = "DISMISS"


@dataclass
class TriageResult:
    failure_id: str
    disposition: FailureDisposition
    reasons: list[str] = field(default_factory=list)
    decided_at: str = field(default_factory=_now_iso)


# --------------------------------------------------------------------------- Curriculum candidate (spec §11, §19-20, §46-48)


class ModelSocietyRole(str, Enum):
    QUERY_REWRITER = "QUERY_REWRITER"
    CLAIM_EXTRACTOR = "CLAIM_EXTRACTOR"
    VERIFIER = "VERIFIER"
    CONSTRUCTOR = "CONSTRUCTOR"
    FALSIFIER = "FALSIFIER"
    TOOL_REASONER = "TOOL_REASONER"


class TargetModelFamily(str, Enum):
    GENESIS = "GENESIS"
    NOVUS = "NOVUS"
    AETERNUM = "AETERNUM"
    FAMILY_SHARED = "FAMILY_SHARED"


class TrainingDestination(str, Enum):
    """Spec §13: tenant-private data must not enter global training by default."""
    TENANT_EVAL_ONLY = "TENANT_EVAL_ONLY"
    TENANT_LOCAL_TRAINING = "TENANT_LOCAL_TRAINING"
    GLOBAL_TRAINING_ELIGIBLE = "GLOBAL_TRAINING_ELIGIBLE"
    DISALLOWED = "DISALLOWED"


class CandidateReviewState(str, Enum):
    DRAFT = "DRAFT"
    APPROVED_FOR_EVAL = "APPROVED_FOR_EVAL"
    APPROVED_FOR_TRAINING = "APPROVED_FOR_TRAINING"
    REJECTED = "REJECTED"
    NEEDS_MORE_EVIDENCE = "NEEDS_MORE_EVIDENCE"
    SECURITY_ONLY = "SECURITY_ONLY"
    TENANT_LOCAL_ONLY = "TENANT_LOCAL_ONLY"


@dataclass
class CurriculumCandidate:
    candidate_id: str = field(default_factory=lambda: _new_id("cand"))
    failure_ids: list[str] = field(default_factory=list)
    task_type: str = ""
    target_role: ModelSocietyRole | None = None      # spec §19: do not force every failure into a role
    target_model_family: TargetModelFamily = TargetModelFamily.FAMILY_SHARED
    input_summary: str = ""                           # minimum necessary information, never a raw dump (spec §12)
    expected_behavior: str = ""
    negative_behavior: str = ""
    evidence_refs: list[str] = field(default_factory=list)
    difficulty: float = 0.0                            # see curriculum.py::score_difficulty for the deterministic formula
    privacy_class: PrivacyClass = PrivacyClass.INTERNAL
    security_class: SecurityClass = SecurityClass.NORMAL
    training_destination: TrainingDestination = TrainingDestination.DISALLOWED
    source_lineage: list[str] = field(default_factory=list)
    dedupe_fingerprint: str = ""
    review_state: CandidateReviewState = CandidateReviewState.DRAFT
    is_synthetic: bool = False
    synthetic_generator_model: str | None = None
    synthetic_generator_checkpoint: str | None = None
    synthetic_generation_ref: str | None = None
    synthetic_verification_state: VerificationState = VerificationState.UNVERIFIED
    created_at: str = field(default_factory=_now_iso)


# --------------------------------------------------------------------------- Human review queue (spec §60)


class ReviewDecision(str, Enum):
    APPROVE_FOR_EVAL = "APPROVE_FOR_EVAL"
    APPROVE_FOR_TRAINING = "APPROVE_FOR_TRAINING"
    REJECT = "REJECT"
    NEEDS_MORE_EVIDENCE = "NEEDS_MORE_EVIDENCE"
    SECURITY_ONLY = "SECURITY_ONLY"
    TENANT_LOCAL_ONLY = "TENANT_LOCAL_ONLY"


_REVIEW_DECISION_TO_STATE = {
    ReviewDecision.APPROVE_FOR_EVAL: CandidateReviewState.APPROVED_FOR_EVAL,
    ReviewDecision.APPROVE_FOR_TRAINING: CandidateReviewState.APPROVED_FOR_TRAINING,
    ReviewDecision.REJECT: CandidateReviewState.REJECTED,
    ReviewDecision.NEEDS_MORE_EVIDENCE: CandidateReviewState.NEEDS_MORE_EVIDENCE,
    ReviewDecision.SECURITY_ONLY: CandidateReviewState.SECURITY_ONLY,
    ReviewDecision.TENANT_LOCAL_ONLY: CandidateReviewState.TENANT_LOCAL_ONLY,
}


@dataclass
class ReviewQueueEntry:
    entry_id: str = field(default_factory=lambda: _new_id("review"))
    candidate_id: str = ""
    decision: ReviewDecision | None = None
    reviewer: str = ""                                 # "human:<id>" or "policy:<rule_name>" -- never "model:*"
    rationale: str = ""
    decided_at: str | None = None


class ModelCannotSelfApprove(Exception):
    """Raised if something tries to record a reviewer identity of 'model:*' (spec §69)."""


def apply_review_decision(entry: ReviewQueueEntry, candidate: CurriculumCandidate) -> CurriculumCandidate:
    if entry.reviewer.startswith("model:"):
        raise ModelCannotSelfApprove(
            f"Reviewer '{entry.reviewer}' looks like a model identity -- models cannot approve "
            f"candidates, freeze datasets, start training, or promote checkpoints (spec §69)."
        )
    if entry.decision is None:
        raise ValueError("ReviewQueueEntry has no decision")
    entry.decided_at = _now_iso()
    candidate.review_state = _REVIEW_DECISION_TO_STATE[entry.decision]
    return candidate


# --------------------------------------------------------------------------- Training experiment (spec §27-30, §72-74)


class TrainingMode(str, Enum):
    SFT = "SFT"
    LORA_QLORA = "LORA_QLORA"
    PREFERENCE_OPTIMIZATION = "PREFERENCE_OPTIMIZATION"
    DISTILLATION = "DISTILLATION"


class TrainingExperimentStatus(str, Enum):
    TRAINING_READY = "TRAINING_READY"
    RUNNING = "RUNNING"
    TRAINING_COMPLETE = "TRAINING_COMPLETE"
    CANCELLED = "CANCELLED"
    FAILED = "FAILED"


class TrainingFailureCategory(str, Enum):
    DATA_ERROR = "DATA_ERROR"
    OOM = "OOM"
    CHECKPOINT_ERROR = "CHECKPOINT_ERROR"
    EVAL_FAILURE = "EVAL_FAILURE"
    SECURITY_FAILURE = "SECURITY_FAILURE"
    CANCELLED = "CANCELLED"
    INFRASTRUCTURE_FAILURE = "INFRASTRUCTURE_FAILURE"


@dataclass
class TrainingBudget:
    """Spec §72: no unbounded training run."""
    max_gpu_seconds: float = 0.0
    max_examples: int = 0
    max_wall_clock_seconds: float = 0.0
    max_storage_bytes: int = 0


@dataclass
class TrainingCostReport:
    gpu_seconds_used: float = 0.0
    examples_used: int = 0
    wall_clock_seconds: float = 0.0
    storage_bytes_used: int = 0

    def exceeds(self, budget: TrainingBudget) -> list[str]:
        violations = []
        if budget.max_gpu_seconds and self.gpu_seconds_used > budget.max_gpu_seconds:
            violations.append("max_gpu_seconds")
        if budget.max_examples and self.examples_used > budget.max_examples:
            violations.append("max_examples")
        if budget.max_wall_clock_seconds and self.wall_clock_seconds > budget.max_wall_clock_seconds:
            violations.append("max_wall_clock_seconds")
        if budget.max_storage_bytes and self.storage_bytes_used > budget.max_storage_bytes:
            violations.append("max_storage_bytes")
        return violations
