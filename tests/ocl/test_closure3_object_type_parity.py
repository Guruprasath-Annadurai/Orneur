"""
Phase 17 acceptance-boundary TYPE PARITY closure. The compiler is the ONLY
acceptance boundary -- an artifact accepted programmatically MUST satisfy
the same type schema as an equivalent artifact accepted from the strict
JSON wire path. This file covers the specific pre-fix gaps the owner audit
identified, each reproduced live (via a one-off script) against the prior
code before this fix landed: atom/relation namespace caused a raw
TypeError from an unhashable-list membership check; a raw string matching
an EvidenceKind member's text was silently accepted, both in a
nonprivileged and a privileged-reference position; a malformed
`provenance`/`model_identity` object raised a raw AttributeError before
any field was even read; and every top-level collection accepted a
wrong-type element with a raw AttributeError from the first field access.
"""
from __future__ import annotations

import pytest

from orneur.intelligence.ocl.artifact import CognitiveArtifact
from orneur.intelligence.ocl.compiler import compile_artifact
from orneur.intelligence.ocl.enums import AtomKind, RelationKind, SourceClass
from orneur.intelligence.ocl.errors import InvalidObjectType, InvalidStructuredValue
from orneur.intelligence.ocl.evidence import EvidenceAnchor
from orneur.intelligence.ocl.graph import CognitiveAtom, CognitiveRelation
from orneur.intelligence.ocl.provenance import ModelIdentityRef, Provenance
from orneur.intelligence.ocl.trust import CompilationTrustContext
from tests.ocl.conftest import make_artifact, make_atom, make_evidence, make_provenance


# ── A/B: namespace type safety (no raw TypeError from unhashable lookup) ──

def test_atom_namespace_wrong_type_raises_typed_error_not_raw_typeerror():
    atom = CognitiveAtom(
        atom_id="a1", kind=AtomKind.ASSERTION, source_class=SourceClass.MODEL_ASSERTION,
        content="x", namespace=[],
    )
    with pytest.raises(InvalidStructuredValue):
        compile_artifact(make_artifact(atoms=(atom,)))


def test_relation_namespace_wrong_type_raises_typed_error_not_raw_typeerror():
    a1 = make_atom("a1")
    a2 = make_atom("a2")
    rel = CognitiveRelation(
        relation_id="r1", kind=RelationKind.SUPPORTS, source_atom_id="a1", target_atom_id="a2", namespace=[],
    )
    with pytest.raises(InvalidStructuredValue):
        compile_artifact(make_artifact(atoms=(a1, a2), relations=(rel,)))


# ── C: EvidenceKind must be a genuine enum member, not a matching string ──

def test_evidence_kind_raw_string_rejected_when_unreferenced():
    ev = EvidenceAnchor(evidence_id="e1", evidence_kind="COURT_DECISION", issuer="x", reference="y")
    with pytest.raises(InvalidObjectType):
        compile_artifact(make_artifact(evidence=(ev,)))


def test_evidence_kind_raw_string_rejected_in_privileged_reference_position():
    ev = EvidenceAnchor(evidence_id="e1", evidence_kind="COURT_DECISION", issuer="x", reference="y")
    atom = make_atom(
        "a1", kind=AtomKind.OBSERVATION_REFERENCE,
        source_class=SourceClass.DETERMINISTIC_POLICY_REFERENCE, evidence_refs=("e1",),
    )
    with pytest.raises(InvalidObjectType):
        compile_artifact(
            make_artifact(atoms=(atom,), evidence=(ev,)),
            trust_context=CompilationTrustContext.TRUSTED_DETERMINISTIC_SYSTEM,
        )


def test_evidence_kind_genuine_enum_member_still_compiles():
    from orneur.intelligence.ocl.enums import EvidenceKind
    ev = make_evidence("e1", kind=EvidenceKind.COURT_DECISION)
    atom = make_atom(
        "a1", kind=AtomKind.OBSERVATION_REFERENCE,
        source_class=SourceClass.DETERMINISTIC_POLICY_REFERENCE, evidence_refs=("e1",),
    )
    compile_artifact(
        make_artifact(atoms=(atom,), evidence=(ev,)),
        trust_context=CompilationTrustContext.TRUSTED_DETERMINISTIC_SYSTEM,
    )


# ── D: Provenance object-type bypass ──────────────────────────────────────

@pytest.mark.parametrize("bad_provenance", [{}, "fake", 42, ["a"]])
def test_malformed_provenance_object_raises_typed_error(bad_provenance):
    art = CognitiveArtifact(
        artifact_id="art-1", schema_version="1.0.0", request_id="req-1",
        provenance=bad_provenance, created_at="2026-01-01T00:00:00+00:00",
    )
    with pytest.raises(InvalidObjectType):
        compile_artifact(art)


# ── E: ModelIdentityRef object-type bypass ────────────────────────────────

@pytest.mark.parametrize("bad_identity", [{}, "fake", 42])
def test_malformed_model_identity_object_raises_typed_error(bad_identity):
    from orneur.intelligence.ocl.enums import ProducerKind
    prov = Provenance(producer_kind=ProducerKind.DETERMINISTIC_SYSTEM, producer_id="x", model_identity=bad_identity)
    with pytest.raises(InvalidObjectType):
        compile_artifact(make_artifact(provenance=prov))


def test_genuine_model_identity_ref_still_compiles():
    from orneur.intelligence.ocl.enums import ProducerKind
    prov = Provenance(
        producer_kind=ProducerKind.DETERMINISTIC_SYSTEM, producer_id="x",
        model_identity=ModelIdentityRef(),
    )
    compile_artifact(make_artifact(provenance=prov))


# ── F: wrong top-level collection element types ───────────────────────────

@pytest.mark.parametrize("field,value", [
    ("atoms", (42,)),
    ("relations", ("bad",)),
    ("evidence", ({},)),
    ("action_intents", (42,)),
    ("verification_contracts", (42,)),
    ("escalation_requests", (42,)),
    ("causal_hypotheses", (42,)),
    ("counterfactual_branches", (42,)),
])
def test_wrong_top_level_collection_element_type_raises_typed_error(field, value):
    with pytest.raises(InvalidObjectType):
        compile_artifact(make_artifact(**{field: value}))


# ── Metadata / structured-object root-mapping parity ──────────────────────

def test_artifact_metadata_must_be_a_mapping_not_a_list():
    with pytest.raises(InvalidStructuredValue):
        compile_artifact(make_artifact(metadata=[]))


def test_atom_metadata_must_be_a_mapping_not_a_list():
    atom = make_atom("a1", metadata=[])
    with pytest.raises(InvalidStructuredValue):
        compile_artifact(make_artifact(atoms=(atom,)))


def test_relation_metadata_must_be_a_mapping_not_a_list():
    a1, a2 = make_atom("a1"), make_atom("a2")
    rel = CognitiveRelation(relation_id="r1", kind=RelationKind.SUPPORTS, source_atom_id="a1", target_atom_id="a2", metadata=[])
    with pytest.raises(InvalidStructuredValue):
        compile_artifact(make_artifact(atoms=(a1, a2), relations=(rel,)))


def test_evidence_metadata_must_be_a_mapping_not_a_list():
    ev = make_evidence("e1", metadata=[])
    with pytest.raises(InvalidStructuredValue):
        compile_artifact(make_artifact(evidence=(ev,)))


def test_action_intent_arguments_summary_must_be_a_mapping_not_a_list():
    from orneur.intelligence.ocl.proposals import ActionIntent
    intent = ActionIntent(intent_id="i1", proposed_capability="x", arguments_summary=[])
    with pytest.raises(InvalidStructuredValue):
        compile_artifact(make_artifact(action_intents=(intent,)))


def test_nested_json_arrays_and_maps_inside_a_valid_root_mapping_still_compile():
    compile_artifact(make_artifact(metadata={"tags": ["a", "b", {"nested": [1, 2, 3]}]}))


def test_top_level_metadata_root_must_be_mapping_but_nested_lists_allowed():
    atom = make_atom("a1", metadata={"list_field": [1, "two", {"three": [4, 5]}]})
    compile_artifact(make_artifact(atoms=(atom,)))
