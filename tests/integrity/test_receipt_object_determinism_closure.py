"""
Closure: the RETURNED IntegrityReceipt object itself must be
permutation-deterministic, not merely its canonical JSON/digest.
Reproduced defect: required_disclosures (and, by the same construction
pattern, violations) were placed into the receipt in
input/iteration-derived order, never sorted at construction time --
only canonical.py's canonicalize() sorted them, which is invoked only
during serialization, not when the caller receives the returned object.
Two permuted-but-semantically-identical proposals therefore produced
receipts with EQUAL digests but UNEQUAL receipt objects
(dataclass `==` compares tuple order), which is confusing and
inconsistent for any caller comparing receipts directly rather than via
canonical.digest().
"""
from __future__ import annotations

from orneur.intelligence.epistemic.enums import EvidenceResolutionStatus, EvidenceStance
from orneur.intelligence.epistemic.resolver import assess_artifact
from orneur.intelligence.integrity.contracts import IntegrityProposal, ProposedAssertion
from orneur.intelligence.integrity.enums import PresentationTreatment
from orneur.intelligence.ocl.compiler import compile_artifact
from tests.integrity.conftest import assess_integrity_trusted as assess_integrity, ASSESSED_AT, TRUSTED_OCL, make_artifact, make_atom


def _two_atom_overlay():
    artifact = make_artifact(atoms=(make_atom(atom_id="a1"), make_atom(atom_id="a2")))
    compiled = compile_artifact(artifact, trust_context=TRUSTED_OCL)
    overlay = assess_artifact(compiled, ocl_trust_context=TRUSTED_OCL, assessment_context_id="ctx-1", assessed_at=ASSESSED_AT)
    return compiled, overlay


def test_assertion_order_permutation_receipt_object_equality():
    artifact, overlay = _two_atom_overlay()
    p_ab = IntegrityProposal(proposal_id="p1", assertions=(
        ProposedAssertion("as1", "a1", PresentationTreatment.UNKNOWN),
        ProposedAssertion("as2", "a2", PresentationTreatment.UNKNOWN),
    ))
    p_ba = IntegrityProposal(proposal_id="p1", assertions=(
        ProposedAssertion("as2", "a2", PresentationTreatment.UNKNOWN),
        ProposedAssertion("as1", "a1", PresentationTreatment.UNKNOWN),
    ))
    r_ab = assess_integrity(p_ab, overlay=overlay, artifact=artifact, receipt_id="fixed")
    r_ba = assess_integrity(p_ba, overlay=overlay, artifact=artifact, receipt_id="fixed")
    assert r_ab == r_ba


def test_disclosure_order_permutation_receipt_object_equality():
    artifact, overlay = _two_atom_overlay()
    p_ab = IntegrityProposal(proposal_id="p1", assertions=(
        ProposedAssertion("as1", "a1", PresentationTreatment.UNKNOWN),
        ProposedAssertion("as2", "a2", PresentationTreatment.UNKNOWN),
    ))
    p_ba = IntegrityProposal(proposal_id="p1", assertions=(
        ProposedAssertion("as2", "a2", PresentationTreatment.UNKNOWN),
        ProposedAssertion("as1", "a1", PresentationTreatment.UNKNOWN),
    ))
    r_ab = assess_integrity(p_ab, overlay=overlay, artifact=artifact, receipt_id="fixed")
    r_ba = assess_integrity(p_ba, overlay=overlay, artifact=artifact, receipt_id="fixed")
    assert r_ab.required_disclosures == r_ba.required_disclosures


def test_violation_order_permutation_receipt_object_equality():
    from orneur.intelligence.epistemic.enums import EpistemicPolarity

    artifact, overlay = _two_atom_overlay()
    # Both assertions overclaim (UNKNOWN state presented as ESTABLISHED) -> both produce violations.
    p_ab = IntegrityProposal(proposal_id="p1", assertions=(
        ProposedAssertion("as1", "a1", PresentationTreatment.ESTABLISHED, EpistemicPolarity.AFFIRMED),
        ProposedAssertion("as2", "a2", PresentationTreatment.ESTABLISHED, EpistemicPolarity.AFFIRMED),
    ))
    p_ba = IntegrityProposal(proposal_id="p1", assertions=(
        ProposedAssertion("as2", "a2", PresentationTreatment.ESTABLISHED, EpistemicPolarity.AFFIRMED),
        ProposedAssertion("as1", "a1", PresentationTreatment.ESTABLISHED, EpistemicPolarity.AFFIRMED),
    ))
    r_ab = assess_integrity(p_ab, overlay=overlay, artifact=artifact, receipt_id="fixed")
    r_ba = assess_integrity(p_ba, overlay=overlay, artifact=artifact, receipt_id="fixed")
    assert r_ab.violations == r_ba.violations
    assert r_ab == r_ba


def test_full_receipt_equality_with_disclosures_and_violations_present_together():
    from orneur.intelligence.epistemic.enums import EpistemicPolarity

    artifact, overlay = _two_atom_overlay()
    # a1 overclaims (violation); a2 correctly discloses UNKNOWN (disclosure only).
    p_ab = IntegrityProposal(proposal_id="p1", assertions=(
        ProposedAssertion("as1", "a1", PresentationTreatment.ESTABLISHED, EpistemicPolarity.AFFIRMED),
        ProposedAssertion("as2", "a2", PresentationTreatment.UNKNOWN),
    ))
    p_ba = IntegrityProposal(proposal_id="p1", assertions=(
        ProposedAssertion("as2", "a2", PresentationTreatment.UNKNOWN),
        ProposedAssertion("as1", "a1", PresentationTreatment.ESTABLISHED, EpistemicPolarity.AFFIRMED),
    ))
    r_ab = assess_integrity(p_ab, overlay=overlay, artifact=artifact, receipt_id="fixed")
    r_ba = assess_integrity(p_ba, overlay=overlay, artifact=artifact, receipt_id="fixed")
    assert r_ab == r_ba
