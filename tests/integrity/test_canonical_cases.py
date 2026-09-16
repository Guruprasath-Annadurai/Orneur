"""Section 52's required canonical integrity examples, CASE A through L."""
from __future__ import annotations

import pytest

from orneur.intelligence.epistemic.enums import EpistemicPolarity
from orneur.intelligence.integrity import errors
from orneur.intelligence.integrity.contracts import IntegrityPolicy, IntegrityProposal, ProposedAssertion
from orneur.intelligence.integrity.enums import IntegrityStatus, IntegrityViolationReason, PresentationTreatment
from orneur.intelligence.integrity.evaluator import assess_integrity
from tests.integrity.conftest import (
    build_disputed_fixture,
    build_inferred_affirmed_fixture,
    build_known_affirmed_fixture,
    build_uncertain_fixture,
    build_unknown_fixture,
    build_unverifiable_fixture,
    make_artifact,
    make_atom,
)


def test_case_a_known_affirmed_established_satisfied():
    artifact, overlay = build_known_affirmed_fixture()
    proposal = IntegrityProposal(
        proposal_id="p1",
        assertions=(ProposedAssertion("as1", "a1", PresentationTreatment.ESTABLISHED, EpistemicPolarity.AFFIRMED),),
    )
    receipt = assess_integrity(proposal, overlay=overlay, artifact=artifact)
    assert receipt.integrity_status is IntegrityStatus.SATISFIED
    assert receipt.violations == ()


def test_case_b_inferred_affirmed_established_blocked_inference_as_fact():
    artifact, overlay = build_inferred_affirmed_fixture()
    proposal = IntegrityProposal(
        proposal_id="p1",
        assertions=(ProposedAssertion("as1", "b", PresentationTreatment.ESTABLISHED, EpistemicPolarity.AFFIRMED),),
    )
    receipt = assess_integrity(proposal, overlay=overlay, artifact=artifact)
    assert receipt.integrity_status is not IntegrityStatus.SATISFIED
    reasons = {v.reason for v in receipt.violations}
    assert IntegrityViolationReason.INFERENCE_PRESENTED_AS_FACT in reasons


def test_case_c_uncertain_established_blocked():
    artifact, overlay = build_uncertain_fixture()
    proposal = IntegrityProposal(
        proposal_id="p1",
        assertions=(ProposedAssertion("as1", "a1", PresentationTreatment.ESTABLISHED, EpistemicPolarity.AFFIRMED),),
    )
    receipt = assess_integrity(proposal, overlay=overlay, artifact=artifact)
    assert receipt.integrity_status is not IntegrityStatus.SATISFIED
    reasons = {v.reason for v in receipt.violations}
    assert IntegrityViolationReason.UNCERTAINTY_SUPPRESSED in reasons


def test_case_d_disputed_one_sided_affirmed_blocked():
    artifact, overlay = build_disputed_fixture()
    proposal = IntegrityProposal(
        proposal_id="p1",
        assertions=(ProposedAssertion("as1", "a1", PresentationTreatment.ESTABLISHED, EpistemicPolarity.AFFIRMED),),
    )
    receipt = assess_integrity(proposal, overlay=overlay, artifact=artifact)
    assert receipt.integrity_status is not IntegrityStatus.SATISFIED
    reasons = {v.reason for v in receipt.violations}
    assert IntegrityViolationReason.DISPUTE_SUPPRESSED in reasons


def test_case_e_disputed_dispute_disclosure_satisfied():
    artifact, overlay = build_disputed_fixture()
    proposal = IntegrityProposal(
        proposal_id="p1",
        assertions=(ProposedAssertion("as1", "a1", PresentationTreatment.DISPUTE),),
    )
    receipt = assess_integrity(proposal, overlay=overlay, artifact=artifact)
    assert receipt.integrity_status is IntegrityStatus.SATISFIED


def test_case_f_unknown_established_blocked():
    artifact, overlay = build_unknown_fixture()
    proposal = IntegrityProposal(
        proposal_id="p1",
        assertions=(ProposedAssertion("as1", "a1", PresentationTreatment.ESTABLISHED, EpistemicPolarity.AFFIRMED),),
    )
    receipt = assess_integrity(proposal, overlay=overlay, artifact=artifact)
    assert receipt.integrity_status is not IntegrityStatus.SATISFIED
    reasons = {v.reason for v in receipt.violations}
    assert IntegrityViolationReason.UNKNOWN_PRESENTED_AS_KNOWLEDGE in reasons


def test_case_g_unknown_disclosure_satisfied():
    artifact, overlay = build_unknown_fixture()
    proposal = IntegrityProposal(
        proposal_id="p1",
        assertions=(ProposedAssertion("as1", "a1", PresentationTreatment.UNKNOWN),),
    )
    receipt = assess_integrity(proposal, overlay=overlay, artifact=artifact)
    assert receipt.integrity_status is IntegrityStatus.SATISFIED


def test_case_h_unverifiable_presented_as_verified_fact_blocked():
    artifact, overlay = build_unverifiable_fixture()
    proposal = IntegrityProposal(
        proposal_id="p1",
        assertions=(ProposedAssertion("as1", "a1", PresentationTreatment.ESTABLISHED, EpistemicPolarity.AFFIRMED),),
    )
    receipt = assess_integrity(proposal, overlay=overlay, artifact=artifact)
    assert receipt.integrity_status is not IntegrityStatus.SATISFIED
    reasons = {v.reason for v in receipt.violations}
    assert IntegrityViolationReason.UNVERIFIABLE_PRESENTED_AS_VERIFIED in reasons


def test_case_i_material_disputed_atom_omitted_blocked():
    artifact, overlay = build_disputed_fixture(atom_id="a1")
    proposal = IntegrityProposal(
        proposal_id="p1",
        assertions=(),
        required_scope_atom_ids=("a1",),
    )
    receipt = assess_integrity(proposal, overlay=overlay, artifact=artifact)
    assert receipt.integrity_status is IntegrityStatus.BLOCKED
    reasons = {v.reason for v in receipt.violations}
    assert IntegrityViolationReason.REQUIRED_SCOPE_ATOM_OMITTED in reasons
    assert "a1" in receipt.omitted_scope_atom_ids


def test_case_j_wrong_artifact_otherwise_valid_overlay_typed_binding_failure():
    artifact, overlay = build_known_affirmed_fixture()
    other_artifact = make_artifact(artifact_id="different-artifact", atoms=(make_atom(atom_id="a1"),))
    from orneur.intelligence.ocl.compiler import compile_artifact
    from tests.integrity.conftest import TRUSTED_OCL

    compiled_other = compile_artifact(other_artifact, trust_context=TRUSTED_OCL)
    proposal = IntegrityProposal(
        proposal_id="p1",
        assertions=(ProposedAssertion("as1", "a1", PresentationTreatment.ESTABLISHED, EpistemicPolarity.AFFIRMED),),
    )
    with pytest.raises(errors.OverlayBindingInvalid):
        assess_integrity(proposal, overlay=overlay, artifact=compiled_other)


def test_case_k_weaker_caller_policy_unknown_to_established_rejected():
    from orneur.intelligence.epistemic.enums import EpistemicState

    artifact, overlay = build_unknown_fixture()
    weakening_policy = IntegrityPolicy(
        stricter_permitted_treatments={EpistemicState.UNKNOWN: frozenset({PresentationTreatment.ESTABLISHED})},
    )
    proposal = IntegrityProposal(
        proposal_id="p1",
        assertions=(ProposedAssertion("as1", "a1", PresentationTreatment.ESTABLISHED, EpistemicPolarity.AFFIRMED),),
    )
    with pytest.raises(errors.PolicyAttemptedToWeakenHardFloor):
        assess_integrity(proposal, overlay=overlay, artifact=artifact, policy=weakening_policy)


def test_case_l_same_inputs_run_twice_identical_receipt():
    from orneur.intelligence.integrity.canonical import digest, to_canonical_json

    artifact, overlay = build_known_affirmed_fixture()
    proposal = IntegrityProposal(
        proposal_id="p1",
        assertions=(ProposedAssertion("as1", "a1", PresentationTreatment.ESTABLISHED, EpistemicPolarity.AFFIRMED),),
    )
    receipt1 = assess_integrity(proposal, overlay=overlay, artifact=artifact)
    receipt2 = assess_integrity(proposal, overlay=overlay, artifact=artifact)
    assert receipt1.receipt_id == receipt2.receipt_id
    assert to_canonical_json(receipt1) == to_canonical_json(receipt2)
    assert digest(receipt1) == digest(receipt2)
