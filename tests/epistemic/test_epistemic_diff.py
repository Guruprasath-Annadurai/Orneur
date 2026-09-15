from __future__ import annotations

from orneur.intelligence.epistemic.diff import diff
from orneur.intelligence.epistemic.enums import EpistemicPolarity, EpistemicResolutionTrustContext, EpistemicState, EvidenceResolutionStatus, EvidenceStance
from orneur.intelligence.epistemic.resolver import assess_artifact
from tests.epistemic.conftest import ASSESSED_AT, TRUSTED_OCL, TRUSTED_VERIFIER, UNTRUSTED_RESOLUTION, make_artifact, make_atom, make_evidence, make_resolved_evidence


def _overlay(artifact, **kw):
    return assess_artifact(
        artifact, ocl_trust_context=TRUSTED_OCL, assessment_context_id="ctx-1", assessed_at=ASSESSED_AT, **kw,
    )


def test_unknown_to_uncertain_transition():
    artifact = make_artifact(atoms=(make_atom(atom_id="a1", evidence_refs=("e1",)),), evidence=(make_evidence(evidence_id="e1"),))
    before = _overlay(artifact, overlay_id="o1")
    after = _overlay(
        artifact, overlay_id="o2",
        resolved_evidence=(make_resolved_evidence(evidence_id="e1", target_atom_id="a1", status=EvidenceResolutionStatus.UNVERIFIED, stance=EvidenceStance.SUPPORTS),),
        resolution_trust_context=TRUSTED_VERIFIER,
    )
    result = diff(before, after)
    transition = next(t for t in result.transitions if t.atom_id == "a1")
    assert transition.previous_state is EpistemicState.UNKNOWN
    assert transition.new_state is EpistemicState.UNCERTAIN


def test_uncertain_to_known_transition():
    artifact = make_artifact(atoms=(make_atom(atom_id="a1", evidence_refs=("e1",)),), evidence=(make_evidence(evidence_id="e1"),))
    before = _overlay(
        artifact, overlay_id="o1",
        resolved_evidence=(make_resolved_evidence(evidence_id="e1", target_atom_id="a1", status=EvidenceResolutionStatus.UNVERIFIED, stance=EvidenceStance.SUPPORTS),),
        resolution_trust_context=TRUSTED_VERIFIER,
    )
    after = _overlay(
        artifact, overlay_id="o2",
        resolved_evidence=(make_resolved_evidence(evidence_id="e1", target_atom_id="a1", status=EvidenceResolutionStatus.VERIFIED, stance=EvidenceStance.SUPPORTS),),
        resolution_trust_context=TRUSTED_VERIFIER,
    )
    transition = next(t for t in diff(before, after).transitions if t.atom_id == "a1")
    assert transition.previous_state is EpistemicState.UNCERTAIN
    assert transition.new_state is EpistemicState.KNOWN


def test_known_to_disputed_transition_new_evidence_reduces_certainty():
    """Doctrine: epistemic state is NOT monotonically increasing. New
    contradicting evidence can downgrade KNOWN to DISPUTED."""
    artifact = make_artifact(
        atoms=(make_atom(atom_id="a1", evidence_refs=("e1", "e2")),),
        evidence=(make_evidence(evidence_id="e1"), make_evidence(evidence_id="e2")),
    )
    before = _overlay(
        artifact, overlay_id="o1",
        resolved_evidence=(make_resolved_evidence(evidence_id="e1", target_atom_id="a1", status=EvidenceResolutionStatus.VERIFIED, stance=EvidenceStance.SUPPORTS),),
        resolution_trust_context=TRUSTED_VERIFIER,
    )
    after = _overlay(
        artifact, overlay_id="o2",
        resolved_evidence=(
            make_resolved_evidence(evidence_id="e1", target_atom_id="a1", status=EvidenceResolutionStatus.VERIFIED, stance=EvidenceStance.SUPPORTS),
            make_resolved_evidence(evidence_id="e2", target_atom_id="a1", status=EvidenceResolutionStatus.VERIFIED, stance=EvidenceStance.REFUTES),
        ),
        resolution_trust_context=TRUSTED_VERIFIER,
    )
    transition = next(t for t in diff(before, after).transitions if t.atom_id == "a1")
    assert transition.previous_state is EpistemicState.KNOWN
    assert transition.new_state is EpistemicState.DISPUTED


def test_disputed_to_known_transition():
    artifact = make_artifact(
        atoms=(make_atom(atom_id="a1", evidence_refs=("e1", "e2")),),
        evidence=(make_evidence(evidence_id="e1"), make_evidence(evidence_id="e2")),
    )
    before = _overlay(
        artifact, overlay_id="o1",
        resolved_evidence=(
            make_resolved_evidence(evidence_id="e1", target_atom_id="a1", status=EvidenceResolutionStatus.VERIFIED, stance=EvidenceStance.SUPPORTS),
            make_resolved_evidence(evidence_id="e2", target_atom_id="a1", status=EvidenceResolutionStatus.VERIFIED, stance=EvidenceStance.REFUTES),
        ),
        resolution_trust_context=TRUSTED_VERIFIER,
    )
    after = _overlay(
        artifact, overlay_id="o2",
        resolved_evidence=(make_resolved_evidence(evidence_id="e1", target_atom_id="a1", status=EvidenceResolutionStatus.VERIFIED, stance=EvidenceStance.SUPPORTS),),
        resolution_trust_context=TRUSTED_VERIFIER,
    )
    transition = next(t for t in diff(before, after).transitions if t.atom_id == "a1")
    assert transition.previous_state is EpistemicState.DISPUTED
    assert transition.new_state is EpistemicState.KNOWN


def test_known_affirmed_to_known_refuted_transition():
    artifact = make_artifact(atoms=(make_atom(atom_id="a1", evidence_refs=("e1",)),), evidence=(make_evidence(evidence_id="e1"),))
    before = _overlay(
        artifact, overlay_id="o1",
        resolved_evidence=(make_resolved_evidence(evidence_id="e1", target_atom_id="a1", status=EvidenceResolutionStatus.VERIFIED, stance=EvidenceStance.SUPPORTS),),
        resolution_trust_context=TRUSTED_VERIFIER,
    )
    after = _overlay(
        artifact, overlay_id="o2",
        resolved_evidence=(make_resolved_evidence(evidence_id="e1", target_atom_id="a1", status=EvidenceResolutionStatus.VERIFIED, stance=EvidenceStance.REFUTES),),
        resolution_trust_context=TRUSTED_VERIFIER,
    )
    transition = next(t for t in diff(before, after).transitions if t.atom_id == "a1")
    assert transition.previous_state is EpistemicState.KNOWN
    assert transition.previous_polarity is EpistemicPolarity.AFFIRMED
    assert transition.new_state is EpistemicState.KNOWN
    assert transition.new_polarity is EpistemicPolarity.REFUTED


def test_unknown_to_unverifiable_transition():
    from orneur.intelligence.epistemic.enums import VerificationFeasibility
    from tests.epistemic.conftest import make_feasibility

    artifact = make_artifact(atoms=(make_atom(atom_id="a1"),))
    before = _overlay(artifact, overlay_id="o1")
    after = _overlay(
        artifact, overlay_id="o2",
        feasibility_records=(make_feasibility(target_atom_id="a1", feasibility=VerificationFeasibility.STRUCTURALLY_UNVERIFIABLE),),
        resolution_trust_context=TRUSTED_VERIFIER,
    )
    transition = next(t for t in diff(before, after).transitions if t.atom_id == "a1")
    assert transition.previous_state is EpistemicState.UNKNOWN
    assert transition.new_state is EpistemicState.UNVERIFIABLE


def test_diff_has_no_transitions_when_overlays_are_identical():
    artifact = make_artifact(atoms=(make_atom(atom_id="a1"),))
    overlay = _overlay(artifact, overlay_id="o1")
    result = diff(overlay, overlay)
    assert result.transitions == ()
