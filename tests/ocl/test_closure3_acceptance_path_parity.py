"""
Phase 17 type-parity closure section 6: the OCL ACCEPTANCE-PATH PARITY
INVARIANT. For every valid programmatically constructed OCL draft:

    compile_artifact(programmatic_draft, trust_context=X)
    to_canonical_json(compiled)
    parse_ocl_draft_json(json)
    compile_artifact(parsed, trust_context=X)

must produce a semantically equal artifact. This proves direct Python
construction and strict JSON construction implement ONE schema, not two
subtly different ones -- the exact property the rest of this closure's
fixes (namespace/evidence-kind/provenance/collection-element type
validation, metadata root-mapping enforcement) exist to guarantee.
"""
from __future__ import annotations

from orneur.intelligence.ocl.canonical import compile_ocl_json, parse_ocl_draft_json, to_canonical_json
from orneur.intelligence.ocl.causal import CausalHypothesis
from orneur.intelligence.ocl.compiler import compile_artifact
from orneur.intelligence.ocl.enums import AtomKind, EvidenceKind, RelationKind, SourceClass
from orneur.intelligence.ocl.graph import CognitiveRelation
from orneur.intelligence.ocl.proposals import ActionIntent, EscalationRequest, VerificationContract
from orneur.intelligence.ocl.trust import CompilationTrustContext
from tests.ocl.conftest import make_artifact, make_atom, make_evidence


def _round_trip(draft, *, trust_context=None):
    kwargs = {} if trust_context is None else {"trust_context": trust_context}
    compiled = compile_artifact(draft, **kwargs)
    wire_json = to_canonical_json(compiled)
    reparsed_draft = parse_ocl_draft_json(wire_json)
    recompiled = compile_artifact(reparsed_draft, **kwargs)
    assert compiled == recompiled
    assert to_canonical_json(compiled) == to_canonical_json(recompiled)
    return compiled, recompiled


def test_parity_atoms_and_relations():
    a1, a2 = make_atom("a1"), make_atom("a2")
    rel = CognitiveRelation(relation_id="r1", kind=RelationKind.SUPPORTS, source_atom_id="a1", target_atom_id="a2")
    _round_trip(make_artifact(atoms=(a1, a2), relations=(rel,)))


def test_parity_evidence():
    atom = make_atom("a1", kind=AtomKind.OBSERVATION_REFERENCE, source_class=SourceClass.MEASURED_EVIDENCE_REFERENCE, evidence_refs=("e1",))
    ev = make_evidence("e1", kind=EvidenceKind.MEASURED_SYSTEM_DATA)
    _round_trip(make_artifact(atoms=(atom,), evidence=(ev,)), trust_context=CompilationTrustContext.TRUSTED_TOOL_ADAPTER)


def test_parity_action_intent():
    intent = ActionIntent(
        intent_id="i1", proposed_capability="cap.x", preconditions=("p1",), risk_hints=("r1",),
        arguments_summary={"a": [1, 2, {"b": "c"}]},
    )
    _round_trip(make_artifact(action_intents=(intent,)))


def test_parity_verification_contract():
    atom = make_atom("a1")
    contract = VerificationContract(
        contract_id="c1", target_atom_ref="a1", required_evidence_kinds=("MEASURED_SYSTEM_DATA",),
        pass_conditions=("x",), fail_conditions=("y",),
    )
    _round_trip(make_artifact(atoms=(atom,), verification_contracts=(contract,)))


def test_parity_escalation_request():
    atom = make_atom("a1")
    esc = EscalationRequest(escalation_id="esc1", triggering_atom_refs=("a1",), reason_categories=("gap",))
    _round_trip(make_artifact(atoms=(atom,), escalation_requests=(esc,)))


def test_parity_causal_structures():
    cause = make_atom("a1")
    effect = make_atom("a2")
    hyp = CausalHypothesis(hypothesis_id="h1", cause_atom_ref="a1", mechanism="m", predicted_consequence_atom_ref="a2")
    _round_trip(make_artifact(atoms=(cause, effect), causal_hypotheses=(hyp,)))


def test_parity_metadata_with_nested_arrays_and_maps():
    atom = make_atom("a1", metadata={"list": [1, "two", {"nested": [True, None]}]})
    _round_trip(make_artifact(atoms=(atom,), metadata={"top": {"deep": [1, 2, 3]}}))


def test_parity_trusted_privileged_evidence_with_resupplied_trust_context():
    atom = make_atom(
        "a1", kind=AtomKind.OBSERVATION_REFERENCE,
        source_class=SourceClass.DETERMINISTIC_POLICY_REFERENCE, evidence_refs=("e1",),
    )
    ev = make_evidence("e1", kind=EvidenceKind.DETERMINISTIC_POLICY_FACT)
    _round_trip(
        make_artifact(atoms=(atom,), evidence=(ev,)),
        trust_context=CompilationTrustContext.TRUSTED_DETERMINISTIC_SYSTEM,
    )


def test_parity_via_compile_ocl_json_public_entry_point_matches_programmatic_untrusted():
    """compile_ocl_json() is the wire path's own safe entry point (parse +
    compile hardcoded UNTRUSTED) -- it must produce an artifact identical
    to programmatic compile_artifact() with the default UNTRUSTED context
    for an equivalent draft."""
    atom = make_atom("a1")
    programmatic = compile_artifact(make_artifact(atoms=(atom,)))
    wire_json = to_canonical_json(programmatic)
    via_public_entry = compile_ocl_json(wire_json)
    assert programmatic == via_public_entry
