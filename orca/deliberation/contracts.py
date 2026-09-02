"""
Deliberation Fabric contracts (Phase 6 spec §4). Typed dataclasses, no
behavior -- behavior lives in the modules named after each contract
(compiler.py, hypothesis.py, twin.py, court.py, causal.py,
counterfactual.py, budget_market.py), mirroring the pattern already
established by orca/truth/contracts.py and orca/memory/contracts.py.

Reuses orca.cognitive.contracts (ComplexityLevel, RiskLevel,
EvidenceLevel, CognitiveBudget, AbstentionReason) and
orca.truth.contracts (EvidenceState, ContradictionRelationship) rather
than duplicating vocabulary Phase 3/4 already established.
"""
from __future__ import annotations

import uuid
from dataclasses import dataclass, field
from datetime import datetime, timezone
from enum import Enum
from typing import Any

from orca.cognitive.contracts import ComplexityLevel, EvidenceLevel, RiskLevel


def _new_id(prefix: str) -> str:
    return f"{prefix}-{uuid.uuid4().hex[:12]}"


def _now_iso() -> str:
    return datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")


# ── Reasoning modes (spec §6) ─────────────────────────────────────────────

class ReasoningMode(str, Enum):
    DIRECT = "DIRECT"
    ANALYTICAL = "ANALYTICAL"
    MULTI_HYPOTHESIS = "MULTI_HYPOTHESIS"
    CAUSAL = "CAUSAL"
    COUNTERFACTUAL = "COUNTERFACTUAL"
    DELIBERATIVE = "DELIBERATIVE"
    COURT_REVIEW = "COURT_REVIEW"


# ── Hypothesis space (spec §7) ────────────────────────────────────────────

class HypothesisStatus(str, Enum):
    ACTIVE = "ACTIVE"
    WEAKENED = "WEAKENED"
    SUPPORTED = "SUPPORTED"
    FALSIFIED = "FALSIFIED"
    UNRESOLVED = "UNRESOLVED"


@dataclass
class Hypothesis:
    """Never silently deleted (spec §7) -- a FALSIFIED hypothesis stays
    in the HypothesisSet, status changed, not removed. `origin` records
    WHERE it came from (e.g. "constructor", "falsifier", "compiler")
    for audit, never a claim of independent generation it didn't have."""
    hypothesis_id: str = field(default_factory=lambda: _new_id("hyp"))
    statement: str = ""
    status: HypothesisStatus = HypothesisStatus.ACTIVE
    supporting_evidence_ids: list[str] = field(default_factory=list)
    contradicting_evidence_ids: list[str] = field(default_factory=list)
    assumption_ids: list[str] = field(default_factory=list)
    origin: str = ""
    created_at: str = field(default_factory=_now_iso)
    updated_at: str = field(default_factory=_now_iso)


@dataclass
class HypothesisSet:
    hypotheses: list[Hypothesis] = field(default_factory=list)
    max_hypotheses: int = 4

    def active(self) -> list[Hypothesis]:
        return [h for h in self.hypotheses if h.status in (HypothesisStatus.ACTIVE, HypothesisStatus.WEAKENED, HypothesisStatus.SUPPORTED)]

    def add(self, hypothesis: Hypothesis) -> bool:
        """Bounded (spec §8) -- refuses beyond max_hypotheses rather than
        growing unbounded. Returns whether it was actually added."""
        if len(self.hypotheses) >= self.max_hypotheses:
            return False
        self.hypotheses.append(hypothesis)
        return True


# ── Assumptions (spec §10) ────────────────────────────────────────────────

class AssumptionVerificationState(str, Enum):
    EXPLICITLY_GIVEN = "EXPLICITLY_GIVEN"
    SUPPORTED = "SUPPORTED"
    UNVERIFIED = "UNVERIFIED"
    CONTESTED = "CONTESTED"
    DISPROVEN = "DISPROVEN"


@dataclass
class Assumption:
    assumption_id: str = field(default_factory=lambda: _new_id("assum"))
    statement: str = ""
    source: str = ""                       # "user" | "constructor" | "falsifier" | "compiler"
    required_for: list[str] = field(default_factory=list)   # hypothesis_ids / argument_ids depending on this
    verification_state: AssumptionVerificationState = AssumptionVerificationState.UNVERIFIED


# ── Evidence needs (spec §9) ──────────────────────────────────────────────

@dataclass
class EvidenceNeed:
    """"What observation would distinguish these hypotheses?" -- spec §9.
    Not more prose; a structured request Truth Fabric/tools can act on."""
    need_id: str = field(default_factory=lambda: _new_id("need"))
    question: str = ""
    distinguishes_hypothesis_ids: list[str] = field(default_factory=list)
    satisfied: bool = False
    satisfying_evidence_ids: list[str] = field(default_factory=list)


# ── Arguments (Constructor/Falsifier output units) ───────────────────────

@dataclass
class Argument:
    argument_id: str = field(default_factory=lambda: _new_id("arg"))
    claim: str = ""
    evidence_ids: list[str] = field(default_factory=list)
    hypothesis_id: str | None = None
    role: str = "constructor"


@dataclass
class CounterArgument:
    counter_argument_id: str = field(default_factory=lambda: _new_id("carg"))
    target_argument_id: str = ""
    objection: str = ""
    objection_kind: str = ""   # "counter_evidence" | "missing_assumption" | "edge_case" | "contradiction" | "alternative_explanation" | "temporal_scope_mismatch" | "unsupported_inference"
    counter_evidence_ids: list[str] = field(default_factory=list)


# ── Causal reasoning (spec §23-24) ────────────────────────────────────────

class CausalRelationType(str, Enum):
    CAUSES = "CAUSES"
    CONTRIBUTES_TO = "CONTRIBUTES_TO"
    CORRELATES_WITH = "CORRELATES_WITH"
    PREVENTS = "PREVENTS"
    UNKNOWN = "UNKNOWN"


@dataclass
class CausalRelation:
    relation_id: str = field(default_factory=lambda: _new_id("causal"))
    cause: str = ""
    effect: str = ""
    relationship_type: CausalRelationType = CausalRelationType.UNKNOWN
    evidence_ids: list[str] = field(default_factory=list)
    assumption_ids: list[str] = field(default_factory=list)
    confidence: float | None = None


# ── Counterfactuals (spec §25) ────────────────────────────────────────────

@dataclass
class Counterfactual:
    counterfactual_id: str = field(default_factory=lambda: _new_id("cf"))
    baseline_state: str = ""
    changed_variable: str = ""
    held_constant: list[str] = field(default_factory=list)
    predicted_consequence: str = ""
    uncertainty_note: str = ""     # never presented as observed fact -- spec §25


# ── World state (spec §26) ────────────────────────────────────────────────

@dataclass
class WorldState:
    """Request/task-scoped, never a giant global mutable model (spec §26)."""
    world_state_id: str = field(default_factory=lambda: _new_id("ws"))
    entities: list[str] = field(default_factory=list)
    known_facts: list[str] = field(default_factory=list)
    memory_refs: list[str] = field(default_factory=list)
    evidence_refs: list[str] = field(default_factory=list)
    variables: dict[str, Any] = field(default_factory=dict)
    assumption_ids: list[str] = field(default_factory=list)
    as_of: str = field(default_factory=_now_iso)
    constraints: list[str] = field(default_factory=list)


# ── Reasoning compiler I/O (spec §5) ──────────────────────────────────────

@dataclass
class ReasoningRequest:
    request_id: str = field(default_factory=lambda: _new_id("rreq"))
    objective: str = ""
    complexity: ComplexityLevel = ComplexityLevel.LOW
    risk: RiskLevel = RiskLevel.LOW
    evidence_requirement: EvidenceLevel = EvidenceLevel.SUPPORTED
    trace_id: str | None = None


@dataclass
class ReasoningPlan:
    plan_id: str = field(default_factory=lambda: _new_id("rplan"))
    goal: str = ""
    mode: ReasoningMode = ReasoningMode.DIRECT
    subproblems: list[str] = field(default_factory=list)
    requires_hypotheses: bool = False
    evidence_needs: list[EvidenceNeed] = field(default_factory=list)
    requires_falsification: bool = False
    requires_counterfactual: bool = False
    requires_court: bool = False
    max_rounds: int = 1
    max_hypotheses: int = 4
    model_policy_hint: str = "BALANCED"
    completion_conditions: list[str] = field(default_factory=list)
    reasons: list[str] = field(default_factory=list)


# ── Deliberation rounds / Twin / Court (spec §11-19) ──────────────────────

@dataclass
class DeliberationRound:
    round_index: int = 0
    arguments: list[Argument] = field(default_factory=list)
    counter_arguments: list[CounterArgument] = field(default_factory=list)
    hypotheses_updated: list[str] = field(default_factory=list)
    stop_reason: str = ""


class CourtRole(str, Enum):
    CONSTRUCTOR = "CONSTRUCTOR"
    FALSIFIER = "FALSIFIER"
    EVIDENCE_CLERK = "EVIDENCE_CLERK"
    RISK_COUNSEL = "RISK_COUNSEL"
    ARBITER = "ARBITER"


@dataclass
class RoleExecution:
    """Spec §21: records WHICH model actually served a role, since
    current model availability means role separation is often
    same-model -- never silently implied as independent intelligence."""
    role: CourtRole = CourtRole.CONSTRUCTOR
    model_id: str = ""
    model_version: str = ""
    latency_ms: float = 0.0


@dataclass
class TwinResult:
    """Spec §13 -- never reduced to "critic says OK."."""
    constructor_claims: list[Argument] = field(default_factory=list)
    falsifier_objections: list[CounterArgument] = field(default_factory=list)
    counter_evidence_ids: list[str] = field(default_factory=list)
    unsupported_assumption_ids: list[str] = field(default_factory=list)
    disputed_claim_ids: list[str] = field(default_factory=list)
    surviving_claim_ids: list[str] = field(default_factory=list)
    unresolved_questions: list[str] = field(default_factory=list)
    role_executions: list[RoleExecution] = field(default_factory=list)


class CourtVerdictState(str, Enum):
    ACCEPT = "ACCEPT"
    REVISE = "REVISE"
    REJECT = "REJECT"
    INSUFFICIENT_EVIDENCE = "INSUFFICIENT_EVIDENCE"


@dataclass
class CourtCase:
    case_id: str = field(default_factory=lambda: _new_id("case"))
    objective: str = ""
    hypotheses: HypothesisSet = field(default_factory=HypothesisSet)
    assumptions: list[Assumption] = field(default_factory=list)
    arguments: list[Argument] = field(default_factory=list)
    counter_arguments: list[CounterArgument] = field(default_factory=list)
    contradictions: list[Any] = field(default_factory=list)  # orca.truth.contracts.Contradiction, loosely typed to avoid a hard import cycle
    evidence_state: str | None = None       # orca.truth.contracts.EvidenceState.value, copied not re-derived
    risk_level: RiskLevel = RiskLevel.LOW
    rounds: list[DeliberationRound] = field(default_factory=list)
    role_executions: list[RoleExecution] = field(default_factory=list)


@dataclass
class CourtVerdict:
    """No raw private chain-of-thought (spec §19)."""
    verdict_id: str = field(default_factory=lambda: _new_id("verdict"))
    verdict: CourtVerdictState = CourtVerdictState.INSUFFICIENT_EVIDENCE
    accepted_claim_ids: list[str] = field(default_factory=list)
    rejected_claim_ids: list[str] = field(default_factory=list)
    unresolved_claim_ids: list[str] = field(default_factory=list)
    required_revision: str = ""
    evidence_state: str | None = None
    risk_state: str = ""
    decision_reasons: list[str] = field(default_factory=list)
    confidence: float | None = None
    epistemic_state: str = "UNVERIFIED"


@dataclass
class ArbitrationResult:
    verdict: CourtVerdict = field(default_factory=CourtVerdict)
    stop_reason: str = ""
    budget_consumed: dict[str, Any] = field(default_factory=dict)


# ── Trace / final result (spec §44-45) ────────────────────────────────────

@dataclass
class DeliberationTrace:
    """Structured flight-recorder metadata only -- never unrestricted
    private reasoning prose (spec §45)."""
    reasoning_plan_id: str | None = None
    mode: str | None = None
    hypothesis_transitions: list[str] = field(default_factory=list)
    evidence_need_ids: list[str] = field(default_factory=list)
    role_executions: list[RoleExecution] = field(default_factory=list)
    verdict: str | None = None
    replan_events: list[str] = field(default_factory=list)
    budget_decisions: list[str] = field(default_factory=list)
    round_count: int = 0
    stop_reason: str = ""
    latency_ms: float = 0.0


@dataclass
class DecisionManifest:
    """Spec §44 -- no raw private chain-of-thought."""
    request_id: str = ""
    trace_id: str | None = None
    reasoning_plan_id: str | None = None
    hypothesis_ids: list[str] = field(default_factory=list)
    evidence_graph_id: str | None = None
    memory_refs: list[str] = field(default_factory=list)
    constructor_claim_ids: list[str] = field(default_factory=list)
    falsifier_objection_ids: list[str] = field(default_factory=list)
    court_verdict: str | None = None
    risk_state: str = ""
    budget_usage: dict[str, Any] = field(default_factory=dict)
    models_used: dict[str, str] = field(default_factory=dict)   # role -> model_id
    stop_reason: str = ""


@dataclass
class DeliberationResult:
    request_id: str = ""
    trace_id: str | None = None
    mode: ReasoningMode = ReasoningMode.DIRECT
    output_text: str | None = None
    hypotheses: HypothesisSet = field(default_factory=HypothesisSet)
    court_verdict: CourtVerdict | None = None
    decision_manifest: DecisionManifest | None = None
    abstention_reason: str | None = None
    stop_reason: str = ""
    latency_ms: float = 0.0
