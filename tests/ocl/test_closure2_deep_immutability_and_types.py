"""
Phase 17 acceptance-boundary closure sections 2-3: true deep immutability
across EVERY dataclass field (not only dict-typed metadata fields), and
programmatic compiler type validation (compile_artifact() must not depend
on the wire parser having already enforced Python types -- a direct
caller can construct a dataclass violating its own type annotation, since
Python does not enforce them at runtime).
"""
from __future__ import annotations

import pytest

from orneur.intelligence.ocl.artifact import CognitiveArtifact
from orneur.intelligence.ocl.canonical import digest
from orneur.intelligence.ocl.compiler import compile_artifact
from orneur.intelligence.ocl.enums import ProducerKind
from orneur.intelligence.ocl.errors import InvalidProvenance, InvalidStructuredValue
from orneur.intelligence.ocl.evidence import EvidenceAnchor
from orneur.intelligence.ocl.proposals import ActionIntent, EscalationRequest, VerificationContract
from orneur.intelligence.ocl.provenance import ModelIdentityRef, Provenance
from orneur.intelligence.ocl.version import CURRENT_SCHEMA_VERSION
from tests.ocl.conftest import FIXED_TIME, make_artifact


def _det_provenance():
    return Provenance(producer_kind=ProducerKind.DETERMINISTIC_SYSTEM, producer_id="x")


# ── True deep immutability for programmatic drafts (section 2) ──────────

@pytest.mark.parametrize("field_name", ["preconditions", "risk_hints"])
def test_action_intent_informational_list_field_becomes_immutable_tuple_after_compile(field_name):
    intent = ActionIntent(intent_id="i1", proposed_capability="x", **{field_name: ["v1"]})
    draft = make_artifact(action_intents=(intent,))
    compiled = compile_artifact(draft)
    value = getattr(compiled.action_intents[0], field_name)
    assert isinstance(value, tuple)
    with pytest.raises(AttributeError):
        value.append("tamper")


def test_action_intent_rationale_atom_refs_becomes_immutable_tuple_after_compile():
    from tests.ocl.conftest import make_atom
    intent = ActionIntent(intent_id="i1", proposed_capability="x", rationale_atom_refs=["a1"])
    draft = make_artifact(atoms=(make_atom("a1"),), action_intents=(intent,))
    compiled = compile_artifact(draft)
    value = compiled.action_intents[0].rationale_atom_refs
    assert isinstance(value, tuple)
    with pytest.raises(AttributeError):
        value.append("tamper")


def test_action_intent_verification_requirement_refs_becomes_immutable_tuple_after_compile():
    from tests.ocl.conftest import make_atom
    atom = make_atom("a1")
    contract = VerificationContract(contract_id="v1", target_atom_ref="a1")
    intent = ActionIntent(intent_id="i1", proposed_capability="x", verification_requirement_refs=["v1"])
    draft = make_artifact(atoms=(atom,), verification_contracts=(contract,), action_intents=(intent,))
    compiled = compile_artifact(draft)
    value = compiled.action_intents[0].verification_requirement_refs
    assert isinstance(value, tuple)
    with pytest.raises(AttributeError):
        value.append("tamper")


def test_verification_contract_list_fields_become_immutable():
    from tests.ocl.conftest import make_atom
    atom = make_atom("a1")
    contract = VerificationContract(
        contract_id="v1", target_atom_ref="a1",
        required_evidence_kinds=["SOURCE_DOCUMENT"], pass_conditions=["c1"], fail_conditions=["c2"],
    )
    compiled = compile_artifact(make_artifact(atoms=(atom,), verification_contracts=(contract,)))
    vc = compiled.verification_contracts[0]
    assert isinstance(vc.required_evidence_kinds, tuple)
    assert isinstance(vc.pass_conditions, tuple)
    assert isinstance(vc.fail_conditions, tuple)


def test_escalation_request_list_fields_become_immutable():
    from tests.ocl.conftest import make_atom
    conflict = make_atom("c1", kind=__import__("orneur.intelligence.ocl.enums", fromlist=["AtomKind"]).AtomKind.CONFLICT)
    esc = EscalationRequest(escalation_id="e1", reason_categories=["reason"], triggering_atom_refs=["c1"])
    compiled = compile_artifact(make_artifact(atoms=(conflict,), escalation_requests=(esc,)))
    assert isinstance(compiled.escalation_requests[0].reason_categories, tuple)


def test_causal_hypothesis_list_field_becomes_immutable():
    from orneur.intelligence.ocl.causal import CausalHypothesis
    from tests.ocl.conftest import make_atom, make_evidence
    atoms = (make_atom("cause"), make_atom("effect"))
    ev = make_evidence("e1")
    hyp = CausalHypothesis(hypothesis_id="h1", cause_atom_ref="cause", mechanism="m", predicted_consequence_atom_ref="effect", observed_evidence_refs=["e1"])
    compiled = compile_artifact(make_artifact(atoms=atoms, evidence=(ev,), causal_hypotheses=(hyp,)))
    assert isinstance(compiled.causal_hypotheses[0].observed_evidence_refs, tuple)


def test_wire_created_and_programmatically_created_artifacts_canonicalize_identically():
    """Non-regression: wire-parsed (already-tuple) and programmatically-
    constructed (list-then-frozen) equivalent artifacts must produce the
    same digest."""
    from orneur.intelligence.ocl.canonical import parse_ocl_draft_json, to_canonical_json

    programmatic = compile_artifact(make_artifact(action_intents=(
        ActionIntent(intent_id="i1", proposed_capability="x", preconditions=["p1", "p2"]),
    )))
    wire_text = to_canonical_json(programmatic)
    from_wire = compile_artifact(parse_ocl_draft_json(wire_text))
    assert digest(programmatic) == digest(from_wire)


def test_source_list_mutation_after_compile_has_no_effect_on_digest():
    source_list = ["p1"]
    intent = ActionIntent(intent_id="i1", proposed_capability="x", preconditions=source_list)
    compiled = compile_artifact(make_artifact(action_intents=(intent,)))
    before = digest(compiled)
    source_list.append("tamper")
    assert digest(compiled) == before


# ── Programmatic compiler type validation (section 3) ────────────────────

def test_model_identity_family_wrong_type_rejected():
    draft = make_artifact(provenance=Provenance(
        producer_kind=ProducerKind.DETERMINISTIC_SYSTEM, producer_id="x",
        model_identity=ModelIdentityRef(family=[]),
    ))
    with pytest.raises(InvalidStructuredValue):
        compile_artifact(draft)


def test_model_identity_lifecycle_state_wrong_type_rejected():
    draft = make_artifact(provenance=Provenance(
        producer_kind=ProducerKind.DETERMINISTIC_SYSTEM, producer_id="x",
        model_identity=ModelIdentityRef(lifecycle_state=[]),
    ))
    with pytest.raises(InvalidStructuredValue):
        compile_artifact(draft)


def test_model_identity_generation_wrong_type_rejected():
    draft = make_artifact(provenance=Provenance(
        producer_kind=ProducerKind.DETERMINISTIC_SYSTEM, producer_id="x",
        model_identity=ModelIdentityRef(family="genesis", generation="not-an-int"),
    ))
    with pytest.raises(InvalidStructuredValue):
        compile_artifact(draft)


def test_provenance_producer_id_wrong_type_rejected():
    draft = make_artifact(provenance=Provenance(producer_kind=ProducerKind.DETERMINISTIC_SYSTEM, producer_id=42))
    with pytest.raises(InvalidStructuredValue):
        compile_artifact(draft)


def test_action_intent_proposed_capability_wrong_type_rejected():
    intent = ActionIntent(intent_id="i1", proposed_capability=42)
    with pytest.raises(InvalidStructuredValue):
        compile_artifact(make_artifact(action_intents=(intent,)))


def test_action_intent_precondition_element_wrong_type_rejected():
    intent = ActionIntent(intent_id="i1", proposed_capability="x", preconditions=[42])
    with pytest.raises(InvalidStructuredValue):
        compile_artifact(make_artifact(action_intents=(intent,)))


def test_verification_contract_pass_condition_wrong_type_rejected():
    from tests.ocl.conftest import make_atom
    atom = make_atom("a1")
    contract = VerificationContract(contract_id="v1", target_atom_ref="a1", pass_conditions=[42])
    with pytest.raises(InvalidStructuredValue):
        compile_artifact(make_artifact(atoms=(atom,), verification_contracts=(contract,)))


def test_escalation_request_reason_category_wrong_type_rejected():
    esc = EscalationRequest(escalation_id="e1", reason_categories=[42])
    with pytest.raises(InvalidStructuredValue):
        compile_artifact(make_artifact(escalation_requests=(esc,)))


def test_escalation_request_role_wrong_type_rejected():
    esc = EscalationRequest(escalation_id="e1", requested_cognitive_role=42)
    with pytest.raises(InvalidStructuredValue):
        compile_artifact(make_artifact(escalation_requests=(esc,)))


def test_evidence_anchor_issuer_wrong_type_rejected():
    ev = EvidenceAnchor(evidence_id="e1", evidence_kind=__import__("orneur.intelligence.ocl.enums", fromlist=["EvidenceKind"]).EvidenceKind.TOOL_OUTPUT, issuer=42, reference="y")
    with pytest.raises(InvalidStructuredValue):
        compile_artifact(make_artifact(evidence=(ev,)))


def test_causal_hypothesis_mechanism_wrong_type_rejected():
    from orneur.intelligence.ocl.causal import CausalHypothesis
    from tests.ocl.conftest import make_atom
    atoms = (make_atom("cause"), make_atom("effect"))
    hyp = CausalHypothesis(hypothesis_id="h1", cause_atom_ref="cause", mechanism=42, predicted_consequence_atom_ref="effect")
    with pytest.raises(InvalidStructuredValue):
        compile_artifact(make_artifact(atoms=atoms, causal_hypotheses=(hyp,)))


def test_no_raw_exception_types_escape_programmatic_malformed_dataclasses():
    cases = [
        make_artifact(provenance=Provenance(producer_kind=ProducerKind.DETERMINISTIC_SYSTEM, producer_id="x", model_identity=ModelIdentityRef(family=[]))),
        make_artifact(action_intents=(ActionIntent(intent_id="i1", proposed_capability=42),)),
        make_artifact(escalation_requests=(EscalationRequest(escalation_id="e1", reason_categories=[42]),)),
    ]
    for draft in cases:
        try:
            compile_artifact(draft)
        except InvalidStructuredValue:
            pass
        except InvalidProvenance:
            pass
        except (AttributeError, TypeError, KeyError) as exc:
            pytest.fail(f"raw Python exception {type(exc).__name__} escaped: {exc}")
