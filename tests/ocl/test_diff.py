from __future__ import annotations

from orneur.intelligence.ocl.diff import diff
from orneur.intelligence.ocl.enums import ProducerKind
from orneur.intelligence.ocl.provenance import ModelIdentityRef, Provenance
from tests.ocl.conftest import make_artifact, make_atom, make_evidence


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
