from __future__ import annotations

import pytest

from orneur.intelligence.ocl.canonical import digest, parse_ocl_draft_json, to_canonical_json
from orneur.intelligence.ocl.compiler import compile_artifact
from orneur.intelligence.ocl.errors import (
    DuplicateWireKey,
    InvalidStructuredValue,
    MissingMandatoryField,
    UnknownWireField,
)
from tests.ocl.conftest import make_artifact, make_atom, make_relation


def test_round_trip_preserves_content():
    original = compile_artifact(make_artifact(atoms=(make_atom("a1"), make_atom("a2"))))
    restored = parse_ocl_draft_json(to_canonical_json(original))
    compiled_restored = compile_artifact(restored)
    assert compiled_restored == original


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
    restored = compile_artifact(parse_ocl_draft_json(to_canonical_json(original)))
    assert restored.atoms[0].content == "héllo wörld — 日本語 🎉"


def test_nan_in_metadata_rejected_at_compile_time():
    """NaN is caught by the recursive structured-value validator during
    compile_artifact() itself, before canonicalization/serialization ever
    runs -- a stronger, earlier rejection than the old json.dumps-time-only
    check."""
    artifact = make_artifact(atoms=(make_atom("a1", metadata={"score": float("nan")}),))
    with pytest.raises(InvalidStructuredValue):
        compile_artifact(artifact)


def test_oversized_wire_payload_rejected_before_parsing():
    from orneur.intelligence.ocl import limits
    from orneur.intelligence.ocl.errors import PayloadLimitExceeded

    oversized = "x" * (limits.MAX_ARTIFACT_SERIALIZED_BYTES + 1)
    with pytest.raises(PayloadLimitExceeded):
        parse_ocl_draft_json(oversized)


def test_duplicate_json_object_key_rejected():
    original = compile_artifact(make_artifact(atoms=(make_atom("a1"),)))
    text = to_canonical_json(original)
    # Inject a duplicate top-level key by string surgery (still valid JSON
    # syntax, just semantically duplicated -- exactly what a real attacker
    # would submit).
    tampered = text[:-1] + ',"artifact_id":"duplicated"}'
    with pytest.raises(DuplicateWireKey):
        parse_ocl_draft_json(tampered)


def test_unknown_top_level_field_rejected():
    original = compile_artifact(make_artifact(atoms=(make_atom("a1"),)))
    text = to_canonical_json(original)
    tampered = text[:-1] + ',"totally_unknown_field":true}'
    with pytest.raises(UnknownWireField):
        parse_ocl_draft_json(tampered)


def test_unknown_atom_field_rejected():
    original = compile_artifact(make_artifact(atoms=(make_atom("a1"),)))
    import json
    data = json.loads(to_canonical_json(original))
    data["atoms"][0]["unexpected_field"] = "smuggled"
    with pytest.raises(UnknownWireField):
        parse_ocl_draft_json(json.dumps(data))


def test_missing_mandatory_field_produces_typed_error():
    import json
    data = json.loads(to_canonical_json(compile_artifact(make_artifact())))
    del data["schema_version"]
    with pytest.raises(MissingMandatoryField):
        parse_ocl_draft_json(json.dumps(data))


def test_compile_ocl_json_is_the_safe_public_entry_point():
    from orneur.intelligence.ocl.canonical import compile_ocl_json

    original = compile_artifact(make_artifact(atoms=(make_atom("a1"),)))
    restored = compile_ocl_json(to_canonical_json(original))
    assert restored == original


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
