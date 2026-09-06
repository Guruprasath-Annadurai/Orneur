"""
Model Society typed contracts (Phase 7 spec §4). Cognitive role is NOT
model identity and NOT model size (spec §2) -- these dataclasses exist so
that fact is enforced structurally: a `RoutingRequest` names a
`CognitiveRole` and a `RoleRequirement`, never a model name; a
`RoutingDecision` records WHY a specific model/deployment was chosen, with
structured rejection reasons for every candidate that wasn't, never a
free-text justification. No dataclass here carries a raw-chain-of-thought
field, matching the discipline established in
`orca/deliberation/contracts.py`.
"""
from __future__ import annotations

import uuid
from dataclasses import dataclass, field
from datetime import datetime, timezone
from enum import Enum
from typing import Any


def _new_id(prefix: str) -> str:
    return f"{prefix}-{uuid.uuid4().hex[:12]}"


def _now_iso() -> str:
    return datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")


# ── Cognitive roles (spec §5) ──────────────────────────────────────────────

class CognitiveRole(str, Enum):
    """Stable role concepts. A role describes what cognitive work is
    needed, never which model performs it (spec §2, §5)."""
    FAST_RESPONDER = "FAST_RESPONDER"
    INTENT_COMPILER = "INTENT_COMPILER"
    RETRIEVAL_PLANNER = "RETRIEVAL_PLANNER"
    QUERY_REWRITER = "QUERY_REWRITER"
    CLAIM_EXTRACTOR = "CLAIM_EXTRACTOR"
    MEMORY_SELECTOR = "MEMORY_SELECTOR"
    CONSTRUCTOR = "CONSTRUCTOR"
    FALSIFIER = "FALSIFIER"
    VERIFIER = "VERIFIER"
    CODER = "CODER"
    TOOL_REASONER = "TOOL_REASONER"
    CAUSAL_REASONER = "CAUSAL_REASONER"
    COUNTERFACTUAL_REASONER = "COUNTERFACTUAL_REASONER"
    SUMMARIZER = "SUMMARIZER"
    ARBITRATION_SUPPORT = "ARBITRATION_SUPPORT"


# ── Model capability profile (spec §7-9) ────────────────────────────────────

class ProfileState(str, Enum):
    """Missing data is never treated as neutral/pass (spec §9)."""
    MEASURED = "MEASURED"
    PARTIALLY_MEASURED = "PARTIALLY_MEASURED"
    UNMEASURED = "UNMEASURED"
    STALE = "STALE"
    DISQUALIFIED = "DISQUALIFIED"


UNMEASURED = "UNMEASURED"  # sentinel for an individual capability score, matching
                           # orca.registry.evaluation_registry.UNMEASURED exactly


@dataclass
class ModelCapability:
    """A single measured (or explicitly unmeasured) capability claim.
    Spec §8: "good falsifier" must never exist merely as a bare float --
    it must carry the evidence lineage that produced it, or be UNMEASURED."""
    role: CognitiveRole
    score: float | str = UNMEASURED     # float in [0,1], or the UNMEASURED sentinel
    evaluation_ids: list[str] = field(default_factory=list)
    evidence_note: str = ""

    @property
    def is_measured(self) -> bool:
        return isinstance(self.score, (int, float))


@dataclass
class ModelLimitation:
    description: str
    evaluation_ids: list[str] = field(default_factory=list)
    severity: str = "MODERATE"   # "MINOR" | "MODERATE" | "SEVERE"


@dataclass
class ModelCapabilityProfile:
    model_id: str                 # canonical family/checkpoint identifier, e.g. "orneur-novus"
    checkpoint_id: str             # exact checkpoint, e.g. "orca-core-combined-v2" -- never collapsed with a future canonical target (spec §48)
    display_name: str = ""
    lifecycle_state: str = "EXPERIMENTAL"
    profile_state: ProfileState = ProfileState.UNMEASURED
    capabilities: dict[str, ModelCapability] = field(default_factory=dict)   # CognitiveRole.value -> ModelCapability
    limitations: list[ModelLimitation] = field(default_factory=list)
    context_length: int | None = None
    structured_output_reliability: float | str = UNMEASURED
    safety_status: str = UNMEASURED
    calibration_status: float | str = UNMEASURED
    cost_class: str = "LOCAL_SELF_HOSTED"   # descriptive resource class, never a fabricated dollar figure (spec §65)
    domain_strengths: list[str] = field(default_factory=list)
    known_weaknesses: list[str] = field(default_factory=list)
    last_evaluated_at: str | None = None
    evidence_note: str = ""

    def capability_for(self, role: CognitiveRole) -> ModelCapability:
        return self.capabilities.get(role.value, ModelCapability(role=role))


# ── Role requirements (spec §6) ─────────────────────────────────────────────

@dataclass
class RoleRequirement:
    """What a role NEEDS, never which model to use (spec §6)."""
    role: CognitiveRole
    min_lifecycle_rank: int = 0          # see orca.society.lifecycle_rank -- 0 = EXPERIMENTAL allowed
    latency_sensitive: bool = False
    min_context_tokens: int = 2048
    requires_structured_output: bool = False
    requires_reasoning: bool = False
    requires_verification: bool = False
    requires_tool_calling: bool = False
    requires_streaming: bool = False
    cost_sensitive: bool = True
    risk_sensitive: bool = False
    evidence_sensitive: bool = False


# ── Routing request/candidate/decision (spec §11-16) ────────────────────────

@dataclass
class RoutingRequest:
    role: CognitiveRole
    request_id: str = field(default_factory=lambda: _new_id("rreq"))
    trace_id: str | None = None
    risk_level: str = "LOW"
    complexity_level: str = "LOW"
    evidence_requirement: str = "SUPPORTED"
    freshness_required: bool = False
    latency_budget_ms: float | None = None
    cost_sensitive: bool = True
    allowed_capability_classes: list[str] = field(default_factory=list)   # CapabilityClass values the caller is entitled to
    allow_experimental: bool = False          # only true for EVALUATION-priority workloads (spec §38)
    required_runtime_capabilities: list[str] = field(default_factory=list)
    exclude_model_ids: list[str] = field(default_factory=list)   # e.g. Constructor's own model, when Falsifier wants a different one


class RoutingReason(str, Enum):
    """Concise structured reasons (spec §16) -- never free-form hidden
    reasoning."""
    SELECTED = "SELECTED"
    NOVUS_REJECTED_LIFECYCLE = "NOVUS_REJECTED_LIFECYCLE"
    AETERNUM_ABSENT = "AETERNUM_ABSENT"
    LEGACY_GENESIS_SELECTED_FOR_FAST_ROLE = "LEGACY_GENESIS_SELECTED_FOR_FAST_ROLE"
    CONTEXT_REQUIREMENT_UNMET = "CONTEXT_REQUIREMENT_UNMET"
    ENTITLEMENT_LIMIT = "ENTITLEMENT_LIMIT"
    LOW_LATENCY_PREFERENCE = "LOW_LATENCY_PREFERENCE"
    VERIFICATION_QUALITY_PREFERRED = "VERIFICATION_QUALITY_PREFERRED"
    ARTIFACT_UNAVAILABLE = "ARTIFACT_UNAVAILABLE"
    DEPLOYMENT_UNHEALTHY = "DEPLOYMENT_UNHEALTHY"
    CIRCUIT_OPEN = "CIRCUIT_OPEN"
    LIFECYCLE_DISQUALIFIED = "LIFECYCLE_DISQUALIFIED"
    EXCLUDED_BY_CALLER = "EXCLUDED_BY_CALLER"
    NO_ELIGIBLE_CANDIDATE = "NO_ELIGIBLE_CANDIDATE"
    ROLE_UNSUPPORTED = "ROLE_UNSUPPORTED"
    COST_PREFERRED_SUFFICIENT_CANDIDATE = "COST_PREFERRED_SUFFICIENT_CANDIDATE"


@dataclass
class RoutingCandidate:
    model_id: str
    checkpoint_id: str
    profile: ModelCapabilityProfile
    deployment_id: str | None = None
    eligible: bool = True
    rejection_reasons: list[RoutingReason] = field(default_factory=list)
    score: float = 0.0
    score_breakdown: dict[str, float] = field(default_factory=dict)


@dataclass
class RoutingOutcome:
    """Recorded after a role execution actually happens (spec §34)."""
    routing_decision_id: str = ""
    role: CognitiveRole = CognitiveRole.FAST_RESPONDER
    model_id: str = ""
    checkpoint_id: str = ""
    success: bool = True
    latency_ms: float = 0.0
    structured_output_valid: bool = True
    verification_outcome: str | None = None
    falsifier_useful: bool | None = None
    error_class: str | None = None
    budget_consumed: dict[str, Any] = field(default_factory=dict)
    timestamp: str = field(default_factory=_now_iso)


@dataclass
class RoutingDecision:
    decision_id: str = field(default_factory=lambda: _new_id("route"))
    requested_role: CognitiveRole = CognitiveRole.FAST_RESPONDER
    eligible_candidates: list[str] = field(default_factory=list)     # checkpoint_ids
    rejected_candidates: list[str] = field(default_factory=list)     # checkpoint_ids
    rejection_reasons: dict[str, list[str]] = field(default_factory=dict)  # checkpoint_id -> [RoutingReason.value]
    selected_model_id: str | None = None
    selected_checkpoint_id: str | None = None
    selected_deployment_id: str | None = None
    capability_evidence: list[str] = field(default_factory=list)     # evaluation_ids backing the selection
    degraded: bool = False
    same_model_role_overlap: bool = False
    escalation_status: str = "NONE"    # "NONE" | "ESCALATED" | "DE_ESCALATED"
    budget_impact: dict[str, Any] = field(default_factory=dict)
    trace_id: str | None = None
    reasons: list[str] = field(default_factory=list)
    outcome: RoutingOutcome | None = None


# ── Society plan (spec §17-18) ──────────────────────────────────────────────

@dataclass
class RoleAssignment:
    role: CognitiveRole
    routing_decision: RoutingDecision


@dataclass
class SocietyPlan:
    plan_id: str = field(default_factory=lambda: _new_id("splan"))
    assignments: list[RoleAssignment] = field(default_factory=list)
    parallelizable_groups: list[list[str]] = field(default_factory=list)   # groups of CognitiveRole.value that may run concurrently
    dependencies: dict[str, list[str]] = field(default_factory=dict)        # role.value -> [role.value it depends on]
    fallbacks: dict[str, str] = field(default_factory=dict)                 # role.value -> fallback note
    escalation_conditions: list[str] = field(default_factory=list)
    same_model_role_overlap: bool = False


# ── Disagreement (spec §19-20) ───────────────────────────────────────────────

class DisagreementType(str, Enum):
    CLAIM_CONFLICT = "CLAIM_CONFLICT"
    ASSUMPTION_CONFLICT = "ASSUMPTION_CONFLICT"
    EVIDENCE_INTERPRETATION_CONFLICT = "EVIDENCE_INTERPRETATION_CONFLICT"
    CAUSAL_CONFLICT = "CAUSAL_CONFLICT"
    TEMPORAL_CONFLICT = "TEMPORAL_CONFLICT"
    RISK_CONFLICT = "RISK_CONFLICT"
    NO_MEANINGFUL_DISAGREEMENT = "NO_MEANINGFUL_DISAGREEMENT"


@dataclass
class DisagreementSignal:
    types: list[DisagreementType] = field(default_factory=list)
    disputed_claim_ids: list[str] = field(default_factory=list)
    disputed_assumption_ids: list[str] = field(default_factory=list)
    severity: str = "NONE"   # "NONE" | "LOW" | "MODERATE" | "HIGH"
    notes: list[str] = field(default_factory=list)

    @property
    def has_meaningful_disagreement(self) -> bool:
        return bool(self.types) and self.types != [DisagreementType.NO_MEANINGFUL_DISAGREEMENT]


# ── Escalation (spec §21-23) ─────────────────────────────────────────────────

class EscalationAction(str, Enum):
    NONE = "NONE"
    ESCALATE = "ESCALATE"
    DE_ESCALATE = "DE_ESCALATE"
    ABSTAIN_NO_CAPABLE_MODEL = "ABSTAIN_NO_CAPABLE_MODEL"


@dataclass
class EscalationDecision:
    action: EscalationAction = EscalationAction.NONE
    target_requirement: str | None = None   # a RoleRequirement-shaped capability tier, e.g. "DEEP_REASONING" -- never a hardcoded model name (spec §22)
    reasons: list[str] = field(default_factory=list)


# ── Routing trace (spec §57) ─────────────────────────────────────────────────

@dataclass
class RoutingTrace:
    routing_decision_ids: list[str] = field(default_factory=list)
    role_assignments: dict[str, str] = field(default_factory=dict)   # role.value -> model_id
    checkpoints_used: dict[str, str] = field(default_factory=dict)   # role.value -> checkpoint_id
    rejection_reasons: dict[str, list[str]] = field(default_factory=dict)
    budget_allocation: dict[str, float] = field(default_factory=dict)
    escalations: list[str] = field(default_factory=list)
    fallbacks: list[str] = field(default_factory=list)
    plan_revisions: list[str] = field(default_factory=list)
    world_state_ref: str | None = None
