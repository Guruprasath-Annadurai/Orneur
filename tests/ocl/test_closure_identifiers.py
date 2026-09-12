"""
Phase 17 closure section 12: consistent non-empty/length-bounded ID
validation across every identified object type. Uniqueness for each type
is already covered by the Duplicate*Id tests in test_closure_authority_
hardening.py; this file focuses on the shared "must be a non-empty,
bounded string" rule applied uniformly via `compiler._require_id`.
"""
from __future__ import annotations

import pytest

from orneur.intelligence.ocl.compiler import compile_artifact
from orneur.intelligence.ocl.errors import InvalidArtifactId
from orneur.intelligence.ocl.proposals import ActionIntent, EscalationRequest, VerificationContract
from tests.ocl.conftest import make_artifact, make_atom, make_evidence, make_relation


def test_empty_atom_id_rejected():
    atom = make_atom("")
    with pytest.raises(InvalidArtifactId):
        compile_artifact(make_artifact(atoms=(atom,)))


def test_empty_relation_id_rejected():
    atoms = (make_atom("a1"), make_atom("a2"))
    rel = make_relation("", source="a1", target="a2")
    with pytest.raises(InvalidArtifactId):
        compile_artifact(make_artifact(atoms=atoms, relations=(rel,)))


def test_empty_evidence_id_rejected():
    ev = make_evidence("")
    with pytest.raises(InvalidArtifactId):
        compile_artifact(make_artifact(evidence=(ev,)))


def test_empty_action_intent_id_rejected():
    intent = ActionIntent(intent_id="", proposed_capability="x")
    with pytest.raises(InvalidArtifactId):
        compile_artifact(make_artifact(action_intents=(intent,)))


def test_empty_verification_contract_id_rejected():
    atom = make_atom("a1")
    contract = VerificationContract(contract_id="", target_atom_ref="a1")
    with pytest.raises(InvalidArtifactId):
        compile_artifact(make_artifact(atoms=(atom,), verification_contracts=(contract,)))


def test_empty_escalation_id_rejected():
    esc = EscalationRequest(escalation_id="")
    with pytest.raises(InvalidArtifactId):
        compile_artifact(make_artifact(escalation_requests=(esc,)))


def test_empty_causal_hypothesis_id_rejected():
    from orneur.intelligence.ocl.causal import CausalHypothesis

    atoms = (make_atom("cause"), make_atom("effect"))
    hyp = CausalHypothesis(hypothesis_id="", cause_atom_ref="cause", mechanism="m", predicted_consequence_atom_ref="effect")
    with pytest.raises(InvalidArtifactId):
        compile_artifact(make_artifact(atoms=atoms, causal_hypotheses=(hyp,)))


def test_empty_counterfactual_branch_id_rejected():
    from orneur.intelligence.ocl.causal import CausalHypothesis, CounterfactualBranch

    atoms = (make_atom("cause"), make_atom("effect"), make_atom("cond"), make_atom("pred"))
    hyp = CausalHypothesis(hypothesis_id="h1", cause_atom_ref="cause", mechanism="m", predicted_consequence_atom_ref="effect")
    branch = CounterfactualBranch(branch_id="", causal_hypothesis_ref="h1", condition_atom_ref="cond", predicted_atom_ref="pred")
    with pytest.raises(InvalidArtifactId):
        compile_artifact(make_artifact(atoms=atoms, causal_hypotheses=(hyp,), counterfactual_branches=(branch,)))


def test_empty_request_id_is_rejected():
    """Phase 17 final closure: request_id is now REQUIRED and non-empty for
    a canonical artifact -- corporate traceability requires every compiled
    artifact to carry a correlation reference back to its originating
    request, matching artifact_id's own non-empty requirement."""
    from dataclasses import replace

    draft = replace(make_artifact(), request_id="")
    with pytest.raises(InvalidArtifactId):
        compile_artifact(draft)


def test_empty_parent_artifact_id_is_rejected_when_set():
    from dataclasses import replace

    draft = replace(make_artifact(), parent_artifact_id="")
    with pytest.raises(InvalidArtifactId):
        compile_artifact(draft)


def test_none_parent_artifact_id_is_valid():
    from dataclasses import replace

    draft = replace(make_artifact(), parent_artifact_id=None)
    compile_artifact(draft)  # None means "no parent" -- a valid, common case
