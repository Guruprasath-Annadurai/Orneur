"""
Closure: proposal_digest must bind the COMPLETE normalized structured
proposal, including proposal.metadata and every assertion.metadata --
previously these were part of the public contract but silently excluded
from the digest, so a caller could change metadata without it being
reflected anywhere in the receipt's identity.
"""
from __future__ import annotations

from orneur.intelligence.epistemic.enums import EpistemicPolarity
from orneur.intelligence.integrity.contracts import IntegrityProposal, ProposedAssertion
from orneur.intelligence.integrity.enums import PresentationTreatment
from tests.integrity.conftest import assess_integrity_trusted as assess_integrity, build_known_affirmed_fixture


def test_differing_proposal_metadata_changes_proposal_digest_and_default_receipt_id():
    artifact, overlay = build_known_affirmed_fixture()
    assertions = (ProposedAssertion("as1", "a1", PresentationTreatment.ESTABLISHED, EpistemicPolarity.AFFIRMED),)
    p1 = IntegrityProposal(proposal_id="p1", assertions=assertions, metadata={"note": "v1"})
    p2 = IntegrityProposal(proposal_id="p1", assertions=assertions, metadata={"note": "v2"})
    r1 = assess_integrity(p1, overlay=overlay, artifact=artifact)
    r2 = assess_integrity(p2, overlay=overlay, artifact=artifact)
    assert r1.proposal_digest != r2.proposal_digest
    assert r1.receipt_id != r2.receipt_id


def test_differing_assertion_metadata_changes_proposal_digest():
    artifact, overlay = build_known_affirmed_fixture()
    a1 = ProposedAssertion("as1", "a1", PresentationTreatment.ESTABLISHED, EpistemicPolarity.AFFIRMED, metadata={"trace": "v1"})
    a2 = ProposedAssertion("as1", "a1", PresentationTreatment.ESTABLISHED, EpistemicPolarity.AFFIRMED, metadata={"trace": "v2"})
    r1 = assess_integrity(IntegrityProposal(proposal_id="p1", assertions=(a1,)), overlay=overlay, artifact=artifact)
    r2 = assess_integrity(IntegrityProposal(proposal_id="p1", assertions=(a2,)), overlay=overlay, artifact=artifact)
    assert r1.proposal_digest != r2.proposal_digest


def test_metadata_key_order_permutation_yields_same_digest():
    """Semantically identical metadata, different key insertion order,
    must yield the SAME proposal_digest -- canonicalization normalizes
    key order, it does not treat order as semantic content."""
    artifact, overlay = build_known_affirmed_fixture()
    assertions = (ProposedAssertion("as1", "a1", PresentationTreatment.ESTABLISHED, EpistemicPolarity.AFFIRMED),)
    meta_ab = {"a": 1, "b": 2}
    meta_ba = {"b": 2, "a": 1}
    p_ab = IntegrityProposal(proposal_id="p1", assertions=assertions, metadata=meta_ab)
    p_ba = IntegrityProposal(proposal_id="p1", assertions=assertions, metadata=meta_ba)
    r_ab = assess_integrity(p_ab, overlay=overlay, artifact=artifact)
    r_ba = assess_integrity(p_ba, overlay=overlay, artifact=artifact)
    assert r_ab.proposal_digest == r_ba.proposal_digest
    assert r_ab.receipt_id == r_ba.receipt_id


def test_no_metadata_at_all_is_stable_and_distinct_from_empty_dict_semantically_equal():
    """Omitting metadata (default empty) and passing an explicit empty
    dict must behave identically -- both are 'no metadata'."""
    artifact, overlay = build_known_affirmed_fixture()
    assertions = (ProposedAssertion("as1", "a1", PresentationTreatment.ESTABLISHED, EpistemicPolarity.AFFIRMED),)
    p_default = IntegrityProposal(proposal_id="p1", assertions=assertions)
    p_explicit_empty = IntegrityProposal(proposal_id="p1", assertions=assertions, metadata={})
    r1 = assess_integrity(p_default, overlay=overlay, artifact=artifact)
    r2 = assess_integrity(p_explicit_empty, overlay=overlay, artifact=artifact)
    assert r1.proposal_digest == r2.proposal_digest
