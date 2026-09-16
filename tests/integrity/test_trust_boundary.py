"""Section 12/33-C: overlay trust boundary."""
from __future__ import annotations

import pytest

from orneur.intelligence.epistemic.enums import EpistemicPolarity
from orneur.intelligence.integrity import errors
from orneur.intelligence.integrity.contracts import IntegrityProposal, ProposedAssertion
from orneur.intelligence.integrity.enums import PresentationTreatment
from orneur.intelligence.integrity.evaluator import assess_integrity
from tests.integrity.conftest import TRUSTED_OCL, build_known_affirmed_fixture, make_artifact, make_atom


def test_wrong_artifact_rejected():
    artifact, overlay = build_known_affirmed_fixture()
    from orneur.intelligence.ocl.compiler import compile_artifact

    other = compile_artifact(make_artifact(artifact_id="other", atoms=(make_atom(atom_id="a1"),)), trust_context=TRUSTED_OCL)
    proposal = IntegrityProposal(proposal_id="p1", assertions=(ProposedAssertion("as1", "a1", PresentationTreatment.ESTABLISHED, EpistemicPolarity.AFFIRMED),))
    with pytest.raises(errors.OverlayBindingInvalid):
        assess_integrity(proposal, overlay=overlay, artifact=other)


def test_mutated_artifact_content_rejected():
    """Same artifact_id, different content -> different digest -> binding invalid."""
    from orneur.intelligence.ocl.compiler import compile_artifact

    artifact, overlay = build_known_affirmed_fixture()
    mutated = compile_artifact(
        make_artifact(artifact_id=artifact.artifact_id, atoms=(make_atom(atom_id="a1", content="mutated content"),)),
        trust_context=TRUSTED_OCL,
    )
    proposal = IntegrityProposal(proposal_id="p1", assertions=(ProposedAssertion("as1", "a1", PresentationTreatment.ESTABLISHED, EpistemicPolarity.AFFIRMED),))
    with pytest.raises(errors.OverlayBindingInvalid):
        assess_integrity(proposal, overlay=overlay, artifact=mutated)


def test_unknown_atom_reference_in_assertion_rejected():
    artifact, overlay = build_known_affirmed_fixture()
    proposal = IntegrityProposal(proposal_id="p1", assertions=(ProposedAssertion("as1", "atom-does-not-exist", PresentationTreatment.ESTABLISHED, EpistemicPolarity.AFFIRMED),))
    with pytest.raises(errors.NonAssessedAtomReference):
        assess_integrity(proposal, overlay=overlay, artifact=artifact)


def test_unknown_atom_reference_in_scope_rejected():
    artifact, overlay = build_known_affirmed_fixture()
    proposal = IntegrityProposal(proposal_id="p1", assertions=(), required_scope_atom_ids=("atom-does-not-exist",))
    with pytest.raises(errors.NonAssessedAtomReference):
        assess_integrity(proposal, overlay=overlay, artifact=artifact)


def test_malformed_overlay_type_rejected():
    artifact, _overlay = build_known_affirmed_fixture()
    proposal = IntegrityProposal(proposal_id="p1", assertions=())
    with pytest.raises(errors.InvalidObjectType):
        assess_integrity(proposal, overlay="not an overlay", artifact=artifact)  # type: ignore[arg-type]


def test_malformed_artifact_type_rejected():
    _artifact, overlay = build_known_affirmed_fixture()
    proposal = IntegrityProposal(proposal_id="p1", assertions=())
    with pytest.raises(errors.InvalidObjectType):
        assess_integrity(proposal, overlay=overlay, artifact={"fake": "artifact"})  # type: ignore[arg-type]


def test_fabricated_overlay_with_valid_looking_fields_still_rejected():
    """An externally constructed overlay whose fields merely LOOK right
    (matching artifact_id, but a digest that doesn't match the real
    canonical content) must not become trusted merely because the shape
    is correct."""
    import dataclasses

    artifact, overlay = build_known_affirmed_fixture()
    fabricated = dataclasses.replace(overlay, source_artifact_digest="0" * 64)
    proposal = IntegrityProposal(proposal_id="p1", assertions=(ProposedAssertion("as1", "a1", PresentationTreatment.ESTABLISHED, EpistemicPolarity.AFFIRMED),))
    with pytest.raises(errors.OverlayBindingInvalid):
        assess_integrity(proposal, overlay=fabricated, artifact=artifact)
