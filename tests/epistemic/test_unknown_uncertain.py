from __future__ import annotations

from orneur.intelligence.epistemic.enums import EpistemicReasonCode, EpistemicState, VerificationFeasibility
from orneur.intelligence.epistemic.resolver import assess_artifact
from tests.epistemic.conftest import ASSESSED_AT, TRUSTED_OCL, TRUSTED_VERIFIER, make_artifact, make_atom, make_feasibility


def _assess(artifact, **kw):
    overlay = assess_artifact(
        artifact, ocl_trust_context=TRUSTED_OCL, assessment_context_id="ctx-1", assessed_at=ASSESSED_AT, **kw,
    )
    return {a.atom_id: a for a in overlay.assessments}


def test_bare_model_assertion_no_evidence_is_unknown_not_uncertain():
    artifact = make_artifact(atoms=(make_atom(atom_id="a1"),))
    results = _assess(artifact)
    assert results["a1"].state is EpistemicState.UNKNOWN


def test_verification_pending_is_uncertain_not_unknown():
    artifact = make_artifact(atoms=(make_atom(atom_id="a1"),))
    results = _assess(
        artifact,
        feasibility_records=(make_feasibility(target_atom_id="a1", feasibility=VerificationFeasibility.PENDING),),
        resolution_trust_context=TRUSTED_VERIFIER,
    )
    assert results["a1"].state is EpistemicState.UNCERTAIN
    assert EpistemicReasonCode.VERIFICATION_PENDING in results["a1"].reason_codes


def test_temporarily_unavailable_feasibility_is_uncertain_not_unverifiable():
    artifact = make_artifact(atoms=(make_atom(atom_id="a1"),))
    results = _assess(
        artifact,
        feasibility_records=(make_feasibility(target_atom_id="a1", feasibility=VerificationFeasibility.TEMPORARILY_UNAVAILABLE),),
        resolution_trust_context=TRUSTED_VERIFIER,
    )
    assert results["a1"].state is EpistemicState.UNCERTAIN
    assert results["a1"].state is not EpistemicState.UNVERIFIABLE
    assert EpistemicReasonCode.TEMPORARY_VERIFICATION_UNAVAILABLE in results["a1"].reason_codes
