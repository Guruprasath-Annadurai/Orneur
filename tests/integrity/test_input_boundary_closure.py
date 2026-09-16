"""
Closure: strict input-boundary gaps. Reproduced defects: explicit
receipt_id of the wrong type silently entered the receipt as-is; root
metadata (receipt-level, proposal-level, and assertion-level) accepted
scalar values like a plain string because freeze.validate_and_freeze()
correctly accepts scalars as valid NESTED values but nothing enforced
the METADATA CONTRACT'S ROOT must be a mapping; nested unsupported
values inside proposal.metadata were never even validated because
proposal.metadata was not read by the evaluator at all before this
closure.
"""
from __future__ import annotations

import pytest

from orneur.intelligence.epistemic.enums import EpistemicPolarity
from orneur.intelligence.integrity import errors
from orneur.intelligence.integrity.contracts import IntegrityProposal, ProposedAssertion
from orneur.intelligence.integrity.enums import PresentationTreatment
from tests.integrity.conftest import assess_integrity_trusted as assess_integrity, build_known_affirmed_fixture


def _base_proposal():
    return IntegrityProposal(proposal_id="p1", assertions=(ProposedAssertion("as1", "a1", PresentationTreatment.ESTABLISHED, EpistemicPolarity.AFFIRMED),))


@pytest.mark.parametrize("bad_receipt_id", [123, True, object(), 1.5])
def test_explicit_receipt_id_wrong_type_rejected(bad_receipt_id):
    artifact, overlay = build_known_affirmed_fixture()
    with pytest.raises(errors.InvalidObjectType):
        assess_integrity(_base_proposal(), overlay=overlay, artifact=artifact, receipt_id=bad_receipt_id)


def test_explicit_receipt_id_valid_string_accepted():
    artifact, overlay = build_known_affirmed_fixture()
    receipt = assess_integrity(_base_proposal(), overlay=overlay, artifact=artifact, receipt_id="my-id")
    assert receipt.receipt_id == "my-id"


@pytest.mark.parametrize("bad_metadata", ["abc", 123, [], True, 1.5])
def test_root_receipt_metadata_wrong_type_rejected(bad_metadata):
    artifact, overlay = build_known_affirmed_fixture()
    with pytest.raises(errors.IntegrityError):
        assess_integrity(_base_proposal(), overlay=overlay, artifact=artifact, metadata=bad_metadata)


@pytest.mark.parametrize("bad_metadata", ["abc", 123, [1, 2], True])
def test_proposal_metadata_root_wrong_type_rejected(bad_metadata):
    artifact, overlay = build_known_affirmed_fixture()
    bad_proposal = IntegrityProposal(proposal_id="p1", assertions=_base_proposal().assertions, metadata=bad_metadata)
    with pytest.raises(errors.IntegrityError):
        assess_integrity(bad_proposal, overlay=overlay, artifact=artifact)


def test_proposal_metadata_nested_unsupported_value_rejected():
    artifact, overlay = build_known_affirmed_fixture()
    bad_proposal = IntegrityProposal(proposal_id="p1", assertions=_base_proposal().assertions, metadata={"x": object()})
    with pytest.raises(errors.InvalidStructuredValue):
        assess_integrity(bad_proposal, overlay=overlay, artifact=artifact)


@pytest.mark.parametrize("bad_metadata", ["abc", 123, [1, 2]])
def test_assertion_metadata_root_wrong_type_rejected(bad_metadata):
    artifact, overlay = build_known_affirmed_fixture()
    bad_assertion = ProposedAssertion("as1", "a1", PresentationTreatment.ESTABLISHED, EpistemicPolarity.AFFIRMED, metadata=bad_metadata)
    proposal = IntegrityProposal(proposal_id="p1", assertions=(bad_assertion,))
    with pytest.raises(errors.IntegrityError):
        assess_integrity(proposal, overlay=overlay, artifact=artifact)


def test_proposal_metadata_valid_mapping_accepted():
    artifact, overlay = build_known_affirmed_fixture()
    proposal = IntegrityProposal(proposal_id="p1", assertions=_base_proposal().assertions, metadata={"note": "ok"})
    receipt = assess_integrity(proposal, overlay=overlay, artifact=artifact)
    assert receipt.integrity_status.value == "SATISFIED"


def test_no_raw_exception_escapes_any_of_the_above():
    artifact, overlay = build_known_affirmed_fixture()
    bad_proposal = IntegrityProposal(proposal_id="p1", assertions=_base_proposal().assertions, metadata="abc")
    try:
        assess_integrity(bad_proposal, overlay=overlay, artifact=artifact)
        assert False, "expected an exception"
    except errors.IntegrityError:
        pass
    except (AttributeError, TypeError, KeyError, ValueError) as exc:
        pytest.fail(f"a raw {type(exc).__name__} escaped instead of a typed IntegrityError: {exc}")
