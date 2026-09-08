"""
Phase 15.7 -- typed Acceptance Criteria (spec section 7).

Distinct from (and complementary to) `orca.mission.requirements
.Requirement.acceptance_criteria`, which is a plain tuple of
descriptive strings a requirement's own registration is validated
against. This module adds the RICHER, independently-tracked object
spec section 7 asks for -- a criterion with its own id, its own
verification method, and its own VERIFIED/evidence lifecycle -- so a
requirement's acceptance can be traced and (later, Phase 15.8)
actually re-verified criterion by criterion, not just declared as a
sentence at registration time.

Every criterion links to a `requirement_id` that MUST already be
registered in `orca.mission.requirements` -- an orphan criterion
(pointing at a requirement that doesn't exist) is rejected at
creation, not merely discouraged.
"""
from __future__ import annotations

from dataclasses import dataclass, field, replace
from datetime import datetime, timezone
from enum import Enum

from orca.mission import requirements as requirements_module


def _now_iso() -> str:
    return datetime.now(timezone.utc).isoformat()


class VerificationMethod(str, Enum):
    UNIT_TEST = "UNIT_TEST"
    INTEGRATION_TEST = "INTEGRATION_TEST"
    E2E_TEST = "E2E_TEST"
    STATIC_ANALYSIS = "STATIC_ANALYSIS"
    SECURITY_TEST = "SECURITY_TEST"
    PERFORMANCE_TEST = "PERFORMANCE_TEST"
    MANUAL_REVIEW = "MANUAL_REVIEW"
    EXTERNAL_CONFIRMATION = "EXTERNAL_CONFIRMATION"
    INSPECTION = "INSPECTION"


class CriterionStatus(str, Enum):
    PENDING = "PENDING"
    IMPLEMENTED = "IMPLEMENTED"
    VERIFIED = "VERIFIED"
    FAILED = "FAILED"


_ALLOWED_TRANSITIONS: dict[CriterionStatus, frozenset[CriterionStatus]] = {
    CriterionStatus.PENDING: frozenset({CriterionStatus.IMPLEMENTED, CriterionStatus.FAILED}),
    CriterionStatus.IMPLEMENTED: frozenset({CriterionStatus.VERIFIED, CriterionStatus.FAILED}),
    CriterionStatus.VERIFIED: frozenset(),
    CriterionStatus.FAILED: frozenset({CriterionStatus.PENDING}),  # retry after a real fix
}


class CriterionError(Exception):
    pass


@dataclass(frozen=True)
class AcceptanceCriterion:
    criterion_id: str
    requirement_id: str
    description: str
    verification_method: VerificationMethod
    created_at: str
    status: CriterionStatus = CriterionStatus.PENDING
    evidence_ref: str | None = None

    def __post_init__(self) -> None:
        if not self.description.strip():
            raise CriterionError(f"{self.criterion_id}: description must not be empty.")
        _VAGUE_PHRASES = ("works well", "is secure", "is fast", "looks professional",
                          "good ux", "user friendly", "robust", "scalable")
        lowered = self.description.strip().lower()
        if lowered in _VAGUE_PHRASES:
            raise CriterionError(
                f"{self.criterion_id}: description {self.description!r} is not measurable/testable -- "
                f"spec section 7 explicitly bans vague criteria like this."
            )
        if self.status is CriterionStatus.VERIFIED and not (self.evidence_ref or "").strip():
            raise CriterionError(
                f"{self.criterion_id}: VERIFIED requires a non-empty evidence_ref -- "
                f"implementation existing is not the same as verified (spec section 7/22)."
            )


_REGISTRY: dict[str, AcceptanceCriterion] = {}


def reset_registry_for_tests() -> None:
    _REGISTRY.clear()


def register_criterion(
    *,
    criterion_id: str,
    requirement_id: str,
    description: str,
    verification_method: VerificationMethod,
) -> AcceptanceCriterion:
    """Rejects an orphan criterion -- requirement_id must already
    exist in orca.mission.requirements' registry."""
    try:
        requirements_module.get(requirement_id)
    except requirements_module.RequirementError:
        raise CriterionError(
            f"{criterion_id}: requirement_id {requirement_id!r} is not a registered requirement "
            f"-- an acceptance criterion cannot be orphaned from its requirement."
        ) from None
    if criterion_id in _REGISTRY:
        raise CriterionError(f"{criterion_id} is already registered.")
    criterion = AcceptanceCriterion(
        criterion_id=criterion_id, requirement_id=requirement_id, description=description,
        verification_method=verification_method, created_at=_now_iso(),
    )
    _REGISTRY[criterion_id] = criterion
    return criterion


def get_criterion(criterion_id: str) -> AcceptanceCriterion:
    try:
        return _REGISTRY[criterion_id]
    except KeyError:
        raise CriterionError(f"No such criterion: {criterion_id}") from None


def criteria_for_requirement(requirement_id: str) -> tuple[AcceptanceCriterion, ...]:
    return tuple(c for c in _REGISTRY.values() if c.requirement_id == requirement_id)


def transition_criterion(
    criterion_id: str,
    new_status: CriterionStatus,
    *,
    evidence_ref: str | None = None,
) -> AcceptanceCriterion:
    current = get_criterion(criterion_id)
    if new_status not in _ALLOWED_TRANSITIONS[current.status]:
        raise CriterionError(
            f"{criterion_id}: cannot transition {current.status.value} -> {new_status.value}. "
            f"Allowed from {current.status.value}: "
            f"{sorted(s.value for s in _ALLOWED_TRANSITIONS[current.status]) or 'none (terminal)'}."
        )
    if new_status is CriterionStatus.VERIFIED and not (evidence_ref or "").strip():
        raise CriterionError(f"{criterion_id}: VERIFIED requires a non-empty evidence_ref.")
    updated = replace(current, status=new_status, evidence_ref=evidence_ref or current.evidence_ref)
    _REGISTRY[criterion_id] = updated
    return updated


def requirement_all_criteria_verified(requirement_id: str) -> bool:
    """True only if the requirement has at least one criterion AND
    every one of them is VERIFIED -- a requirement with zero criteria
    is never considered "fully verified" by this check (an empty set
    is not vacuously true here, by design)."""
    criteria = criteria_for_requirement(requirement_id)
    if not criteria:
        return False
    return all(c.status is CriterionStatus.VERIFIED for c in criteria)
