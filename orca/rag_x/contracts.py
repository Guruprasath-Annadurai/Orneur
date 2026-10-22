"""Versioned RAG-X contracts.

Names follow the programme contract list. `orca.truth.contracts.RetrievalPlan`
remains the Cognitive Kernel planner type and is not duplicated here.
"""
from __future__ import annotations

from dataclasses import dataclass, field
from enum import Enum
from typing import Any


SCHEMA_VERSION = "rag-x.1"


class RetrievalStatus(str, Enum):
    NO_RETRIEVAL_REQUIRED = "no_retrieval_required"
    SUCCESS = "success"
    PARTIAL = "partial"
    INSUFFICIENT = "insufficient"
    CONTRADICTORY = "contradictory"
    STALE = "stale"
    SOURCE_INACCESSIBLE = "source_inaccessible"
    BACKEND_UNAVAILABLE = "backend_unavailable"
    BUDGET_EXHAUSTED = "budget_exhausted"
    VERIFICATION_UNAVAILABLE = "verification_unavailable"
    GENERATION_INTERRUPTED = "generation_interrupted"
    UNAUTHORIZED = "unauthorized"
    MODEL_NOT_TRAINED = "model_not_trained"
    MODEL_NOT_QUALIFIED = "model_not_qualified"


class CapabilityClass(str, Enum):
    EXISTING_VERIFIED = "EXISTING_VERIFIED"
    IMPLEMENTED_AND_QUALIFIED = "IMPLEMENTED_AND_QUALIFIED"
    RESEARCH_PROTOTYPE = "RESEARCH_PROTOTYPE"
    BACKEND_UNAVAILABLE = "BACKEND_UNAVAILABLE"
    BLOCKED = "BLOCKED"


NATIVE_MODEL_IDS = frozenset({"genesis", "novus", "aeternum"})


@dataclass(frozen=True)
class AuthorizedRetrievalScope:
    tenant_id: str
    principal_id: str
    workspace_id: str
    session_id: str
    as_of: str


@dataclass(frozen=True)
class RetrievalBudget:
    max_retrieval_calls: int = 4
    max_tokens: int = 400
    max_rounds: int = 2
    max_hops: int = 2
    deadline_steps: int = 8


@dataclass(frozen=True)
class RetrievalRequest:
    query: str
    scope: AuthorizedRetrievalScope
    mode: str
    budget: RetrievalBudget = field(default_factory=RetrievalBudget)
    model_identity: str = "none"
    backend_id: str = "synthetic-template-backend"
    config_id: str = "rag-x-kernel-1"
    history: tuple[str, ...] = ()
    subqueries: tuple[str, ...] = ()
    structured_filter: dict[str, str] | None = None
    raw_sql: str | None = None
    domain: str = "technical"
    as_of: str | None = None


@dataclass(frozen=True)
class EvidenceSpan:
    document_id: str
    version_id: str
    chunk_id: str
    text: str
    start: int
    end: int
    digest: str
    authoritative: bool = True


@dataclass(frozen=True)
class RetrievedEvidence:
    evidence_id: str
    span: EvidenceSpan
    score: float
    rank: int
    method: str
    tenant_id: str
    source_uri: str
    language: str
    modality: str
    valid_from: str
    valid_to: str | None
    provider_status: str
    synthetic_query: bool = False
    hop: int = 0


@dataclass(frozen=True)
class ContradictionRecord:
    subject: str
    left_evidence_id: str
    right_evidence_id: str
    left_value: str
    right_value: str
    temporal: bool


@dataclass(frozen=True)
class ClaimVerification:
    claim: str
    supported: bool
    evidence_ids: tuple[str, ...]
    reason: str


@dataclass
class AnswerEvidenceManifest:
    schema_version: str
    request_id: str
    scope_digest: str
    config_id: str
    config_digest: str
    mode: str
    model_identity: str
    backend_id: str
    status: RetrievalStatus
    evidence_ids: tuple[str, ...]
    document_versions: tuple[str, ...]
    steps: list[str] = field(default_factory=list)
    retrieval_calls: int = 0
    software_revision: str = "unspecified"
    partial_reasons: list[str] = field(default_factory=list)


@dataclass
class AnswerResult:
    status: RetrievalStatus
    answer: str
    claims: list[ClaimVerification]
    evidence: list[RetrievedEvidence]
    contradictions: list[ContradictionRecord]
    manifest: AnswerEvidenceManifest
    lexical_scores: dict[str, float] = field(default_factory=dict)
    notes: list[str] = field(default_factory=list)

    def as_dict(self) -> dict[str, Any]:
        return {
            "status": self.status.value,
            "answer": self.answer,
            "evidence_ids": [item.evidence_id for item in self.evidence],
            "claims": [claim.reason for claim in self.claims],
        }
