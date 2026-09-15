from __future__ import annotations

from orneur.intelligence.epistemic.enums import EpistemicReasonCode, EpistemicState, VerificationFeasibility
from orneur.intelligence.epistemic.resolver import assess_artifact
from tests.epistemic.conftest import ASSESSED_AT, TRUSTED_OCL, TRUSTED_TOOL, TRUSTED_VERIFIER, make_artifact, make_atom, make_feasibility


def _assess(artifact, **kw):
    overlay = assess_artifact(
        artifact, ocl_trust_context=TRUSTED_OCL, assessment_context_id="ctx-1", assessed_at=ASSESSED_AT, **kw,
    )
    return {a.atom_id: a for a in overlay.assessments}


def test_trusted_deterministic_verifier_feasibility_record_creates_unverifiable():
    artifact = make_artifact(atoms=(make_atom(atom_id="a1"),))
    results = _assess(
        artifact,
        feasibility_records=(make_feasibility(target_atom_id="a1", feasibility=VerificationFeasibility.STRUCTURALLY_UNVERIFIABLE),),
        resolution_trust_context=TRUSTED_VERIFIER,
    )
    assert results["a1"].state is EpistemicState.UNVERIFIABLE
    assert EpistemicReasonCode.STRUCTURALLY_UNVERIFIABLE in results["a1"].reason_codes


def test_trusted_tool_resolver_tier_cannot_mint_unverifiable():
    """Only TRUSTED_DETERMINISTIC_VERIFIER may establish
    STRUCTURALLY_UNVERIFIABLE -- a lower TRUSTED_TOOL_RESOLVER tier
    (e.g. a failed tool call) must not."""
    artifact = make_artifact(atoms=(make_atom(atom_id="a1"),))
    results = _assess(
        artifact,
        feasibility_records=(make_feasibility(target_atom_id="a1", feasibility=VerificationFeasibility.STRUCTURALLY_UNVERIFIABLE),),
        resolution_trust_context=TRUSTED_TOOL,
    )
    assert results["a1"].state is not EpistemicState.UNVERIFIABLE


def test_model_limitation_text_alone_cannot_create_unverifiable():
    """A model writing content saying verification is impossible has no
    channel into feasibility_records at all -- there is no code path
    that reads atom.content or atom.metadata to build a
    VerificationFeasibilityRecord. Simulate the attack by simply NOT
    supplying any feasibility record and confirming the state is never
    UNVERIFIABLE regardless of atom content."""
    from orneur.intelligence.ocl.enums import AtomKind, SourceClass

    artifact = make_artifact(
        atoms=(make_atom(atom_id="a1", kind=AtomKind.ASSERTION, source_class=SourceClass.MODEL_ASSERTION, content="this can never be verified"),),
    )
    results = _assess(artifact)
    assert results["a1"].state is not EpistemicState.UNVERIFIABLE
    assert results["a1"].state is EpistemicState.UNKNOWN


def test_temporary_unavailability_does_not_escalate_to_unverifiable():
    artifact = make_artifact(atoms=(make_atom(atom_id="a1"),))
    results = _assess(
        artifact,
        feasibility_records=(make_feasibility(target_atom_id="a1", feasibility=VerificationFeasibility.TEMPORARILY_UNAVAILABLE),),
        resolution_trust_context=TRUSTED_VERIFIER,
    )
    assert results["a1"].state is not EpistemicState.UNVERIFIABLE
