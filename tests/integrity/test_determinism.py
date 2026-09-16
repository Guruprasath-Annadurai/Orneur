"""Sections 19/20/33-F/33-G/33-H: determinism, permutation, duplicates."""
from __future__ import annotations

import pytest

from orneur.intelligence.epistemic.enums import EpistemicPolarity
from orneur.intelligence.integrity import errors
from orneur.intelligence.integrity.canonical import digest, to_canonical_json
from orneur.intelligence.integrity.contracts import IntegrityProposal, ProposedAssertion
from orneur.intelligence.integrity.enums import PresentationTreatment
from tests.integrity.conftest import assess_integrity_trusted as assess_integrity, build_disputed_fixture, build_known_affirmed_fixture, make_artifact, make_atom, make_evidence


def _two_atom_fixture():
    from orneur.intelligence.epistemic.enums import EvidenceResolutionStatus, EvidenceStance
    from orneur.intelligence.epistemic.resolver import assess_artifact
    from orneur.intelligence.ocl.compiler import compile_artifact
    from tests.integrity.conftest import ASSESSED_AT, TRUSTED_OCL, TRUSTED_VERIFIER, make_resolved_evidence

    artifact = make_artifact(
        atoms=(make_atom(atom_id="a1", evidence_refs=("e1",)), make_atom(atom_id="a2", evidence_refs=("e2",))),
        evidence=(make_evidence(evidence_id="e1"), make_evidence(evidence_id="e2")),
    )
    compiled = compile_artifact(artifact, trust_context=TRUSTED_OCL)
    overlay = assess_artifact(
        artifact, ocl_trust_context=TRUSTED_OCL, assessment_context_id="ctx-1", assessed_at=ASSESSED_AT,
        resolved_evidence=(
            make_resolved_evidence(evidence_id="e1", target_atom_id="a1", status=EvidenceResolutionStatus.VERIFIED, stance=EvidenceStance.SUPPORTS),
            make_resolved_evidence(evidence_id="e2", target_atom_id="a2", status=EvidenceResolutionStatus.VERIFIED, stance=EvidenceStance.SUPPORTS),
        ),
        resolution_trust_context=TRUSTED_VERIFIER, overlay_id="overlay-fixed",
    )
    return compiled, overlay


def test_default_receipt_id_is_deterministic_across_two_default_calls():
    artifact, overlay = build_known_affirmed_fixture()
    proposal = IntegrityProposal(proposal_id="p1", assertions=(ProposedAssertion("as1", "a1", PresentationTreatment.ESTABLISHED, EpistemicPolarity.AFFIRMED),))
    r1 = assess_integrity(proposal, overlay=overlay, artifact=artifact)
    r2 = assess_integrity(proposal, overlay=overlay, artifact=artifact)
    assert r1.receipt_id == r2.receipt_id
    assert digest(r1) == digest(r2)


def test_changing_proposal_changes_default_receipt_id():
    artifact, overlay = build_known_affirmed_fixture()
    p1 = IntegrityProposal(proposal_id="p1", assertions=(ProposedAssertion("as1", "a1", PresentationTreatment.ESTABLISHED, EpistemicPolarity.AFFIRMED),))
    p2 = IntegrityProposal(proposal_id="p2", assertions=(ProposedAssertion("as1", "a1", PresentationTreatment.ESTABLISHED, EpistemicPolarity.AFFIRMED),))
    r1 = assess_integrity(p1, overlay=overlay, artifact=artifact)
    r2 = assess_integrity(p2, overlay=overlay, artifact=artifact)
    assert r1.receipt_id != r2.receipt_id


def test_assertion_order_permutation_yields_identical_digest():
    artifact, overlay = _two_atom_fixture()
    proposal_ab = IntegrityProposal(
        proposal_id="p1",
        assertions=(
            ProposedAssertion("as1", "a1", PresentationTreatment.ESTABLISHED, EpistemicPolarity.AFFIRMED),
            ProposedAssertion("as2", "a2", PresentationTreatment.ESTABLISHED, EpistemicPolarity.AFFIRMED),
        ),
    )
    proposal_ba = IntegrityProposal(
        proposal_id="p1",
        assertions=(
            ProposedAssertion("as2", "a2", PresentationTreatment.ESTABLISHED, EpistemicPolarity.AFFIRMED),
            ProposedAssertion("as1", "a1", PresentationTreatment.ESTABLISHED, EpistemicPolarity.AFFIRMED),
        ),
    )
    r_ab = assess_integrity(proposal_ab, overlay=overlay, artifact=artifact, receipt_id="fixed")
    r_ba = assess_integrity(proposal_ba, overlay=overlay, artifact=artifact, receipt_id="fixed")
    assert digest(r_ab) == digest(r_ba)
    assert to_canonical_json(r_ab) == to_canonical_json(r_ba)


def test_scope_order_permutation_yields_identical_digest():
    artifact, overlay = _two_atom_fixture()
    assertions = (
        ProposedAssertion("as1", "a1", PresentationTreatment.ESTABLISHED, EpistemicPolarity.AFFIRMED),
        ProposedAssertion("as2", "a2", PresentationTreatment.ESTABLISHED, EpistemicPolarity.AFFIRMED),
    )
    p_ab = IntegrityProposal(proposal_id="p1", assertions=assertions, required_scope_atom_ids=("a1", "a2"))
    p_ba = IntegrityProposal(proposal_id="p1", assertions=assertions, required_scope_atom_ids=("a2", "a1"))
    r_ab = assess_integrity(p_ab, overlay=overlay, artifact=artifact, receipt_id="fixed")
    r_ba = assess_integrity(p_ba, overlay=overlay, artifact=artifact, receipt_id="fixed")
    assert digest(r_ab) == digest(r_ba)


def test_duplicate_assertion_ids_rejected():
    artifact, overlay = build_known_affirmed_fixture()
    proposal = IntegrityProposal(
        proposal_id="p1",
        assertions=(
            ProposedAssertion("as1", "a1", PresentationTreatment.ESTABLISHED, EpistemicPolarity.AFFIRMED),
            ProposedAssertion("as1", "a1", PresentationTreatment.ESTABLISHED, EpistemicPolarity.AFFIRMED),
        ),
    )
    with pytest.raises(errors.DuplicateAssertionId):
        assess_integrity(proposal, overlay=overlay, artifact=artifact)


def test_duplicate_scope_atoms_rejected():
    artifact, overlay = build_known_affirmed_fixture()
    proposal = IntegrityProposal(proposal_id="p1", assertions=(), required_scope_atom_ids=("a1", "a1"))
    with pytest.raises(errors.DuplicateScopeAtom):
        assess_integrity(proposal, overlay=overlay, artifact=artifact)


def test_no_random_or_time_dependency_across_many_default_calls():
    """Repeated calls (not just two) must all agree -- rules out any
    accidental per-call randomness."""
    artifact, overlay = build_known_affirmed_fixture()
    proposal = IntegrityProposal(proposal_id="p1", assertions=(ProposedAssertion("as1", "a1", PresentationTreatment.ESTABLISHED, EpistemicPolarity.AFFIRMED),))
    receipts = [assess_integrity(proposal, overlay=overlay, artifact=artifact) for _ in range(5)]
    ids = {r.receipt_id for r in receipts}
    digests = {digest(r) for r in receipts}
    assert len(ids) == 1
    assert len(digests) == 1
