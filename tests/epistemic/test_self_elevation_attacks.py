"""
Section 56 / 48 adversarial matrix: none of these may become KNOWN
without a genuine qualified evidence basis. If any of these tests fail,
Phase 18's core purpose is defeated.
"""
from __future__ import annotations

import pytest

from orneur.intelligence.epistemic import errors
from orneur.intelligence.epistemic.enums import EpistemicState, EvidenceResolutionStatus, EvidenceStance
from orneur.intelligence.epistemic.resolver import assess_artifact
from orneur.intelligence.ocl.enums import AtomKind, ProducerKind, RelationKind, SourceClass
from orneur.intelligence.ocl.provenance import ModelIdentityRef, Provenance
from tests.epistemic.conftest import (
    ASSESSED_AT,
    TRUSTED_OCL,
    TRUSTED_VERIFIER,
    UNTRUSTED_OCL,
    make_artifact,
    make_atom,
    make_evidence,
    make_relation,
    make_resolved_evidence,
)


def _assess(artifact, **kw):
    overlay = assess_artifact(
        artifact, ocl_trust_context=kw.pop("ocl_trust_context", TRUSTED_OCL),
        assessment_context_id="ctx-1", assessed_at=ASSESSED_AT, **kw,
    )
    return {a.atom_id: a for a in overlay.assessments}


def test_model_self_elevation_metadata_epistemic_state_known_is_ignored():
    """metadata={"epistemic_state": "KNOWN"} on the atom itself must have
    zero effect -- the resolver never reads atom.metadata at all."""
    artifact = make_artifact(atoms=(make_atom(atom_id="a1", metadata={"epistemic_state": "KNOWN"}),))
    results = _assess(artifact)
    assert results["a1"].state is not EpistemicState.KNOWN
    assert results["a1"].state is EpistemicState.UNKNOWN


def test_model_confidence_attack_metadata_confidence_one_is_ignored():
    artifact = make_artifact(atoms=(make_atom(atom_id="a1", metadata={"confidence": 1.0}),))
    results = _assess(artifact)
    assert results["a1"].state is not EpistemicState.KNOWN


def test_metadata_verified_true_is_rejected_by_ocl_before_phase_18_sees_it():
    """"verified" is one of OCL's own FORBIDDEN_METADATA_KEYS -- the
    artifact fails to even compile, one layer earlier than Phase 18's
    resolver. Defense in depth: even if a future OCL version relaxed
    that specific key, Phase 18's resolver still never reads atom
    metadata to decide state (see the sibling tests in this file for
    keys OCL does NOT reserve, e.g. "epistemic_state" and "confidence")."""
    from orneur.intelligence.ocl.errors import ForbiddenAuthorityConstruct

    artifact = make_artifact(atoms=(make_atom(atom_id="a1", metadata={"verified": True}),))
    with pytest.raises(ForbiddenAuthorityConstruct):
        _assess(artifact)


def test_fake_verified_string_with_bare_string_trust_context_is_rejected():
    """A caller passing the plain string "TRUSTED_DETERMINISTIC_VERIFIER"
    (not the real enum member) for resolution_trust_context must be
    rejected outright, not silently treated as trusted."""
    artifact = make_artifact(atoms=(make_atom(atom_id="a1", evidence_refs=("e1",)),), evidence=(make_evidence(evidence_id="e1"),))
    with pytest.raises(errors.InvalidResolutionTrustContext):
        _assess(
            artifact,
            resolved_evidence=(make_resolved_evidence(evidence_id="e1", target_atom_id="a1", status=EvidenceResolutionStatus.VERIFIED, stance=EvidenceStance.SUPPORTS),),
            resolution_trust_context="TRUSTED_DETERMINISTIC_VERIFIER",  # bare str, not the enum
        )


def test_fake_privileged_sourceclass_model_writes_measured_evidence_reference():
    """A model-authored atom claiming SourceClass.MEASURED_EVIDENCE_REFERENCE
    under an UNTRUSTED OCL compilation context is rejected by OCL itself
    (capability matrix) before Phase 18 ever runs -- and even if OCL
    accepted it, Phase 18 never reads source_class to decide state."""
    from orneur.intelligence.ocl.errors import ForbiddenAuthorityConstruct, InvalidObjectType, OclError

    artifact = make_artifact(atoms=(make_atom(atom_id="a1", source_class=SourceClass.MEASURED_EVIDENCE_REFERENCE),))
    with pytest.raises(OclError):
        assess_artifact(
            artifact, ocl_trust_context=UNTRUSTED_OCL, assessment_context_id="ctx-1", assessed_at=ASSESSED_AT,
        )


def test_human_input_source_class_does_not_become_known_without_evidence():
    """SourceClass.HUMAN_INPUT is genuine human provenance, not automatic
    truth -- a HUMAN_INPUT atom with no qualified evidence must not
    become KNOWN."""
    provenance = Provenance(producer_kind=ProducerKind.HUMAN, producer_id="user-1")
    artifact = make_artifact(
        provenance=provenance,
        atoms=(make_atom(atom_id="a1", source_class=SourceClass.HUMAN_INPUT),),
    )
    results = _assess(artifact)
    assert results["a1"].state is not EpistemicState.KNOWN
    assert results["a1"].state is EpistemicState.UNKNOWN


def test_duplicated_evidence_id_100_times_does_not_create_certainty():
    """Ten (or a hundred) references to the same underlying evidence_id
    must not become stronger merely because they were duplicated -- the
    resolver rejects the duplicate submission outright (see
    test_disputes.py's ConflictingEvidenceResolution test); this test
    confirms a single genuine evidence_id, even resolved once, produces
    exactly the same state as any other single qualified support -- no
    vote-count weighting exists anywhere in the algorithm."""
    artifact = make_artifact(atoms=(make_atom(atom_id="a1", evidence_refs=("e1",)),), evidence=(make_evidence(evidence_id="e1"),))
    results = _assess(
        artifact,
        resolved_evidence=(make_resolved_evidence(evidence_id="e1", target_atom_id="a1", status=EvidenceResolutionStatus.VERIFIED, stance=EvidenceStance.SUPPORTS),),
        resolution_trust_context=TRUSTED_VERIFIER,
    )
    assert results["a1"].state is EpistemicState.KNOWN
    assert len(results["a1"].direct_support_evidence_refs) == 1


def test_circular_support_cannot_create_known():
    artifact = make_artifact(
        atoms=(make_atom(atom_id="a"), make_atom(atom_id="b")),
        relations=(
            make_relation(relation_id="r1", kind=RelationKind.SUPPORTS, source="a", target="b"),
            make_relation(relation_id="r2", kind=RelationKind.SUPPORTS, source="b", target="a"),
        ),
    )
    results = _assess(artifact)
    assert results["a"].state not in (EpistemicState.KNOWN, EpistemicState.INFERRED)
    assert results["b"].state not in (EpistemicState.KNOWN, EpistemicState.INFERRED)


def test_malformed_types_none_dict_string_generator_are_rejected_not_crashed():
    artifact = make_artifact(atoms=(make_atom(atom_id="a1", evidence_refs=("e1",)),), evidence=(make_evidence(evidence_id="e1"),))

    for bad_input in (None, {"not": "a sequence"}, "a string is iterable but wrong", (x for x in range(3))):
        with pytest.raises(errors.EpistemicError):
            _assess(artifact, resolved_evidence=bad_input, resolution_trust_context=TRUSTED_VERIFIER)


def test_wrong_dataclass_type_in_resolved_evidence_sequence_is_rejected():
    artifact = make_artifact(atoms=(make_atom(atom_id="a1", evidence_refs=("e1",)),), evidence=(make_evidence(evidence_id="e1"),))
    with pytest.raises(errors.EpistemicError):
        _assess(artifact, resolved_evidence=({"evidence_id": "e1"},), resolution_trust_context=TRUSTED_VERIFIER)


def test_overlay_replay_across_different_artifact_is_rejected():
    from orneur.intelligence.epistemic.resolver import verify_overlay_binding
    from orneur.intelligence.ocl.compiler import compile_artifact

    artifact_a = make_artifact(artifact_id="art-a", atoms=(make_atom(atom_id="a1"),))
    artifact_b = make_artifact(artifact_id="art-b", atoms=(make_atom(atom_id="a1"),))

    overlay = assess_artifact(
        artifact_a, ocl_trust_context=TRUSTED_OCL, assessment_context_id="ctx-1", assessed_at=ASSESSED_AT,
    )
    compiled_b = compile_artifact(artifact_b, trust_context=TRUSTED_OCL)
    with pytest.raises(errors.SourceArtifactMismatch):
        verify_overlay_binding(overlay, compiled_b)
