from __future__ import annotations

from dataclasses import replace

import pytest

from orneur.intelligence.ocl.compiler import compile_artifact
from orneur.intelligence.ocl.enums import AtomKind, SourceClass
from orneur.intelligence.ocl.errors import DuplicateAtomId, EvidenceImpersonation
from tests.ocl.conftest import make_artifact, make_atom, make_evidence


def test_unique_atom_ids_accepted():
    artifact = make_artifact(atoms=(make_atom("a1"), make_atom("a2")))
    compile_artifact(artifact)


def test_duplicate_atom_id_rejected():
    artifact = make_artifact(atoms=(make_atom("a1"), make_atom("a1")))
    with pytest.raises(DuplicateAtomId):
        compile_artifact(artifact)


def test_all_atom_kinds_are_individually_valid():
    for i, kind in enumerate(AtomKind):
        atom = make_atom(f"a{i}", kind=kind, source_class=SourceClass.MODEL_ASSERTION)
        compile_artifact(make_artifact(atoms=(atom,)))


def test_model_assertion_cannot_claim_measured_evidence_source_class():
    """An ASSERTION atom (not OBSERVATION_REFERENCE) claiming
    MEASURED_EVIDENCE_REFERENCE is evidence impersonation -- rejected."""
    atom = make_atom("a1", kind=AtomKind.ASSERTION, source_class=SourceClass.MEASURED_EVIDENCE_REFERENCE)
    with pytest.raises(EvidenceImpersonation):
        compile_artifact(make_artifact(atoms=(atom,)))


def test_observation_reference_with_authoritative_source_and_evidence_ref_is_valid():
    ev = make_evidence("e1")
    atom = make_atom(
        "a1", kind=AtomKind.OBSERVATION_REFERENCE, source_class=SourceClass.MEASURED_EVIDENCE_REFERENCE,
        evidence_refs=("e1",),
    )
    compile_artifact(make_artifact(atoms=(atom,), evidence=(ev,)))


def test_observation_reference_claiming_authoritative_source_without_evidence_ref_rejected():
    atom = make_atom("a1", kind=AtomKind.OBSERVATION_REFERENCE, source_class=SourceClass.MEASURED_EVIDENCE_REFERENCE)
    with pytest.raises(EvidenceImpersonation):
        compile_artifact(make_artifact(atoms=(atom,)))
