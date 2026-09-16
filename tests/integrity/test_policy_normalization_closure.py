"""
Closure: policy deep immutability/normalization. Reproduced defect:
IntegrityPolicy could be constructed with a plain mutable dict for
stricter_permitted_treatments (as every existing test already did) and
the evaluator read that live, caller-owned mapping directly -- a caller
mutating the dict between/during calls could change behavior out from
under an already-issued policy object. Fixed: floor.normalize_policy()
deep-freezes stricter_permitted_treatments into a genuine
MappingProxyType[EpistemicState, frozenset[PresentationTreatment]]
before any validation/evaluation/digesting touches it.
"""
from __future__ import annotations

from types import MappingProxyType

import pytest

from orneur.intelligence.epistemic.enums import EpistemicPolarity, EpistemicState
from orneur.intelligence.integrity import errors
from orneur.intelligence.integrity.contracts import IntegrityPolicy, IntegrityProposal, ProposedAssertion
from orneur.intelligence.integrity.enums import IntegrityStatus, PresentationTreatment
from orneur.intelligence.integrity.evaluator import assess_integrity
from orneur.intelligence.integrity.floor import normalize_policy
from tests.integrity.conftest import build_known_affirmed_fixture


def test_public_api_accepts_a_plain_mutable_dict_for_the_policy():
    """The PUBLIC API must not force callers to hand-construct
    MappingProxyType -- a normal dict/set is fine at the boundary; only
    the INTERNAL canonical state must end up deeply frozen."""
    artifact, overlay = build_known_affirmed_fixture()
    policy = IntegrityPolicy(stricter_permitted_treatments={EpistemicState.KNOWN: {PresentationTreatment.ABSTAIN}})
    proposal = IntegrityProposal(proposal_id="p1", assertions=(ProposedAssertion("as1", "a1", PresentationTreatment.ABSTAIN),))
    receipt = assess_integrity(proposal, overlay=overlay, artifact=artifact, policy=policy)
    assert receipt.integrity_status is IntegrityStatus.SATISFIED


def test_normalize_policy_returns_deeply_frozen_structure():
    policy = IntegrityPolicy(stricter_permitted_treatments={EpistemicState.KNOWN: {PresentationTreatment.ABSTAIN}})
    normalized = normalize_policy(policy)
    assert isinstance(normalized.stricter_permitted_treatments, MappingProxyType)
    assert isinstance(normalized.stricter_permitted_treatments[EpistemicState.KNOWN], frozenset)
    with pytest.raises(TypeError):
        normalized.stricter_permitted_treatments[EpistemicState.KNOWN] = frozenset()  # type: ignore[index]


def test_caller_mutating_original_dict_after_the_call_does_not_change_a_prior_receipt():
    artifact, overlay = build_known_affirmed_fixture()
    mutable_treatments = {EpistemicState.KNOWN: {PresentationTreatment.ESTABLISHED, PresentationTreatment.ABSTAIN}}
    policy = IntegrityPolicy(stricter_permitted_treatments=mutable_treatments)
    proposal = IntegrityProposal(proposal_id="p1", assertions=(ProposedAssertion("as1", "a1", PresentationTreatment.ESTABLISHED, EpistemicPolarity.AFFIRMED),))
    receipt_before = assess_integrity(proposal, overlay=overlay, artifact=artifact, policy=policy)
    assert receipt_before.integrity_status is IntegrityStatus.SATISFIED

    # Mutate the caller's own dict/set after the call returned.
    mutable_treatments[EpistemicState.KNOWN].discard(PresentationTreatment.ESTABLISHED)
    mutable_treatments[EpistemicState.KNOWN].add(PresentationTreatment.UNKNOWN)  # would be illegal if it leaked in

    # A second call with the SAME (now-mutated) policy object must be
    # evaluated fresh against whatever it currently says -- but the
    # ALREADY-ISSUED prior receipt must never have been retroactively
    # changed by this mutation (frozen at construction time).
    assert receipt_before.integrity_status is IntegrityStatus.SATISFIED
    assert receipt_before.policy_digest  # unchanged, still readable, still reflects the ORIGINAL policy state


def test_second_call_with_mutated_policy_object_is_rejected_if_now_illegal():
    """After the caller mutates the dict to add UNKNOWN (illegal for
    KNOWN under the hard floor), a FRESH call using that same policy
    object must be evaluated against its current (now illegal) content
    and rejected -- proving the evaluator reads live content per-call,
    while still never retroactively touching a prior receipt (previous
    test)."""
    artifact, overlay = build_known_affirmed_fixture()
    mutable_treatments = {EpistemicState.KNOWN: {PresentationTreatment.ESTABLISHED}}
    policy = IntegrityPolicy(stricter_permitted_treatments=mutable_treatments)
    proposal = IntegrityProposal(proposal_id="p1", assertions=())

    assess_integrity(proposal, overlay=overlay, artifact=artifact, policy=policy)  # legal, must not raise

    mutable_treatments[EpistemicState.KNOWN].add(PresentationTreatment.UNKNOWN)  # illegal for KNOWN
    with pytest.raises(errors.PolicyAttemptedToWeakenHardFloor):
        assess_integrity(proposal, overlay=overlay, artifact=artifact, policy=policy)


def test_empty_override_set_rejected_as_invalid_policy():
    artifact, overlay = build_known_affirmed_fixture()
    policy = IntegrityPolicy(stricter_permitted_treatments={EpistemicState.KNOWN: frozenset()})
    with pytest.raises(errors.InvalidIntegrityPolicy):
        assess_integrity(IntegrityProposal(proposal_id="p1", assertions=()), overlay=overlay, artifact=artifact, policy=policy)


def test_policy_aware_permitted_maximum_for_known_abstain_only():
    artifact, overlay = build_known_affirmed_fixture()
    policy = IntegrityPolicy(stricter_permitted_treatments={EpistemicState.KNOWN: frozenset({PresentationTreatment.ABSTAIN})})
    proposal = IntegrityProposal(proposal_id="p1", assertions=(ProposedAssertion("as1", "a1", PresentationTreatment.ABSTAIN),))
    receipt = assess_integrity(proposal, overlay=overlay, artifact=artifact, policy=policy)
    assert receipt.assertion_assessments[0].permitted_maximum_treatment is PresentationTreatment.ABSTAIN


def test_policy_aware_permitted_maximum_unaffected_by_policy_on_other_states():
    artifact, overlay = build_known_affirmed_fixture()
    policy = IntegrityPolicy(stricter_permitted_treatments={EpistemicState.UNCERTAIN: frozenset({PresentationTreatment.ABSTAIN})})
    proposal = IntegrityProposal(proposal_id="p1", assertions=(ProposedAssertion("as1", "a1", PresentationTreatment.ESTABLISHED, EpistemicPolarity.AFFIRMED),))
    receipt = assess_integrity(proposal, overlay=overlay, artifact=artifact, policy=policy)
    assert receipt.assertion_assessments[0].permitted_maximum_treatment is PresentationTreatment.ESTABLISHED


def test_no_policy_permitted_maximum_matches_pure_hard_floor():
    artifact, overlay = build_known_affirmed_fixture()
    proposal = IntegrityProposal(proposal_id="p1", assertions=(ProposedAssertion("as1", "a1", PresentationTreatment.ESTABLISHED, EpistemicPolarity.AFFIRMED),))
    receipt = assess_integrity(proposal, overlay=overlay, artifact=artifact)
    assert receipt.assertion_assessments[0].permitted_maximum_treatment is PresentationTreatment.ESTABLISHED
