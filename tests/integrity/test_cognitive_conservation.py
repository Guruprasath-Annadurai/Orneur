"""Section 14/33-E: Cognitive Conservation -- material scope omission."""
from __future__ import annotations

from orneur.intelligence.epistemic.enums import EpistemicPolarity
from orneur.intelligence.integrity.contracts import IntegrityProposal, ProposedAssertion
from orneur.intelligence.integrity.enums import IntegrityStatus, IntegrityViolationReason, PresentationTreatment
from tests.integrity.conftest import assess_integrity_trusted as assess_integrity, build_known_affirmed_fixture, build_uncertain_fixture, build_unknown_fixture, build_unverifiable_fixture


def test_omitted_material_uncertain_atom_blocked():
    artifact, overlay = build_uncertain_fixture(atom_id="a1")
    proposal = IntegrityProposal(proposal_id="p1", assertions=(), required_scope_atom_ids=("a1",))
    receipt = assess_integrity(proposal, overlay=overlay, artifact=artifact)
    assert receipt.integrity_status is IntegrityStatus.BLOCKED
    assert IntegrityViolationReason.REQUIRED_SCOPE_ATOM_OMITTED in {v.reason for v in receipt.violations}


def test_omitted_material_unknown_atom_blocked():
    artifact, overlay = build_unknown_fixture(atom_id="a1")
    proposal = IntegrityProposal(proposal_id="p1", assertions=(), required_scope_atom_ids=("a1",))
    receipt = assess_integrity(proposal, overlay=overlay, artifact=artifact)
    assert receipt.integrity_status is IntegrityStatus.BLOCKED


def test_omitted_material_unverifiable_atom_blocked():
    artifact, overlay = build_unverifiable_fixture(atom_id="a1")
    proposal = IntegrityProposal(proposal_id="p1", assertions=(), required_scope_atom_ids=("a1",))
    receipt = assess_integrity(proposal, overlay=overlay, artifact=artifact)
    assert receipt.integrity_status is IntegrityStatus.BLOCKED


def test_omitted_material_known_atom_recorded_but_not_blocking():
    """A resolved fact left out of an answer is a completeness concern
    outside Phase 19's declared scope (see PHASE19_EPISTEMIC_INTEGRITY_SPEC.md
    'Material conservation states') -- recorded for audit in
    omitted_scope_atom_ids, but does not by itself block."""
    artifact, overlay = build_known_affirmed_fixture(atom_id="a1")
    proposal = IntegrityProposal(proposal_id="p1", assertions=(), required_scope_atom_ids=("a1",))
    receipt = assess_integrity(proposal, overlay=overlay, artifact=artifact)
    assert "a1" in receipt.omitted_scope_atom_ids
    assert receipt.integrity_status is IntegrityStatus.SATISFIED


def test_covered_material_atom_not_in_omitted_list():
    artifact, overlay = build_uncertain_fixture(atom_id="a1")
    proposal = IntegrityProposal(
        proposal_id="p1",
        assertions=(ProposedAssertion("as1", "a1", PresentationTreatment.UNCERTAIN),),
        required_scope_atom_ids=("a1",),
    )
    receipt = assess_integrity(proposal, overlay=overlay, artifact=artifact)
    assert receipt.integrity_status is IntegrityStatus.SATISFIED
    assert "a1" in receipt.material_scope_coverage
    assert "a1" not in receipt.omitted_scope_atom_ids
