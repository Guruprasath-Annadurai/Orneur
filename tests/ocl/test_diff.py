from __future__ import annotations

from orneur.intelligence.ocl.diff import diff
from orneur.intelligence.ocl.enums import ProducerKind
from orneur.intelligence.ocl.provenance import ModelIdentityRef, Provenance
from tests.ocl.conftest import make_artifact, make_atom, make_evidence, make_relation


def test_added_and_removed_atoms_detected():
    a = make_artifact(artifact_id="a", atoms=(make_atom("a1"), make_atom("a2")))
    b = make_artifact(artifact_id="b", atoms=(make_atom("a2"), make_atom("a3")))
    d = diff(a, b)
    assert d.atoms_added == ("a3",)
    assert d.atoms_removed == ("a1",)


def test_evidence_added_and_removed_detected():
    a = make_artifact(artifact_id="a", evidence=(make_evidence("e1"),))
    b = make_artifact(artifact_id="b", evidence=(make_evidence("e2"),))
    d = diff(a, b)
    assert d.evidence_added == ("e2",)
    assert d.evidence_removed == ("e1",)


def test_no_change_yields_empty_diff():
    a = make_artifact(artifact_id="a", atoms=(make_atom("a1"),))
    b = make_artifact(artifact_id="b", atoms=(make_atom("a1"),))
    d = diff(a, b)
    assert d.atoms_added == ()
    assert d.atoms_removed == ()


def test_provenance_change_is_visible():
    prov_a = Provenance(producer_kind=ProducerKind.NATIVE_MODEL, producer_id="genesis-1", model_identity=ModelIdentityRef(family="genesis"))
    prov_b = Provenance(producer_kind=ProducerKind.NATIVE_MODEL, producer_id="novus-1", model_identity=ModelIdentityRef(family="novus"))
    a = make_artifact(artifact_id="a", provenance=prov_a)
    b = make_artifact(artifact_id="b", provenance=prov_b)
    assert diff(a, b).provenance_changed is True
    assert diff(a, a).provenance_changed is False


def test_diff_is_deterministic_across_repeated_calls():
    a = make_artifact(artifact_id="a", atoms=(make_atom("a1"), make_atom("a2")))
    b = make_artifact(artifact_id="b", atoms=(make_atom("a2"), make_atom("a3")))
    assert diff(a, b) == diff(a, b)


def test_same_id_atom_content_change_is_detected_as_modified():
    """Phase 17 closure: a same-ID atom whose content genuinely changed
    must be visible in the diff, not silently invisible just because the
    ID set didn't change."""
    a = make_artifact(artifact_id="a", atoms=(make_atom("a1", content="A"),))
    b = make_artifact(artifact_id="b", atoms=(make_atom("a1", content="COMPLETELY DIFFERENT"),))
    d = diff(a, b)
    assert d.atoms_added == ()
    assert d.atoms_removed == ()
    assert d.atoms_modified == ("a1",)


def test_same_id_atom_with_unchanged_content_is_not_modified():
    a = make_artifact(artifact_id="a", atoms=(make_atom("a1", content="same"),))
    b = make_artifact(artifact_id="b", atoms=(make_atom("a1", content="same"),))
    assert diff(a, b).atoms_modified == ()


def test_same_id_atom_changed_evidence_refs_is_detected():
    ev = make_evidence("e1")
    a = make_artifact(artifact_id="a", atoms=(make_atom("a1", evidence_refs=()),), evidence=(ev,))
    b = make_artifact(artifact_id="b", atoms=(make_atom("a1", evidence_refs=("e1",)),), evidence=(ev,))
    assert diff(a, b).atoms_modified == ("a1",)


def test_same_id_evidence_changed_reference_is_detected():
    a = make_artifact(artifact_id="a", evidence=(make_evidence("e1", reference="ref-A"),))
    b = make_artifact(artifact_id="b", evidence=(make_evidence("e1", reference="ref-B"),))
    d = diff(a, b)
    assert d.evidence_added == ()
    assert d.evidence_removed == ()
    assert d.evidence_modified == ("e1",)


def test_same_id_action_intent_changed_arguments_is_detected():
    from orneur.intelligence.ocl.proposals import ActionIntent

    a = make_artifact(artifact_id="a", action_intents=(ActionIntent(intent_id="i1", proposed_capability="x", arguments_summary={"n": 1}),))
    b = make_artifact(artifact_id="b", action_intents=(ActionIntent(intent_id="i1", proposed_capability="x", arguments_summary={"n": 2}),))
    assert diff(a, b).action_intents_modified == ("i1",)


def test_same_id_relation_changed_target_is_detected():
    a = make_artifact(artifact_id="a", atoms=(make_atom("a1"), make_atom("a2"), make_atom("a3")), relations=(make_relation("r1", source="a1", target="a2"),))
    b = make_artifact(artifact_id="b", atoms=(make_atom("a1"), make_atom("a2"), make_atom("a3")), relations=(make_relation("r1", source="a1", target="a3"),))
    assert diff(a, b).relations_modified == ("r1",)
