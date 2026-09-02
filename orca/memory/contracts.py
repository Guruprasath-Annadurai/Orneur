"""
Memory Continuum contracts (Phase 5 spec §4-5). Typed dataclasses, no
behavior -- behavior lives in the modules named after each contract
(episodic.py, semantic.py, arbiter.py, firewall.py, ...), mirroring the
pattern already established by orca/truth/contracts.py and
orca/cognitive/contracts.py.

Reuses orca.cognitive.contracts.PrivacyClass rather than inventing a
parallel PUBLIC/INTERNAL/PRIVATE/SENSITIVE scheme (spec §37: "use current
project conventions if already defined").
"""
from __future__ import annotations

import hashlib
import uuid
from dataclasses import dataclass, field
from datetime import datetime, timezone
from enum import Enum
from typing import Any

from orca.cognitive.contracts import PrivacyClass


def _new_id(prefix: str) -> str:
    return f"{prefix}-{uuid.uuid4().hex[:12]}"


def _now_iso() -> str:
    return datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")


def content_hash(text: str) -> str:
    return hashlib.sha256(text.encode("utf-8")).hexdigest()[:16]


# ── Scope / type enums ───────────────────────────────────────────────────

class MemoryScope(str, Enum):
    """Spec §6. Not every scope is meaningful on this platform today --
    see docs/orneur/phase-5/ARCHITECTURE.md for which are actually
    enforceable (SESSION, USER via auth/store.py's user_sessions) versus
    reserved contract surface for a future multi-tenant deployment
    (TENANT, WORKSPACE, PROJECT) that this single-tenant codebase doesn't
    yet have a concept of."""
    GLOBAL = "GLOBAL"
    TENANT = "TENANT"
    WORKSPACE = "WORKSPACE"
    PROJECT = "PROJECT"
    USER = "USER"
    SESSION = "SESSION"
    AGENT = "AGENT"


class MemoryType(str, Enum):
    WORKING = "WORKING"
    EPISODIC = "EPISODIC"
    SEMANTIC = "SEMANTIC"
    ENTITY = "ENTITY"
    PROCEDURAL = "PROCEDURAL"
    FAILURE = "FAILURE"
    AGENT = "AGENT"


class EpistemicState(str, Enum):
    """Spec §13: never reduce all memory trust to one float. A numeric
    confidence MAY supplement this but never replaces it."""
    KNOWN = "KNOWN"
    SUPPORTED = "SUPPORTED"
    PROBABLE = "PROBABLE"
    CONTESTED = "CONTESTED"
    STALE = "STALE"
    UNVERIFIED = "UNVERIFIED"
    UNKNOWN = "UNKNOWN"
    DISPROVEN = "DISPROVEN"


class MemoryLifecycleState(str, Enum):
    ACTIVE = "ACTIVE"
    DORMANT = "DORMANT"
    ARCHIVED = "ARCHIVED"
    PURGED = "PURGED"


class MemoryRelationshipType(str, Enum):
    """Spec §16."""
    SUPERSEDES = "SUPERSEDES"
    SUPERSEDED_BY = "SUPERSEDED_BY"
    VALID_DURING = "VALID_DURING"
    CONTRADICTS = "CONTRADICTS"
    DERIVED_FROM = "DERIVED_FROM"


class ContradictionResolution(str, Enum):
    """Spec §17 -- never "pick the newest string"."""
    TEMPORAL_CHANGE = "TEMPORAL_CHANGE"
    SCOPE_DIFFERENCE = "SCOPE_DIFFERENCE"
    VERSION_DIFFERENCE = "VERSION_DIFFERENCE"
    CONTESTED = "CONTESTED"
    DISPROVEN = "DISPROVEN"
    UNRESOLVED = "UNRESOLVED"


class DuplicateClassification(str, Enum):
    """Spec §26."""
    IDENTICAL = "IDENTICAL"
    NEAR_DUPLICATE = "NEAR_DUPLICATE"
    SAME_FACT_DIFFERENT_WORDING = "SAME_FACT_DIFFERENT_WORDING"
    POTENTIAL_CONFLICT = "POTENTIAL_CONFLICT"
    DISTINCT = "DISTINCT"


class PromotionDecision(str, Enum):
    PROMOTED = "PROMOTED"
    REJECTED = "REJECTED"
    DEFERRED = "DEFERRED"


class FailureVerificationState(str, Enum):
    """Spec §22 -- never manufacture a permanent failure memory from an
    unverified guess."""
    VERIFIED_ROOT_CAUSE = "VERIFIED_ROOT_CAUSE"
    PROBABLE = "PROBABLE"
    UNVERIFIED = "UNVERIFIED"


# ── Identity / evidence lineage (spec §5, §11) ───────────────────────────

@dataclass
class MemoryEvidence:
    """One reference in a semantic memory's evidence lineage -- spec §11's
    signature mechanism: "WHY DOES ORNEUR BELIEVE THIS?" must be
    answerable by walking this list, never invented retrospectively.
    Points at EITHER a Memory Continuum episode OR a Truth Fabric result
    (never both blank) -- see docs/orneur/phase-5/MEMORY_EVIDENCE_LEDGER.md."""
    episode_id: str | None = None
    truth_request_id: str | None = None       # orca.truth.contracts.TruthResult.request_id, when Truth Fabric verified this
    truth_evidence_id: str | None = None      # orca.truth.contracts.Evidence.evidence_id
    truth_claim_id: str | None = None         # orca.truth.contracts.AtomicClaim.claim_id
    citation_verdict_state: str | None = None  # orca.truth.contracts.CitationVerdictState.value, copied not re-derived
    document_ref: str | None = None            # a DocStore doc_id/filename, when not Truth-Fabric-mediated
    note: str = ""                             # short, human-authored context -- never raw chain-of-thought


@dataclass
class MemoryRecord:
    """Common identity fields every persisted memory type carries (spec
    §5). Never uses a vector-store row position as identity -- memory_id
    is assigned at creation and is stable for the record's lifetime."""
    memory_id: str = field(default_factory=lambda: _new_id("mem"))
    memory_type: MemoryType = MemoryType.EPISODIC
    scope: MemoryScope = MemoryScope.SESSION
    scope_id: str = ""                          # the actual session_id/user_id/etc. this scope resolves to
    created_at: str = field(default_factory=_now_iso)
    updated_at: str = field(default_factory=_now_iso)
    valid_from: str | None = None
    valid_to: str | None = None
    epistemic_state: EpistemicState = EpistemicState.UNVERIFIED
    confidence: float | None = None             # supplements epistemic_state, never replaces it (spec §13)
    source_refs: list[str] = field(default_factory=list)     # episode_ids this was derived from
    evidence_refs: list[MemoryEvidence] = field(default_factory=list)
    privacy: PrivacyClass = PrivacyClass.STANDARD
    lifecycle_state: MemoryLifecycleState = MemoryLifecycleState.ACTIVE
    content_hash: str = ""


# ── Episodic (spec §8) ───────────────────────────────────────────────────

@dataclass
class MemoryEpisode(MemoryRecord):
    """Append-only. A correction creates a NEW linked episode
    (superseded_by/derived_from on a later record), never an in-place
    rewrite -- see docs/orneur/phase-5/EPISODIC_LEDGER.md."""
    memory_type: MemoryType = MemoryType.EPISODIC
    actors: list[str] = field(default_factory=list)
    event: str = ""
    context: str = ""
    actions: list[str] = field(default_factory=list)
    observations: list[str] = field(default_factory=list)
    outcome: str = ""


# ── Semantic (spec §14-16) ───────────────────────────────────────────────

@dataclass
class SemanticMemoryRecord(MemoryRecord):
    memory_type: MemoryType = MemoryType.SEMANTIC
    claim: str = ""
    entities: list[str] = field(default_factory=list)
    last_verified_at: str | None = None
    supersedes: str | None = None               # memory_id of the record this replaces
    superseded_by: str | None = None
    contradicts: list[str] = field(default_factory=list)   # memory_ids in an unresolved contradiction with this one


# ── Entity (spec §19) ────────────────────────────────────────────────────

@dataclass
class EntityMemoryRecord(MemoryRecord):
    """Links out to other memory_ids by reference -- never a growing
    mutable JSON blob per entity (spec §19)."""
    memory_type: MemoryType = MemoryType.ENTITY
    entity_name: str = ""
    entity_kind: str = "concept"                 # mirrors orca.brain.knowledge_graph.Entity.entity_type
    semantic_memory_ids: list[str] = field(default_factory=list)
    episode_ids: list[str] = field(default_factory=list)
    procedure_ids: list[str] = field(default_factory=list)
    failure_ids: list[str] = field(default_factory=list)


# ── Procedural (spec §20) ────────────────────────────────────────────────

@dataclass
class ProceduralMemoryRecord(MemoryRecord):
    memory_type: MemoryType = MemoryType.PROCEDURAL
    procedure_id: str = field(default_factory=lambda: _new_id("proc"))
    name: str = ""
    steps: list[str] = field(default_factory=list)
    preconditions: list[str] = field(default_factory=list)
    postconditions: list[str] = field(default_factory=list)
    version: int = 1
    successful_executions: int = 0
    failed_executions: int = 0
    last_verified_at: str | None = None


# ── Failure (spec §21-22) ────────────────────────────────────────────────

@dataclass
class FailureMemoryRecord(MemoryRecord):
    memory_type: MemoryType = MemoryType.FAILURE
    task_context: str = ""
    attempted_strategy: str = ""
    failure_mode: str = ""
    root_cause: str = ""
    correction: str = ""
    regression_test_ref: str | None = None
    verification_state: FailureVerificationState = FailureVerificationState.UNVERIFIED


# ── Working memory (spec §7, bounded, not a persisted MemoryRecord) ──────

@dataclass
class WorkingMemory:
    """Ephemeral cognitive state for the CURRENT request -- not long-term
    storage by default (spec §7). Bounded lists, never the full
    transcript. Promotion to a persisted MemoryEpisode/MemoryCandidate
    happens explicitly at request completion (spec §42), never
    automatically."""
    objective: str = ""
    active_plan_ref: str | None = None
    hypotheses: list[str] = field(default_factory=list)
    entities: list[str] = field(default_factory=list)
    evidence_refs: list[MemoryEvidence] = field(default_factory=list)
    tool_observations: list[str] = field(default_factory=list)
    recalled_memory_ids: list[str] = field(default_factory=list)
    decisions: list[str] = field(default_factory=list)
    unresolved_questions: list[str] = field(default_factory=list)
    next_actions: list[str] = field(default_factory=list)

    MAX_ITEMS_PER_LIST: int = field(default=20, repr=False, compare=False)

    def _bounded_append(self, list_name: str, item: str) -> None:
        lst = getattr(self, list_name)
        lst.append(item)
        if len(lst) > self.MAX_ITEMS_PER_LIST:
            del lst[: len(lst) - self.MAX_ITEMS_PER_LIST]


# ── Candidate pipeline (spec §10) ────────────────────────────────────────

@dataclass
class MemoryCandidate:
    """A candidate is NOT truth (spec §10) -- promotion is a separate,
    explicit decision made by MemoryArbiter, never automatic."""
    candidate_id: str = field(default_factory=lambda: _new_id("cand"))
    source_episode_id: str | None = None
    extracted_claim: str = ""
    entities: list[str] = field(default_factory=list)
    evidence_refs: list[MemoryEvidence] = field(default_factory=list)
    duplicate_of: str | None = None
    duplicate_classification: DuplicateClassification | None = None
    contradiction_of: list[str] = field(default_factory=list)
    scope: MemoryScope = MemoryScope.SESSION
    scope_id: str = ""
    privacy: PrivacyClass = PrivacyClass.STANDARD
    valid_from: str | None = None
    promotion_decision: PromotionDecision = PromotionDecision.DEFERRED
    reasons: list[str] = field(default_factory=list)


# ── Query / recall (spec §33-35) ─────────────────────────────────────────

@dataclass
class MemoryQuery:
    """Structured, typed -- never an arbitrary query string a model could
    generate directly against a store (spec §33, §35)."""
    query_id: str = field(default_factory=lambda: _new_id("mq"))
    scope: MemoryScope = MemoryScope.SESSION
    scope_id: str = ""
    memory_types: list[MemoryType] = field(default_factory=list)
    entity: str | None = None
    time_range: tuple[str, str] | None = None
    epistemic_states: list[EpistemicState] = field(default_factory=list)
    min_evidence_quality: int = 0               # minimum len(evidence_refs) required
    relevance_text: str = ""
    limit: int = 5


@dataclass
class MemoryRecallResult:
    query_id: str
    memories: list[MemoryRecord] = field(default_factory=list)
    stale_memory_ids: list[str] = field(default_factory=list)
    refresh_needed_ids: list[str] = field(default_factory=list)
    latency_ms: float = 0.0


# ── Arbiter / consolidation decisions (spec §18, §24-25) ─────────────────

@dataclass
class MemoryConsolidationResult:
    consolidated_memory_id: str
    derived_from: list[str] = field(default_factory=list)   # episode_ids, NEVER deleted by consolidation
    criteria_matched: list[str] = field(default_factory=list)
    rejected: bool = False
    rejected_reason: str = ""


@dataclass
class MemoryDecision:
    decision_id: str = field(default_factory=lambda: _new_id("dec"))
    decision_type: str = ""    # "PROMOTE" | "REJECT" | "SUPERSEDE" | "ARCHIVE" | "PURGE" | "CONSOLIDATE"
    memory_id: str = ""
    reason: str = ""
    made_by: str = "arbiter"   # "arbiter" | "human" | "policy"
    timestamp: str = field(default_factory=_now_iso)


# ── Trace (spec §45) ─────────────────────────────────────────────────────

@dataclass
class MemoryTrace:
    """Safe, structured metadata only -- never raw stored memory text or
    hidden reasoning (spec §45, §11 of the CLAUDE-facing project rules)."""
    memory_query_id: str | None = None
    memory_ids_recalled: list[str] = field(default_factory=list)
    memory_types: list[str] = field(default_factory=list)
    epistemic_states: list[str] = field(default_factory=list)
    stale_memory_count: int = 0
    refresh_count: int = 0
    promotion_decisions: list[str] = field(default_factory=list)
