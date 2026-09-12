"""
TransformationRecord + Cognitive Conservation validation (spec section 13).

V1 definition of "important" (documented here, not over-engineered): an
atom is IMPORTANT if its kind is one of `IMPORTANT_ATOM_KINDS` below --
substantive cognitive content (assertions, hypotheses, assumptions,
conflicts, causal hypotheses, action/decision proposals, alternatives,
counterexamples, predictions). Procedural/scaffolding kinds (QUESTION,
UNKNOWN, LIMITATION, CONSTRAINT, OBSERVATION_REFERENCE, TEST_PROPOSAL,
VERIFICATION_REQUEST, ESCALATION_REQUEST) are not required to be tracked
across a transform -- they are expected to churn as an investigation
proceeds. This is a deliberately conservative V1 scope; a future phase may
refine it with real evidence of what actually needs conservation.

Conservation rule: every IMPORTANT atom present in the parent artifact
must either (a) still be present in the child artifact, or (b) appear in
the transformation's `superseded_atom_ids` or `removed_atom_ids` (each
with a `justification_refs` entry) -- an important atom that simply
disappears with no record raises `ConservationViolation`.
"""
from __future__ import annotations

from dataclasses import dataclass, field

from orneur.intelligence.ocl.artifact import CognitiveArtifact
from orneur.intelligence.ocl.enums import AtomKind, TransformationOperation
from orneur.intelligence.ocl.errors import ConservationViolation
from orneur.intelligence.ocl.provenance import Provenance

IMPORTANT_ATOM_KINDS = frozenset({
    AtomKind.ASSERTION,
    AtomKind.HYPOTHESIS,
    AtomKind.ASSUMPTION,
    AtomKind.CONFLICT,
    AtomKind.CAUSAL_HYPOTHESIS,
    AtomKind.ACTION_PROPOSAL,
    AtomKind.DECISION_PROPOSAL,
    AtomKind.ALTERNATIVE,
    AtomKind.COUNTEREXAMPLE,
    AtomKind.PREDICTION,
})


@dataclass(frozen=True)
class TransformationRecord:
    transformation_id: str
    parent_artifact_id: str
    child_artifact_id: str
    producer: Provenance
    operation: TransformationOperation
    timestamp: str
    schema_version: str
    affected_atom_ids: tuple[str, ...] = field(default_factory=tuple)
    created_atom_ids: tuple[str, ...] = field(default_factory=tuple)
    superseded_atom_ids: tuple[str, ...] = field(default_factory=tuple)
    removed_atom_ids: tuple[str, ...] = field(default_factory=tuple)
    justification_refs: tuple[str, ...] = field(default_factory=tuple)


def validate_conservation(
    parent: CognitiveArtifact, child: CognitiveArtifact, transformation: TransformationRecord,
) -> None:
    """Raises ConservationViolation if an IMPORTANT parent atom silently
    disappears in `child` without being recorded as superseded/removed in
    `transformation`."""
    child_atom_ids = {a.atom_id for a in child.atoms}
    accounted_for = set(transformation.superseded_atom_ids) | set(transformation.removed_atom_ids)

    for atom in parent.atoms:
        if atom.kind not in IMPORTANT_ATOM_KINDS:
            continue
        if atom.atom_id in child_atom_ids:
            continue
        if atom.atom_id in accounted_for:
            continue
        raise ConservationViolation(
            f"Important atom {atom.atom_id!r} (kind={atom.kind.value}) from parent artifact "
            f"{parent.artifact_id!r} is missing from child artifact {child.artifact_id!r} and "
            "is not recorded as superseded or removed in the transformation record."
        )
