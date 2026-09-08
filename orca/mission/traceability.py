"""
Phase 15.7 -- requirement traceability report (spec section 13).

    Product Contract -> Requirement -> Acceptance Criterion ->
    Implementation reference -> Test reference -> Evidence reference

This module only READS the existing registries
(`orca.mission.requirements`, `orca.mission.acceptance_criteria`) and
assembles a report -- it never mutates state. A missing link is
represented explicitly (empty tuple / None), never omitted from the
report structure. Phase 15.8's Verification Engine will use this same
shape as its data foundation.
"""
from __future__ import annotations

from dataclasses import dataclass

from orca.mission.acceptance_criteria import AcceptanceCriterion, criteria_for_requirement
from orca.mission.requirements import Requirement
from orca.mission.requirements import get as get_requirement


@dataclass(frozen=True)
class TraceabilityRow:
    requirement_id: str
    status: str
    implementation_files: tuple[str, ...]
    test_files: tuple[str, ...]
    evidence_ref: str | None
    acceptance_criteria: tuple[AcceptanceCriterion, ...]

    @property
    def has_missing_links(self) -> bool:
        return (
            not self.implementation_files
            or not self.test_files
            or self.evidence_ref is None
            or not self.acceptance_criteria
            or any(c.evidence_ref is None for c in self.acceptance_criteria)
        )


def trace_requirement(requirement_id: str) -> TraceabilityRow:
    req: Requirement = get_requirement(requirement_id)
    criteria = criteria_for_requirement(requirement_id)
    return TraceabilityRow(
        requirement_id=req.id,
        status=req.status.value,
        implementation_files=req.implementation_files,
        test_files=req.test_files,
        evidence_ref=req.evidence_ref,
        acceptance_criteria=criteria,
    )


def trace_requirements(requirement_ids: tuple[str, ...]) -> tuple[TraceabilityRow, ...]:
    return tuple(trace_requirement(rid) for rid in requirement_ids)
