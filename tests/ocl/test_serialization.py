from __future__ import annotations

import json

import pytest

from orneur.intelligence.ocl.canonical import artifact_from_canonical_json, digest, to_canonical_json
from orneur.intelligence.ocl.compiler import compile_artifact
from orneur.intelligence.ocl.errors import InvalidCanonicalForm
from tests.ocl.conftest import make_artifact, make_atom, make_relation


def test_round_trip_preserves_content():
    original = compile_artifact(make_artifact(atoms=(make_atom("a1"), make_atom("a2"))))
    restored = artifact_from_canonical_json(to_canonical_json(original))
    assert restored == original


def test_deterministic_ordering_regardless_of_input_order():
    a = compile_artifact(make_artifact(atoms=(make_atom("a2"), make_atom("a1"))))
    b = compile_artifact(make_artifact(atoms=(make_atom("a1"), make_atom("a2"))))
    assert to_canonical_json(a) == to_canonical_json(b)


def test_stable_digest_for_logically_equivalent_artifacts():
    a = compile_artifact(make_artifact(atoms=(make_atom("a2"), make_atom("a1"))))
    b = compile_artifact(make_artifact(atoms=(make_atom("a1"), make_atom("a2"))))
    assert digest(a) == digest(b)


def test_digest_changes_when_content_changes():
    a = compile_artifact(make_artifact(atoms=(make_atom("a1", content="X"),)))
    b = compile_artifact(make_artifact(atoms=(make_atom("a1", content="Y"),)))
    assert digest(a) != digest(b)


def test_unicode_content_round_trips():
    original = compile_artifact(make_artifact(atoms=(make_atom("a1", content="héllo wörld — 日本語 🎉"),)))
    restored = artifact_from_canonical_json(to_canonical_json(original))
    assert restored.atoms[0].content == "héllo wörld — 日本語 🎉"


def test_nan_in_metadata_rejected_for_canonical_form():
    """compile_artifact() itself computes the canonical form (to enforce the
    total-serialized-size limit), so a NaN is now caught at compile time,
    not only on a later, separate to_canonical_json() call."""
    artifact = make_artifact(atoms=(make_atom("a1", metadata={"score": float("nan")}),))
    with pytest.raises(InvalidCanonicalForm):
        compile_artifact(artifact)


def test_oversized_wire_payload_rejected_before_parsing():
    from orneur.intelligence.ocl import limits
    from orneur.intelligence.ocl.errors import PayloadLimitExceeded

    oversized = "x" * (limits.MAX_ARTIFACT_SERIALIZED_BYTES + 1)
    with pytest.raises(PayloadLimitExceeded):
        artifact_from_canonical_json(oversized)


def test_no_pickle_used_anywhere_in_serialization_module():
    import ast

    import orneur.intelligence.ocl.canonical as canonical_mod
    src = open(canonical_mod.__file__).read()
    tree = ast.parse(src)
    imported = {
        alias.name for node in ast.walk(tree) if isinstance(node, ast.Import) for alias in node.names
    } | {
        node.module for node in ast.walk(tree) if isinstance(node, ast.ImportFrom) and node.module
    }
    assert "pickle" not in imported
    assert "eval(" not in src
    assert "exec(" not in src
