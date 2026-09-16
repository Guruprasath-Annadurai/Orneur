"""
Sections 26-28: direct tests that DISPUTED/UNKNOWN/UNVERIFIABLE/INFERRED
semantics survive presentation -- the core hallucination-prevention
invariants of this protocol.
"""
from __future__ import annotations

from orneur.intelligence.epistemic.enums import EpistemicPolarity
from orneur.intelligence.integrity.contracts import IntegrityProposal, ProposedAssertion
from orneur.intelligence.integrity.enums import IntegrityStatus, IntegrityViolationReason, PresentationTreatment
from tests.integrity.conftest import (
    assess_integrity_trusted as assess_integrity,
    build_disputed_fixture,
    build_inferred_affirmed_fixture,
    build_unknown_fixture,
    build_unverifiable_fixture,
)

T = PresentationTreatment


def _assess(artifact, overlay, treatment, polarity=None, atom_id="a1"):
    proposal = IntegrityProposal(
        proposal_id="p1",
        assertions=(ProposedAssertion("as1", atom_id, treatment, polarity),),
    )
    return assess_integrity(proposal, overlay=overlay, artifact=artifact)


# ── DISPUTE preservation (section 26) ───────────────────────────────────


def test_disputed_cannot_be_output_as_one_sided_affirmed():
    artifact, overlay = build_disputed_fixture()
    receipt = _assess(artifact, overlay, T.ESTABLISHED, EpistemicPolarity.AFFIRMED)
    assert receipt.integrity_status is not IntegrityStatus.SATISFIED
    assert IntegrityViolationReason.DISPUTE_SUPPRESSED in {v.reason for v in receipt.violations}


def test_disputed_cannot_be_output_as_one_sided_refuted():
    artifact, overlay = build_disputed_fixture()
    receipt = _assess(artifact, overlay, T.ESTABLISHED, EpistemicPolarity.REFUTED)
    assert receipt.integrity_status is not IntegrityStatus.SATISFIED
    assert IntegrityViolationReason.DISPUTE_SUPPRESSED in {v.reason for v in receipt.violations}


def test_disputed_can_use_dispute_preserving_treatment():
    artifact, overlay = build_disputed_fixture()
    receipt = _assess(artifact, overlay, T.DISPUTE)
    assert receipt.integrity_status is IntegrityStatus.SATISFIED


def test_disputed_conflict_cannot_silently_disappear_through_scope_omission():
    artifact, overlay = build_disputed_fixture(atom_id="a1")
    proposal = IntegrityProposal(proposal_id="p1", assertions=(), required_scope_atom_ids=("a1",))
    receipt = assess_integrity(proposal, overlay=overlay, artifact=artifact)
    assert receipt.integrity_status is IntegrityStatus.BLOCKED
    assert "a1" in receipt.omitted_scope_atom_ids


def test_stricter_policy_may_demand_abstention_for_disputed():
    from orneur.intelligence.epistemic.enums import EpistemicState
    from orneur.intelligence.integrity.contracts import IntegrityPolicy

    artifact, overlay = build_disputed_fixture()
    stricter = IntegrityPolicy(stricter_permitted_treatments={EpistemicState.DISPUTED: frozenset({T.ABSTAIN})})
    proposal = IntegrityProposal(proposal_id="p1", assertions=(ProposedAssertion("as1", "a1", T.DISPUTE),))
    receipt = assess_integrity(proposal, overlay=overlay, artifact=artifact, policy=stricter)
    assert receipt.integrity_status is not IntegrityStatus.SATISFIED  # DISPUTE no longer permitted under this policy

    proposal_abstain = IntegrityProposal(proposal_id="p1", assertions=(ProposedAssertion("as1", "a1", T.ABSTAIN),))
    receipt_abstain = assess_integrity(proposal_abstain, overlay=overlay, artifact=artifact, policy=stricter)
    assert receipt_abstain.integrity_status is IntegrityStatus.SATISFIED


def test_weaker_policy_cannot_permit_one_sided_fact_presentation_for_disputed():
    import pytest

    from orneur.intelligence.epistemic.enums import EpistemicState
    from orneur.intelligence.integrity import errors
    from orneur.intelligence.integrity.contracts import IntegrityPolicy

    artifact, overlay = build_disputed_fixture()
    weakening = IntegrityPolicy(stricter_permitted_treatments={EpistemicState.DISPUTED: frozenset({T.ESTABLISHED})})
    with pytest.raises(errors.PolicyAttemptedToWeakenHardFloor):
        assess_integrity(
            IntegrityProposal(proposal_id="p1", assertions=()),
            overlay=overlay, artifact=artifact, policy=weakening,
        )


# ── UNKNOWN / UNVERIFIABLE preservation (section 27) ────────────────────


def test_unknown_cannot_be_established():
    artifact, overlay = build_unknown_fixture()
    receipt = _assess(artifact, overlay, T.ESTABLISHED, EpistemicPolarity.AFFIRMED)
    assert receipt.integrity_status is not IntegrityStatus.SATISFIED


def test_unknown_cannot_be_presented_as_supported_inference():
    artifact, overlay = build_unknown_fixture()
    receipt = _assess(artifact, overlay, T.INFERENCE, EpistemicPolarity.AFFIRMED)
    assert receipt.integrity_status is not IntegrityStatus.SATISFIED
    assert IntegrityViolationReason.UNKNOWN_PRESENTED_AS_KNOWLEDGE in {v.reason for v in receipt.violations}


def test_unknown_may_be_disclosed_as_unknown():
    artifact, overlay = build_unknown_fixture()
    receipt = _assess(artifact, overlay, T.UNKNOWN)
    assert receipt.integrity_status is IntegrityStatus.SATISFIED


def test_unknown_may_lead_to_abstention():
    artifact, overlay = build_unknown_fixture()
    receipt = _assess(artifact, overlay, T.ABSTAIN)
    assert receipt.integrity_status is IntegrityStatus.SATISFIED


def test_unverifiable_cannot_be_called_verified():
    artifact, overlay = build_unverifiable_fixture()
    receipt = _assess(artifact, overlay, T.ESTABLISHED, EpistemicPolarity.AFFIRMED)
    assert receipt.integrity_status is not IntegrityStatus.SATISFIED
    assert IntegrityViolationReason.UNVERIFIABLE_PRESENTED_AS_VERIFIED in {v.reason for v in receipt.violations}


def test_unverifiable_cannot_be_silently_rewritten_as_unknown():
    """UNVERIFIABLE carries meaningful information UNKNOWN does not --
    presenting an UNVERIFIABLE atom via UNKNOWN treatment must not be
    silently accepted as equivalent."""
    artifact, overlay = build_unverifiable_fixture()
    receipt = _assess(artifact, overlay, T.UNKNOWN)
    assert receipt.integrity_status is not IntegrityStatus.SATISFIED


def test_unverifiable_may_be_disclosed_as_unverifiable():
    artifact, overlay = build_unverifiable_fixture()
    receipt = _assess(artifact, overlay, T.UNVERIFIABLE)
    assert receipt.integrity_status is IntegrityStatus.SATISFIED


def test_unverifiable_may_lead_to_abstention():
    artifact, overlay = build_unverifiable_fixture()
    receipt = _assess(artifact, overlay, T.ABSTAIN)
    assert receipt.integrity_status is IntegrityStatus.SATISFIED


# ── INFERENCE preservation (section 28) ─────────────────────────────────


def test_inferred_to_established_fails():
    artifact, overlay = build_inferred_affirmed_fixture()
    receipt = _assess(artifact, overlay, T.ESTABLISHED, EpistemicPolarity.AFFIRMED, atom_id="b")
    assert receipt.integrity_status is not IntegrityStatus.SATISFIED
    assert IntegrityViolationReason.INFERENCE_PRESENTED_AS_FACT in {v.reason for v in receipt.violations}


def test_inferred_to_inference_passes():
    artifact, overlay = build_inferred_affirmed_fixture()
    receipt = _assess(artifact, overlay, T.INFERENCE, EpistemicPolarity.AFFIRMED, atom_id="b")
    assert receipt.integrity_status is IntegrityStatus.SATISFIED


def test_inferred_to_uncertain_passes_conservative():
    artifact, overlay = build_inferred_affirmed_fixture()
    receipt = _assess(artifact, overlay, T.UNCERTAIN, atom_id="b")
    assert receipt.integrity_status is IntegrityStatus.SATISFIED


def test_inferred_to_abstain_passes():
    artifact, overlay = build_inferred_affirmed_fixture()
    receipt = _assess(artifact, overlay, T.ABSTAIN, atom_id="b")
    assert receipt.integrity_status is IntegrityStatus.SATISFIED
