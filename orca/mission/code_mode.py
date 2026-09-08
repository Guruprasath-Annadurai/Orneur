"""
Phase 15.6 -- the ORNEUR Code mode contract (spec sections 1-2, 15-16).

Four canonical modes -- ASSIST, PROTOTYPE, BUILD, LAUNCH -- each with an
enforceable capability policy, not a display label. A mode NARROWS what
may even be attempted; it never expands authority beyond what the real
authority engine (`orca.godmode`, via `orca.mission.operation_store`)
grants. Concretely: `is_allowed_by_mode()` is a necessary-but-not-
sufficient gate checked BEFORE ever calling
`orca.mission.operation_store.request_operation()`/`authorize_operation()`
for a given `CapabilityAction` -- passing this gate does not skip
authority, it only decides whether the mode permits attempting the
action at all.

This module also carries `PrototypeDebt` (structured, queryable
shortcut-tracking -- spec section 15) and the LAUNCH evidence-category
gate (spec section 23), both as in-process registries mirroring the
existing pattern in `orca.mission.requirements` (module-level state,
`reset_registry_for_tests()` for test isolation) rather than a new
database table -- Phase 15.2's schema already covers durable
mission/requirement/evidence storage, and no acceptance criterion here
requires cross-process persistence of debt/gate state, so no new
migration is introduced (spec section 27).
"""
from __future__ import annotations

from dataclasses import dataclass, field
from datetime import datetime, timezone
from enum import Enum


def _now_iso() -> str:
    return datetime.now(timezone.utc).isoformat()


class CodeMode(str, Enum):
    ASSIST = "ASSIST"
    PROTOTYPE = "PROTOTYPE"
    BUILD = "BUILD"
    LAUNCH = "LAUNCH"


class CapabilityAction(str, Enum):
    READ_FILES = "READ_FILES"
    WRITE_FILES = "WRITE_FILES"
    DELETE_FILES = "DELETE_FILES"
    RUN_TESTS = "RUN_TESTS"
    RUN_ARBITRARY_COMMANDS = "RUN_ARBITRARY_COMMANDS"
    NETWORK_ACCESS = "NETWORK_ACCESS"
    INSTALL_DEPENDENCIES = "INSTALL_DEPENDENCIES"
    MODIFY_LOCKFILES = "MODIFY_LOCKFILES"
    ACCESS_SECRETS = "ACCESS_SECRETS"
    PERFORM_MIGRATIONS = "PERFORM_MIGRATIONS"
    DEPLOY = "DEPLOY"
    PUBLISH = "PUBLISH"
    MODIFY_PRODUCTION_RESOURCES = "MODIFY_PRODUCTION_RESOURCES"


# The mode capability matrix: what a mode may even ATTEMPT. This is a
# ceiling, not a grant -- every action in PRIVILEGED_ACTIONS below
# still requires a real, external authority decision regardless of
# mode, and mode membership here never substitutes for that decision.
_MODE_POLICY: dict[CodeMode, frozenset[CapabilityAction]] = {
    CodeMode.ASSIST: frozenset({
        CapabilityAction.READ_FILES,
        CapabilityAction.RUN_TESTS,
    }),
    CodeMode.PROTOTYPE: frozenset({
        CapabilityAction.READ_FILES,
        CapabilityAction.WRITE_FILES,
        CapabilityAction.RUN_TESTS,
        CapabilityAction.RUN_ARBITRARY_COMMANDS,
        CapabilityAction.INSTALL_DEPENDENCIES,
    }),
    CodeMode.BUILD: frozenset({
        CapabilityAction.READ_FILES,
        CapabilityAction.WRITE_FILES,
        CapabilityAction.DELETE_FILES,
        CapabilityAction.RUN_TESTS,
        CapabilityAction.RUN_ARBITRARY_COMMANDS,
        CapabilityAction.INSTALL_DEPENDENCIES,
        CapabilityAction.MODIFY_LOCKFILES,
    }),
    CodeMode.LAUNCH: frozenset({
        CapabilityAction.READ_FILES,
        CapabilityAction.WRITE_FILES,
        CapabilityAction.RUN_TESTS,
        CapabilityAction.RUN_ARBITRARY_COMMANDS,
        CapabilityAction.INSTALL_DEPENDENCIES,
        CapabilityAction.MODIFY_LOCKFILES,
        CapabilityAction.PERFORM_MIGRATIONS,
        CapabilityAction.DEPLOY,
        CapabilityAction.PUBLISH,
        CapabilityAction.MODIFY_PRODUCTION_RESOURCES,
    }),
}

# Actions that ALWAYS require the real Phase 15.5 authority path
# (orca.mission.operation_store.authorize_operation ->
# orca.mission.authority_bridge -> orca.godmode), no matter which mode
# permits attempting them. ASSIST permitting READ_FILES does not mean
# ASSIST can skip authority for DEPLOY -- DEPLOY is not even in
# ASSIST's policy, and even in LAUNCH (where it is), it still routes
# through real authority.
PRIVILEGED_ACTIONS: frozenset[CapabilityAction] = frozenset({
    CapabilityAction.DELETE_FILES,
    CapabilityAction.INSTALL_DEPENDENCIES,
    CapabilityAction.MODIFY_LOCKFILES,
    CapabilityAction.ACCESS_SECRETS,
    CapabilityAction.PERFORM_MIGRATIONS,
    CapabilityAction.DEPLOY,
    CapabilityAction.PUBLISH,
    CapabilityAction.MODIFY_PRODUCTION_RESOURCES,
})


def is_allowed_by_mode(mode: CodeMode, action: CapabilityAction) -> bool:
    """True if `mode`'s policy even permits attempting `action`. This
    is NOT an authority decision -- it is the ceiling mode narrows
    execution to. Callers must still route through
    orca.mission.operation_store for any action in
    PRIVILEGED_ACTIONS."""
    return action in _MODE_POLICY[mode]


def requires_authority(action: CapabilityAction) -> bool:
    return action in PRIVILEGED_ACTIONS


def mode_policy(mode: CodeMode) -> frozenset[CapabilityAction]:
    return _MODE_POLICY[mode]


# ─────────────────────────────────────────────────────────────────
#  Prototype Debt (spec section 15-16)
# ─────────────────────────────────────────────────────────────────

class PrototypeDebtError(Exception):
    pass


class DebtSeverity(str, Enum):
    LOW = "LOW"
    MEDIUM = "MEDIUM"
    HIGH = "HIGH"


class DebtResolutionStatus(str, Enum):
    OPEN = "OPEN"
    ACCEPTED = "ACCEPTED"  # explicitly accepted under policy -- not silently erased
    RESOLVED = "RESOLVED"


@dataclass(frozen=True)
class PrototypeDebt:
    id: str
    mission_id: str
    category: str
    description: str
    reason: str
    created_at: str
    severity: DebtSeverity
    blocking_for_build: bool
    blocking_for_launch: bool
    resolution_status: DebtResolutionStatus = DebtResolutionStatus.OPEN

    def __post_init__(self) -> None:
        if not self.description.strip():
            raise PrototypeDebtError("PrototypeDebt.description must not be empty")
        if not self.reason.strip():
            raise PrototypeDebtError("PrototypeDebt.reason must not be empty")


_DEBT_REGISTRY: dict[str, PrototypeDebt] = {}


def reset_registry_for_tests() -> None:
    _DEBT_REGISTRY.clear()


def record_debt(
    *,
    id: str,
    mission_id: str,
    category: str,
    description: str,
    reason: str,
    severity: DebtSeverity = DebtSeverity.MEDIUM,
    blocking_for_build: bool = False,
    blocking_for_launch: bool = True,
) -> PrototypeDebt:
    debt = PrototypeDebt(
        id=id,
        mission_id=mission_id,
        category=category,
        description=description,
        reason=reason,
        created_at=_now_iso(),
        severity=severity,
        blocking_for_build=blocking_for_build,
        blocking_for_launch=blocking_for_launch,
    )
    _DEBT_REGISTRY[id] = debt
    return debt


def debt_for_mission(mission_id: str) -> list[PrototypeDebt]:
    return [d for d in _DEBT_REGISTRY.values() if d.mission_id == mission_id]


def blocking_debt_for_mission(mission_id: str, *, target_mode: CodeMode) -> list[PrototypeDebt]:
    """Debt that must block a PROTOTYPE -> BUILD/LAUNCH transition
    unless resolved or explicitly ACCEPTED. Debt is never silently
    erased by this function -- it is surfaced, not cleared."""
    if target_mode not in (CodeMode.BUILD, CodeMode.LAUNCH):
        return []
    field_name = "blocking_for_build" if target_mode is CodeMode.BUILD else "blocking_for_launch"
    return [
        d for d in debt_for_mission(mission_id)
        if getattr(d, field_name) and d.resolution_status == DebtResolutionStatus.OPEN
    ]


def resolve_debt(debt_id: str, *, status: DebtResolutionStatus) -> PrototypeDebt:
    if status is DebtResolutionStatus.OPEN:
        raise PrototypeDebtError("resolve_debt() cannot re-open debt; construct a new record instead")
    existing = _DEBT_REGISTRY.get(debt_id)
    if existing is None:
        raise PrototypeDebtError(f"no such debt: {debt_id}")
    updated = PrototypeDebt(
        id=existing.id,
        mission_id=existing.mission_id,
        category=existing.category,
        description=existing.description,
        reason=existing.reason,
        created_at=existing.created_at,
        severity=existing.severity,
        blocking_for_build=existing.blocking_for_build,
        blocking_for_launch=existing.blocking_for_launch,
        resolution_status=status,
    )
    _DEBT_REGISTRY[debt_id] = updated
    return updated


# ─────────────────────────────────────────────────────────────────
#  LAUNCH evidence-category gate (spec section 23)
# ─────────────────────────────────────────────────────────────────

class LaunchCheckResult(str, Enum):
    PASS = "PASS"
    FAIL = "FAIL"
    UNVERIFIED = "UNVERIFIED"
    NOT_APPLICABLE = "NOT_APPLICABLE"


#: Category -> tri-state evidence. True = evidence supports PASS,
#: False = evidence proves FAIL, None = no evidence gathered yet
#: (UNVERIFIED, never defaulted to PASS), and a category entirely
#: absent from the input dict is also UNVERIFIED -- there is no
#: implicit-pass path through this function.
LaunchEvidence = dict[str, bool | None]

REQUIRED_LAUNCH_CATEGORIES: tuple[str, ...] = (
    "build_evidence",
    "tests",
    "regression",
    "security",
    "authority",
    "supply_chain",
    "release_configuration",
    "deployment_readiness",
    "rollback_readiness",
    "production_proof_hooks",
)


def evaluate_launch_gate(
    evidence: LaunchEvidence,
    *,
    not_applicable: frozenset[str] = frozenset(),
) -> dict[str, LaunchCheckResult]:
    """Missing evidence NEVER defaults to PASS. `not_applicable` marks
    categories genuinely inapplicable to this mission (e.g. no
    migration involved -> no PERFORM_MIGRATIONS evidence needed)."""
    results: dict[str, LaunchCheckResult] = {}
    for category in REQUIRED_LAUNCH_CATEGORIES:
        if category in not_applicable:
            results[category] = LaunchCheckResult.NOT_APPLICABLE
            continue
        value = evidence.get(category)
        if value is True:
            results[category] = LaunchCheckResult.PASS
        elif value is False:
            results[category] = LaunchCheckResult.FAIL
        else:
            results[category] = LaunchCheckResult.UNVERIFIED
    return results


def launch_gate_passes(results: dict[str, LaunchCheckResult]) -> bool:
    """True only if every category is PASS or NOT_APPLICABLE. Any
    FAIL or UNVERIFIED blocks a true LAUNCH-ready claim."""
    return all(r in (LaunchCheckResult.PASS, LaunchCheckResult.NOT_APPLICABLE) for r in results.values())


# ─────────────────────────────────────────────────────────────────
#  Launch-readiness sub-states (spec section 1, LAUNCH)
# ─────────────────────────────────────────────────────────────────

class LaunchReadiness(str, Enum):
    ENGINEERING_READY = "ENGINEERING_READY"
    SUBMISSION_READY = "SUBMISSION_READY"
    RELEASE_CANDIDATE = "RELEASE_CANDIDATE"
    PUBLISHED = "PUBLISHED"  # requires real external confirmation -- never self-asserted
