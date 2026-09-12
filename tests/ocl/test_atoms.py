from __future__ import annotations

from dataclasses import replace

import pytest

from orneur.intelligence.ocl.compiler import compile_artifact
from orneur.intelligence.ocl.enums import AtomKind, ProducerKind, SourceClass
from orneur.intelligence.ocl.errors import DuplicateAtomId, EvidenceImpersonation
from orneur.intelligence.ocl.provenance import Provenance
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
    """An authoritative source_class is only accepted inside an artifact
    produced by a TRUSTED system (DETERMINISTIC_SYSTEM here) -- a
    NATIVE_MODEL/EXTERNAL_PROVIDER-produced artifact can never
    self-authenticate its own evidence (Phase 17 closure §8)."""
    ev = make_evidence("e1")
    atom = make_atom(
        "a1", kind=AtomKind.OBSERVATION_REFERENCE, source_class=SourceClass.MEASURED_EVIDENCE_REFERENCE,
        evidence_refs=("e1",),
    )
    trusted_provenance = Provenance(producer_kind=ProducerKind.DETERMINISTIC_SYSTEM, producer_id="orca.mission.verification")
    compile_artifact(make_artifact(atoms=(atom,), evidence=(ev,), provenance=trusted_provenance))


def test_native_model_artifact_cannot_self_authenticate_evidence():
    """The exact Phase 17 closure §8 doctrine: a NATIVE_MODEL-produced
    artifact cannot make its own OBSERVATION_REFERENCE atom authoritative
    merely by citing an EvidenceAnchor it also produced."""
    ev = make_evidence("e1")
    atom = make_atom(
        "a1", kind=AtomKind.OBSERVATION_REFERENCE, source_class=SourceClass.MEASURED_EVIDENCE_REFERENCE,
        evidence_refs=("e1",),
    )
    with pytest.raises(EvidenceImpersonation):
        compile_artifact(make_artifact(atoms=(atom,), evidence=(ev,)))  # default provenance is NATIVE_MODEL


def test_observation_reference_claiming_authoritative_source_without_evidence_ref_rejected():
    atom = make_atom("a1", kind=AtomKind.OBSERVATION_REFERENCE, source_class=SourceClass.MEASURED_EVIDENCE_REFERENCE)
    with pytest.raises(EvidenceImpersonation):
        compile_artifact(make_artifact(atoms=(atom,)))
