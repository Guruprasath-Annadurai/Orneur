from __future__ import annotations

from orneur.intelligence.epistemic.enums import EpistemicPolarity, EpistemicReasonCode, EpistemicState, EvidenceResolutionStatus, EvidenceStance
from orneur.intelligence.epistemic.resolver import assess_artifact
from orneur.intelligence.ocl.enums import RelationKind
from tests.epistemic.conftest import ASSESSED_AT, TRUSTED_OCL, TRUSTED_VERIFIER, make_artifact, make_atom, make_evidence, make_relation, make_resolved_evidence


def _assess(artifact, **kw):
    overlay = assess_artifact(
        artifact, ocl_trust_context=TRUSTED_OCL, assessment_context_id="ctx-1", assessed_at=ASSESSED_AT, **kw,
    )
    return {a.atom_id: a for a in overlay.assessments}


def test_direct_support_and_direct_refutation_on_same_atom_yields_disputed():
    artifact = make_artifact(
        atoms=(make_atom(atom_id="a1", evidence_refs=("e1", "e2")),),
        evidence=(make_evidence(evidence_id="e1"), make_evidence(evidence_id="e2")),
    )
    results = _assess(
        artifact,
        resolved_evidence=(
            make_resolved_evidence(evidence_id="e1", target_atom_id="a1", status=EvidenceResolutionStatus.VERIFIED, stance=EvidenceStance.SUPPORTS),
            make_resolved_evidence(evidence_id="e2", target_atom_id="a1", status=EvidenceResolutionStatus.VERIFIED, stance=EvidenceStance.REFUTES),
        ),
        resolution_trust_context=TRUSTED_VERIFIER,
    )
    a1 = results["a1"]
    assert a1.state is EpistemicState.DISPUTED
    assert a1.polarity is EpistemicPolarity.MIXED
    assert EpistemicReasonCode.VERIFIED_CONTRADICTION in a1.reason_codes


def test_direct_support_plus_derived_refutation_yields_disputed():
    # a1 has direct support; a2 has direct support and FALSIFIES a1
    artifact = make_artifact(
        atoms=(
            make_atom(atom_id="a1", evidence_refs=("e1",)),
            make_atom(atom_id="a2", evidence_refs=("e2",)),
        ),
        relations=(make_relation(relation_id="r1", kind=RelationKind.FALSIFIES, source="a2", target="a1"),),
        evidence=(make_evidence(evidence_id="e1"), make_evidence(evidence_id="e2")),
    )
    results = _assess(
        artifact,
        resolved_evidence=(
            make_resolved_evidence(evidence_id="e1", target_atom_id="a1", status=EvidenceResolutionStatus.VERIFIED, stance=EvidenceStance.SUPPORTS),
            make_resolved_evidence(evidence_id="e2", target_atom_id="a2", status=EvidenceResolutionStatus.VERIFIED, stance=EvidenceStance.SUPPORTS),
        ),
        resolution_trust_context=TRUSTED_VERIFIER,
    )
    assert results["a1"].state is EpistemicState.DISPUTED


def test_unsupported_model_assertions_contradicting_each_other_do_not_create_disputed():
    """Two unsupported model assertions contradicting each other is mere
    disagreement, not a qualified dispute -- must downgrade to UNCERTAIN
    with UNQUALIFIED_CONTRADICTION, never DISPUTED."""
    artifact = make_artifact(
        atoms=(make_atom(atom_id="a1"), make_atom(atom_id="a2")),
        relations=(make_relation(relation_id="r1", kind=RelationKind.CONTRADICTS, source="a1", target="a2"),),
    )
    results = _assess(artifact)
    assert results["a1"].state is EpistemicState.UNCERTAIN
    assert results["a2"].state is EpistemicState.UNCERTAIN
    assert EpistemicReasonCode.UNQUALIFIED_CONTRADICTION in results["a1"].reason_codes
    assert EpistemicReasonCode.UNQUALIFIED_CONTRADICTION in results["a2"].reason_codes


def test_qualified_atom_contradicting_unqualified_atom_only_flags_the_unqualified_one():
    """a1 is qualified (KNOWN); a2 has no evidence of its own but is
    CONTRADICTED by a1, which IS established. This is not "unsupported
    disagreement" (test above) -- a1's qualified basis is a real,
    epistemically relevant signal against a2, so a2 must be UNCERTAIN
    (with CONTRADICTED_BY_QUALIFIED_ATOM), not UNKNOWN. Critically, a1
    itself must NOT be downgraded merely because a2 is unsupported
    prose -- a1 stays KNOWN."""
    artifact = make_artifact(
        atoms=(make_atom(atom_id="a1", evidence_refs=("e1",)), make_atom(atom_id="a2")),
        relations=(make_relation(relation_id="r1", kind=RelationKind.CONTRADICTS, source="a1", target="a2"),),
        evidence=(make_evidence(evidence_id="e1"),),
    )
    results = _assess(
        artifact,
        resolved_evidence=(make_resolved_evidence(evidence_id="e1", target_atom_id="a1", status=EvidenceResolutionStatus.VERIFIED, stance=EvidenceStance.SUPPORTS),),
        resolution_trust_context=TRUSTED_VERIFIER,
    )
    assert results["a1"].state is EpistemicState.KNOWN
    assert results["a2"].state is EpistemicState.UNCERTAIN
    assert EpistemicReasonCode.CONTRADICTED_BY_QUALIFIED_ATOM in results["a2"].reason_codes


def test_duplicate_evidence_reference_does_not_create_extra_certainty():
    """Evidence stuffing: the SAME evidence_id duplicated must be
    rejected as a conflicting/duplicate resolution, not silently voted
    into stronger certainty."""
    import pytest

    from orneur.intelligence.epistemic import errors

    artifact = make_artifact(atoms=(make_atom(atom_id="a1", evidence_refs=("e1",)),), evidence=(make_evidence(evidence_id="e1"),))
    with pytest.raises(errors.ConflictingEvidenceResolution):
        _assess(
            artifact,
            resolved_evidence=(
                make_resolved_evidence(evidence_id="e1", target_atom_id="a1", status=EvidenceResolutionStatus.VERIFIED, stance=EvidenceStance.SUPPORTS),
                make_resolved_evidence(evidence_id="e1", target_atom_id="a1", status=EvidenceResolutionStatus.VERIFIED, stance=EvidenceStance.SUPPORTS),
            ),
            resolution_trust_context=TRUSTED_VERIFIER,
        )


def test_qualified_a_contradicts_b_both_independently_affirmed_forces_disputed():
    """Reproduced defect: A and B each have independent VERIFIED+SUPPORTS
    evidence, and A CONTRADICTS B. Prior behavior left both KNOWN/
    AFFIRMED, silently ignoring the qualified conflict. Correct
    behavior: both atoms become DISPUTED -- their independently
    established bases cannot both be true given the CONTRADICTS
    relation between them, and contradiction must not be hidden by
    confidence."""
    artifact = make_artifact(
        atoms=(
            make_atom(atom_id="a", evidence_refs=("e1",)),
            make_atom(atom_id="b", evidence_refs=("e2",)),
        ),
        relations=(make_relation(relation_id="r1", kind=RelationKind.CONTRADICTS, source="a", target="b"),),
        evidence=(make_evidence(evidence_id="e1"), make_evidence(evidence_id="e2")),
    )
    results = _assess(
        artifact,
        resolved_evidence=(
            make_resolved_evidence(evidence_id="e1", target_atom_id="a", status=EvidenceResolutionStatus.VERIFIED, stance=EvidenceStance.SUPPORTS),
            make_resolved_evidence(evidence_id="e2", target_atom_id="b", status=EvidenceResolutionStatus.VERIFIED, stance=EvidenceStance.SUPPORTS),
        ),
        resolution_trust_context=TRUSTED_VERIFIER,
    )
    assert results["a"].state is EpistemicState.DISPUTED
    assert results["b"].state is EpistemicState.DISPUTED
    assert EpistemicReasonCode.VERIFIED_CONTRADICTION in results["a"].reason_codes
    assert EpistemicReasonCode.VERIFIED_CONTRADICTION in results["b"].reason_codes


def test_qualified_a_contradicts_b_one_affirmed_one_refuted_is_compatible_no_dispute():
    """A AFFIRMED + B REFUTED is logically compatible with A CONTRADICTS
    B (A true, B false, they contradict -- consistent). Neither should
    be forced into DISPUTED."""
    artifact = make_artifact(
        atoms=(
            make_atom(atom_id="a", evidence_refs=("e1",)),
            make_atom(atom_id="b", evidence_refs=("e2",)),
        ),
        relations=(make_relation(relation_id="r1", kind=RelationKind.CONTRADICTS, source="a", target="b"),),
        evidence=(make_evidence(evidence_id="e1"), make_evidence(evidence_id="e2")),
    )
    results = _assess(
        artifact,
        resolved_evidence=(
            make_resolved_evidence(evidence_id="e1", target_atom_id="a", status=EvidenceResolutionStatus.VERIFIED, stance=EvidenceStance.SUPPORTS),
            make_resolved_evidence(evidence_id="e2", target_atom_id="b", status=EvidenceResolutionStatus.VERIFIED, stance=EvidenceStance.REFUTES),
        ),
        resolution_trust_context=TRUSTED_VERIFIER,
    )
    assert results["a"].state is EpistemicState.KNOWN
    assert results["a"].polarity is EpistemicPolarity.AFFIRMED
    assert results["b"].state is EpistemicState.KNOWN
    assert results["b"].polarity is EpistemicPolarity.REFUTED


def test_qualified_a_contradicts_b_both_independently_refuted_invents_no_truth():
    """A REFUTED + B REFUTED is compatible with CONTRADICTS (both false
    satisfies "not both true") -- CONTRADICTS must not invent truth
    about either merely from this relation."""
    artifact = make_artifact(
        atoms=(
            make_atom(atom_id="a", evidence_refs=("e1",)),
            make_atom(atom_id="b", evidence_refs=("e2",)),
        ),
        relations=(make_relation(relation_id="r1", kind=RelationKind.CONTRADICTS, source="a", target="b"),),
        evidence=(make_evidence(evidence_id="e1"), make_evidence(evidence_id="e2")),
    )
    results = _assess(
        artifact,
        resolved_evidence=(
            make_resolved_evidence(evidence_id="e1", target_atom_id="a", status=EvidenceResolutionStatus.VERIFIED, stance=EvidenceStance.REFUTES),
            make_resolved_evidence(evidence_id="e2", target_atom_id="b", status=EvidenceResolutionStatus.VERIFIED, stance=EvidenceStance.REFUTES),
        ),
        resolution_trust_context=TRUSTED_VERIFIER,
    )
    assert results["a"].state is EpistemicState.KNOWN
    assert results["a"].polarity is EpistemicPolarity.REFUTED
    assert results["b"].state is EpistemicState.KNOWN
    assert results["b"].polarity is EpistemicPolarity.REFUTED


def test_conflicting_resolution_records_fail_closed_not_silently_picked():
    import pytest

    from orneur.intelligence.epistemic import errors

    artifact = make_artifact(atoms=(make_atom(atom_id="a1", evidence_refs=("e1",)),), evidence=(make_evidence(evidence_id="e1"),))
    with pytest.raises(errors.ConflictingEvidenceResolution):
        _assess(
            artifact,
            resolved_evidence=(
                make_resolved_evidence(evidence_id="e1", target_atom_id="a1", status=EvidenceResolutionStatus.VERIFIED, stance=EvidenceStance.SUPPORTS),
                make_resolved_evidence(evidence_id="e1", target_atom_id="a1", status=EvidenceResolutionStatus.VERIFIED, stance=EvidenceStance.REFUTES),
            ),
            resolution_trust_context=TRUSTED_VERIFIER,
        )
