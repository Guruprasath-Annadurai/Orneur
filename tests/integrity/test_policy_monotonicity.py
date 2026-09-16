"""Section 11/33-D: policy monotonicity -- dedicated coverage beyond the
single case already exercised in test_canonical_cases.py CASE K."""
from __future__ import annotations

import pytest

from orneur.intelligence.epistemic.enums import EpistemicPolarity, EpistemicState
from orneur.intelligence.integrity import errors
from orneur.intelligence.integrity.contracts import IntegrityPolicy, IntegrityProposal, ProposedAssertion
from orneur.intelligence.integrity.enums import IntegrityStatus, PresentationTreatment
from orneur.intelligence.integrity.evaluator import assess_integrity
from tests.integrity.conftest import build_known_affirmed_fixture, build_uncertain_fixture


def test_stricter_policy_narrowing_known_to_abstain_only_works():
    artifact, overlay = build_known_affirmed_fixture()
    stricter = IntegrityPolicy(stricter_permitted_treatments={EpistemicState.KNOWN: frozenset({PresentationTreatment.ABSTAIN})})
    proposal = IntegrityProposal(proposal_id="p1", assertions=(ProposedAssertion("as1", "a1", PresentationTreatment.ESTABLISHED, EpistemicPolarity.AFFIRMED),))
    receipt = assess_integrity(proposal, overlay=overlay, artifact=artifact, policy=stricter)
    assert receipt.integrity_status is not IntegrityStatus.SATISFIED  # ESTABLISHED no longer permitted under this policy

    proposal_abstain = IntegrityProposal(proposal_id="p1", assertions=(ProposedAssertion("as1", "a1", PresentationTreatment.ABSTAIN),))
    receipt_abstain = assess_integrity(proposal_abstain, overlay=overlay, artifact=artifact, policy=stricter)
    assert receipt_abstain.integrity_status is IntegrityStatus.SATISFIED


def test_policy_narrowing_a_state_leaves_other_states_at_the_hard_floor():
    artifact, overlay = build_known_affirmed_fixture()
    stricter = IntegrityPolicy(stricter_permitted_treatments={EpistemicState.UNCERTAIN: frozenset({PresentationTreatment.ABSTAIN})})
    proposal = IntegrityProposal(proposal_id="p1", assertions=(ProposedAssertion("as1", "a1", PresentationTreatment.ESTABLISHED, EpistemicPolarity.AFFIRMED),))
    receipt = assess_integrity(proposal, overlay=overlay, artifact=artifact, policy=stricter)
    assert receipt.integrity_status is IntegrityStatus.SATISFIED  # KNOWN untouched by an UNCERTAIN-only override


def test_attempted_weakening_for_multiple_states_at_once_rejected():
    artifact, overlay = build_known_affirmed_fixture()
    weakening = IntegrityPolicy(
        stricter_permitted_treatments={
            EpistemicState.UNCERTAIN: frozenset({PresentationTreatment.ESTABLISHED}),
            EpistemicState.UNKNOWN: frozenset({PresentationTreatment.ESTABLISHED}),
        },
    )
    with pytest.raises(errors.PolicyAttemptedToWeakenHardFloor):
        assess_integrity(
            IntegrityProposal(proposal_id="p1", assertions=()),
            overlay=overlay, artifact=artifact, policy=weakening,
        )


def test_policy_with_wrong_key_type_rejected():
    artifact, overlay = build_known_affirmed_fixture()
    policy = IntegrityPolicy(stricter_permitted_treatments={"KNOWN": frozenset({PresentationTreatment.ABSTAIN})})  # type: ignore[dict-item]
    with pytest.raises(errors.InvalidIntegrityPolicy):
        assess_integrity(
            IntegrityProposal(proposal_id="p1", assertions=()),
            overlay=overlay, artifact=artifact, policy=policy,
        )


def test_policy_with_wrong_value_type_rejected():
    artifact, overlay = build_known_affirmed_fixture()
    policy = IntegrityPolicy(stricter_permitted_treatments={EpistemicState.KNOWN: "ABSTAIN"})  # type: ignore[dict-item]
    with pytest.raises(errors.InvalidIntegrityPolicy):
        assess_integrity(
            IntegrityProposal(proposal_id="p1", assertions=()),
            overlay=overlay, artifact=artifact, policy=policy,
        )


def test_no_policy_at_all_uses_pure_hard_floor():
    artifact, overlay = build_uncertain_fixture()
    proposal = IntegrityProposal(proposal_id="p1", assertions=(ProposedAssertion("as1", "a1", PresentationTreatment.UNCERTAIN),))
    receipt = assess_integrity(proposal, overlay=overlay, artifact=artifact, policy=None)
    assert receipt.integrity_status is IntegrityStatus.SATISFIED
