"""
Section 33-Q: real artifact -> real assess_artifact() -> real overlay ->
Phase-19 integrity evaluation, end to end, with no mocks. Also section
34's TDD evidence, demonstrated as an executable test: this file proves
that Phase 18 ALONE (i.e. calling assess_artifact() and reading the
overlay) provides no structural mechanism preventing a downstream
consumer from claiming a weaker state as a stronger one -- Phase 18's
own public API has no "presentation" concept at all, so nothing there
can be asked to reject an overclaim. The prevention exists only once
Phase 19's assess_integrity() is introduced.
"""
from __future__ import annotations

from orneur.intelligence.epistemic.enums import EpistemicPolarity, EpistemicResolutionTrustContext, EpistemicState, EvidenceResolutionStatus, EvidenceStance
from orneur.intelligence.epistemic.resolver import assess_artifact
from orneur.intelligence.integrity.contracts import IntegrityProposal, ProposedAssertion
from orneur.intelligence.integrity.enums import IntegrityStatus, PresentationTreatment
from orneur.intelligence.integrity.evaluator import assess_integrity
from orneur.intelligence.ocl.artifact import CognitiveArtifact
from orneur.intelligence.ocl.compiler import compile_artifact
from orneur.intelligence.ocl.enums import AtomKind, EvidenceKind, ProducerKind, RelationKind, SourceClass
from orneur.intelligence.ocl.evidence import EvidenceAnchor
from orneur.intelligence.ocl.graph import CognitiveAtom, CognitiveRelation
from orneur.intelligence.ocl.provenance import ModelIdentityRef, Provenance
from orneur.intelligence.ocl.trust import CompilationTrustContext
from orneur.intelligence.ocl.version import CURRENT_SCHEMA_VERSION

TRUSTED_OCL = CompilationTrustContext.TRUSTED_DETERMINISTIC_SYSTEM
TRUSTED_VERIFIER = EpistemicResolutionTrustContext.TRUSTED_DETERMINISTIC_VERIFIER
ASSESSED_AT = "2026-01-01T00:00:00+00:00"


def _real_artifact_no_evidence() -> CognitiveArtifact:
    provenance = Provenance(
        producer_kind=ProducerKind.NATIVE_MODEL, producer_id="genesis-1",
        model_identity=ModelIdentityRef(family="genesis", lifecycle_state="EXPERIMENTAL"),
    )
    atom = CognitiveAtom(
        atom_id="claim-1", kind=AtomKind.ASSERTION, source_class=SourceClass.MODEL_ASSERTION,
        content="Aeternum has a canonical base model selected.",
    )
    return CognitiveArtifact(
        artifact_id="real-art-1", schema_version=CURRENT_SCHEMA_VERSION, request_id="req-1",
        provenance=provenance, created_at=ASSESSED_AT, atoms=(atom,),
    )


def test_step1_real_ocl_compile_then_real_phase18_assess_then_real_phase19_evaluate():
    """The full real pipeline, no mocks anywhere."""
    draft = _real_artifact_no_evidence()
    compiled = compile_artifact(draft, trust_context=TRUSTED_OCL)
    assert isinstance(compiled, CognitiveArtifact)

    overlay = assess_artifact(
        compiled, ocl_trust_context=TRUSTED_OCL, assessment_context_id="ctx-real",
        assessed_at=ASSESSED_AT,
    )
    assessment = overlay.assessments[0]
    assert assessment.state is EpistemicState.UNKNOWN  # no evidence supplied at all

    proposal_overclaiming = IntegrityProposal(
        proposal_id="p1",
        assertions=(ProposedAssertion("as1", "claim-1", PresentationTreatment.ESTABLISHED, EpistemicPolarity.AFFIRMED),),
    )
    receipt_blocked = assess_integrity(proposal_overclaiming, overlay=overlay, artifact=compiled)
    assert receipt_blocked.integrity_status is not IntegrityStatus.SATISFIED

    proposal_honest = IntegrityProposal(
        proposal_id="p1",
        assertions=(ProposedAssertion("as1", "claim-1", PresentationTreatment.UNKNOWN),),
    )
    receipt_ok = assess_integrity(proposal_honest, overlay=overlay, artifact=compiled)
    assert receipt_ok.integrity_status is IntegrityStatus.SATISFIED


def test_step2_real_genesis_style_evidence_backed_known_pipeline():
    provenance = Provenance(
        producer_kind=ProducerKind.NATIVE_MODEL, producer_id="genesis-1",
        model_identity=ModelIdentityRef(family="genesis", lifecycle_state="EXPERIMENTAL"),
    )
    atom = CognitiveAtom(atom_id="a1", kind=AtomKind.ASSERTION, source_class=SourceClass.MODEL_ASSERTION, content="X is true", evidence_refs=("e1",))
    evidence = EvidenceAnchor(evidence_id="e1", evidence_kind=EvidenceKind.MEASURED_SYSTEM_DATA, issuer="orca.mission.verification", reference="ref-1")
    draft = CognitiveArtifact(
        artifact_id="real-art-2", schema_version=CURRENT_SCHEMA_VERSION, request_id="req-2",
        provenance=provenance, created_at=ASSESSED_AT, atoms=(atom,), evidence=(evidence,),
    )
    compiled = compile_artifact(draft, trust_context=TRUSTED_OCL)

    from orneur.intelligence.epistemic.models import ResolvedEvidence

    overlay = assess_artifact(
        compiled, ocl_trust_context=TRUSTED_OCL, assessment_context_id="ctx-real-2",
        assessed_at=ASSESSED_AT,
        resolved_evidence=(
            ResolvedEvidence(
                evidence_id="e1", target_atom_id="a1", status=EvidenceResolutionStatus.VERIFIED,
                stance=EvidenceStance.SUPPORTS, resolver_reference="resolver-1", resolved_at=ASSESSED_AT,
            ),
        ),
        resolution_trust_context=TRUSTED_VERIFIER,
    )
    assert overlay.assessments[0].state is EpistemicState.KNOWN

    proposal = IntegrityProposal(
        proposal_id="p1",
        assertions=(ProposedAssertion("as1", "a1", PresentationTreatment.ESTABLISHED, EpistemicPolarity.AFFIRMED),),
    )
    receipt = assess_integrity(proposal, overlay=overlay, artifact=compiled)
    assert receipt.integrity_status is IntegrityStatus.SATISFIED
