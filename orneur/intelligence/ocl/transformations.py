"""
TransformationRecord + Cognitive Conservation validation (spec section 13;
Phase 17 closure section 11).

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

Conservation rule (strengthened this closure -- the original version only
checked whether an important parent atom ID remained present in the
child, which allowed a SAME-ID semantic rewrite to pass silently):

- an important atom present in the child UNDER THE SAME ID with an
  UNCHANGED canonical value is RETAINED -- no record needed.
- an important atom present in the child under the same ID with a
  CHANGED canonical value is a same-ID rewrite -- it MUST have an
  `AtomDisposition(atom_id, disposition="MODIFIED", justification_ref=...)`
  entry in `transformation.atom_dispositions`, with a non-empty
  `justification_ref` (enforced by `AtomDisposition.__post_init__`).
- an important atom ABSENT from the child MUST be accounted for either via
  the legacy `superseded_atom_ids`/`removed_atom_ids` tuples (kept for
  backward compatibility with the original, simpler V1 shape) or via an
  `AtomDisposition` entry with disposition SUPERSEDED/REMOVED.

An unaccounted-for disappearance OR rewrite raises `ConservationViolation`.
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

_VALID_DISPOSITIONS = frozenset({"SUPERSEDED", "REMOVED", "MODIFIED"})


@dataclass(frozen=True)
class AtomDisposition:
    """An explicit, auditable record of what happened to ONE important
    atom across a transform -- required whenever that atom's fate is not
    a simple, unchanged carry-forward."""
    atom_id: str
    disposition: str  # "SUPERSEDED" | "REMOVED" | "MODIFIED"
    justification_ref: str

    def __post_init__(self) -> None:
        if self.disposition not in _VALID_DISPOSITIONS:
            raise ConservationViolation(
                f"AtomDisposition for {self.atom_id!r} has unknown disposition {self.disposition!r} "
                f"-- must be one of {sorted(_VALID_DISPOSITIONS)!r}"
            )
        if not self.justification_ref:
            raise ConservationViolation(
                f"AtomDisposition for {self.atom_id!r} requires a non-empty justification_ref -- "
                "an important atom's supersession/removal/modification must be auditable, not bare."
            )


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
    # Legacy V1 shape, kept for backward compatibility: an atom named here
    # is treated as accounted-for when it disappears entirely (no specific
    # per-atom justification enforced -- prefer `atom_dispositions` for new
    # code, which DOES enforce a justification per atom).
    superseded_atom_ids: tuple[str, ...] = field(default_factory=tuple)
    removed_atom_ids: tuple[str, ...] = field(default_factory=tuple)
    justification_refs: tuple[str, ...] = field(default_factory=tuple)
    # Preferred, stronger V1.1-in-place shape: one explicit, justified
    # disposition per important atom whose fate is not a plain unchanged
    # carry-forward. Required for a SAME-ID semantic rewrite, since the
    # legacy tuples above can only express "this ID disappeared."
    atom_dispositions: tuple[AtomDisposition, ...] = field(default_factory=tuple)


def validate_conservation(
    parent: CognitiveArtifact, child: CognitiveArtifact, transformation: TransformationRecord,
) -> None:
    """Raises ConservationViolation if an IMPORTANT parent atom silently
    disappears from `child`, or is silently rewritten under the same ID,
    without being recorded in `transformation`."""
    child_atoms_by_id = {a.atom_id: a for a in child.atoms}
    legacy_accounted = set(transformation.superseded_atom_ids) | set(transformation.removed_atom_ids)
    disposition_by_id = {d.atom_id: d for d in transformation.atom_dispositions}

    for atom in parent.atoms:
        if atom.kind not in IMPORTANT_ATOM_KINDS:
            continue

        child_atom = child_atoms_by_id.get(atom.atom_id)
        if child_atom is not None:
            if child_atom == atom:
                continue  # retained, unchanged -- no record needed
            disp = disposition_by_id.get(atom.atom_id)
            if disp is None or disp.disposition != "MODIFIED":
                raise ConservationViolation(
                    f"Important atom {atom.atom_id!r} was rewritten under the same ID in child "
                    f"artifact {child.artifact_id!r} (its canonical value changed) without an "
                    "explicit MODIFIED AtomDisposition + justification -- a same-ID semantic "
                    "replacement must be recorded, not silent."
                )
            continue

        # Atom is entirely absent from the child.
        if atom.atom_id in legacy_accounted:
            continue
        disp = disposition_by_id.get(atom.atom_id)
        if disp is not None and disp.disposition in ("SUPERSEDED", "REMOVED"):
            continue

        raise ConservationViolation(
            f"Important atom {atom.atom_id!r} (kind={atom.kind.value}) from parent artifact "
            f"{parent.artifact_id!r} is missing from child artifact {child.artifact_id!r} and "
            "is not recorded as superseded or removed in the transformation record."
        )
