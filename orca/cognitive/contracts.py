"""
Typed cognitive contracts -- the normalized shapes the Cognitive Kernel
(orca/cognitive/kernel.py) and its bounded components (intent/complexity/
risk/freshness/evidence classifiers, budget, planner, state machine) pass
between each other. Mirrors orca/gateway/contracts.py's own pattern:
stable dataclasses/enums so callers never need to know which classifier
or policy produced a value, only its documented shape.

None of these types call Ollama, query a vector DB, search the web, or
execute a tool -- they are pure data. Behavior lives in the modules named
after each contract (intent.py, complexity.py, risk.py, ...).
"""
from __future__ import annotations

import uuid
from dataclasses import dataclass, field
from enum import Enum
from typing import Any


def _new_id(prefix: str) -> str:
    return f"{prefix}-{uuid.uuid4().hex[:12]}"


# ── Intent ────────────────────────────────────────────────────────────────

class IntentCategory(str, Enum):
    FACTUAL = "FACTUAL"
    RESEARCH = "RESEARCH"
    REASONING = "REASONING"
    CODING = "CODING"
    PLANNING = "PLANNING"
    TOOL_USE = "TOOL_USE"
    MEMORY_RECALL = "MEMORY_RECALL"
    DOCUMENT_ANALYSIS = "DOCUMENT_ANALYSIS"
    CONVERSATIONAL = "CONVERSATIONAL"
    AGENTIC = "AGENTIC"
    UNKNOWN = "UNKNOWN"


class PrivacyClass(str, Enum):
    """How sensitive the request's own content is -- NOT an authorization
    grant. Purely descriptive; capability/permission decisions remain a
    separate, later (Godmode) system per the Phase 3 spec's §37."""
    STANDARD = "STANDARD"
    SENSITIVE = "SENSITIVE"
    RESTRICTED = "RESTRICTED"


class ExpectedOutputType(str, Enum):
    TEXT = "TEXT"
    CODE = "CODE"
    STRUCTURED_DATA = "STRUCTURED_DATA"
    LIST = "LIST"
    LONG_FORM = "LONG_FORM"


class FreshnessLevel(str, Enum):
    STATIC = "STATIC"              # e.g. math, established facts
    LONG_LIVED = "LONG_LIVED"      # e.g. historical events, stable docs
    RECENT = "RECENT"              # e.g. "this year", slowly-changing topics
    CURRENT = "CURRENT"            # e.g. "latest version", ongoing situations
    REAL_TIME = "REAL_TIME"        # e.g. stock price, breaking news


class EvidenceLevel(str, Enum):
    NONE = "NONE"                  # casual/creative -- no grounding required
    LIGHT = "LIGHT"                # a plausible answer is enough
    SUPPORTED = "SUPPORTED"        # normal factual answer, should be groundable
    STRICT = "STRICT"              # e.g. security/research recommendations
    AUDIT_GRADE = "AUDIT_GRADE"    # high-stakes enterprise evidence report


@dataclass
class FreshnessRequirement:
    level: FreshnessLevel
    reasons: list[str] = field(default_factory=list)


@dataclass
class EvidenceRequirement:
    level: EvidenceLevel
    reasons: list[str] = field(default_factory=list)


@dataclass
class IntentPlan:
    primary_intent: IntentCategory
    secondary_intents: list[IntentCategory] = field(default_factory=list)
    requires_retrieval: bool = False
    requires_search: bool = False
    requires_memory: bool = False
    requires_tools: bool = False
    requires_reasoning: bool = False
    requires_agents: bool = False
    citation_requirement: bool = False
    freshness_requirement: FreshnessRequirement = field(
        default_factory=lambda: FreshnessRequirement(level=FreshnessLevel.STATIC)
    )
    privacy_class: PrivacyClass = PrivacyClass.STANDARD
    expected_output_type: ExpectedOutputType = ExpectedOutputType.TEXT


# ── Complexity / Risk ────────────────────────────────────────────────────

class ComplexityLevel(str, Enum):
    TRIVIAL = "TRIVIAL"
    LOW = "LOW"
    MEDIUM = "MEDIUM"
    HIGH = "HIGH"
    DEEP = "DEEP"


class RiskLevel(str, Enum):
    LOW = "LOW"
    MODERATE = "MODERATE"
    HIGH = "HIGH"
    CRITICAL = "CRITICAL"


@dataclass
class ComplexityAssessment:
    level: ComplexityLevel
    score: float  # deterministic 0.0-1.0, mapped to `level` -- see complexity.py
    factors: list[str] = field(default_factory=list)


@dataclass
class RiskAssessment:
    level: RiskLevel
    factors: list[str] = field(default_factory=list)


# ── Budget ───────────────────────────────────────────────────────────────

class BudgetDimension(str, Enum):
    TOKENS = "TOKENS"
    LATENCY_MS = "LATENCY_MS"
    MODEL_CALLS = "MODEL_CALLS"
    RETRIEVAL_CALLS = "RETRIEVAL_CALLS"
    TOOL_CALLS = "TOOL_CALLS"
    AGENT_CALLS = "AGENT_CALLS"
    COST_USD = "COST_USD"
    REASONING_ROUNDS = "REASONING_ROUNDS"


# Limits are None-able (no cap tracked for that dimension); consumed_*
# fields are mutable ledger state. All validation/consumption logic lives
# in budget.py -- this is pure data, per this module's own charter.
@dataclass
class CognitiveBudget:
    max_tokens: int | None = None
    max_latency_ms: float | None = None
    max_model_calls: int | None = None
    max_retrieval_calls: int | None = None
    max_tool_calls: int | None = None
    max_agent_calls: int | None = None
    max_cost_usd: float | None = None
    max_reasoning_rounds: int | None = None

    consumed_tokens: int = 0
    consumed_latency_ms: float = 0.0
    consumed_model_calls: int = 0
    consumed_retrieval_calls: int = 0
    consumed_tool_calls: int = 0
    consumed_agent_calls: int = 0
    consumed_cost_usd: float = 0.0
    consumed_reasoning_rounds: int = 0


# ── Cognitive Request ────────────────────────────────────────────────────

class LatencyPreference(str, Enum):
    LOWEST = "LOWEST"
    BALANCED = "BALANCED"
    QUALITY_FIRST = "QUALITY_FIRST"


class QualityPreference(str, Enum):
    DRAFT = "DRAFT"
    STANDARD = "STANDARD"
    HIGHEST = "HIGHEST"


@dataclass
class CognitiveRequest:
    """
    Normalizes a user/system objective. Deliberately does NOT carry raw
    infrastructure/runtime settings (model names, hosts, temperatures) --
    those belong to ModelGateway/InferenceRequest, resolved later by model
    policy (see policy.py), not chosen here.
    """
    objective: str
    request_id: str = field(default_factory=lambda: _new_id("creq"))
    trace_id: str = field(default_factory=lambda: _new_id("trace"))
    tenant: str | None = None
    session_id: str | None = None
    context_refs: list[str] = field(default_factory=list)
    requested_mode: str | None = None  # e.g. "chat", "stream", "ultra" -- advisory only
    latency_preference: LatencyPreference = LatencyPreference.BALANCED
    quality_preference: QualityPreference = QualityPreference.STANDARD
    budget_constraints: CognitiveBudget | None = None
    privacy_scope: PrivacyClass = PrivacyClass.STANDARD
    capability_context: dict[str, Any] = field(default_factory=dict)
    metadata: dict[str, Any] = field(default_factory=dict)


# ── Context ──────────────────────────────────────────────────────────────

@dataclass
class CognitiveContext:
    """
    Carries references, not fabricated content. In Phase 3 most of these
    lists are legitimately empty -- Truth Fabric/Memory Continuum/
    Deliberation Fabric don't exist yet, so there is nothing real to put
    here. An empty list is honest; inventing placeholder content would not
    be (see Phase 3 spec §15).
    """
    objective: str
    conversation_ref: str | None = None
    working_context: dict[str, Any] = field(default_factory=dict)
    memory_refs: list[str] = field(default_factory=list)
    evidence_refs: list[str] = field(default_factory=list)
    tool_observations: list[dict[str, Any]] = field(default_factory=list)
    world_state_refs: list[str] = field(default_factory=list)
    capability_context: dict[str, Any] = field(default_factory=dict)


# ── Operations / Plan ────────────────────────────────────────────────────

class OperationType(str, Enum):
    ANSWER_DIRECTLY = "ANSWER_DIRECTLY"
    RETRIEVE = "RETRIEVE"
    SEARCH = "SEARCH"
    RECALL_MEMORY = "RECALL_MEMORY"
    REASON = "REASON"
    USE_TOOL = "USE_TOOL"
    DELEGATE_AGENT = "DELEGATE_AGENT"
    VERIFY = "VERIFY"
    SIMULATE = "SIMULATE"
    ABSTAIN = "ABSTAIN"


class OperationSupportState(str, Enum):
    SUPPORTED_NOW = "SUPPORTED_NOW"
    PLANNED = "PLANNED"
    UNAVAILABLE = "UNAVAILABLE"
    FORBIDDEN = "FORBIDDEN"


@dataclass
class CognitiveOperation:
    type: OperationType
    support_state: OperationSupportState
    detail: str = ""


class ModelPolicyCharacteristic(str, Enum):
    """Desired cognitive characteristics -- NOT a model name. The existing
    router/registry (orca/serve/registry.py) resolves this to an eligible
    deployment; see policy.py. Keeps cognitive intent separate from actual
    model availability (Phase 3 spec §19-20: Aeternum does not exist, do
    not hard-code HIGH -> Aeternum)."""
    FAST = "FAST"
    BALANCED = "BALANCED"
    DEEP = "DEEP"
    CODE = "CODE"
    REASONING = "REASONING"
    VERIFICATION = "VERIFICATION"


@dataclass
class ModelPolicy:
    characteristic: ModelPolicyCharacteristic
    reasons: list[str] = field(default_factory=list)


class CompletionCondition(str, Enum):
    DIRECT_ANSWER_PRODUCED = "DIRECT_ANSWER_PRODUCED"
    EVIDENCE_OBTAINED = "EVIDENCE_OBTAINED"
    VERIFICATION_COMPLETE = "VERIFICATION_COMPLETE"
    OPERATION_UNAVAILABLE_ABSTAIN = "OPERATION_UNAVAILABLE_ABSTAIN"
    BUDGET_EXHAUSTED = "BUDGET_EXHAUSTED"
    MAX_ROUNDS_REACHED = "MAX_ROUNDS_REACHED"


@dataclass
class SubObjective:
    """Bounded, non-recursive decomposition -- see decomposition.py for the
    max-count/max-depth enforcement (Phase 3 spec §22)."""
    sub_objective_id: str
    description: str
    depends_on: list[str] = field(default_factory=list)


@dataclass
class CognitivePlan:
    request_id: str
    trace_id: str
    intent: IntentPlan
    complexity: ComplexityAssessment
    risk: RiskAssessment
    freshness: FreshnessRequirement
    evidence_requirement: EvidenceRequirement
    operations: list[CognitiveOperation]
    model_policy: ModelPolicy
    budget: CognitiveBudget
    completion_conditions: list[CompletionCondition] = field(default_factory=list)
    sub_objectives: list[SubObjective] = field(default_factory=list)
    plan_id: str = field(default_factory=lambda: _new_id("plan"))


# ── Abstention / Result ──────────────────────────────────────────────────

class AbstentionReason(str, Enum):
    INSUFFICIENT_CAPABILITY = "INSUFFICIENT_CAPABILITY"
    INSUFFICIENT_EVIDENCE = "INSUFFICIENT_EVIDENCE"
    BUDGET_EXHAUSTED = "BUDGET_EXHAUSTED"
    MODEL_UNAVAILABLE = "MODEL_UNAVAILABLE"
    REQUIRED_OPERATION_UNAVAILABLE = "REQUIRED_OPERATION_UNAVAILABLE"
    POLICY_RESTRICTION = "POLICY_RESTRICTION"
    AMBIGUOUS_REQUEST = "AMBIGUOUS_REQUEST"


class CognitiveState(str, Enum):
    RECEIVED = "RECEIVED"
    CLASSIFYING = "CLASSIFYING"
    PLANNED = "PLANNED"
    EXECUTING = "EXECUTING"
    WAITING = "WAITING"
    VERIFYING = "VERIFYING"
    COMPLETED = "COMPLETED"
    ABSTAINED = "ABSTAINED"
    FAILED = "FAILED"
    CANCELLED = "CANCELLED"


@dataclass
class CognitiveResult:
    request_id: str
    trace_id: str
    status: CognitiveState
    output: str | None = None
    resolved_model: str | None = None
    resolved_tier: str | None = None
    plan_id: str | None = None
    operations_executed: list[OperationType] = field(default_factory=list)
    abstention_reason: AbstentionReason | None = None
    usage: dict[str, Any] = field(default_factory=dict)
    latency_ms: float = 0.0
    warnings: list[str] = field(default_factory=list)
    # Phase 3.1: entitlement/cognitive-policy reconciliation outcome. Never
    # exposes internal class names -- `degraded`/`degradation_reason` are
    # the stable, user-safe surface (see orca/cognitive/reconciliation.py).
    degraded: bool = False
    degradation_reason: str | None = None
    user_notification_required: bool = False


# ── Trace ────────────────────────────────────────────────────────────────

@dataclass
class StateTransition:
    from_state: CognitiveState
    to_state: CognitiveState
    at_monotonic: float


@dataclass
class CognitiveTrace:
    """
    Structured execution metadata -- the beginning of the Orneur Cognitive
    Flight Recorder (Phase 3 spec §25). Deliberately excludes raw
    chain-of-thought: every field here is a short, structured, auditable
    label, never free-form model reasoning text.
    """
    request_id: str
    trace_id: str
    intent_decision: str | None = None
    complexity: ComplexityLevel | None = None
    risk: RiskLevel | None = None
    freshness: FreshnessLevel | None = None
    evidence_requirement: EvidenceLevel | None = None
    budget_allocated: dict[str, Any] = field(default_factory=dict)
    plan_operations: list[str] = field(default_factory=list)
    model_policy: ModelPolicyCharacteristic | None = None
    model_resolved: str | None = None
    operation_outcomes: list[str] = field(default_factory=list)
    state_transitions: list[StateTransition] = field(default_factory=list)
    abstention_reason: AbstentionReason | None = None
    decision_explanations: list[str] = field(default_factory=list)
    latency_ms: float = 0.0
    resource_consumption: dict[str, Any] = field(default_factory=dict)
    # Phase 3.1: entitlement/reconciliation observability (§19) -- labels
    # only, never raw prompts/user IDs.
    entitlement_ceiling: str | None = None
    effective_capability: str | None = None
    reconciliation_outcome: str | None = None
    resolved_tier: str | None = None
