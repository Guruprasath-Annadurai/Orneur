"""
Agent Runtime typed contracts (Phase 8 spec §4). Models NEVER own
permissions (spec §2) -- these dataclasses exist so that fact is
structural: an `ActionRequest` is a REQUEST, never itself an
authorization; only a `PolicyDecision`/`ActionAuthorization` produced by
the deterministic Policy Engine (orca/agent/policy.py) can move a request
toward execution. No dataclass here carries a raw-chain-of-thought field,
matching Deliberation Fabric's discipline.
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


# ── Capabilities (spec §10-11) ───────────────────────────────────────────

class Capability(str, Enum):
    """What an agent may REQUEST -- never what it may do unconditionally
    (spec §11: capability is necessary, not sufficient)."""
    FILE_READ = "FILE_READ"
    FILE_WRITE = "FILE_WRITE"
    NETWORK_READ = "NETWORK_READ"
    NETWORK_WRITE = "NETWORK_WRITE"
    TOOL_EXECUTION = "TOOL_EXECUTION"
    SUBAGENT_DELEGATION = "SUBAGENT_DELEGATION"
    SECRET_USE = "SECRET_USE"
    EXTERNAL_MESSAGE = "EXTERNAL_MESSAGE"
    PROCESS_EXECUTION = "PROCESS_EXECUTION"
    # Phase 9 (spec §10): distinct from FILE_READ/FILE_WRITE/NETWORK_*
    # -- an enterprise connector read/write is its own capability class,
    # gated by the SAME Capability Engine, on top of (never instead of)
    # orca.connectors.policy's own tenant/scope/sensitivity checks.
    CONNECTOR_READ = "CONNECTOR_READ"
    CONNECTOR_WRITE = "CONNECTOR_WRITE"


@dataclass
class CapabilityRequirement:
    required: frozenset[Capability] = field(default_factory=frozenset)


@dataclass
class CapabilityDecision:
    granted: bool
    missing: frozenset[Capability] = field(default_factory=frozenset)
    reasons: list[str] = field(default_factory=list)


# ── Side effect / risk classification (spec §9, §39) ─────────────────────

class SideEffectClass(str, Enum):
    READ_ONLY = "READ_ONLY"
    REVERSIBLE_WRITE = "REVERSIBLE_WRITE"
    IRREVERSIBLE_WRITE = "IRREVERSIBLE_WRITE"
    EXTERNAL_SIDE_EFFECT = "EXTERNAL_SIDE_EFFECT"
    DESTRUCTIVE = "DESTRUCTIVE"


class ActionRiskLevel(str, Enum):
    LOW = "LOW"
    MEDIUM = "MEDIUM"
    HIGH = "HIGH"
    CRITICAL = "CRITICAL"


# ── Tool contracts (spec §8) ──────────────────────────────────────────────

@dataclass
class ToolSpec:
    tool_id: str
    version: str = "1"
    description: str = ""
    input_schema: dict = field(default_factory=dict)
    output_schema: dict = field(default_factory=dict)
    required_capabilities: frozenset[Capability] = field(default_factory=frozenset)
    side_effect_class: SideEffectClass = SideEffectClass.READ_ONLY
    risk_class: ActionRiskLevel = ActionRiskLevel.LOW
    timeout_s: float = 30.0
    idempotent: bool = True
    network_required: bool = False
    filesystem_scope: str | None = None
    secrets_required: bool = False


@dataclass
class ToolInvocation:
    invocation_id: str = field(default_factory=lambda: _new_id("inv"))
    tool_id: str = ""
    arguments: dict = field(default_factory=dict)
    idempotency_key: str | None = None


@dataclass
class ToolResult:
    invocation_id: str = ""
    tool_id: str = ""
    success: bool = False
    output: str = ""
    error_class: str | None = None
    latency_ms: float = 0.0
    retries: int = 0


# ── Goal / Plan / Task / Action (spec §5-7) ───────────────────────────────

@dataclass
class AgentGoal:
    objective: str = ""
    success_criteria: list[str] = field(default_factory=list)
    constraints: list[str] = field(default_factory=list)
    risk: ActionRiskLevel = ActionRiskLevel.LOW
    evidence_requirement: str = "SUPPORTED"
    scope: str = ""
    allowed_action_classes: frozenset[SideEffectClass] = field(
        default_factory=lambda: frozenset({SideEffectClass.READ_ONLY})
    )


class TaskStatus(str, Enum):
    PENDING = "PENDING"
    RUNNING = "RUNNING"
    COMPLETED = "COMPLETED"
    FAILED = "FAILED"
    BLOCKED = "BLOCKED"
    SKIPPED = "SKIPPED"


@dataclass
class AgentTask:
    task_id: str = field(default_factory=lambda: _new_id("task"))
    description: str = ""
    status: TaskStatus = TaskStatus.PENDING
    dependencies: list[str] = field(default_factory=list)
    completion_criteria: list[str] = field(default_factory=list)


@dataclass
class AgentAction:
    action_id: str = field(default_factory=lambda: _new_id("act"))
    task_id: str = ""
    tool_id: str = ""
    arguments: dict = field(default_factory=dict)
    expected_side_effect: SideEffectClass = SideEffectClass.READ_ONLY
    # Phase 8.1 spec §12-13: a typed runtime decision, set by the planner
    # (or a caller) when the action depends on a fresh/strict external
    # fact -- never inferred silently by the runtime itself. Checked BEFORE
    # execution; if True and no sufficient TruthResult is available, the
    # runtime does not guess-and-execute (spec §13).
    requires_truth_check: bool = False


@dataclass
class AgentPlan:
    plan_id: str = field(default_factory=lambda: _new_id("aplan"))
    version: int = 1
    parent_version: int | None = None
    revision_reason: str | None = None
    tasks: list[AgentTask] = field(default_factory=list)
    actions: list[AgentAction] = field(default_factory=list)
    created_at: str = field(default_factory=_now_iso)


# ── Authorization (spec §12-13) ───────────────────────────────────────────

class PolicyDecisionState(str, Enum):
    ALLOW = "ALLOW"
    DENY = "DENY"
    REQUIRE_APPROVAL = "REQUIRE_APPROVAL"
    ALLOW_WITH_RESTRICTIONS = "ALLOW_WITH_RESTRICTIONS"


@dataclass
class ActionRequest:
    """A REQUEST only -- never itself authority (spec §2)."""
    request_id: str = field(default_factory=lambda: _new_id("areq"))
    action: AgentAction = field(default_factory=AgentAction)
    requested_capabilities: frozenset[Capability] = field(default_factory=frozenset)


@dataclass
class PolicyDecision:
    state: PolicyDecisionState = PolicyDecisionState.DENY
    reasons: list[str] = field(default_factory=list)
    restrictions: list[str] = field(default_factory=list)


@dataclass
class ActionAuthorization:
    """The ONLY thing that may precede execution (spec §13). Produced
    exclusively by the deterministic Policy Engine -- never by a model,
    never by Court ACCEPT, never by Society routing, never by Memory."""
    request_id: str = ""
    decision: PolicyDecision = field(default_factory=PolicyDecision)
    capability_decision: CapabilityDecision = field(default_factory=lambda: CapabilityDecision(granted=False))
    authorized: bool = False
    authorization_id: str = field(default_factory=lambda: _new_id("auth"))


@dataclass
class ActionResult:
    request_id: str = ""
    tool_result: ToolResult = field(default_factory=ToolResult)
    verified: bool = False


# ── Observation / WorldState provenance (spec §21-23) ─────────────────────

class ObservationTrustClass(str, Enum):
    SYSTEM_VERIFIED = "SYSTEM_VERIFIED"    # filesystem stat, subprocess exit code
    EXTERNAL_API = "EXTERNAL_API"           # HTTP response, search result
    USER_STATEMENT = "USER_STATEMENT"
    MODEL_INTERPRETATION = "MODEL_INTERPRETATION"


@dataclass
class Observation:
    observation_id: str = field(default_factory=lambda: _new_id("obs"))
    action_id: str = ""
    source: str = ""
    timestamp: str = field(default_factory=_now_iso)
    facts: list[str] = field(default_factory=list)
    status: str = "OK"
    evidence_refs: list[str] = field(default_factory=list)
    error: str | None = None
    trust_class: ObservationTrustClass = ObservationTrustClass.SYSTEM_VERIFIED
    world_state_changes: list[str] = field(default_factory=list)


# ── Agent run / state / stop reasons (spec §5) ────────────────────────────

class AgentRunStatus(str, Enum):
    CREATED = "CREATED"
    PLANNING = "PLANNING"
    RUNNING = "RUNNING"
    WAITING = "WAITING"
    REPLANNING = "REPLANNING"
    COMPLETED = "COMPLETED"
    FAILED = "FAILED"
    CANCELLED = "CANCELLED"
    BLOCKED = "BLOCKED"
    PARTIAL = "PARTIAL"


class ExecutionStopReason(str, Enum):
    GOAL_ACHIEVED = "GOAL_ACHIEVED"
    TOOL_ERROR = "TOOL_ERROR"
    POLICY_DENIED = "POLICY_DENIED"
    CAPABILITY_MISSING = "CAPABILITY_MISSING"
    APPROVAL_REQUIRED = "APPROVAL_REQUIRED"
    BUDGET_EXHAUSTED = "BUDGET_EXHAUSTED"
    TIMEOUT = "TIMEOUT"
    CANCELLED = "CANCELLED"
    NO_VALID_PLAN = "NO_VALID_PLAN"
    UNRESOLVED_WORLD_STATE = "UNRESOLVED_WORLD_STATE"
    DEPENDENCY_FAILED = "DEPENDENCY_FAILED"
    MAX_REPLANS_EXCEEDED = "MAX_REPLANS_EXCEEDED"


@dataclass
class AgentRun:
    run_id: str = field(default_factory=lambda: _new_id("run"))
    goal: AgentGoal = field(default_factory=AgentGoal)
    scope: str = ""
    owner: str | None = None
    plan_id: str | None = None
    world_state_id: str | None = None
    capabilities: frozenset[Capability] = field(default_factory=frozenset)
    deadline_s: float = 120.0
    status: AgentRunStatus = AgentRunStatus.CREATED
    created_at: str = field(default_factory=_now_iso)
    updated_at: str = field(default_factory=_now_iso)
    stop_reason: ExecutionStopReason | None = None
    completed_task_ids: list[str] = field(default_factory=list)
    blocked_task_ids: list[str] = field(default_factory=list)


@dataclass
class AgentTrace:
    run_id: str = ""
    plan_versions: list[int] = field(default_factory=list)
    task_ids: list[str] = field(default_factory=list)
    action_ids: list[str] = field(default_factory=list)
    authorization_ids: list[str] = field(default_factory=list)
    tool_invocation_ids: list[str] = field(default_factory=list)
    observation_ids: list[str] = field(default_factory=list)
    world_state_ids: list[str] = field(default_factory=list)
    replan_events: list[str] = field(default_factory=list)
    subagent_run_ids: list[str] = field(default_factory=list)
    budget_summary: dict[str, Any] = field(default_factory=dict)
    stop_reason: str | None = None


# ── Delegation (spec §30-34) ───────────────────────────────────────────────

@dataclass
class DelegationRequest:
    parent_run_id: str = ""
    goal: AgentGoal = field(default_factory=AgentGoal)
    scope: str = ""
    capabilities_subset: frozenset[Capability] = field(default_factory=frozenset)
    budget_subset: dict[str, int] = field(default_factory=dict)
    deadline_s: float = 60.0
    expected_result_schema: dict = field(default_factory=dict)
    depth: int = 1


@dataclass
class DelegationResult:
    child_run_id: str = ""
    status: AgentRunStatus = AgentRunStatus.COMPLETED
    result: Any = None
    trusted: bool = False
