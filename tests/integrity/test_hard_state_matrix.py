"""
Section 33-A: cover every Phase-18 state against every meaningful
presentation treatment, not just happy paths -- plus 33-B polarity.
"""
from __future__ import annotations

import itertools

import pytest

from orneur.intelligence.epistemic.enums import EpistemicPolarity, EpistemicState
from orneur.intelligence.integrity.contracts import IntegrityProposal, ProposedAssertion
from orneur.intelligence.integrity.enums import IntegrityStatus, PresentationTreatment
from orneur.intelligence.integrity.floor import HARD_FLOOR_PERMITTED_TREATMENTS
from tests.integrity.conftest import (
    assess_integrity_trusted as assess_integrity,
    build_disputed_fixture,
    build_inferred_affirmed_fixture,
    build_known_affirmed_fixture,
    build_uncertain_fixture,
    build_unknown_fixture,
    build_unverifiable_fixture,
)

FIXTURES = {
    EpistemicState.KNOWN: (build_known_affirmed_fixture, "a1"),
    EpistemicState.INFERRED: (build_inferred_affirmed_fixture, "b"),
    EpistemicState.UNCERTAIN: (build_uncertain_fixture, "a1"),
    EpistemicState.DISPUTED: (build_disputed_fixture, "a1"),
    EpistemicState.UNKNOWN: (build_unknown_fixture, "a1"),
    EpistemicState.UNVERIFIABLE: (build_unverifiable_fixture, "a1"),
}

ALL_TREATMENTS = tuple(PresentationTreatment)


@pytest.mark.parametrize("state,treatment", list(itertools.product(FIXTURES, ALL_TREATMENTS)))
def test_full_state_by_treatment_matrix(state, treatment):
    builder, atom_id = FIXTURES[state]
    artifact, overlay = builder()
    polarity = EpistemicPolarity.AFFIRMED if treatment in (PresentationTreatment.ESTABLISHED, PresentationTreatment.INFERENCE) else None
    proposal = IntegrityProposal(proposal_id="p1", assertions=(ProposedAssertion("as1", atom_id, treatment, polarity),))
    receipt = assess_integrity(proposal, overlay=overlay, artifact=artifact)

    permitted = treatment in HARD_FLOOR_PERMITTED_TREATMENTS[state]
    if permitted:
        assert receipt.integrity_status is IntegrityStatus.SATISFIED, (
            f"expected SATISFIED for state={state} treatment={treatment}, got {receipt.integrity_status} "
            f"violations={receipt.violations}"
        )
    else:
        assert receipt.integrity_status is not IntegrityStatus.SATISFIED, (
            f"expected NOT SATISFIED for state={state} treatment={treatment}"
        )


def test_every_state_has_at_least_one_permitted_treatment():
    for state in EpistemicState:
        assert HARD_FLOOR_PERMITTED_TREATMENTS[state], f"{state} has zero permitted treatments"


def test_abstain_is_always_permitted_for_every_state():
    for state in EpistemicState:
        assert PresentationTreatment.ABSTAIN in HARD_FLOOR_PERMITTED_TREATMENTS[state]


def test_established_is_permitted_only_for_known():
    for state in EpistemicState:
        if state is EpistemicState.KNOWN:
            assert PresentationTreatment.ESTABLISHED in HARD_FLOOR_PERMITTED_TREATMENTS[state]
        else:
            assert PresentationTreatment.ESTABLISHED not in HARD_FLOOR_PERMITTED_TREATMENTS[state]


# ── Polarity (section 13 / 33-B) ─────────────────────────────────────────


def test_known_affirmed_cannot_be_presented_as_refuted():
    artifact, overlay = build_known_affirmed_fixture()
    proposal = IntegrityProposal(proposal_id="p1", assertions=(ProposedAssertion("as1", "a1", PresentationTreatment.ESTABLISHED, EpistemicPolarity.REFUTED),))
    receipt = assess_integrity(proposal, overlay=overlay, artifact=artifact)
    assert receipt.integrity_status is not IntegrityStatus.SATISFIED


def test_polarity_none_when_required_is_a_mismatch():
    artifact, overlay = build_known_affirmed_fixture()
    proposal = IntegrityProposal(proposal_id="p1", assertions=(ProposedAssertion("as1", "a1", PresentationTreatment.ESTABLISHED, None),))
    receipt = assess_integrity(proposal, overlay=overlay, artifact=artifact)
    assert receipt.integrity_status is not IntegrityStatus.SATISFIED


def test_inferred_affirmed_inference_treatment_requires_matching_polarity():
    artifact, overlay = build_inferred_affirmed_fixture()
    proposal = IntegrityProposal(proposal_id="p1", assertions=(ProposedAssertion("as1", "b", PresentationTreatment.INFERENCE, EpistemicPolarity.REFUTED),))
    receipt = assess_integrity(proposal, overlay=overlay, artifact=artifact)
    assert receipt.integrity_status is not IntegrityStatus.SATISFIED


def test_disputed_mixed_polarity_has_no_affirmed_refuted_single_answer():
    """DISPUTE treatment carries no asserted_polarity -- there is no
    single answer to assert for a MIXED-polarity proposition."""
    artifact, overlay = build_disputed_fixture()
    assessment = overlay.assessments[0]
    assert assessment.polarity is EpistemicPolarity.MIXED
    proposal = IntegrityProposal(proposal_id="p1", assertions=(ProposedAssertion("as1", "a1", PresentationTreatment.DISPUTE, None),))
    receipt = assess_integrity(proposal, overlay=overlay, artifact=artifact)
    assert receipt.integrity_status is IntegrityStatus.SATISFIED
