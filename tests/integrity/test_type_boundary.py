"""Section 21/33-I: strict input boundary, no raw exception leakage."""
from __future__ import annotations

import dataclasses

import pytest

from orneur.intelligence.epistemic.enums import EpistemicPolarity
from orneur.intelligence.integrity import errors
from orneur.intelligence.integrity.contracts import IntegrityProposal, ProposedAssertion
from orneur.intelligence.integrity.enums import PresentationTreatment
from tests.integrity.conftest import assess_integrity_trusted as assess_integrity, build_known_affirmed_fixture


def _base_assertion():
    return ProposedAssertion("as1", "a1", PresentationTreatment.ESTABLISHED, EpistemicPolarity.AFFIRMED)


@pytest.mark.parametrize("bad_treatment", ["ESTABLISHED", None, 1, True, EpistemicPolarity.AFFIRMED])
def test_malformed_treatment_rejected(bad_treatment):
    artifact, overlay = build_known_affirmed_fixture()
    bad = dataclasses.replace(_base_assertion(), treatment=bad_treatment)
    proposal = IntegrityProposal(proposal_id="p1", assertions=(bad,))
    with pytest.raises(errors.IntegrityError):
        assess_integrity(proposal, overlay=overlay, artifact=artifact)


@pytest.mark.parametrize("bad_polarity", ["AFFIRMED", 1, True, PresentationTreatment.ESTABLISHED])
def test_malformed_asserted_polarity_rejected(bad_polarity):
    artifact, overlay = build_known_affirmed_fixture()
    bad = dataclasses.replace(_base_assertion(), asserted_polarity=bad_polarity)
    proposal = IntegrityProposal(proposal_id="p1", assertions=(bad,))
    with pytest.raises(errors.IntegrityError):
        assess_integrity(proposal, overlay=overlay, artifact=artifact)


@pytest.mark.parametrize("field", ["assertion_id", "source_atom_id"])
@pytest.mark.parametrize("bad_value", [None, 1, True, object()])
def test_malformed_id_fields_rejected(field, bad_value):
    artifact, overlay = build_known_affirmed_fixture()
    bad = dataclasses.replace(_base_assertion(), **{field: bad_value})
    proposal = IntegrityProposal(proposal_id="p1", assertions=(bad,))
    with pytest.raises(errors.IntegrityError):
        assess_integrity(proposal, overlay=overlay, artifact=artifact)


def test_wrong_dataclass_type_in_assertions_sequence_rejected():
    artifact, overlay = build_known_affirmed_fixture()
    proposal = IntegrityProposal(proposal_id="p1", assertions=({"not": "an assertion"},))
    with pytest.raises(errors.IntegrityError):
        assess_integrity(proposal, overlay=overlay, artifact=artifact)


@pytest.mark.parametrize("bad_container", [None, {"a": 1}, "a string", (x for x in range(3))])
def test_malformed_assertions_container_rejected(bad_container):
    artifact, overlay = build_known_affirmed_fixture()
    proposal = IntegrityProposal(proposal_id="p1", assertions=bad_container)
    with pytest.raises(errors.IntegrityError):
        assess_integrity(proposal, overlay=overlay, artifact=artifact)


def test_malformed_proposal_type_rejected():
    artifact, overlay = build_known_affirmed_fixture()
    with pytest.raises(errors.IntegrityError):
        assess_integrity({"not": "a proposal"}, overlay=overlay, artifact=artifact)  # type: ignore[arg-type]


def test_malformed_policy_type_rejected():
    artifact, overlay = build_known_affirmed_fixture()
    proposal = IntegrityProposal(proposal_id="p1", assertions=(_base_assertion(),))
    with pytest.raises(errors.IntegrityError):
        assess_integrity(proposal, overlay=overlay, artifact=artifact, policy="not a policy")  # type: ignore[arg-type]


def test_malformed_evaluated_at_timestamp_rejected():
    artifact, overlay = build_known_affirmed_fixture()
    proposal = IntegrityProposal(proposal_id="p1", assertions=(_base_assertion(),))
    with pytest.raises(errors.IntegrityError):
        assess_integrity(proposal, overlay=overlay, artifact=artifact, evaluated_at="not-a-timestamp")


def test_no_raw_exception_types_ever_escape_malformed_input():
    artifact, overlay = build_known_affirmed_fixture()
    bad = dataclasses.replace(_base_assertion(), treatment="ESTABLISHED")
    proposal = IntegrityProposal(proposal_id="p1", assertions=(bad,))
    try:
        assess_integrity(proposal, overlay=overlay, artifact=artifact)
        assert False, "expected an exception"
    except errors.IntegrityError:
        pass
    except (AttributeError, TypeError, KeyError, ValueError) as exc:
        pytest.fail(f"a raw {type(exc).__name__} escaped instead of a typed IntegrityError: {exc}")
