"""ORNEUR Core Intelligence Protocol (stable, model-independent contracts).

Frozen dataclasses plus ``problems()`` validators. Nothing here names a model
family, a parameter count, or a neural architecture: models are replaceable
organs behind these interfaces. This module implements contracts only; it
does not implement any subsystem.
"""
from __future__ import annotations

import hashlib
import json
import re
from dataclasses import asdict, dataclass, field, replace
from enum import Enum
from typing import Any, Mapping, Optional, Sequence

PROTOCOL_VERSION = "orneur.core-protocol/1.0.0"
_SHA256 = re.compile(r"^[0-9a-f]{64}$")
_OPEN_NAME = re.compile(r"^(FUTURE:)?[A-Za-z][A-Za-z0-9_.\-]{0,63}$")


class ProtocolViolation(ValueError):
    """Raised by ``assert_valid``; carries every problem found."""

    def __init__(self, kind: str, problems: Sequence[str]):
        super().__init__(f"{kind}: " + "; ".join(problems))
        self.kind, self.problems = kind, tuple(problems)


class _Contract:
    def problems(self) -> list[str]:  # pragma: no cover - overridden
        return []

    def assert_valid(self) -> "_Contract":
        found = self.problems()
        if found:
            raise ProtocolViolation(type(self).__name__, found)
        return self

    def to_dict(self) -> dict[str, Any]:
        return json.loads(json.dumps(asdict(self), default=lambda o: o.value if isinstance(o, Enum) else str(o)))

    def digest(self) -> str:
        blob = json.dumps(self.to_dict(), sort_keys=True, separators=(",", ":"), ensure_ascii=False)
        return hashlib.sha256(blob.encode()).hexdigest()


def _blank(v: Any) -> bool:
    return v is None or (isinstance(v, str) and not v.strip())


def _need(obj: Any, names: Sequence[str], out: list[str]) -> None:
    for n in names:
        v = getattr(obj, n)
        if _blank(v) or (isinstance(v, (tuple, list, dict)) and not v):
            out.append(f"{n} is required")


def _unit(name: str, v: Any, out: list[str]) -> None:
    if not isinstance(v, (int, float)) or isinstance(v, bool) or not 0.0 <= float(v) <= 1.0:
        out.append(f"{name} must be within [0, 1]")


# ---------------------------------------------------------------- enums
class ComputeMode(str, Enum):
    FAST = "FAST"
    REASON = "REASON"
    FRONTIER = "FRONTIER"


class CounterEvidenceStatus(str, Enum):
    SEARCHED_FOUND = "SEARCHED_FOUND"
    SEARCHED_NONE_FOUND = "SEARCHED_NONE_FOUND"
    NOT_SEARCHED = "NOT_SEARCHED"


class DiscoveryOutcome(str, Enum):
    PROPOSED = "PROPOSED"
    UNDER_TEST = "UNDER_TEST"
    CONFIRMED = "CONFIRMED"
    FALSIFIED = "FALSIFIED"
    ACTED_ON = "ACTED_ON"
    EXPIRED = "EXPIRED"


class HypothesisVerdict(str, Enum):
    UNTESTED = "UNTESTED"
    SUPPORTED = "SUPPORTED"
    FALSIFIED = "FALSIFIED"
    INCONCLUSIVE = "INCONCLUSIVE"


class QualificationState(str, Enum):
    CANDIDATE = "CANDIDATE"
    SHADOW = "SHADOW"
    QUALIFIED = "QUALIFIED"
    RETIRED = "RETIRED"


class OutcomeSource(str, Enum):
    OBSERVED_WORLD_STATE = "OBSERVED_WORLD_STATE"
    MEASURED_METRIC = "MEASURED_METRIC"
    TOOL_RESULT = "TOOL_RESULT"
    USER_PREFERENCE = "USER_PREFERENCE"  # never a valid Outcome source


class PromotionVerdict(str, Enum):
    PROMOTE = "PROMOTE"
    REJECT = "REJECT"
    HOLD = "HOLD"


class MigrationAsset(str, Enum):
    DATASETS = "datasets"
    EVAL_SUITES = "eval_suites"
    EXPERTS = "experts"
    MEMORY_SCHEMAS = "memory_schemas"
    WORLD_MODELS = "world_models"
    DISCOVERY_HISTORY = "discovery_history"
    OUTCOME_HISTORY = "outcome_history"
    FAILURE_GENOME = "failure_genome"
    COGNITIVE_PRIMITIVES = "cognitive_primitives"
    ROUTER_BEHAVIOR = "router_behavior"
    AUTHORITY_EVIDENCE_CONTRACTS = "authority_evidence_contracts"


class MigrationMechanism(str, Enum):
    DISTILLATION = "distillation"
    CONTINUED_TRAINING = "continued_training"
    REPRESENTATION_CONVERSION = "representation_conversion"
    ADAPTER_CONVERSION = "adapter_conversion"
    REINDEXING = "reindexing"
    REPLAY = "replay"
    SHADOW_COMPARISON = "shadow_comparison"
    DUAL_RUNNING = "dual_running"
    EVAL_PRESERVING_CUTOVER = "eval_preserving_cutover"
    NO_CHANGE_REQUIRED = "no_change_required"


# ---------------------------------------------------------------- evidence
@dataclass(frozen=True)
class EvidenceReference(_Contract):
    ref_id: str
    kind: str
    source_uri: str
    content_digest: str
    retrieved_at: str
    tenant_id: str

    def problems(self) -> list[str]:
        out: list[str] = []
        _need(self, ["ref_id", "kind", "source_uri", "retrieved_at", "tenant_id"], out)
        if not _SHA256.match(self.content_digest or ""):
            out.append("content_digest must be a lowercase sha256 hex digest")
        return out


# ---------------------------------------------------------------- objectives / world
@dataclass(frozen=True)
class Objective(_Contract):
    objective_id: str
    tenant_id: str
    statement: str
    success_metrics: tuple[str, ...]
    constraints: tuple[str, ...] = ()
    parent_objective_id: Optional[str] = None
    status: str = "ACTIVE"
    revision: int = 0
    created_at: str = ""

    def problems(self) -> list[str]:
        out: list[str] = []
        _need(self, ["objective_id", "tenant_id", "statement", "success_metrics", "created_at"], out)
        if self.status not in {"ACTIVE", "PAUSED", "ACHIEVED", "ABANDONED"}:
            out.append("status must be ACTIVE|PAUSED|ACHIEVED|ABANDONED")
        if self.revision < 0:
            out.append("revision must be >= 0")
        return out


@dataclass(frozen=True)
class WorldState(_Contract):
    """One immutable WorldModelVersion (V_n). State content is referenced by digest."""

    world_id: str
    tenant_id: str
    version: int
    parent_version: Optional[int]
    content_digest: str
    created_at: str
    protocol_version: str = PROTOCOL_VERSION

    def problems(self) -> list[str]:
        out: list[str] = []
        _need(self, ["world_id", "tenant_id", "created_at"], out)
        if not _SHA256.match(self.content_digest or ""):
            out.append("content_digest must be sha256 hex")
        if self.version < 0:
            out.append("version must be >= 0")
        if (self.version == 0) != (self.parent_version is None):
            out.append("parent_version is None exactly when version == 0")
        elif self.parent_version is not None and self.parent_version != self.version - 1:
            out.append("parent_version must equal version - 1")
        return out


WORLD_CHANGE_KINDS = frozenset({"ADD", "UPDATE", "REMOVE", "RETRACT"})


@dataclass(frozen=True)
class WorldDelta(_Contract):
    """Explicit V_n + evidence -> V_n+1 transition. Every change cites evidence."""

    delta_id: str
    world_id: str
    tenant_id: str
    base_version: int
    result_version: int
    changes: tuple[Mapping[str, Any], ...]
    created_at: str

    def problems(self) -> list[str]:
        out: list[str] = []
        _need(self, ["delta_id", "world_id", "tenant_id", "changes", "created_at"], out)
        if self.result_version != self.base_version + 1:
            out.append("result_version must equal base_version + 1")
        for i, c in enumerate(self.changes):
            if c.get("kind") not in WORLD_CHANGE_KINDS:
                out.append(f"changes[{i}].kind must be one of {sorted(WORLD_CHANGE_KINDS)}")
            if _blank(c.get("target_ref")):
                out.append(f"changes[{i}].target_ref is required")
            if not c.get("evidence_refs"):
                out.append(f"changes[{i}].evidence_refs is required")
        return out


def propagate_delta(edges: Mapping[str, Sequence[str]], node_kinds: Mapping[str, str],
                    changed: Sequence[str]) -> dict[str, list[str]]:
    """World Delta -> dependency graph -> assumptions -> conclusions -> objectives.

    ``edges[x]`` lists nodes that DEPEND ON x. ``node_kinds`` maps node -> one of
    ``assumption|conclusion|objective|other``. Returns impacted nodes grouped by kind
    (sorted, deterministic) so selective re-verification can be scheduled.
    """
    seen: set[str] = set()
    stack = list(changed)
    while stack:
        n = stack.pop()
        for dep in edges.get(n, ()):
            if dep not in seen:
                seen.add(dep)
                stack.append(dep)
    grouped: dict[str, list[str]] = {"assumption": [], "conclusion": [], "objective": [], "other": []}
    for n in sorted(seen):
        k = node_kinds.get(n, "other")
        grouped[k if k in grouped else "other"].append(n)
    return grouped


# ---------------------------------------------------------------- discovery / hypothesis
DISCOVERY_TYPES = frozenset({"OPPORTUNITY", "RISK", "CONTRADICTION", "WEAK_SIGNAL", "UNEXPECTED_CONNECTION",
                             "NOVEL_HYPOTHESIS", "MISSING_INFORMATION", "INVALIDATED_CONCLUSION",
                             "CROSS_DOMAIN_TRANSFER"})


@dataclass(frozen=True)
class Discovery(_Contract):
    discovery_id: str
    objective_id: str
    discovery_type: str
    statement: str
    why_non_obvious: str
    evidence_refs: tuple[str, ...]
    counter_evidence_refs: tuple[str, ...]
    counter_evidence_status: CounterEvidenceStatus
    assumptions: tuple[str, ...]
    confidence: float
    estimated_importance: float
    falsification_condition: str
    suggested_experiment: str
    potential_action: str
    affected_prior_decisions: tuple[str, ...]
    outcome_status: DiscoveryOutcome
    created_at: str
    updated_at: str
    tenant_id: str = ""
    revision: int = 0
    parent_digest: Optional[str] = None

    def problems(self) -> list[str]:
        out: list[str] = []
        _need(self, ["discovery_id", "objective_id", "statement", "why_non_obvious", "evidence_refs",
                     "falsification_condition", "created_at", "updated_at", "tenant_id"], out)
        if self.discovery_type not in DISCOVERY_TYPES:
            out.append(f"discovery_type must be one of {sorted(DISCOVERY_TYPES)}")
        _unit("confidence", self.confidence, out)
        _unit("estimated_importance", self.estimated_importance, out)
        st = self.counter_evidence_status
        if st is CounterEvidenceStatus.SEARCHED_FOUND and not self.counter_evidence_refs:
            out.append("counter_evidence_refs required when counter_evidence_status is SEARCHED_FOUND")
        if st is CounterEvidenceStatus.SEARCHED_NONE_FOUND and self.counter_evidence_refs:
            out.append("counter_evidence_refs must be empty when SEARCHED_NONE_FOUND")
        if st is CounterEvidenceStatus.NOT_SEARCHED:
            if isinstance(self.confidence, (int, float)) and self.confidence > 0.5:
                out.append("confidence is capped at 0.5 while counter-evidence has not been searched")
            if self.outcome_status in {DiscoveryOutcome.CONFIRMED, DiscoveryOutcome.ACTED_ON}:
                out.append("a discovery cannot be CONFIRMED/ACTED_ON before counter-evidence is searched")
        if self.revision < 0 or (self.revision == 0) != (self.parent_digest is None):
            out.append("parent_digest is None exactly when revision == 0")
        return out

    def revise(self, updated_at: str, **changes: Any) -> "Discovery":
        """Immutable update: returns a new revision that chains to this one's digest."""
        return replace(self, updated_at=updated_at, revision=self.revision + 1,
                       parent_digest=self.digest(), **changes)


@dataclass(frozen=True)
class Hypothesis(_Contract):
    hypothesis_id: str
    tenant_id: str
    statement: str
    supporting_evidence_refs: tuple[str, ...]
    counter_evidence_refs: tuple[str, ...]
    assumptions: tuple[str, ...]
    prediction: str
    falsification_test: str
    experiment_ref: Optional[str] = None
    simulation_ref: Optional[str] = None
    result_refs: tuple[str, ...] = ()
    verdict: HypothesisVerdict = HypothesisVerdict.UNTESTED

    def problems(self) -> list[str]:
        out: list[str] = []
        _need(self, ["hypothesis_id", "tenant_id", "statement", "prediction", "falsification_test"], out)
        if self.verdict in {HypothesisVerdict.SUPPORTED, HypothesisVerdict.FALSIFIED}:
            if not self.result_refs:
                out.append("SUPPORTED/FALSIFIED verdicts require result_refs from an executed test")
            if not (self.experiment_ref or self.simulation_ref):
                out.append("SUPPORTED/FALSIFIED verdicts require an experiment_ref or simulation_ref")
        return out


VERIFICATION_METHODS = frozenset({"DETERMINISTIC", "TOOL", "ADVERSARIAL_EXPERT", "SIMULATION", "HUMAN", "CONTRACT_ENGINE"})


@dataclass(frozen=True)
class VerificationResult(_Contract):
    verification_id: str
    subject_ref: str
    method: str
    verdict: str
    evidence_refs: tuple[str, ...]
    verifier_id: str
    producer_id: str

    def problems(self) -> list[str]:
        out: list[str] = []
        _need(self, ["verification_id", "subject_ref", "verifier_id", "producer_id"], out)
        if self.method not in VERIFICATION_METHODS:
            out.append(f"method must be one of {sorted(VERIFICATION_METHODS)}")
        if self.verdict not in {"PASSED", "FAILED", "INCONCLUSIVE"}:
            out.append("verdict must be PASSED|FAILED|INCONCLUSIVE")
        if self.verifier_id == self.producer_id:
            out.append("verifier must be independent of the producer")
        if self.verdict == "PASSED" and not self.evidence_refs:
            out.append("a PASSED verification requires evidence_refs")
        return out


# ---------------------------------------------------------------- compute / request / result
@dataclass(frozen=True)
class ComputeBudget(_Contract):
    """Compute expressed as budgets, never as a model size."""

    latency_target_ms: Optional[int] = None
    cost_ceiling_units: Optional[float] = None
    reasoning_steps: Optional[int] = None
    max_experts: Optional[int] = None
    verification_depth: int = 1

    def problems(self) -> list[str]:
        out: list[str] = []
        for n in ("latency_target_ms", "cost_ceiling_units", "reasoning_steps", "max_experts"):
            v = getattr(self, n)
            if v is not None and (isinstance(v, bool) or not isinstance(v, (int, float)) or v <= 0):
                out.append(f"{n} must be positive when set")
        if self.verification_depth < 0:
            out.append("verification_depth must be >= 0")
        return out


@dataclass(frozen=True)
class CognitiveRequest(_Contract):
    request_id: str
    tenant_id: str
    mode: str
    input_ref: str
    objective_id: Optional[str] = None
    budget: ComputeBudget = field(default_factory=ComputeBudget)
    contract_ref: Optional[str] = None
    protocol_version: str = PROTOCOL_VERSION

    def problems(self) -> list[str]:
        out: list[str] = []
        _need(self, ["request_id", "tenant_id", "input_ref"], out)
        if self.mode not in {m.value for m in ComputeMode} and not (
                isinstance(self.mode, str) and self.mode.startswith("FUTURE:") and _OPEN_NAME.match(self.mode)):
            out.append("mode must be FAST|REASON|FRONTIER or a FUTURE:<name> extension")
        if self.protocol_version != PROTOCOL_VERSION:
            out.append(f"protocol_version must be {PROTOCOL_VERSION}")
        return out + self.budget.problems()


@dataclass(frozen=True)
class InformationGainQuery(_Contract):
    """The single highest-value question when evidence is insufficient."""

    question: str
    target_uncertainty: str
    expected_uncertainty_reduction: float
    alternatives_considered: tuple[str, ...]

    def problems(self) -> list[str]:
        out: list[str] = []
        _need(self, ["question", "target_uncertainty"], out)
        _unit("expected_uncertainty_reduction", self.expected_uncertainty_reduction, out)
        if self.question.count("?") > 1:
            out.append("ask exactly one question")
        return out


@dataclass(frozen=True)
class CognitiveResult(_Contract):
    request_id: str
    status: str  # COMPLETED | FAILED_CLOSED | NEEDS_INFORMATION
    output_ref: Optional[str]
    evidence_refs: tuple[str, ...]
    verification_ids: tuple[str, ...]
    confidence: Optional[float]
    contract_status: Optional[str] = None
    information_request: Optional[InformationGainQuery] = None

    def problems(self) -> list[str]:
        out: list[str] = []
        _need(self, ["request_id"], out)
        if self.status not in {"COMPLETED", "FAILED_CLOSED", "NEEDS_INFORMATION"}:
            out.append("status must be COMPLETED|FAILED_CLOSED|NEEDS_INFORMATION")
        if self.status == "COMPLETED":
            if _blank(self.output_ref):
                out.append("COMPLETED requires output_ref")
            if not self.verification_ids and self.contract_status != "SATISFIED":
                out.append("COMPLETED requires verification_ids or a SATISFIED contract")
            if self.confidence is None:
                out.append("COMPLETED requires a calibrated confidence")
        if self.status != "COMPLETED" and self.output_ref is not None:
            out.append("only COMPLETED results may carry an output_ref")
        if self.status == "NEEDS_INFORMATION":
            if self.information_request is None:
                out.append("NEEDS_INFORMATION requires an information_request")
            else:
                out += self.information_request.problems()
        if self.confidence is not None:
            _unit("confidence", self.confidence, out)
        return out


# ---------------------------------------------------------------- experts
@dataclass(frozen=True)
class ExpertCapability(_Contract):
    expert_id: str
    kind: str  # open vocabulary; future experts are legal
    realization: str  # open vocabulary (adapter, checkpoint, symbolic, simulator, FUTURE:...)
    capability_tags: tuple[str, ...]
    state: QualificationState
    qualification_eval_refs: tuple[str, ...] = ()
    interface_version: str = PROTOCOL_VERSION

    def problems(self) -> list[str]:
        out: list[str] = []
        _need(self, ["expert_id", "capability_tags"], out)
        for n in ("kind", "realization"):
            if not _OPEN_NAME.match(getattr(self, n) or ""):
                out.append(f"{n} must be a plain name (optionally FUTURE:-prefixed)")
        if self.state is QualificationState.QUALIFIED and not self.qualification_eval_refs:
            out.append("QUALIFIED experts require qualification_eval_refs")
        return out


@dataclass(frozen=True)
class ExpertRequest(_Contract):
    request_id: str
    expert_id: str
    tenant_id: str
    task_ref: str
    budget: ComputeBudget = field(default_factory=ComputeBudget)

    def problems(self) -> list[str]:
        out: list[str] = []
        _need(self, ["request_id", "expert_id", "tenant_id", "task_ref"], out)
        return out + self.budget.problems()


@dataclass(frozen=True)
class ExpertResult(_Contract):
    request_id: str
    expert_id: str
    status: str  # OK | FAILED | REFUSED
    output_ref: Optional[str]
    evidence_refs: tuple[str, ...] = ()
    self_reported_confidence: Optional[float] = None
    claims_trusted: bool = False  # expert claims are never trusted; ORNEUR verifies

    def problems(self) -> list[str]:
        out: list[str] = []
        _need(self, ["request_id", "expert_id"], out)
        if self.status not in {"OK", "FAILED", "REFUSED"}:
            out.append("status must be OK|FAILED|REFUSED")
        if self.status == "OK" and _blank(self.output_ref):
            out.append("OK requires output_ref")
        if self.claims_trusted:
            out.append("expert self-reports are never trusted (claims_trusted must be False)")
        return out


# ---------------------------------------------------------------- outcome learning
@dataclass(frozen=True)
class PreferenceFeedback(_Contract):
    """What the user LIKED. Deliberately a different type from Outcome."""

    feedback_id: str
    tenant_id: str
    response_ref: str
    signal: str
    created_at: str

    def problems(self) -> list[str]:
        out: list[str] = []
        _need(self, ["feedback_id", "tenant_id", "response_ref", "signal", "created_at"], out)
        return out


@dataclass(frozen=True)
class Outcome(_Contract):
    """Did the recommendation/action actually work? Never derived from preference alone."""

    outcome_id: str
    tenant_id: str
    objective_id: str
    decision_ref: str
    action_ref: str
    expected_outcome: str
    time_horizon: str
    success_metric: str
    source: OutcomeSource
    status: str = "PENDING"  # PENDING | OBSERVED
    observed_outcome: Optional[str] = None
    observation_evidence_refs: tuple[str, ...] = ()
    difference: Optional[str] = None
    root_cause: Optional[str] = None
    lesson: Optional[str] = None
    reusable_strategy_candidate_ref: Optional[str] = None

    def problems(self) -> list[str]:
        out: list[str] = []
        _need(self, ["outcome_id", "tenant_id", "objective_id", "decision_ref", "action_ref",
                     "expected_outcome", "time_horizon", "success_metric"], out)
        if self.source is OutcomeSource.USER_PREFERENCE:
            out.append("user preference is not an outcome source; use PreferenceFeedback")
        if self.status not in {"PENDING", "OBSERVED"}:
            out.append("status must be PENDING|OBSERVED")
        if self.status == "OBSERVED":
            if _blank(self.observed_outcome):
                out.append("OBSERVED requires observed_outcome")
            if not self.observation_evidence_refs:
                out.append("OBSERVED requires observation_evidence_refs")
        elif self.observed_outcome is not None:
            out.append("PENDING outcomes cannot carry observed_outcome")
        return out


@dataclass(frozen=True)
class FailureGenomeEntry(_Contract):
    entry_id: str
    tenant_id: str
    failure_class: str
    trigger_conditions: tuple[str, ...]
    capability_gap: str
    evidence_refs: tuple[str, ...]
    scope: str = "TENANT_PRIVATE"  # or ANONYMIZED_SHAREABLE
    anonymization_evidence_ref: Optional[str] = None
    occurrences: int = 1

    def problems(self) -> list[str]:
        out: list[str] = []
        _need(self, ["entry_id", "tenant_id", "failure_class", "trigger_conditions", "capability_gap",
                     "evidence_refs"], out)
        if self.scope not in {"TENANT_PRIVATE", "ANONYMIZED_SHAREABLE"}:
            out.append("scope must be TENANT_PRIVATE|ANONYMIZED_SHAREABLE")
        if self.scope == "ANONYMIZED_SHAREABLE" and _blank(self.anonymization_evidence_ref):
            out.append("cross-tenant sharing requires anonymization_evidence_ref")
        return out


@dataclass(frozen=True)
class CognitivePrimitive(_Contract):
    """A structured, versioned strategy. Raw reasoning traces are never stored."""

    primitive_id: str
    version: int
    problem_class: str
    strategy_steps: tuple[str, ...]
    worked_conditions: tuple[str, ...]
    failed_conditions: tuple[str, ...]
    evidence_refs: tuple[str, ...]
    state: QualificationState = QualificationState.CANDIDATE
    qualification_eval_refs: tuple[str, ...] = ()
    raw_reasoning_trace_stored: bool = False

    def problems(self) -> list[str]:
        out: list[str] = []
        _need(self, ["primitive_id", "problem_class", "strategy_steps", "worked_conditions", "evidence_refs"], out)
        if self.version < 1:
            out.append("version must be >= 1")
        if self.raw_reasoning_trace_stored:
            out.append("free-form reasoning traces must not be stored as a permanent asset")
        if self.state is QualificationState.QUALIFIED and not self.qualification_eval_refs:
            out.append("QUALIFIED primitives require qualification_eval_refs")
        return out


# ---------------------------------------------------------------- migration / promotion
@dataclass(frozen=True)
class ArchitectureDescriptor(_Contract):
    architecture_id: str
    generation: int
    family_label: str  # informational only; no logic may branch on it

    def problems(self) -> list[str]:
        out: list[str] = []
        _need(self, ["architecture_id", "family_label"], out)
        if self.generation < 0:
            out.append("generation must be >= 0")
        return out


@dataclass(frozen=True)
class AssetMigration(_Contract):
    asset: MigrationAsset
    mechanisms: tuple[MigrationMechanism, ...]
    preservation_eval_refs: tuple[str, ...] = ()

    def problems(self) -> list[str]:
        out: list[str] = []
        if not self.mechanisms:
            out.append(f"{self.asset.value}: at least one mechanism is required")
        return out


@dataclass(frozen=True)
class ArchitectureMigrationManifest(_Contract):
    manifest_id: str
    source: ArchitectureDescriptor
    target: ArchitectureDescriptor
    assets: tuple[AssetMigration, ...]
    shadow_comparison_ref: Optional[str]
    rollback_plan_ref: Optional[str]
    obsolescence_review_ref: Optional[str]  # Self-Obsolescence Rule: what is now unnecessary?
    cutover_approved: bool = False
    protocol_version: str = PROTOCOL_VERSION

    def problems(self) -> list[str]:
        out: list[str] = _collect(self.source, self.target)
        _need(self, ["manifest_id"], out)
        if self.source.architecture_id == self.target.architecture_id:
            out.append("source and target architecture must differ")
        have = {a.asset for a in self.assets}
        for a in MigrationAsset:
            if a not in have:
                out.append(f"asset class {a.value} is not covered")
        for a in self.assets:
            out += a.problems()
        if self.cutover_approved:
            for n in ("shadow_comparison_ref", "rollback_plan_ref", "obsolescence_review_ref"):
                if _blank(getattr(self, n)):
                    out.append(f"cutover_approved requires {n}")
            for a in self.assets:
                if a.asset in {MigrationAsset.EVAL_SUITES, MigrationAsset.AUTHORITY_EVIDENCE_CONTRACTS} \
                        and not a.preservation_eval_refs:
                    out.append(f"cutover requires preservation_eval_refs for {a.asset.value}")
        return out


def _collect(*items: _Contract) -> list[str]:
    out: list[str] = []
    for i in items:
        out += i.problems()
    return out


@dataclass(frozen=True)
class PromotionDecision(_Contract):
    decision_id: str
    candidate_id: str
    candidate_produced_by: str
    decided_by: str
    decider_kind: str  # HUMAN_OWNER | QUALIFIED_GATE_SERVICE
    verdict: PromotionVerdict
    frozen_eval_ref: Optional[str] = None
    adversarial_eval_ref: Optional[str] = None
    regression_eval_ref: Optional[str] = None
    shadow_deployment_ref: Optional[str] = None
    measured_improvement: Optional[float] = None
    regressions_found: Optional[int] = None

    def problems(self) -> list[str]:
        out: list[str] = []
        _need(self, ["decision_id", "candidate_id", "candidate_produced_by", "decided_by"], out)
        if self.decider_kind not in {"HUMAN_OWNER", "QUALIFIED_GATE_SERVICE"}:
            out.append("decider_kind must be HUMAN_OWNER|QUALIFIED_GATE_SERVICE")
        if self.decided_by in {self.candidate_produced_by, self.candidate_id}:
            out.append("a self-generated component cannot promote itself")
        if self.verdict is PromotionVerdict.PROMOTE:
            for n in ("frozen_eval_ref", "adversarial_eval_ref", "regression_eval_ref", "shadow_deployment_ref"):
                if _blank(getattr(self, n)):
                    out.append(f"PROMOTE requires {n}")
            if self.measured_improvement is None or self.measured_improvement <= 0:
                out.append("PROMOTE requires a measured positive improvement")
            if self.regressions_found is None or self.regressions_found != 0:
                out.append("PROMOTE requires zero regressions")
        return out
