from __future__ import annotations

import pytest

from orneur.intelligence.epistemic import errors
from orneur.intelligence.epistemic.resolver import assess_artifact, verify_overlay_binding
from orneur.intelligence.ocl.compiler import compile_artifact
from tests.epistemic.conftest import ASSESSED_AT, TRUSTED_OCL, make_artifact, make_atom


def test_overlay_binds_to_the_exact_artifact_it_assessed():
    artifact = make_artifact(artifact_id="art-1", atoms=(make_atom(atom_id="a1"),))
    compiled = compile_artifact(artifact, trust_context=TRUSTED_OCL)
    overlay = assess_artifact(
        artifact, ocl_trust_context=TRUSTED_OCL, assessment_context_id="ctx-1", assessed_at=ASSESSED_AT,
    )
    verify_overlay_binding(overlay, compiled)  # must not raise


def test_overlay_rejects_binding_to_mutated_artifact_content():
    artifact_v1 = make_artifact(artifact_id="art-1", atoms=(make_atom(atom_id="a1", content="v1"),))
    overlay = assess_artifact(
        artifact_v1, ocl_trust_context=TRUSTED_OCL, assessment_context_id="ctx-1", assessed_at=ASSESSED_AT,
    )
    artifact_v2 = make_artifact(artifact_id="art-1", atoms=(make_atom(atom_id="a1", content="v2 -- mutated"),))
    compiled_v2 = compile_artifact(artifact_v2, trust_context=TRUSTED_OCL)
    with pytest.raises(errors.SourceArtifactMismatch):
        verify_overlay_binding(overlay, compiled_v2)


def test_overlay_rejects_binding_to_different_artifact_id():
    artifact_a = make_artifact(artifact_id="art-a", atoms=(make_atom(atom_id="a1"),))
    artifact_b = make_artifact(artifact_id="art-b", atoms=(make_atom(atom_id="a1"),))
    overlay = assess_artifact(
        artifact_a, ocl_trust_context=TRUSTED_OCL, assessment_context_id="ctx-1", assessed_at=ASSESSED_AT,
    )
    compiled_b = compile_artifact(artifact_b, trust_context=TRUSTED_OCL)
    with pytest.raises(errors.SourceArtifactMismatch):
        verify_overlay_binding(overlay, compiled_b)


def test_resolver_rejects_evidence_targeting_atom_not_associated_with_it():
    from orneur.intelligence.epistemic.enums import EvidenceResolutionStatus, EvidenceStance
    from tests.epistemic.conftest import TRUSTED_VERIFIER, make_evidence, make_resolved_evidence

    # a1 does NOT reference e1 in its evidence_refs
    artifact = make_artifact(atoms=(make_atom(atom_id="a1", evidence_refs=()),), evidence=(make_evidence(evidence_id="e1"),))
    with pytest.raises(errors.EvidenceAtomMismatch):
        assess_artifact(
            artifact,
            ocl_trust_context=TRUSTED_OCL,
            resolved_evidence=(make_resolved_evidence(evidence_id="e1", target_atom_id="a1", status=EvidenceResolutionStatus.VERIFIED, stance=EvidenceStance.SUPPORTS),),
            resolution_trust_context=TRUSTED_VERIFIER,
            assessment_context_id="ctx-1",
            assessed_at=ASSESSED_AT,
        )


def test_resolver_rejects_unknown_evidence_id():
    from orneur.intelligence.epistemic.enums import EvidenceResolutionStatus, EvidenceStance
    from tests.epistemic.conftest import TRUSTED_VERIFIER, make_resolved_evidence

    artifact = make_artifact(atoms=(make_atom(atom_id="a1"),))
    with pytest.raises(errors.UnknownEvidenceReference):
        assess_artifact(
            artifact,
            ocl_trust_context=TRUSTED_OCL,
            resolved_evidence=(make_resolved_evidence(evidence_id="e-does-not-exist", target_atom_id="a1", status=EvidenceResolutionStatus.VERIFIED, stance=EvidenceStance.SUPPORTS),),
            resolution_trust_context=TRUSTED_VERIFIER,
            assessment_context_id="ctx-1",
            assessed_at=ASSESSED_AT,
        )


def test_resolver_rejects_target_atom_id_not_in_artifact():
    from orneur.intelligence.epistemic.enums import EvidenceResolutionStatus, EvidenceStance
    from tests.epistemic.conftest import TRUSTED_VERIFIER, make_evidence, make_resolved_evidence

    artifact = make_artifact(atoms=(make_atom(atom_id="a1"),), evidence=(make_evidence(evidence_id="e1"),))
    with pytest.raises(errors.UnknownAtomReference):
        assess_artifact(
            artifact,
            ocl_trust_context=TRUSTED_OCL,
            resolved_evidence=(make_resolved_evidence(evidence_id="e1", target_atom_id="atom-does-not-exist", status=EvidenceResolutionStatus.VERIFIED, stance=EvidenceStance.SUPPORTS),),
            resolution_trust_context=TRUSTED_VERIFIER,
            assessment_context_id="ctx-1",
            assessed_at=ASSESSED_AT,
        )


def test_requesting_assessment_of_non_assessable_atom_kind_fails_closed():
    from orneur.intelligence.ocl.enums import AtomKind

    artifact = make_artifact(atoms=(make_atom(atom_id="q1", kind=AtomKind.QUESTION),))
    with pytest.raises(errors.NonAssessableAtomKind):
        assess_artifact(
            artifact,
            ocl_trust_context=TRUSTED_OCL,
            assessment_context_id="ctx-1",
            assessed_at=ASSESSED_AT,
            target_atom_ids=("q1",),
        )


def test_non_assessable_atoms_are_silently_excluded_from_whole_artifact_assessment():
    from orneur.intelligence.ocl.enums import AtomKind

    artifact = make_artifact(atoms=(make_atom(atom_id="a1"), make_atom(atom_id="q1", kind=AtomKind.QUESTION)))
    overlay = assess_artifact(
        artifact, ocl_trust_context=TRUSTED_OCL, assessment_context_id="ctx-1", assessed_at=ASSESSED_AT,
    )
    assessed_ids = {a.atom_id for a in overlay.assessments}
    assert "a1" in assessed_ids
    assert "q1" not in assessed_ids


def test_invalid_assessed_at_format_is_rejected():
    artifact = make_artifact(atoms=(make_atom(atom_id="a1"),))
    with pytest.raises(errors.InvalidAssessmentContext):
        assess_artifact(
            artifact, ocl_trust_context=TRUSTED_OCL, assessment_context_id="ctx-1", assessed_at="not-a-timestamp",
        )
