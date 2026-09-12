"""
Phase 17 closure: proves the whole-artifact validation, recursive
authority-construct scanning (including nested lists), and evidence
self-authentication doctrine added in this closure. Several of these
reproduce a gap that genuinely existed in the prior implementation
(commit ea9426f) -- verified by inspecting `git show
ea9426f:orneur/intelligence/ocl/compiler.py`, which had no
`_validate_action_intents`/no list-recursion in `_check_forbidden_metadata`/
no untrusted-artifact evidence-impersonation check -- rather than by
reverting the working tree, per the closure's own TDD discipline.
"""
from __future__ import annotations

import pytest

from orneur.intelligence.ocl.compiler import compile_artifact
from orneur.intelligence.ocl.enums import AtomKind
from orneur.intelligence.ocl.errors import (
    DanglingRelation,
    DuplicateActionIntentId,
    DuplicateCausalHypothesisId,
    DuplicateCounterfactualBranchId,
    DuplicateEscalationRequestId,
    DuplicateVerificationContractId,
    ForbiddenAuthorityConstruct,
    InvalidRelationShape,
    InvalidVerificationStatus,
)
from orneur.intelligence.ocl.proposals import ActionIntent, EscalationRequest, VerificationContract
from tests.ocl.conftest import make_artifact, make_atom


def _vc(**kw):
    base = dict(contract_id="v1", target_atom_ref="a1")
    base.update(kw)
    return VerificationContract(**base)


def test_verification_contract_arbitrary_status_rejected():
    atom = make_atom("a1")
    contract = _vc(status="VERIFIED")
    with pytest.raises(InvalidVerificationStatus):
        compile_artifact(make_artifact(atoms=(atom,), verification_contracts=(contract,)))


@pytest.mark.parametrize("bad_status", ["PASS", "PASSED", "ACCEPT", "SUCCESS", "VERIFIED_TRUE", "unresolved"])
def test_every_non_exact_unresolved_status_rejected(bad_status):
    atom = make_atom("a1")
    contract = _vc(status=bad_status)
    with pytest.raises(InvalidVerificationStatus):
        compile_artifact(make_artifact(atoms=(atom,), verification_contracts=(contract,)))


def test_exact_unresolved_status_accepted():
    atom = make_atom("a1")
    contract = _vc(status="UNRESOLVED")
    compile_artifact(make_artifact(atoms=(atom,), verification_contracts=(contract,)))


def test_verification_contract_dangling_target_rejected():
    contract = _vc(target_atom_ref="does-not-exist")
    with pytest.raises(DanglingRelation):
        compile_artifact(make_artifact(verification_contracts=(contract,)))


def test_duplicate_verification_contract_id_rejected():
    atom = make_atom("a1")
    with pytest.raises(DuplicateVerificationContractId):
        compile_artifact(make_artifact(atoms=(atom,), verification_contracts=(_vc(), _vc())))


def test_action_intent_dangling_rationale_ref_rejected():
    intent = ActionIntent(intent_id="i1", proposed_capability="write_file", rationale_atom_refs=("missing",))
    with pytest.raises(DanglingRelation):
        compile_artifact(make_artifact(action_intents=(intent,)))


def test_duplicate_action_intent_id_rejected():
    intent1 = ActionIntent(intent_id="i1", proposed_capability="a")
    intent2 = ActionIntent(intent_id="i1", proposed_capability="b")
    with pytest.raises(DuplicateActionIntentId):
        compile_artifact(make_artifact(action_intents=(intent1, intent2)))


def test_action_intent_dangling_verification_requirement_ref_rejected():
    intent = ActionIntent(intent_id="i1", proposed_capability="x", verification_requirement_refs=("missing-contract",))
    with pytest.raises(DanglingRelation):
        compile_artifact(make_artifact(action_intents=(intent,)))


def test_escalation_request_unresolved_conflict_ref_must_be_a_conflict_atom():
    non_conflict = make_atom("a1", kind=AtomKind.ASSERTION)
    esc = EscalationRequest(escalation_id="e1", unresolved_conflict_refs=("a1",))
    with pytest.raises(InvalidRelationShape):
        compile_artifact(make_artifact(atoms=(non_conflict,), escalation_requests=(esc,)))


def test_escalation_request_with_real_conflict_atom_accepted():
    conflict_atom = make_atom("a1", kind=AtomKind.CONFLICT)
    esc = EscalationRequest(escalation_id="e1", unresolved_conflict_refs=("a1",))
    compile_artifact(make_artifact(atoms=(conflict_atom,), escalation_requests=(esc,)))


def test_duplicate_escalation_request_id_rejected():
    esc1 = EscalationRequest(escalation_id="e1")
    esc2 = EscalationRequest(escalation_id="e1")
    with pytest.raises(DuplicateEscalationRequestId):
        compile_artifact(make_artifact(escalation_requests=(esc1, esc2)))


def test_causal_hypothesis_dangling_cause_ref_rejected():
    from orneur.intelligence.ocl.causal import CausalHypothesis

    effect = make_atom("effect")
    hyp = CausalHypothesis(hypothesis_id="h1", cause_atom_ref="missing", mechanism="m", predicted_consequence_atom_ref="effect")
    with pytest.raises(DanglingRelation):
        compile_artifact(make_artifact(atoms=(effect,), causal_hypotheses=(hyp,)))


def test_duplicate_causal_hypothesis_id_rejected():
    from orneur.intelligence.ocl.causal import CausalHypothesis

    atoms = (make_atom("cause"), make_atom("effect"))
    hyp1 = CausalHypothesis(hypothesis_id="h1", cause_atom_ref="cause", mechanism="m", predicted_consequence_atom_ref="effect")
    hyp2 = CausalHypothesis(hypothesis_id="h1", cause_atom_ref="cause", mechanism="m2", predicted_consequence_atom_ref="effect")
    with pytest.raises(DuplicateCausalHypothesisId):
        compile_artifact(make_artifact(atoms=atoms, causal_hypotheses=(hyp1, hyp2)))


def test_counterfactual_branch_dangling_hypothesis_ref_rejected():
    from orneur.intelligence.ocl.causal import CounterfactualBranch

    atoms = (make_atom("cond"), make_atom("pred"))
    branch = CounterfactualBranch(branch_id="b1", causal_hypothesis_ref="missing", condition_atom_ref="cond", predicted_atom_ref="pred")
    with pytest.raises(DanglingRelation):
        compile_artifact(make_artifact(atoms=atoms, counterfactual_branches=(branch,)))


def test_duplicate_counterfactual_branch_id_rejected():
    from orneur.intelligence.ocl.causal import CausalHypothesis, CounterfactualBranch

    atoms = (make_atom("cause"), make_atom("effect"), make_atom("cond"), make_atom("pred"))
    hyp = CausalHypothesis(hypothesis_id="h1", cause_atom_ref="cause", mechanism="m", predicted_consequence_atom_ref="effect")
    b1 = CounterfactualBranch(branch_id="b1", causal_hypothesis_ref="h1", condition_atom_ref="cond", predicted_atom_ref="pred")
    b2 = CounterfactualBranch(branch_id="b1", causal_hypothesis_ref="h1", condition_atom_ref="cond", predicted_atom_ref="pred")
    with pytest.raises(DuplicateCounterfactualBranchId):
        compile_artifact(make_artifact(atoms=atoms, causal_hypotheses=(hyp,), counterfactual_branches=(b1, b2)))


# ── Recursive authority-construct smuggling (section 3) ─────────────────

def test_nested_list_authority_smuggling_rejected():
    atom = make_atom("a1", metadata={"wrapper": [{"authority_granted": True}]})
    with pytest.raises(ForbiddenAuthorityConstruct):
        compile_artifact(make_artifact(atoms=(atom,)))


def test_relation_metadata_authority_smuggling_rejected():
    from orneur.intelligence.ocl.enums import RelationKind
    from orneur.intelligence.ocl.graph import CognitiveRelation

    atoms = (make_atom("a1"), make_atom("a2"))
    rel = CognitiveRelation(relation_id="r1", kind=RelationKind.SUPPORTS, source_atom_id="a1", target_atom_id="a2", metadata={"human_approved": True})
    with pytest.raises(ForbiddenAuthorityConstruct):
        compile_artifact(make_artifact(atoms=atoms, relations=(rel,)))


def test_evidence_metadata_authority_smuggling_rejected():
    from orneur.intelligence.ocl.evidence import EvidenceAnchor
    from orneur.intelligence.ocl.enums import EvidenceKind

    ev = EvidenceAnchor(evidence_id="e1", evidence_kind=EvidenceKind.TOOL_OUTPUT, issuer="x", reference="y", metadata={"verified": True})
    with pytest.raises(ForbiddenAuthorityConstruct):
        compile_artifact(make_artifact(evidence=(ev,)))


def test_action_intent_arguments_summary_authority_smuggling_rejected():
    intent = ActionIntent(intent_id="i1", proposed_capability="x", arguments_summary={"nested": [{"policy_allows": True}]})
    with pytest.raises(ForbiddenAuthorityConstruct):
        compile_artifact(make_artifact(action_intents=(intent,)))


def test_deeply_nested_list_of_lists_authority_smuggling_rejected():
    atom = make_atom("a1", metadata={"a": [[{"production_ready": True}]]})
    with pytest.raises(ForbiddenAuthorityConstruct):
        compile_artifact(make_artifact(atoms=(atom,)))
