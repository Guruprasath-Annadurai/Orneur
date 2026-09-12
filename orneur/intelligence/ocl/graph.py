"""
CognitiveAtom + CognitiveRelation -- the OCL cognitive graph's node/edge
types (spec sections 8.2, 8.3, 11). Plain, frozen data shapes; graph-level
validation (dangling references, cycles, duplicate IDs, forbidden
authority-like constructs) lives in `compiler.py`, which is the only
module allowed to reject an artifact.
"""
from __future__ import annotations

from dataclasses import dataclass, field

from orneur.intelligence.ocl.enums import AtomKind, RelationKind, SourceClass


@dataclass(frozen=True)
class CognitiveAtom:
    atom_id: str
    kind: AtomKind
    source_class: SourceClass
    content: str
    namespace: str = "core"
    evidence_refs: tuple[str, ...] = field(default_factory=tuple)
    metadata: dict = field(default_factory=dict)


@dataclass(frozen=True)
class CognitiveRelation:
    relation_id: str
    kind: RelationKind
    source_atom_id: str
    target_atom_id: str
    namespace: str = "core"
    metadata: dict = field(default_factory=dict)
