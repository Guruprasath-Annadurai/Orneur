from __future__ import annotations

import pytest

from orneur.intelligence.ocl.compiler import compile_artifact
from orneur.intelligence.ocl.enums import RelationKind
from orneur.intelligence.ocl.errors import DanglingRelation, InvalidRelationShape
from tests.ocl.conftest import make_artifact, make_atom, make_relation


def test_valid_relation_between_existing_atoms_accepted():
    rel = make_relation("r1", RelationKind.SUPPORTS, "a1", "a2")
    compile_artifact(make_artifact(atoms=(make_atom("a1"), make_atom("a2")), relations=(rel,)))


def test_dangling_source_rejected():
    rel = make_relation("r1", RelationKind.SUPPORTS, "missing", "a2")
    with pytest.raises(DanglingRelation):
        compile_artifact(make_artifact(atoms=(make_atom("a2"),), relations=(rel,)))


def test_dangling_target_rejected():
    rel = make_relation("r1", RelationKind.SUPPORTS, "a1", "missing")
    with pytest.raises(DanglingRelation):
        compile_artifact(make_artifact(atoms=(make_atom("a1"),), relations=(rel,)))


def test_cycle_tolerant_relation_kind_allows_a_cycle():
    """Two atoms mutually CONTRADICTing each other is a real, valid shape."""
    atoms = (make_atom("a1"), make_atom("a2"))
    relations = (
        make_relation("r1", RelationKind.CONTRADICTS, "a1", "a2"),
        make_relation("r2", RelationKind.CONTRADICTS, "a2", "a1"),
    )
    compile_artifact(make_artifact(atoms=atoms, relations=relations))


def test_acyclic_relation_kind_rejects_a_cycle():
    atoms = (make_atom("a1"), make_atom("a2"), make_atom("a3"))
    relations = (
        make_relation("r1", RelationKind.DEPENDS_ON, "a1", "a2"),
        make_relation("r2", RelationKind.DEPENDS_ON, "a2", "a3"),
        make_relation("r3", RelationKind.DEPENDS_ON, "a3", "a1"),
    )
    with pytest.raises(InvalidRelationShape):
        compile_artifact(make_artifact(atoms=atoms, relations=relations))


def test_acyclic_relation_kind_rejects_self_loop():
    rel = make_relation("r1", RelationKind.DEPENDS_ON, "a1", "a1")
    with pytest.raises(InvalidRelationShape):
        compile_artifact(make_artifact(atoms=(make_atom("a1"),), relations=(rel,)))
