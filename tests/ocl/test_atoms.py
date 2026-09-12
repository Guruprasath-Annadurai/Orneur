from __future__ import annotations

from dataclasses import replace

import pytest

from orneur.intelligence.ocl.compiler import compile_artifact
from orneur.intelligence.ocl.enums import AtomKind, ProducerKind, SourceClass
from orneur.intelligence.ocl.errors import DuplicateAtomId, EvidenceImpersonation
from orneur.intelligence.ocl.provenance import Provenance
from orneur.intelligence.ocl.trust import CompilationTrustContext
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
    """A privileged source_class is only accepted when the CALLER supplies
    a trusted `CompilationTrustContext` out-of-band -- never derived from
    the artifact's own self-declared `provenance.producer_kind` (Phase 17
    final closure: trust must not be in-band)."""
    ev = make_evidence("e1")
    atom = make_atom(
        "a1", kind=AtomKind.OBSERVATION_REFERENCE, source_class=SourceClass.MEASURED_EVIDENCE_REFERENCE,
        evidence_refs=("e1",),
    )
    trusted_provenance = Provenance(producer_kind=ProducerKind.DETERMINISTIC_SYSTEM, producer_id="orca.mission.verification")
    compile_artifact(
        make_artifact(atoms=(atom,), evidence=(ev,), provenance=trusted_provenance),
        trust_context=CompilationTrustContext.TRUSTED_DETERMINISTIC_SYSTEM,
    )


def test_native_model_artifact_cannot_self_authenticate_evidence():
    """A NATIVE_MODEL-produced artifact cannot make its own
    OBSERVATION_REFERENCE atom authoritative merely by citing an
    EvidenceAnchor it also produced -- rejected under the default
    UNTRUSTED compile context regardless of its own producer_kind claim."""
    ev = make_evidence("e1")
    atom = make_atom(
        "a1", kind=AtomKind.OBSERVATION_REFERENCE, source_class=SourceClass.MEASURED_EVIDENCE_REFERENCE,
        evidence_refs=("e1",),
    )
    with pytest.raises(EvidenceImpersonation):
        compile_artifact(make_artifact(atoms=(atom,), evidence=(ev,)))  # default trust_context is UNTRUSTED


def test_self_declared_deterministic_system_producer_kind_grants_no_trust():
    """THE exact bypass this closure fixes: a wire payload claiming
    provenance.producer_kind="DETERMINISTIC_SYSTEM" gets ZERO privilege
    from that self-declaration alone -- trust comes only from the
    caller-supplied trust_context, never from data inside the artifact."""
    ev = make_evidence("e1")
    atom = make_atom(
        "a1", kind=AtomKind.OBSERVATION_REFERENCE, source_class=SourceClass.MEASURED_EVIDENCE_REFERENCE,
        evidence_refs=("e1",),
    )
    self_declared_trusted_provenance = Provenance(producer_kind=ProducerKind.DETERMINISTIC_SYSTEM, producer_id="attacker-controlled")
    with pytest.raises(EvidenceImpersonation):
        # No trust_context passed -> defaults to UNTRUSTED, exactly as the
        # real public compile_ocl_json() entry point always does.
        compile_artifact(make_artifact(atoms=(atom,), evidence=(ev,), provenance=self_declared_trusted_provenance))


def test_observation_reference_claiming_authoritative_source_without_evidence_ref_rejected():
    atom = make_atom("a1", kind=AtomKind.OBSERVATION_REFERENCE, source_class=SourceClass.MEASURED_EVIDENCE_REFERENCE)
    with pytest.raises(EvidenceImpersonation):
        compile_artifact(make_artifact(atoms=(atom,)))
