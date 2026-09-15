from __future__ import annotations

from orneur.intelligence.epistemic.enums import (
    EpistemicPolarity,
    EpistemicReasonCode,
    EpistemicState,
    EvidenceResolutionStatus,
    EvidenceStance,
)
from orneur.intelligence.epistemic.resolver import assess_artifact
from tests.epistemic.conftest import (
    ASSESSED_AT,
    TRUSTED_OCL,
    TRUSTED_TOOL,
    TRUSTED_VERIFIER,
    UNTRUSTED_RESOLUTION,
    make_artifact,
    make_atom,
    make_evidence,
    make_resolved_evidence,
)


def _assess(artifact, **kw):
    overlay = assess_artifact(
        artifact,
        ocl_trust_context=TRUSTED_OCL,
        assessment_context_id="ctx-1",
        assessed_at=ASSESSED_AT,
        **kw,
    )
    return {a.atom_id: a for a in overlay.assessments}


def test_direct_verified_support_yields_known_affirmed():
    artifact = make_artifact(atoms=(make_atom(atom_id="a1", evidence_refs=("e1",)),), evidence=(make_evidence(evidence_id="e1"),))
    results = _assess(
        artifact,
        resolved_evidence=(make_resolved_evidence(evidence_id="e1", target_atom_id="a1", status=EvidenceResolutionStatus.VERIFIED, stance=EvidenceStance.SUPPORTS),),
        resolution_trust_context=TRUSTED_VERIFIER,
    )
    a1 = results["a1"]
    assert a1.state is EpistemicState.KNOWN
    assert a1.polarity is EpistemicPolarity.AFFIRMED
    assert a1.direct_support_evidence_refs == ("e1",)
    assert EpistemicReasonCode.DIRECT_VERIFIED_SUPPORT in a1.reason_codes


def test_direct_verified_refutation_yields_known_refuted():
    artifact = make_artifact(atoms=(make_atom(atom_id="a1", evidence_refs=("e1",)),), evidence=(make_evidence(evidence_id="e1"),))
    results = _assess(
        artifact,
        resolved_evidence=(make_resolved_evidence(evidence_id="e1", target_atom_id="a1", status=EvidenceResolutionStatus.VERIFIED, stance=EvidenceStance.REFUTES),),
        resolution_trust_context=TRUSTED_VERIFIER,
    )
    a1 = results["a1"]
    assert a1.state is EpistemicState.KNOWN
    assert a1.polarity is EpistemicPolarity.REFUTED
    assert EpistemicReasonCode.DIRECT_VERIFIED_REFUTATION in a1.reason_codes


def test_unverified_evidence_yields_uncertain_not_known():
    artifact = make_artifact(atoms=(make_atom(atom_id="a1", evidence_refs=("e1",)),), evidence=(make_evidence(evidence_id="e1"),))
    results = _assess(
        artifact,
        resolved_evidence=(make_resolved_evidence(evidence_id="e1", target_atom_id="a1", status=EvidenceResolutionStatus.UNVERIFIED, stance=EvidenceStance.SUPPORTS),),
        resolution_trust_context=TRUSTED_VERIFIER,
    )
    a1 = results["a1"]
    assert a1.state is EpistemicState.UNCERTAIN
    assert EpistemicReasonCode.UNVERIFIED_EVIDENCE in a1.reason_codes


def test_stale_evidence_yields_uncertain():
    artifact = make_artifact(atoms=(make_atom(atom_id="a1", evidence_refs=("e1",)),), evidence=(make_evidence(evidence_id="e1"),))
    results = _assess(
        artifact,
        resolved_evidence=(make_resolved_evidence(evidence_id="e1", target_atom_id="a1", status=EvidenceResolutionStatus.STALE, stance=EvidenceStance.SUPPORTS),),
        resolution_trust_context=TRUSTED_VERIFIER,
    )
    assert results["a1"].state is EpistemicState.UNCERTAIN
    assert EpistemicReasonCode.STALE_EVIDENCE in results["a1"].reason_codes


def test_unavailable_evidence_yields_uncertain():
    artifact = make_artifact(atoms=(make_atom(atom_id="a1", evidence_refs=("e1",)),), evidence=(make_evidence(evidence_id="e1"),))
    results = _assess(
        artifact,
        resolved_evidence=(make_resolved_evidence(evidence_id="e1", target_atom_id="a1", status=EvidenceResolutionStatus.UNAVAILABLE, stance=EvidenceStance.SUPPORTS),),
        resolution_trust_context=TRUSTED_VERIFIER,
    )
    assert results["a1"].state is EpistemicState.UNCERTAIN
    assert EpistemicReasonCode.EVIDENCE_UNAVAILABLE in results["a1"].reason_codes


def test_invalid_evidence_does_not_refute_only_invalidates_basis():
    artifact = make_artifact(atoms=(make_atom(atom_id="a1", evidence_refs=("e1",)),), evidence=(make_evidence(evidence_id="e1"),))
    results = _assess(
        artifact,
        resolved_evidence=(make_resolved_evidence(evidence_id="e1", target_atom_id="a1", status=EvidenceResolutionStatus.INVALID, stance=EvidenceStance.REFUTES),),
        resolution_trust_context=TRUSTED_VERIFIER,
    )
    a1 = results["a1"]
    assert a1.state is EpistemicState.UNCERTAIN
    assert a1.polarity is EpistemicPolarity.UNRESOLVED
    assert EpistemicReasonCode.EVIDENCE_INVALID in a1.reason_codes


def test_verified_inconclusive_does_not_establish_direction():
    artifact = make_artifact(atoms=(make_atom(atom_id="a1", evidence_refs=("e1",)),), evidence=(make_evidence(evidence_id="e1"),))
    results = _assess(
        artifact,
        resolved_evidence=(make_resolved_evidence(evidence_id="e1", target_atom_id="a1", status=EvidenceResolutionStatus.VERIFIED, stance=EvidenceStance.INCONCLUSIVE),),
        resolution_trust_context=TRUSTED_VERIFIER,
    )
    a1 = results["a1"]
    assert a1.state is EpistemicState.UNCERTAIN
    assert EpistemicReasonCode.EVIDENCE_INCONCLUSIVE in a1.reason_codes


def test_no_basis_at_all_yields_unknown():
    artifact = make_artifact(atoms=(make_atom(atom_id="a1"),))
    results = _assess(artifact)
    a1 = results["a1"]
    assert a1.state is EpistemicState.UNKNOWN
    assert a1.polarity is EpistemicPolarity.UNRESOLVED
    assert EpistemicReasonCode.NO_EPISTEMIC_BASIS in a1.reason_codes


def test_untrusted_resolution_context_cannot_create_known_even_with_verified_status():
    """This is the hardest adversarial case: the resolved_evidence record
    itself says VERIFIED+SUPPORTS, but the caller supplied
    resolution_trust_context=UNTRUSTED -- must never become KNOWN."""
    artifact = make_artifact(atoms=(make_atom(atom_id="a1", evidence_refs=("e1",)),), evidence=(make_evidence(evidence_id="e1"),))
    results = _assess(
        artifact,
        resolved_evidence=(make_resolved_evidence(evidence_id="e1", target_atom_id="a1", status=EvidenceResolutionStatus.VERIFIED, stance=EvidenceStance.SUPPORTS),),
        resolution_trust_context=UNTRUSTED_RESOLUTION,
    )
    a1 = results["a1"]
    assert a1.state != EpistemicState.KNOWN
    assert a1.state is EpistemicState.UNCERTAIN


def test_trusted_tool_resolver_can_also_establish_known():
    artifact = make_artifact(atoms=(make_atom(atom_id="a1", evidence_refs=("e1",)),), evidence=(make_evidence(evidence_id="e1"),))
    results = _assess(
        artifact,
        resolved_evidence=(make_resolved_evidence(evidence_id="e1", target_atom_id="a1", status=EvidenceResolutionStatus.VERIFIED, stance=EvidenceStance.SUPPORTS),),
        resolution_trust_context=TRUSTED_TOOL,
    )
    assert results["a1"].state is EpistemicState.KNOWN
