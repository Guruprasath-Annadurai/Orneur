"""
Phase 17 closure section 5: deep immutability. Verified against commit
ea9426f (`git show ea9426f:orneur/intelligence/ocl/canonical.py` has no
`deep_freeze`/`freeze_value` function at all -- `compile_artifact()` there
returned `canonicalize(draft)` directly, a shallow-frozen dataclass whose
`metadata` field was still an ordinary mutable dict) that this was a real,
reproducible gap before this closure's fix.
"""
from __future__ import annotations

from types import MappingProxyType

import pytest

from orneur.intelligence.ocl.canonical import digest
from orneur.intelligence.ocl.compiler import compile_artifact
from orneur.intelligence.ocl.proposals import ActionIntent
from tests.ocl.conftest import make_artifact, make_atom


def test_compiled_artifact_metadata_is_not_a_plain_mutable_dict():
    compiled = compile_artifact(make_artifact(metadata={"k": "v"}))
    assert isinstance(compiled.metadata, MappingProxyType)
    with pytest.raises(TypeError):
        compiled.metadata["tampered"] = True


def test_compiled_atom_metadata_cannot_be_mutated():
    compiled = compile_artifact(make_artifact(atoms=(make_atom("a1", metadata={"k": 1}),)))
    with pytest.raises(TypeError):
        compiled.atoms[0].metadata["x"] = "changed"


def test_compiled_action_intent_arguments_summary_cannot_be_mutated():
    intent = ActionIntent(intent_id="i1", proposed_capability="x", arguments_summary={"a": 1})
    compiled = compile_artifact(make_artifact(action_intents=(intent,)))
    with pytest.raises(TypeError):
        compiled.action_intents[0].arguments_summary["a"] = 2


def test_nested_list_inside_metadata_cannot_be_mutated():
    compiled = compile_artifact(make_artifact(atoms=(make_atom("a1", metadata={"items": [1, 2, 3]}),)))
    assert isinstance(compiled.atoms[0].metadata["items"], tuple)
    with pytest.raises(AttributeError):
        compiled.atoms[0].metadata["items"].append(4)


def test_caller_owned_dict_alias_is_not_shared_after_compile():
    """The load-bearing alias test: mutating the ORIGINAL dict the caller
    passed in must have zero effect on the already-compiled artifact."""
    metadata = {"nested": {"x": 1}}
    draft = make_artifact(atoms=(make_atom("a1", metadata=metadata),))
    compiled = compile_artifact(draft)

    metadata["nested"]["x"] = 999
    metadata["new_key"] = "should never appear"

    assert compiled.atoms[0].metadata["nested"]["x"] == 1
    assert "new_key" not in compiled.atoms[0].metadata


def test_digest_is_unaffected_by_post_compile_source_dict_mutation():
    metadata = {"nested": {"x": 1}}
    draft = make_artifact(atoms=(make_atom("a1", metadata=metadata),))
    compiled = compile_artifact(draft)
    before = digest(compiled)

    metadata["nested"]["x"] = 999

    assert digest(compiled) == before
