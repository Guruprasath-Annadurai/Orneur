"""
Typed Truth Fabric contracts -- pure data, mirroring the pattern already
established by orca/gateway/contracts.py and orca/cognitive/contracts.py.
No behavior lives here; behavior lives in the modules named after each
contract (planner.py, evidence.py, graph.py, claims.py, verification.py,
citation.py, contradiction.py, state.py).

Reuses orca.cognitive.contracts.FreshnessLevel/EvidenceLevel rather than
duplicating them -- RetrievalPlanner consumes the Cognitive Kernel's own
freshness_requirement/evidence_requirement directly (Phase 4 spec §7),
so the vocabulary must be the same enum, not a parallel one.
"""
from __future__ import annotations

import uuid
from dataclasses import dataclass, field
from datetime import datetime, timezone
from enum import Enum
from typing import Any

from orca.cognitive.contracts import EvidenceLevel, FreshnessLevel


def _new_id(prefix: str) -> str:
    return f"{prefix}-{uuid.uuid4().hex[:12]}"


def _now_iso() -> str:
    return datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")


# ── Retrieval modes ──────────────────────────────────────────────────────

class RetrievalMode(str, Enum):
    RAG_0_NONE = "RAG_0_NONE"
    RAG_1_SEMANTIC = "RAG_1_SEMANTIC"
    RAG_2_HYBRID = "RAG_2_HYBRID"
    RAG_3_MULTI_HOP = "RAG_3_MULTI_HOP"
    RAG_4_CORRECTIVE = "RAG_4_CORRECTIVE"
    RAG_5_RESEARCH = "RAG_5_RESEARCH"


class RetrievalSourceType(str, Enum):
    DENSE = "DENSE"
    SPARSE = "SPARSE"
    GRAPH = "GRAPH"
    MEMORY = "MEMORY"
    WEB = "WEB"


@dataclass
class RetrievalQuery:
    text: str
    source_types: list[RetrievalSourceType] = field(default_factory=lambda: [RetrievalSourceType.DENSE])
    hop_index: int = 0                 # 0 = original query; >0 = a multi-hop follow-up
    corrective_round: int = 0          # 0 = first pass; >0 = a corrective retry


@dataclass
class RetrievalPlan:
    mode: RetrievalMode
    queries: list[RetrievalQuery]
    sources: list[RetrievalSourceType]
    max_documents: int
    max_passages: int
    rerank_required: bool
    freshness_required: FreshnessLevel
    authority_required: bool
    multi_hop_depth: int
    corrective_rounds: int
    reasons: list[str] = field(default_factory=list)
    plan_id: str = field(default_factory=lambda: _new_id("rplan"))


# ── Truth request/result ─────────────────────────────────────────────────

@dataclass
class TruthRequest:
    objective: str
    evidence_requirement: EvidenceLevel
    freshness_requirement: FreshnessLevel
    risk_level: str = "LOW"            # mirrors orca.cognitive.contracts.RiskLevel.value, kept as str to avoid a cognitive<->truth import cycle
    request_id: str = field(default_factory=lambda: _new_id("treq"))
    trace_id: str | None = None
    context_refs: list[str] = field(default_factory=list)   # e.g. session doc_store ids, memory refs -- references, not content


# ── Source / Document / Evidence ─────────────────────────────────────────

class SourceType(str, Enum):
    UPLOADED_DOCUMENT = "UPLOADED_DOCUMENT"
    WEB_PRIMARY = "WEB_PRIMARY"        # official docs, original paper, regulator, first-party API docs
    WEB_SECONDARY = "WEB_SECONDARY"    # news, blogs, secondary reporting
    WEB_COMMUNITY = "WEB_COMMUNITY"    # forums, Q&A, social
    MEMORY = "MEMORY"                  # this session's own conversation/long-term memory -- distinguishable from external evidence (spec §38)


class IndependenceState(str, Enum):
    INDEPENDENT = "INDEPENDENT"
    LIKELY_DERIVED = "LIKELY_DERIVED"
    UNKNOWN = "UNKNOWN"


@dataclass
class SourceQuality:
    """Structured, CONTEXTUAL factors -- never one permanent global "truth
    score" per domain (spec §32). The same source can be strong for one
    kind of claim and weak for another; that judgment happens where the
    factors are actually used (evidence.py/state.py), not baked in here."""
    is_primary: bool = False
    is_official: bool = False
    is_community: bool = False
    domain: str = ""
    factors: list[str] = field(default_factory=list)


@dataclass
class EvidenceSource:
    source_id: str
    identity: str                      # URL, or a stable doc-store identifier -- never collapsed to "just a URL string"
    source_type: SourceType
    domain: str = ""
    publisher: str = ""
    author: str = ""
    published_at: str | None = None
    updated_at: str | None = None
    quality: SourceQuality = field(default_factory=SourceQuality)
    content_hash: str | None = None
    independence: IndependenceState = IndependenceState.UNKNOWN
    derived_from: list[str] = field(default_factory=list)   # source_ids this one is believed derived from (provenance lineage)


@dataclass
class EvidencePassage:
    text: str
    location: str = ""                 # e.g. chunk index, page, byte offset -- whatever the source type can supply


@dataclass
class Evidence:
    evidence_id: str
    source_id: str
    document_id: str
    passage: EvidencePassage
    retrieved_at: str = field(default_factory=_now_iso)
    published_at: str | None = None
    updated_at: str | None = None
    content_hash: str = ""
    freshness: FreshnessLevel = FreshnessLevel.STATIC
    origin_metadata: dict[str, Any] = field(default_factory=dict)


# ── Evidence Graph ───────────────────────────────────────────────────────

class EvidenceEdgeType(str, Enum):
    SUPPORTS = "SUPPORTS"
    CONTRADICTS = "CONTRADICTS"
    DERIVED_FROM = "DERIVED_FROM"
    MENTIONS = "MENTIONS"
    SAME_ORIGIN = "SAME_ORIGIN"
    SUPERSEDES = "SUPERSEDES"


class EvidenceNodeType(str, Enum):
    CLAIM = "CLAIM"
    EVIDENCE = "EVIDENCE"
    SOURCE = "SOURCE"
    DOCUMENT = "DOCUMENT"
    ENTITY = "ENTITY"


@dataclass
class EvidenceGraphNode:
    node_id: str
    node_type: EvidenceNodeType
    label: str = ""


@dataclass
class EvidenceGraphEdge:
    from_id: str
    to_id: str
    edge_type: EvidenceEdgeType
    weight: float = 1.0


# ── Claims ───────────────────────────────────────────────────────────────

class ClaimSupportState(str, Enum):
    SUPPORTED = "SUPPORTED"
    PARTIALLY_SUPPORTED = "PARTIALLY_SUPPORTED"
    UNSUPPORTED = "UNSUPPORTED"
    CONTRADICTED = "CONTRADICTED"
    UNKNOWN = "UNKNOWN"


@dataclass
class AtomicClaim:
    claim_id: str
    text: str
    source_span: str = ""              # the substring of the generated answer this claim was extracted from


@dataclass
class ClaimSupport:
    claim_id: str
    evidence_ids: list[str]
    support_state: ClaimSupportState
    support_strength: str = ""         # short structured label (e.g. "strong lexical+semantic match"), never a fabricated numeric confidence
    contradiction_ids: list[str] = field(default_factory=list)
    reasons: list[str] = field(default_factory=list)


# ── Citations ────────────────────────────────────────────────────────────

class CitationVerdictState(str, Enum):
    SUPPORTED = "SUPPORTED"
    PARTIAL = "PARTIAL"
    UNSUPPORTED = "UNSUPPORTED"
    CONTRADICTED = "CONTRADICTED"


@dataclass
class CitationCandidate:
    claim_id: str
    source_id: str
    evidence_id: str


@dataclass
class CitationVerdict:
    candidate: CitationCandidate
    verdict: CitationVerdictState
    reasons: list[str] = field(default_factory=list)


# ── Contradictions ───────────────────────────────────────────────────────

class ContradictionRelationship(str, Enum):
    DIRECT_CONTRADICTION = "DIRECT_CONTRADICTION"
    TEMPORALLY_RECONCILABLE = "TEMPORALLY_RECONCILABLE"   # e.g. "was true, no longer is" -- not a real contradiction
    UNRELATED = "UNRELATED"


@dataclass
class Contradiction:
    claim_a_id: str
    claim_b_id: str
    relationship: ContradictionRelationship
    temporal_context: str = ""
    source_context: str = ""


# ── Evidence state / Truth result ────────────────────────────────────────

class EvidenceState(str, Enum):
    SUFFICIENT = "SUFFICIENT"
    PARTIAL = "PARTIAL"
    CONFLICTED = "CONFLICTED"
    STALE = "STALE"
    LOW_AUTHORITY = "LOW_AUTHORITY"
    INSUFFICIENT = "INSUFFICIENT"


# Future Epistemic State Machine hook (Phase 4 spec §31) -- not implemented
# as a state machine yet; TruthResult carries enough (claim_supports,
# contradictions, evidence_state) for a later phase to compute one of
# these without needing new data collected retroactively.
class EpistemicHook(str, Enum):
    KNOWN = "KNOWN"
    SUPPORTED = "SUPPORTED"
    PROBABLE = "PROBABLE"
    CONTESTED = "CONTESTED"
    STALE = "STALE"
    UNVERIFIED = "UNVERIFIED"
    UNKNOWN = "UNKNOWN"
    DISPROVEN = "DISPROVEN"


@dataclass
class TruthResult:
    request_id: str
    trace_id: str | None
    evidence_state: EvidenceState
    retrieval_plan_id: str | None = None
    evidence: list[Evidence] = field(default_factory=list)
    sources: list[EvidenceSource] = field(default_factory=list)
    claims: list[AtomicClaim] = field(default_factory=list)
    claim_supports: list[ClaimSupport] = field(default_factory=list)
    citation_verdicts: list[CitationVerdict] = field(default_factory=list)
    contradictions: list[Contradiction] = field(default_factory=list)
    context_block: str = ""            # citation-tagged text ready for the answering model's prompt
    citation_coverage: dict[str, Any] = field(default_factory=dict)
    warnings: list[str] = field(default_factory=list)
    latency_ms: float = 0.0
