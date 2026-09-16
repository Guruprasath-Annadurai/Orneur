from __future__ import annotations

from orneur.intelligence.epistemic.enums import EpistemicResolutionTrustContext, EvidenceResolutionStatus, EvidenceStance
from orneur.intelligence.epistemic.models import ResolvedEvidence
from orneur.intelligence.epistemic.resolver import assess_artifact
from orneur.intelligence.ocl.artifact import CognitiveArtifact
from orneur.intelligence.ocl.enums import AtomKind, EvidenceKind, ProducerKind, RelationKind, SourceClass
from orneur.intelligence.ocl.evidence import EvidenceAnchor
from orneur.intelligence.ocl.graph import CognitiveAtom, CognitiveRelation
from orneur.intelligence.ocl.provenance import ModelIdentityRef, Provenance
from orneur.intelligence.ocl.trust import CompilationTrustContext
from orneur.intelligence.ocl.version import CURRENT_SCHEMA_VERSION

FIXED_TIME = "2026-01-01T00:00:00+00:00"
ASSESSED_AT = "2026-01-01T00:00:00+00:00"
EVALUATED_AT = "2026-01-02T00:00:00+00:00"

TRUSTED_OCL = CompilationTrustContext.TRUSTED_DETERMINISTIC_SYSTEM
TRUSTED_VERIFIER = EpistemicResolutionTrustContext.TRUSTED_DETERMINISTIC_VERIFIER


def make_atom(atom_id="a1", kind=AtomKind.ASSERTION, source_class=SourceClass.MODEL_ASSERTION, content="content", evidence_refs=(), **kw):
    return CognitiveAtom(atom_id=atom_id, kind=kind, source_class=source_class, content=content, evidence_refs=evidence_refs, **kw)


def make_relation(relation_id="r1", kind=RelationKind.SUPPORTS, source="a1", target="a2", **kw):
    return CognitiveRelation(relation_id=relation_id, kind=kind, source_atom_id=source, target_atom_id=target, **kw)


def make_evidence(evidence_id="e1", kind=EvidenceKind.MEASURED_SYSTEM_DATA, issuer="orca.mission.verification", reference="ref-1", **kw):
    return EvidenceAnchor(evidence_id=evidence_id, evidence_kind=kind, issuer=issuer, reference=reference, **kw)


def make_provenance(producer_kind=ProducerKind.NATIVE_MODEL, producer_id="genesis-1", family="genesis", lifecycle_state="EXPERIMENTAL"):
    identity = ModelIdentityRef(family=family, lifecycle_state=lifecycle_state) if family else None
    return Provenance(producer_kind=producer_kind, producer_id=producer_id, model_identity=identity)


def make_artifact(artifact_id="art-1", request_id="req-1", provenance=None, atoms=(), relations=(), evidence=(), **kw) -> CognitiveArtifact:
    return CognitiveArtifact(
        artifact_id=artifact_id,
        schema_version=CURRENT_SCHEMA_VERSION,
        request_id=request_id,
        provenance=provenance or make_provenance(),
        created_at=FIXED_TIME,
        atoms=atoms,
        relations=relations,
        evidence=evidence,
        **kw,
    )


def make_resolved_evidence(evidence_id="e1", target_atom_id="a1", status=EvidenceResolutionStatus.VERIFIED, stance=EvidenceStance.SUPPORTS, resolver_reference="resolver-1", resolved_at=ASSESSED_AT, **kw):
    return ResolvedEvidence(
        evidence_id=evidence_id, target_atom_id=target_atom_id, status=status, stance=stance,
        resolver_reference=resolver_reference, resolved_at=resolved_at, **kw,
    )


def build_known_affirmed_fixture(atom_id="a1"):
    """Real Phase-17 artifact + real Phase-18 assess_artifact() call,
    producing a genuine KNOWN/AFFIRMED overlay -- not a mock."""
    artifact = make_artifact(
        atoms=(make_atom(atom_id=atom_id, evidence_refs=("e1",)),),
        evidence=(make_evidence(evidence_id="e1"),),
    )
    compiled = _compile(artifact)
    overlay = assess_artifact(
        artifact, ocl_trust_context=TRUSTED_OCL, assessment_context_id="ctx-1", assessed_at=ASSESSED_AT,
        resolved_evidence=(make_resolved_evidence(evidence_id="e1", target_atom_id=atom_id, status=EvidenceResolutionStatus.VERIFIED, stance=EvidenceStance.SUPPORTS),),
        resolution_trust_context=TRUSTED_VERIFIER,
        overlay_id="overlay-fixed",
    )
    return compiled, overlay


def build_inferred_affirmed_fixture():
    """A SUPPORTS B, A has direct verified support -> B is INFERRED/AFFIRMED."""
    artifact = make_artifact(
        atoms=(make_atom(atom_id="a", evidence_refs=("e1",)), make_atom(atom_id="b")),
        relations=(make_relation(relation_id="r1", kind=RelationKind.SUPPORTS, source="a", target="b"),),
        evidence=(make_evidence(evidence_id="e1"),),
    )
    compiled = _compile(artifact)
    overlay = assess_artifact(
        artifact, ocl_trust_context=TRUSTED_OCL, assessment_context_id="ctx-1", assessed_at=ASSESSED_AT,
        resolved_evidence=(make_resolved_evidence(evidence_id="e1", target_atom_id="a", status=EvidenceResolutionStatus.VERIFIED, stance=EvidenceStance.SUPPORTS),),
        resolution_trust_context=TRUSTED_VERIFIER,
        overlay_id="overlay-fixed",
    )
    return compiled, overlay


def build_uncertain_fixture(atom_id="a1"):
    artifact = make_artifact(atoms=(make_atom(atom_id=atom_id, evidence_refs=("e1",)),), evidence=(make_evidence(evidence_id="e1"),))
    compiled = _compile(artifact)
    overlay = assess_artifact(
        artifact, ocl_trust_context=TRUSTED_OCL, assessment_context_id="ctx-1", assessed_at=ASSESSED_AT,
        resolved_evidence=(make_resolved_evidence(evidence_id="e1", target_atom_id=atom_id, status=EvidenceResolutionStatus.UNVERIFIED, stance=EvidenceStance.SUPPORTS),),
        resolution_trust_context=TRUSTED_VERIFIER,
        overlay_id="overlay-fixed",
    )
    return compiled, overlay


def build_disputed_fixture(atom_id="a1"):
    artifact = make_artifact(
        atoms=(make_atom(atom_id=atom_id, evidence_refs=("e1", "e2")),),
        evidence=(make_evidence(evidence_id="e1"), make_evidence(evidence_id="e2")),
    )
    compiled = _compile(artifact)
    overlay = assess_artifact(
        artifact, ocl_trust_context=TRUSTED_OCL, assessment_context_id="ctx-1", assessed_at=ASSESSED_AT,
        resolved_evidence=(
            make_resolved_evidence(evidence_id="e1", target_atom_id=atom_id, status=EvidenceResolutionStatus.VERIFIED, stance=EvidenceStance.SUPPORTS),
            make_resolved_evidence(evidence_id="e2", target_atom_id=atom_id, status=EvidenceResolutionStatus.VERIFIED, stance=EvidenceStance.REFUTES),
        ),
        resolution_trust_context=TRUSTED_VERIFIER,
        overlay_id="overlay-fixed",
    )
    return compiled, overlay


def build_unknown_fixture(atom_id="a1"):
    artifact = make_artifact(atoms=(make_atom(atom_id=atom_id),))
    compiled = _compile(artifact)
    overlay = assess_artifact(
        artifact, ocl_trust_context=TRUSTED_OCL, assessment_context_id="ctx-1", assessed_at=ASSESSED_AT,
        overlay_id="overlay-fixed",
    )
    return compiled, overlay


def build_unverifiable_fixture(atom_id="a1"):
    from orneur.intelligence.epistemic.enums import VerificationFeasibility
    from orneur.intelligence.epistemic.models import VerificationFeasibilityRecord

    artifact = make_artifact(atoms=(make_atom(atom_id=atom_id),))
    compiled = _compile(artifact)
    overlay = assess_artifact(
        artifact, ocl_trust_context=TRUSTED_OCL, assessment_context_id="ctx-1", assessed_at=ASSESSED_AT,
        feasibility_records=(
            VerificationFeasibilityRecord(
                target_atom_id=atom_id, feasibility=VerificationFeasibility.STRUCTURALLY_UNVERIFIABLE,
                verifier_reference="verifier-1", recorded_at=ASSESSED_AT,
            ),
        ),
        resolution_trust_context=TRUSTED_VERIFIER,
        overlay_id="overlay-fixed",
    )
    return compiled, overlay


def _compile(artifact):
    from orneur.intelligence.ocl.compiler import compile_artifact

    return compile_artifact(artifact, trust_context=TRUSTED_OCL)
