"""
Simulation Chamber typed contracts (Phase 11). No loose-dict simulation
protocol -- every simulation artifact is a typed dataclass.

Canonical rule (spec §1-2):

    simulation result != real observation
    simulation success != authorization

Every `PredictedEffect`/`SimulationResult` is provenance-tagged as
`SIMULATION` (see `Provenance`), structurally distinct from
`TOOL_OBSERVATION`/`CONNECTOR_OBSERVATION`/`TRUTH_EVIDENCE`/`USER_INPUT`
-- there is no code path anywhere in this package that inserts a
`PredictedEffect` into a real `orca.deliberation.contracts.WorldState`
as an observed fact (see `worldstate_projection.py`).
"""
from __future__ import annotations

import uuid
from dataclasses import dataclass, field
from datetime import datetime, timezone
from enum import Enum


def _new_id(prefix: str) -> str:
    return f"{prefix}-{uuid.uuid4().hex[:12]}"


def now_iso() -> str:
    return datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")


# ── Provenance (spec §6) ──────────────────────────────────────────────────

class Provenance(str, Enum):
    SIMULATION = "SIMULATION"
    TOOL_OBSERVATION = "TOOL_OBSERVATION"
    CONNECTOR_OBSERVATION = "CONNECTOR_OBSERVATION"
    TRUTH_EVIDENCE = "TRUTH_EVIDENCE"
    USER_INPUT = "USER_INPUT"


# ── Simulation modes (spec §5) ────────────────────────────────────────────

class SimulationMode(str, Enum):
    STATIC_ANALYSIS = "STATIC_ANALYSIS"
    DRY_RUN = "DRY_RUN"
    SANDBOX_EXECUTION = "SANDBOX_EXECUTION"
    STATE_PROJECTION = "STATE_PROJECTION"
    COUNTERFACTUAL = "COUNTERFACTUAL"
    SHADOW_EXECUTION = "SHADOW_EXECUTION"
    PROVIDER_PREVIEW = "PROVIDER_PREVIEW"


class SimulationSupportLevel(str, Enum):
    SUPPORTED = "SUPPORTED"
    PARTIAL = "PARTIAL"
    UNAVAILABLE = "UNAVAILABLE"


@dataclass
class ToolSimulationCapability:
    """Extends ToolSpec/connector metadata (spec §10) -- never inferred
    from a tool's name, always declared explicitly per tool/connector."""
    supports_static_validation: bool = True   # cheapest mode; always at least this
    supports_dry_run: bool = False
    supports_sandbox: bool = False
    supports_preview: bool = False
    supports_read_back_prediction: bool = False
    simulation_fidelity: str = "LOW"          # "LOW" | "MEDIUM" | "HIGH" -- descriptive, not authoritative

    def support_for(self, mode: SimulationMode) -> SimulationSupportLevel:
        mapping = {
            SimulationMode.STATIC_ANALYSIS: self.supports_static_validation,
            SimulationMode.DRY_RUN: self.supports_dry_run,
            SimulationMode.SANDBOX_EXECUTION: self.supports_sandbox,
            SimulationMode.PROVIDER_PREVIEW: self.supports_preview,
        }
        supported = mapping.get(mode)
        if supported is None:
            return SimulationSupportLevel.UNAVAILABLE
        return SimulationSupportLevel.SUPPORTED if supported else SimulationSupportLevel.UNAVAILABLE


# ── Simulation requirement policy (spec §8-9) ─────────────────────────────

class SimulationRequirement(str, Enum):
    NOT_REQUIRED = "NOT_REQUIRED"
    OPTIONAL = "OPTIONAL"
    REQUIRED = "REQUIRED"
    UNAVAILABLE_BUT_REVIEW_REQUIRED = "UNAVAILABLE_BUT_REVIEW_REQUIRED"


# ── Effect model (spec §18-21) ────────────────────────────────────────────

class EffectType(str, Enum):
    CREATE = "CREATE"
    UPDATE = "UPDATE"
    DELETE = "DELETE"
    SEND = "SEND"
    MOVE = "MOVE"
    PERMISSION_CHANGE = "PERMISSION_CHANGE"
    STATE_TRANSITION = "STATE_TRANSITION"
    RESOURCE_CONSUMPTION = "RESOURCE_CONSUMPTION"
    UNKNOWN_EFFECT = "UNKNOWN_EFFECT"


class Reversibility(str, Enum):
    REVERSIBLE = "REVERSIBLE"
    COMPENSATABLE = "COMPENSATABLE"
    IRREVERSIBLE = "IRREVERSIBLE"
    UNKNOWN = "UNKNOWN"


class BlastRadius(str, Enum):
    SINGLE_OBJECT = "SINGLE_OBJECT"
    MULTIPLE_OBJECTS = "MULTIPLE_OBJECTS"
    WORKSPACE_OR_PROJECT = "WORKSPACE_OR_PROJECT"
    TENANT = "TENANT"
    EXTERNAL_RECIPIENTS = "EXTERNAL_RECIPIENTS"
    PRODUCTION_SYSTEM = "PRODUCTION_SYSTEM"
    UNKNOWN = "UNKNOWN"


class EffectConfidence(str, Enum):
    HIGH = "HIGH"           # deterministic mechanism (e.g. real filesystem diff)
    MEDIUM = "MEDIUM"       # partial deterministic + model interpretation
    LOW = "LOW"             # model-only projection
    UNVERIFIABLE = "UNVERIFIABLE"   # no mechanism could establish this


@dataclass
class Assumption:
    """spec §17: every nontrivial simulation exposes its assumptions
    explicitly -- never left implicit in prose."""
    assumption_id: str = field(default_factory=lambda: _new_id("assume"))
    description: str = ""
    source: str = ""                 # e.g. "state_fingerprint", "model_projection", "provider_metadata"
    verification_state: str = "UNVERIFIED"   # "UNVERIFIED" | "VERIFIED" | "CONTRADICTED"
    impact_if_false: str = ""


@dataclass
class PredictedEffect:
    effect_id: str = field(default_factory=lambda: _new_id("peffect"))
    resource: str = ""
    effect_type: EffectType = EffectType.UNKNOWN_EFFECT
    before_reference: str | None = None      # a hash/version/description of prior state, never the full payload
    predicted_after_reference: str | None = None
    reversibility: Reversibility = Reversibility.UNKNOWN
    blast_radius: BlastRadius = BlastRadius.UNKNOWN
    confidence: EffectConfidence = EffectConfidence.LOW
    assumption_ids: list[str] = field(default_factory=list)
    provenance: Provenance = Provenance.SIMULATION


@dataclass
class CompensationPlan:
    """spec §22: compensation is NOT guaranteed rollback -- every field
    here is descriptive of a PROPOSED compensating action, never a
    promise it will succeed."""
    plan_id: str = field(default_factory=lambda: _new_id("comp"))
    original_effect_id: str = ""
    compensating_action_description: str = ""
    preconditions: list[str] = field(default_factory=list)
    limitations: list[str] = field(default_factory=list)
    required_capability: str | None = None
    risk: str = "MEDIUM"
    confidence: EffectConfidence = EffectConfidence.LOW


# ── Simulation environment / constraints (spec §4, §7) ────────────────────

@dataclass
class SimulationConstraint:
    max_actions: int = 1
    max_branches: int = 1
    deadline_s: float = 30.0
    required_fidelity: str = "LOW"


@dataclass
class SimulationEnvironment:
    """Where the simulation actually runs -- a sandbox root, a fake
    provider state handle, or nothing (STATIC_ANALYSIS needs none).
    Deliberately opaque handles (never a raw credential) -- see
    `orca.godmode` and `orca.connectors` for the real security
    boundaries this environment must respect."""
    environment_id: str = field(default_factory=lambda: _new_id("simenv"))
    sandbox_root: str | None = None          # absolute path, filesystem sandbox only
    fake_provider_state_id: str | None = None  # connector sandbox only


@dataclass
class SimulationAction:
    """The one action being simulated -- mirrors `orca.agent.contracts.AgentAction`
    deliberately (same tool_id/arguments shape) so a real `AgentAction`
    can be simulated without re-deriving a parallel schema."""
    action_id: str = ""
    tool_id: str = ""
    arguments: dict = field(default_factory=dict)
    resource_scope: str = ""
    operation_scope: str = ""


@dataclass
class SimulationRequest:
    request_id: str = field(default_factory=lambda: _new_id("simreq"))
    action: SimulationAction = field(default_factory=SimulationAction)
    tool_or_connector_id: str = ""
    risk_class: str = "LOW"
    side_effect_class: str = "READ_ONLY"
    tenant_id: str = ""
    principal_id: str = ""
    lease_id: str | None = None              # Godmode context, if elevated -- NEVER consumed by simulation itself
    # The Godmode CAPABILITY the lease would need to grant (e.g.
    # "FILE_WRITE", "CONNECTOR_WRITE") -- deliberately distinct from
    # `side_effect_class` (READ_ONLY/IRREVERSIBLE_WRITE/...), which
    # describes the ACTION's effect class, not the capability string a
    # CapabilityLease binds to. Conflating the two was a real bug found
    # during this phase's own eval harness run (a compatibility check
    # comparing "FILE_WRITE" against the literal string "READ_ONLY").
    capability: str = ""
    # Which orca.godmode.contracts.CapabilityDomain the lease (if any)
    # would need to belong to -- explicit, never inferred from
    # `tool_or_connector_id`'s spelling (a "write_file" tool could
    # legitimately be elevated via either an AGENT-domain Capability
    # lease, through AgentRuntime's generic path, or a FILE-domain
    # resource lease, through the dedicated file_elevation.py path --
    # the caller knows which one applies, this module must not guess).
    capability_domain: str = "FILE"
    simulation_budget_units: int = 1
    deadline_s: float = 30.0
    required_fidelity: str = "LOW"
    parent_agent_run_deadline_s: float | None = None
    created_at: str = field(default_factory=now_iso)


# ── State fingerprint / staleness (spec §49-51) ───────────────────────────

@dataclass
class StateFingerprint:
    resource: str = ""
    kind: str = "UNKNOWN"       # "VERSION" | "ETAG" | "CONTENT_HASH" | "REVISION" | "MTIME" | "UNAVAILABLE"
    value: str | None = None
    captured_at: str = field(default_factory=now_iso)


# ── Simulation verdict / result / trace (spec §43, §57, §63) ──────────────

class SimulationVerdict(str, Enum):
    PASS = "PASS"
    PASS_WITH_WARNINGS = "PASS_WITH_WARNINGS"
    REVISE = "REVISE"
    BLOCK = "BLOCK"
    INCONCLUSIVE = "INCONCLUSIVE"


class SimulationFailureReason(str, Enum):
    UNSUPPORTED = "UNSUPPORTED"
    FAILED = "FAILED"
    TIMEOUT = "TIMEOUT"
    CANCELLED = "CANCELLED"
    BUDGET_EXHAUSTED = "BUDGET_EXHAUSTED"
    STALE_INPUT = "STALE_INPUT"
    POLICY_BLOCKED = "POLICY_BLOCKED"


@dataclass
class SimulationResult:
    result_id: str = field(default_factory=lambda: _new_id("simres"))
    request_id: str = ""
    mode_used: SimulationMode = SimulationMode.STATIC_ANALYSIS
    verdict: SimulationVerdict = SimulationVerdict.INCONCLUSIVE
    predicted_effects: list[PredictedEffect] = field(default_factory=list)
    assumptions: list[Assumption] = field(default_factory=list)
    compensation_plans: list[CompensationPlan] = field(default_factory=list)
    warnings: list[str] = field(default_factory=list)
    block_reasons: list[str] = field(default_factory=list)
    failure_reason: SimulationFailureReason | None = None
    input_fingerprints: list[StateFingerprint] = field(default_factory=list)
    result_hash: str = ""            # tamper-evidence -- see integrity.py
    created_at: str = field(default_factory=now_iso)

    def can_proceed(self) -> bool:
        return self.verdict in (SimulationVerdict.PASS, SimulationVerdict.PASS_WITH_WARNINGS)


@dataclass
class SimulationTrace:
    trace_id: str = field(default_factory=lambda: _new_id("simtrace"))
    request_id: str = ""
    mode: SimulationMode = SimulationMode.STATIC_ANALYSIS
    provider_id: str = ""
    effect_ids: list[str] = field(default_factory=list)
    assumption_ids: list[str] = field(default_factory=list)
    branch_count: int = 1
    verdict: SimulationVerdict = SimulationVerdict.INCONCLUSIVE
    budget_summary: dict = field(default_factory=dict)
    model_calls_used: int = 0
    truth_reference_ids: list[str] = field(default_factory=list)
    memory_reference_ids: list[str] = field(default_factory=list)
    court_verdict: str | None = None
    gate_decision: str | None = None
    staleness_checked: bool = False
    reality_diff_id: str | None = None


# ── Execution gate (spec §46) ─────────────────────────────────────────────

class ExecutionGateDecision(str, Enum):
    ALLOW_TO_PROCEED_TO_AUTHORIZATION = "ALLOW_TO_PROCEED_TO_AUTHORIZATION"
    REQUIRE_REVIEW = "REQUIRE_REVIEW"
    REVISE_PLAN = "REVISE_PLAN"
    BLOCK = "BLOCK"


# ── Reality reconciliation (spec §58-60) ──────────────────────────────────

class RealityDiffStatus(str, Enum):
    MATCHED = "MATCHED"
    PARTIAL_MATCH = "PARTIAL_MATCH"
    UNEXPECTED_EFFECT = "UNEXPECTED_EFFECT"
    MISSING_EXPECTED_EFFECT = "MISSING_EXPECTED_EFFECT"
    OUTCOME_UNKNOWN = "OUTCOME_UNKNOWN"


@dataclass
class RealityDiff:
    diff_id: str = field(default_factory=lambda: _new_id("rdiff"))
    simulation_id: str = ""
    action_id: str = ""
    status: RealityDiffStatus = RealityDiffStatus.OUTCOME_UNKNOWN
    predicted_effect_ids: list[str] = field(default_factory=list)
    actual_observation_summary: str = ""
    differences: list[str] = field(default_factory=list)
    severity: str = "LOW"           # "LOW" | "MEDIUM" | "HIGH" | "CRITICAL"
    follow_up_required: bool = False
    created_at: str = field(default_factory=now_iso)


@dataclass
class PlanRealityDiff:
    """Phase 11.1 spec §39-40: per-action RealityDiff list plus a
    deterministic aggregate status -- never a single flattened diff that
    hides which specific action diverged."""
    plan_diff_id: str = field(default_factory=lambda: _new_id("plandiff"))
    plan_simulation_id: str = ""
    per_action_diffs: list[RealityDiff] = field(default_factory=list)
    aggregate_status: RealityDiffStatus = RealityDiffStatus.OUTCOME_UNKNOWN
    remaining_actions_halted: bool = False
    created_at: str = field(default_factory=now_iso)


class SimulationFailureCandidateKind(str, Enum):
    """spec §61-62: emitted only as a CANDIDATE record -- never
    auto-written to durable Memory, never auto-converted to training
    data (that is explicitly Phase 12, not built here)."""
    SIMULATION_FAILURE_CANDIDATE = "simulation_failure_candidate"
    EVAL_CANDIDATE = "eval_candidate"


@dataclass
class FailureCandidateRecord:
    record_id: str = field(default_factory=lambda: _new_id("failcand"))
    kind: SimulationFailureCandidateKind = SimulationFailureCandidateKind.SIMULATION_FAILURE_CANDIDATE
    simulation_id: str = ""
    reality_diff_id: str = ""
    summary: str = ""
    created_at: str = field(default_factory=now_iso)
