"""Section 22/33-J: deep immutability, applying the Phase-18 standard."""
from __future__ import annotations

from types import MappingProxyType

import pytest

from orneur.intelligence.epistemic.enums import EpistemicPolarity
from orneur.intelligence.integrity import errors
from orneur.intelligence.integrity.canonical import digest
from orneur.intelligence.integrity.contracts import IntegrityProposal, ProposedAssertion
from orneur.intelligence.integrity.enums import PresentationTreatment
from orneur.intelligence.integrity.evaluator import assess_integrity
from tests.integrity.conftest import build_known_affirmed_fixture


def test_receipt_metadata_deeply_frozen():
    artifact, overlay = build_known_affirmed_fixture()
    proposal = IntegrityProposal(proposal_id="p1", assertions=(ProposedAssertion("as1", "a1", PresentationTreatment.ESTABLISHED, EpistemicPolarity.AFFIRMED),))
    metadata = {"nested": {"items": [1, 2]}}
    receipt = assess_integrity(proposal, overlay=overlay, artifact=artifact, metadata=metadata, receipt_id="fixed")
    assert isinstance(receipt.metadata, MappingProxyType)
    assert isinstance(receipt.metadata["nested"], MappingProxyType)
    assert isinstance(receipt.metadata["nested"]["items"], tuple)


def test_mutating_caller_original_receipt_metadata_after_construction_does_not_change_digest():
    artifact, overlay = build_known_affirmed_fixture()
    proposal = IntegrityProposal(proposal_id="p1", assertions=(ProposedAssertion("as1", "a1", PresentationTreatment.ESTABLISHED, EpistemicPolarity.AFFIRMED),))
    metadata = {"nested": {"items": [1, 2]}}
    receipt = assess_integrity(proposal, overlay=overlay, artifact=artifact, metadata=metadata, receipt_id="fixed")
    before = digest(receipt)
    metadata["nested"]["items"].append(999)
    after = digest(receipt)
    assert before == after
    assert receipt.metadata["nested"]["items"] == (1, 2)


def test_mutating_caller_original_assertion_metadata_after_construction_does_not_change_digest():
    artifact, overlay = build_known_affirmed_fixture()
    assertion_metadata = {"trace": [1, 2]}
    assertion = ProposedAssertion("as1", "a1", PresentationTreatment.ESTABLISHED, EpistemicPolarity.AFFIRMED, metadata=assertion_metadata)
    proposal = IntegrityProposal(proposal_id="p1", assertions=(assertion,))
    receipt = assess_integrity(proposal, overlay=overlay, artifact=artifact, receipt_id="fixed")
    before = digest(receipt)
    assertion_metadata["trace"].append(999)
    after = digest(receipt)
    assert before == after


def test_receipt_metadata_mapping_itself_cannot_be_mutated():
    artifact, overlay = build_known_affirmed_fixture()
    proposal = IntegrityProposal(proposal_id="p1", assertions=(ProposedAssertion("as1", "a1", PresentationTreatment.ESTABLISHED, EpistemicPolarity.AFFIRMED),))
    receipt = assess_integrity(proposal, overlay=overlay, artifact=artifact, metadata={"a": 1}, receipt_id="fixed")
    with pytest.raises(TypeError):
        receipt.metadata["a"] = 2


def test_nan_infinity_rejected_in_receipt_metadata():
    artifact, overlay = build_known_affirmed_fixture()
    proposal = IntegrityProposal(proposal_id="p1", assertions=(ProposedAssertion("as1", "a1", PresentationTreatment.ESTABLISHED, EpistemicPolarity.AFFIRMED),))
    with pytest.raises(errors.InvalidStructuredValue):
        assess_integrity(proposal, overlay=overlay, artifact=artifact, metadata={"v": float("nan")}, receipt_id="fixed")


def test_unsupported_object_type_in_metadata_rejected():
    artifact, overlay = build_known_affirmed_fixture()
    proposal = IntegrityProposal(proposal_id="p1", assertions=(ProposedAssertion("as1", "a1", PresentationTreatment.ESTABLISHED, EpistemicPolarity.AFFIRMED),))
    with pytest.raises(errors.InvalidStructuredValue):
        assess_integrity(proposal, overlay=overlay, artifact=artifact, metadata={"v": object()}, receipt_id="fixed")
