from __future__ import annotations

import dataclasses

import pytest

from orneur.intelligence.ocl.artifact import CognitiveArtifact
from orneur.intelligence.ocl.checkpoint import create_checkpoint, restore_checkpoint
from orneur.intelligence.ocl.errors import SecretContentRejected
from tests.ocl.conftest import make_artifact, make_atom, make_evidence


def test_checkpoint_round_trip():
    original = make_artifact(atoms=(make_atom("a1", content="the sky is blue"),))
    checkpoint = create_checkpoint(original)
    restored = restore_checkpoint(checkpoint)
    assert restored.artifact_id == original.artifact_id
    assert restored.atoms[0].content == "the sky is blue"


def test_cognitive_artifact_has_no_hidden_chain_of_thought_field():
    field_names = {f.name for f in dataclasses.fields(CognitiveArtifact)}
    forbidden_substrings = ("chain_of_thought", "raw_reasoning", "scratchpad", "hidden_cot", "private_reasoning")
    for name in field_names:
        for bad in forbidden_substrings:
            assert bad not in name.lower()


def test_secret_shaped_atom_content_is_rejected_not_silently_persisted():
    atom = make_atom("a1", content="here is my key: sk-abcdefghijklmnopqrstuvwx")
    with pytest.raises(SecretContentRejected):
        create_checkpoint(make_artifact(atoms=(atom,)))


def test_secret_shaped_evidence_reference_is_rejected():
    ev = make_evidence("e1", reference="sk-abcdefghijklmnopqrstuvwx")
    with pytest.raises(SecretContentRejected):
        create_checkpoint(make_artifact(evidence=(ev,)))


def test_secret_in_nested_metadata_is_rejected():
    atom = make_atom("a1", metadata={"nested": {"note": "key: sk-abcdefghijklmnopqrstuvwx"}})
    with pytest.raises(SecretContentRejected):
        create_checkpoint(make_artifact(atoms=(atom,)))


def test_secret_in_action_intent_arguments_summary_is_rejected():
    from orneur.intelligence.ocl.proposals import ActionIntent

    intent = ActionIntent(intent_id="i1", proposed_capability="x", arguments_summary={"token": "sk-abcdefghijklmnopqrstuvwx"})
    with pytest.raises(SecretContentRejected):
        create_checkpoint(make_artifact(action_intents=(intent,)))


def test_secret_in_verification_contract_proposed_test_is_rejected():
    from orneur.intelligence.ocl.proposals import VerificationContract

    atom = make_atom("a1")
    contract = VerificationContract(contract_id="v1", target_atom_ref="a1", proposed_test="curl -H 'Authorization: sk-abcdefghijklmnopqrstuvwx'")
    with pytest.raises(SecretContentRejected):
        create_checkpoint(make_artifact(atoms=(atom,), verification_contracts=(contract,)))


def test_secret_in_escalation_request_evidence_deficit_is_rejected():
    from orneur.intelligence.ocl.proposals import EscalationRequest

    esc = EscalationRequest(escalation_id="e1", evidence_deficit="need access via sk-abcdefghijklmnopqrstuvwx")
    with pytest.raises(SecretContentRejected):
        create_checkpoint(make_artifact(escalation_requests=(esc,)))


def test_secret_in_causal_hypothesis_mechanism_is_rejected():
    from orneur.intelligence.ocl.causal import CausalHypothesis

    atoms = (make_atom("cause"), make_atom("effect"))
    hyp = CausalHypothesis(hypothesis_id="h1", cause_atom_ref="cause", mechanism="leaked via sk-abcdefghijklmnopqrstuvwx", predicted_consequence_atom_ref="effect")
    with pytest.raises(SecretContentRejected):
        create_checkpoint(make_artifact(atoms=atoms, causal_hypotheses=(hyp,)))


def test_secret_in_provenance_invocation_ref_is_rejected():
    from orneur.intelligence.ocl.enums import ProducerKind
    from orneur.intelligence.ocl.provenance import Provenance

    prov = Provenance(producer_kind=ProducerKind.DETERMINISTIC_SYSTEM, producer_id="x", invocation_ref="sk-abcdefghijklmnopqrstuvwx")
    with pytest.raises(SecretContentRejected):
        create_checkpoint(make_artifact(provenance=prov))


def test_ordinary_content_checkpoints_without_rejection():
    atom = make_atom("a1", content="the investigation found no evidence of a regression")
    create_checkpoint(make_artifact(atoms=(atom,)))


def test_compiled_artifact_is_immutable():
    from orneur.intelligence.ocl.compiler import compile_artifact
    compiled = compile_artifact(make_artifact(atoms=(make_atom("a1"),)))
    with pytest.raises(dataclasses.FrozenInstanceError):
        compiled.artifact_id = "tampered"
