from __future__ import annotations

import pytest

from orneur.intelligence.ocl import limits
from orneur.intelligence.ocl.compiler import compile_artifact
from orneur.intelligence.ocl.errors import GraphLimitExceeded, InvalidStructuredValue, PayloadLimitExceeded
from tests.ocl.conftest import make_artifact, make_atom, make_relation


def test_max_atoms_limit_enforced():
    atoms = tuple(make_atom(f"a{i}") for i in range(limits.MAX_ATOMS_PER_ARTIFACT + 1))
    with pytest.raises(GraphLimitExceeded):
        compile_artifact(make_artifact(atoms=atoms))


def test_atoms_at_exact_limit_accepted():
    atoms = tuple(make_atom(f"a{i}") for i in range(limits.MAX_ATOMS_PER_ARTIFACT))
    compile_artifact(make_artifact(atoms=atoms))


def test_max_relations_limit_enforced():
    from orneur.intelligence.ocl.enums import RelationKind
    atoms = (make_atom("a1"), make_atom("a2"))
    relations = tuple(
        make_relation(f"r{i}", RelationKind.CORRELATES_WITH, "a1", "a2")
        for i in range(limits.MAX_RELATIONS_PER_ARTIFACT + 1)
    )
    with pytest.raises(GraphLimitExceeded):
        compile_artifact(make_artifact(atoms=atoms, relations=relations))


def test_oversized_content_rejected():
    """Phase 17 final closure: string length + type checking is now
    unified in typecheck.require_string(), which raises
    InvalidStructuredValue for both a wrong type AND an oversized value --
    replacing the narrower, type-unsafe _check_string_limits()."""
    atom = make_atom("a1", content="x" * (limits.MAX_STRING_FIELD_LENGTH + 1))
    with pytest.raises(InvalidStructuredValue):
        compile_artifact(make_artifact(atoms=(atom,)))


def test_oversized_metadata_key_count_rejected():
    metadata = {f"k{i}": i for i in range(limits.MAX_METADATA_KEYS + 1)}
    atom = make_atom("a1", metadata=metadata)
    with pytest.raises(PayloadLimitExceeded):
        compile_artifact(make_artifact(atoms=(atom,)))


def test_oversized_total_serialized_payload_rejected():
    atom = make_atom("a1", content="x" * (limits.MAX_STRING_FIELD_LENGTH))
    atoms = tuple(make_atom(f"a{i}", content="x" * limits.MAX_STRING_FIELD_LENGTH) for i in range(500))
    with pytest.raises((GraphLimitExceeded, PayloadLimitExceeded)):
        compile_artifact(make_artifact(atoms=atoms))


def test_oversized_metadata_nesting_rejected():
    nested = {"x": True}
    for _ in range(limits.MAX_METADATA_DEPTH + 2):
        nested = {"x": nested}
    atom = make_atom("a1", metadata=nested)
    with pytest.raises(PayloadLimitExceeded):
        compile_artifact(make_artifact(atoms=(atom,)))
