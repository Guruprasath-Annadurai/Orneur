"""
Cognitive Diff (spec section 12) -- a deterministic STRUCTURAL diff
between two CognitiveArtifacts. Never infers semantic/epistemic truth
beyond what is encoded in the artifacts themselves (e.g. "hypothesis
promoted" is not a concept this module invents -- only atom/relation/
evidence/provenance presence changes are reported).
"""
from __future__ import annotations

from dataclasses import dataclass

from orneur.intelligence.ocl.artifact import CognitiveArtifact


@dataclass(frozen=True)
class CognitiveDiff:
    from_artifact_id: str
    to_artifact_id: str
    atoms_added: tuple[str, ...]
    atoms_removed: tuple[str, ...]
    relations_added: tuple[str, ...]
    relations_removed: tuple[str, ...]
    evidence_added: tuple[str, ...]
    evidence_removed: tuple[str, ...]
    action_intents_added: tuple[str, ...]
    action_intents_removed: tuple[str, ...]
    limitations_added: tuple[str, ...]
    limitations_removed: tuple[str, ...]
    provenance_changed: bool


def _added_removed(before: set, after: set) -> tuple[tuple[str, ...], tuple[str, ...]]:
    return tuple(sorted(after - before)), tuple(sorted(before - after))


def diff(a: CognitiveArtifact, b: CognitiveArtifact) -> CognitiveDiff:
    atoms_added, atoms_removed = _added_removed(
        {x.atom_id for x in a.atoms}, {x.atom_id for x in b.atoms}
    )
    relations_added, relations_removed = _added_removed(
        {x.relation_id for x in a.relations}, {x.relation_id for x in b.relations}
    )
    evidence_added, evidence_removed = _added_removed(
        {x.evidence_id for x in a.evidence}, {x.evidence_id for x in b.evidence}
    )
    intents_added, intents_removed = _added_removed(
        {x.intent_id for x in a.action_intents}, {x.intent_id for x in b.action_intents}
    )
    limitations_added, limitations_removed = _added_removed(
        set(a.limitation_atom_refs), set(b.limitation_atom_refs)
    )

    return CognitiveDiff(
        from_artifact_id=a.artifact_id,
        to_artifact_id=b.artifact_id,
        atoms_added=atoms_added,
        atoms_removed=atoms_removed,
        relations_added=relations_added,
        relations_removed=relations_removed,
        evidence_added=evidence_added,
        evidence_removed=evidence_removed,
        action_intents_added=intents_added,
        action_intents_removed=intents_removed,
        limitations_added=limitations_added,
        limitations_removed=limitations_removed,
        provenance_changed=(a.provenance != b.provenance),
    )
