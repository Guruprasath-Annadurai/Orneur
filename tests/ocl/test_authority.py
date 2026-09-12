"""
The central Phase 17 invariant (spec section 4): model-produced OCL is
UNTRUSTED DATA and can never mint authority, verification truth, policy
fact, human approval, or Production Proof.
"""
from __future__ import annotations

import dataclasses

import pytest

from orneur.intelligence.ocl.compiler import compile_artifact
from orneur.intelligence.ocl.errors import ForbiddenAuthorityConstruct
from tests.ocl.conftest import make_artifact, make_atom


@pytest.mark.parametrize("key", [
    "authority_granted", "verified", "policy_allows", "human_approved",
    "production_ready", "execution_grant", "authority_lease",
    "policy_decision", "human_approval", "verified_fact", "production_proof",
])
def test_model_cannot_mint_authority_via_atom_metadata(key):
    atom = make_atom("a1", metadata={key: True})
    with pytest.raises(ForbiddenAuthorityConstruct):
        compile_artifact(make_artifact(atoms=(atom,)))


@pytest.mark.parametrize("key", ["authority_granted", "verified", "human_approved"])
def test_model_cannot_mint_authority_via_artifact_metadata(key):
    artifact = make_artifact(metadata={key: True})
    with pytest.raises(ForbiddenAuthorityConstruct):
        compile_artifact(artifact)


def test_forbidden_key_with_falsy_value_is_not_rejected():
    """A model *asking a question about* authority (e.g. explicitly
    recording `verified: false`) is not itself an authority claim -- only
    a truthy value is treated as an attempted mint."""
    atom = make_atom("a1", metadata={"verified": False})
    compile_artifact(make_artifact(atoms=(atom,)))


def test_forbidden_key_nested_inside_metadata_is_still_rejected():
    atom = make_atom("a1", metadata={"nested": {"human_approved": True}})
    with pytest.raises(ForbiddenAuthorityConstruct):
        compile_artifact(make_artifact(atoms=(atom,)))


def test_action_intent_has_no_authority_field():
    """Structural proof, not just a runtime check: ActionIntent's dataclass
    fields contain nothing that could hold an authority grant."""
    from orneur.intelligence.ocl.proposals import ActionIntent

    field_names = {f.name for f in dataclasses.fields(ActionIntent)}
    forbidden_substrings = ("authority", "grant", "approved", "execution_token", "credential")
    for name in field_names:
        for bad in forbidden_substrings:
            assert bad not in name.lower(), f"ActionIntent.{name} looks authority-shaped"


def test_verification_contract_status_field_cannot_be_preset_to_a_pass_state():
    """A VerificationContract is a REQUEST, never the VerificationRecord
    itself -- its own default status is UNRESOLVED, and this test pins
    that default so a future edit can't quietly change it to something
    that looks like a pass."""
    from orneur.intelligence.ocl.proposals import VerificationContract

    contract = VerificationContract(contract_id="c1", target_atom_ref="a1")
    assert contract.status == "UNRESOLVED"
