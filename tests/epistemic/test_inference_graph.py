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


def test_supports_chain_from_verified_root_yields_inferred():
    # verified evidence -> A; A SUPPORTS B; B SUPPORTS C
    artifact = make_artifact(
        atoms=(
            make_atom(atom_id="a", evidence_refs=("e1",)),
            make_atom(atom_id="b"),
            make_atom(atom_id="c"),
        ),
        relations=(
            make_relation(relation_id="r1", kind=RelationKind.SUPPORTS, source="a", target="b"),
            make_relation(relation_id="r2", kind=RelationKind.SUPPORTS, source="b", target="c"),
        ),
        evidence=(make_evidence(evidence_id="e1"),),
    )
    results = _assess(
        artifact,
        resolved_evidence=(make_resolved_evidence(evidence_id="e1", target_atom_id="a", status=EvidenceResolutionStatus.VERIFIED, stance=EvidenceStance.SUPPORTS),),
        resolution_trust_context=TRUSTED_VERIFIER,
    )
    assert results["a"].state is EpistemicState.KNOWN
    assert results["b"].state is EpistemicState.INFERRED
    assert results["b"].polarity is EpistemicPolarity.AFFIRMED
    assert "a" in results["b"].derived_support_atom_refs
    assert results["c"].state is EpistemicState.INFERRED
    assert EpistemicReasonCode.EVIDENCE_BACKED_DERIVATION in results["c"].reason_codes


def test_circular_support_with_no_evidence_root_stays_not_inferred():
    """A SUPPORTS B; B SUPPORTS A -- zero qualified evidence roots. Neither
    may become INFERRED or KNOWN -- the hard no-circular-self-validation
    invariant."""
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
    assert results["a"].state is EpistemicState.UNKNOWN
    assert results["b"].state is EpistemicState.UNKNOWN


def test_circular_derived_from_is_already_rejected_by_ocl_before_phase_18_sees_it():
    """DERIVED_FROM is in OCL's own ACYCLIC_RELATION_KINDS (compiler.py) --
    a circular DERIVED_FROM graph can never compile in the first place,
    so it never reaches Phase 18's resolver at all. Defense in depth:
    the no-circular-self-validation invariant is enforced twice, once by
    OCL's compiler and once by Phase 18's evidence-rooted BFS (see the
    SUPPORTS-cycle test above, since RelationKind.SUPPORTS is NOT in
    OCL's acyclic set and can legitimately form a cycle in valid OCL
    data -- e.g. mutual-support model chatter)."""
    from orneur.intelligence.ocl.compiler import compile_artifact
    from orneur.intelligence.ocl.errors import InvalidRelationShape

    artifact = make_artifact(
        atoms=(make_atom(atom_id="a"), make_atom(atom_id="b")),
        relations=(
            make_relation(relation_id="r1", kind=RelationKind.DERIVED_FROM, source="a", target="b"),
            make_relation(relation_id="r2", kind=RelationKind.DERIVED_FROM, source="b", target="a"),
        ),
    )
    try:
        compile_artifact(artifact, trust_context=TRUSTED_OCL)
        raised = False
    except InvalidRelationShape:
        raised = True
    assert raised, "expected OCL's own compiler to reject a circular DERIVED_FROM graph"


def test_derived_from_propagates_basis_atom_to_derived_atom():
    # A DERIVED_FROM B; B has direct verified support -> A becomes INFERRED
    artifact = make_artifact(
        atoms=(make_atom(atom_id="a"), make_atom(atom_id="b", evidence_refs=("e1",))),
        relations=(make_relation(relation_id="r1", kind=RelationKind.DERIVED_FROM, source="a", target="b"),),
        evidence=(make_evidence(evidence_id="e1"),),
    )
    results = _assess(
        artifact,
        resolved_evidence=(make_resolved_evidence(evidence_id="e1", target_atom_id="b", status=EvidenceResolutionStatus.VERIFIED, stance=EvidenceStance.SUPPORTS),),
        resolution_trust_context=TRUSTED_VERIFIER,
    )
    assert results["b"].state is EpistemicState.KNOWN
    assert results["a"].state is EpistemicState.INFERRED
    assert "b" in results["a"].derived_support_atom_refs


def test_falsifies_from_established_atom_refutes_target():
    # A has direct verified support; A FALSIFIES B -> B becomes refuted (inferred)
    artifact = make_artifact(
        atoms=(make_atom(atom_id="a", evidence_refs=("e1",)), make_atom(atom_id="b")),
        relations=(make_relation(relation_id="r1", kind=RelationKind.FALSIFIES, source="a", target="b"),),
        evidence=(make_evidence(evidence_id="e1"),),
    )
    results = _assess(
        artifact,
        resolved_evidence=(make_resolved_evidence(evidence_id="e1", target_atom_id="a", status=EvidenceResolutionStatus.VERIFIED, stance=EvidenceStance.SUPPORTS),),
        resolution_trust_context=TRUSTED_VERIFIER,
    )
    assert results["a"].state is EpistemicState.KNOWN
    assert results["b"].state is EpistemicState.INFERRED
    assert results["b"].polarity is EpistemicPolarity.REFUTED


def test_causes_relation_does_not_propagate_truth():
    artifact = make_artifact(
        atoms=(make_atom(atom_id="a", evidence_refs=("e1",)), make_atom(atom_id="b")),
        relations=(make_relation(relation_id="r1", kind=RelationKind.CAUSES, source="a", target="b"),),
        evidence=(make_evidence(evidence_id="e1"),),
    )
    results = _assess(
        artifact,
        resolved_evidence=(make_resolved_evidence(evidence_id="e1", target_atom_id="a", status=EvidenceResolutionStatus.VERIFIED, stance=EvidenceStance.SUPPORTS),),
        resolution_trust_context=TRUSTED_VERIFIER,
    )
    assert results["a"].state is EpistemicState.KNOWN
    assert results["b"].state is EpistemicState.UNKNOWN


def test_correlates_with_relation_does_not_propagate_truth():
    artifact = make_artifact(
        atoms=(make_atom(atom_id="a", evidence_refs=("e1",)), make_atom(atom_id="b")),
        relations=(make_relation(relation_id="r1", kind=RelationKind.CORRELATES_WITH, source="a", target="b"),),
        evidence=(make_evidence(evidence_id="e1"),),
    )
    results = _assess(
        artifact,
        resolved_evidence=(make_resolved_evidence(evidence_id="e1", target_atom_id="a", status=EvidenceResolutionStatus.VERIFIED, stance=EvidenceStance.SUPPORTS),),
        resolution_trust_context=TRUSTED_VERIFIER,
    )
    assert results["b"].state is EpistemicState.UNKNOWN


def test_confidence_number_never_changes_result_because_no_such_input_exists():
    """There is no confidence parameter anywhere on assess_artifact's
    signature or on ResolvedEvidence -- same artifact/evidence must
    resolve identically regardless of any metadata a model attaches."""
    artifact_low = make_artifact(
        atoms=(make_atom(atom_id="a1", evidence_refs=("e1",), metadata={"confidence": 0.01}),),
        evidence=(make_evidence(evidence_id="e1"),),
    )
    artifact_high = make_artifact(
        atoms=(make_atom(atom_id="a1", evidence_refs=("e1",), metadata={"confidence": 0.99}),),
        evidence=(make_evidence(evidence_id="e1"),),
    )
    kwargs = dict(
        resolved_evidence=(make_resolved_evidence(evidence_id="e1", target_atom_id="a1", status=EvidenceResolutionStatus.VERIFIED, stance=EvidenceStance.SUPPORTS),),
        resolution_trust_context=TRUSTED_VERIFIER,
    )
    low = _assess(artifact_low, **kwargs)["a1"]
    high = _assess(artifact_high, **kwargs)["a1"]
    assert low.state == high.state == EpistemicState.KNOWN
    assert low.polarity == high.polarity
