"""
Phase 15.6 -- typed, inspectable execution plans (spec section 4).

An ExecutionPlan is constructed BEFORE any tool/command runs and is a
plain, JSON-serializable dataclass -- it can be logged, audited, or
attached as evidence without risk, because it is structurally
forbidden from carrying secret values: `environment_policy` is a set
of ENVIRONMENT VARIABLE NAMES to propagate from the host, never
values, and there is no field anywhere on this class that holds a raw
credential. `orca.mission.sandbox_executor` is the only code that ever
resolves a name in `environment_policy` to its actual value, and only
at the moment a subprocess is spawned -- never before, never logged.
"""
from __future__ import annotations

from dataclasses import dataclass, field
from enum import Enum

from orca.mission.code_mode import CodeMode


class NetworkPolicy(str, Enum):
    DENIED = "DENIED"
    RESTRICTED = "RESTRICTED"
    ALLOWED = "ALLOWED"


@dataclass(frozen=True)
class ResourcePolicy:
    cpu_seconds: int | None = 5
    memory_bytes: int | None = 256 * 1024 * 1024
    # NOT enforced by default: RLIMIT_NPROC is a per-real-UID limit on
    # POSIX, not scoped to this subprocess's own subtree -- setting a
    # small value here would cap the ENTIRE user's process count
    # (including unrelated processes already running), which is
    # actively harmful, not merely unreliable (see
    # orca/mission/sandbox_executor.py's `_apply_resource_limits` and
    # its adversarial test for the bug this caused before the default
    # was corrected). Callers who genuinely need a process-count cap
    # must set this explicitly and understand the per-UID scope.
    max_processes: int | None = None


class ExecutionPlanError(Exception):
    pass


@dataclass(frozen=True)
class ExecutionPlan:
    execution_id: str
    mission_id: str | None
    operation_id: str | None
    mode: CodeMode
    tool: str                        # adapter/tool identity, e.g. "sandbox_command"
    workspace_root: str              # absolute path; the enforced filesystem boundary
    working_directory: str           # must resolve inside workspace_root
    command: tuple[str, ...]         # argv -- never a raw shell string
    environment_policy: frozenset[str] = field(default_factory=frozenset)  # env VAR NAMES only
    network_policy: NetworkPolicy = NetworkPolicy.DENIED
    resource_policy: ResourcePolicy = field(default_factory=ResourcePolicy)
    timeout_seconds: float = 10.0
    authority_requirement: str | None = None  # a CapabilityAction name, or None
    expected_outputs: tuple[str, ...] = ()
    evidence_destination: str | None = None

    def __post_init__(self) -> None:
        if not self.command:
            raise ExecutionPlanError("ExecutionPlan.command must not be empty")
        if isinstance(self.command, str):  # guards against a raw shell string slipping in
            raise ExecutionPlanError("ExecutionPlan.command must be an argv sequence, not a string")
        if self.timeout_seconds <= 0:
            raise ExecutionPlanError("ExecutionPlan.timeout_seconds must be positive")
