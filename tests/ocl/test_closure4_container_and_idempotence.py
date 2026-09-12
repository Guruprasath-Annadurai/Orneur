"""
Phase 17 FINAL container / transformation / compiler-idempotence closure.
Covers: (A) wrong top-level collection CONTAINER types (None/dict/int/str,
as distinct from wrong ELEMENT types inside a valid container, which the
prior closure already covers); (B) generator consumption -- a generator
must never be accepted as a draft sequence field, since one validator
iterating it during type-checking would silently exhaust it before a
later pass needs to iterate it again; (C) wrong top-level draft object
type; (D/E) AtomDisposition.disposition/justification_ref type safety
without raw exceptions; (F) compiler revalidation/idempotence --
compile_artifact(compile_artifact(draft)) must equal compile_artifact
(draft), which requires validate_structured_value to accept the
MappingProxyType a compiled artifact's metadata already is.

Every case here was reproduced live against unmodified 6629130 before
this fix landed: A/evidence=42/action_intents=42 raised a raw
TypeError: '<type>' object is not iterable; A/atoms={}/relations=""
silently "compiled" as an empty collection with NO error at all;
B raised TypeError: object of type 'generator' has no len() (the
generator was consumed once by an early per-element type-check loop,
then found exhausted by a later len() call); C raised AttributeError:
'<type>' object has no attribute 'atoms'; D raised TypeError: unhashable
type: 'list' from a frozenset membership check on an unvalidated value;
E1/E5 raised NO exception at all (a non-string and an unbounded-length
justification_ref were both silently accepted); F raised
InvalidStructuredValue: disallowed value type mappingproxy.
"""
from __future__ import annotations

import pytest

from orneur.intelligence.ocl.artifact import CognitiveArtifact
from orneur.intelligence.ocl.canonical import digest, to_canonical_json
from orneur.intelligence.ocl.compiler import compile_artifact
from orneur.intelligence.ocl.enums import ProducerKind
from orneur.intelligence.ocl.errors import ConservationViolation, InvalidObjectType, InvalidStructuredValue
from orneur.intelligence.ocl.provenance import Provenance
from orneur.intelligence.ocl.transformations import AtomDisposition
from orneur.intelligence.ocl.trust import CompilationTrustContext
from orneur.intelligence.ocl.version import CURRENT_SCHEMA_VERSION
from tests.ocl.conftest import make_artifact, make_atom, make_evidence

FIXED_TIME = "2026-01-01T00:00:00+00:00"


def _base_kwargs(**overrides):
    kwargs = dict(
        artifact_id="art-1", schema_version=CURRENT_SCHEMA_VERSION, request_id="req-1",
        provenance=Provenance(producer_kind=ProducerKind.NATIVE_MODEL, producer_id="genesis-1"),
        created_at=FIXED_TIME,
    )
    kwargs.update(overrides)
    return kwargs


# ── A: wrong collection CONTAINER type (not merely wrong element type) ────

@pytest.mark.parametrize("field,value", [
    ("atoms", None),
    ("atoms", {}),
    ("atoms", ""),
    ("relations", None),
    ("relations", {}),
    ("relations", ""),
    ("evidence", None),
    ("evidence", 42),
    ("evidence", {}),
    ("action_intents", 42),
    ("verification_contracts", {}),
    ("escalation_requests", ""),
    ("causal_hypotheses", None),
    ("counterfactual_branches", 42),
])
def test_wrong_collection_container_type_raises_typed_error_not_raw_typeerror(field, value):
    art = CognitiveArtifact(**_base_kwargs(**{field: value}))
    with pytest.raises(InvalidStructuredValue):
        compile_artifact(art)


def test_empty_dict_container_does_not_silently_compile_as_empty_collection():
    """An empty dict/string ITERATES to zero elements -- it must not be
    accepted as if it were an empty tuple/list; only list/tuple are valid
    sequence containers, regardless of emptiness."""
    art = CognitiveArtifact(**_base_kwargs(atoms={}))
    with pytest.raises(InvalidStructuredValue):
        compile_artifact(art)


def test_valid_list_and_tuple_containers_still_compile():
    compile_artifact(make_artifact(atoms=[make_atom("a1")]))
    compile_artifact(make_artifact(atoms=(make_atom("a1"),)))


# ── B: generator consumption ───────────────────────────────────────────────

def test_generator_is_rejected_as_a_draft_sequence_field():
    gen = (make_atom(f"a{i}") for i in range(3))
    art = CognitiveArtifact(**_base_kwargs(atoms=gen))
    with pytest.raises(InvalidStructuredValue):
        compile_artifact(art)


def test_set_is_rejected_as_a_draft_sequence_field():
    art = CognitiveArtifact(**_base_kwargs(atoms={"not-a-real-atom"}))
    with pytest.raises(InvalidStructuredValue):
        compile_artifact(art)


# ── C: wrong top-level draft object type ──────────────────────────────────

@pytest.mark.parametrize("bad_draft", [{}, "fake", 42, ["a"], None])
def test_wrong_top_level_draft_type_raises_typed_error_not_raw_attributeerror(bad_draft):
    with pytest.raises(InvalidObjectType):
        compile_artifact(bad_draft)


# ── D: AtomDisposition.disposition type safety ────────────────────────────

@pytest.mark.parametrize("bad_disposition", [[], 42, None, {"x": 1}])
def test_atom_disposition_wrong_type_raises_conservation_violation_not_raw_typeerror(bad_disposition):
    with pytest.raises(ConservationViolation):
        AtomDisposition(atom_id="a1", disposition=bad_disposition, justification_ref="reason")


def test_atom_disposition_valid_string_still_constructs():
    AtomDisposition(atom_id="a1", disposition="REMOVED", justification_ref="reason")


# ── E: AtomDisposition.justification_ref type safety ──────────────────────

@pytest.mark.parametrize("bad_ref", [42, None, [], {"x": 1}])
def test_atom_disposition_justification_ref_wrong_type_rejected(bad_ref):
    with pytest.raises(ConservationViolation):
        AtomDisposition(atom_id="a1", disposition="REMOVED", justification_ref=bad_ref)


def test_atom_disposition_justification_ref_empty_string_rejected():
    with pytest.raises(ConservationViolation):
        AtomDisposition(atom_id="a1", disposition="REMOVED", justification_ref="")


def test_atom_disposition_justification_ref_overlong_rejected():
    from orneur.intelligence.ocl import limits
    with pytest.raises(ConservationViolation):
        AtomDisposition(atom_id="a1", disposition="REMOVED", justification_ref="x" * (limits.MAX_STRING_FIELD_LENGTH + 1))


# ── F: compiler revalidation / idempotence ────────────────────────────────

def test_compile_of_compiled_artifact_is_idempotent():
    draft = make_artifact(atoms=(make_atom("a1", metadata={"k": "v", "nested": [1, 2, {"x": "y"}]}),))
    first = compile_artifact(draft)
    second = compile_artifact(first)
    assert second == first
    assert to_canonical_json(first) == to_canonical_json(second)
    assert digest(first) == digest(second)


def test_compile_of_compiled_artifact_idempotent_with_nested_frozen_metadata():
    draft = make_artifact(
        atoms=(make_atom("a1", metadata={"a": {"b": {"c": [1, 2, 3]}}}),),
        metadata={"top": ["x", {"y": 1}]},
    )
    first = compile_artifact(draft)
    second = compile_artifact(first)
    assert second == first
    assert digest(first) == digest(second)


def test_compile_of_compiled_privileged_artifact_requires_same_trust_context_resupplied():
    """Revalidation is NOT trust persistence -- the same rule as checkpoint
    restore. Recompiling a privileged artifact with the same explicit
    trust_context succeeds; recompiling with the default (weaker) context
    fails closed, exactly as it would for the original draft."""
    from orneur.intelligence.ocl.enums import AtomKind, EvidenceKind, SourceClass

    atom = make_atom(
        "a1", kind=AtomKind.OBSERVATION_REFERENCE,
        source_class=SourceClass.DETERMINISTIC_POLICY_REFERENCE, evidence_refs=("e1",),
    )
    ev = make_evidence("e1", kind=EvidenceKind.DETERMINISTIC_POLICY_FACT)
    draft = make_artifact(atoms=(atom,), evidence=(ev,))

    first = compile_artifact(draft, trust_context=CompilationTrustContext.TRUSTED_DETERMINISTIC_SYSTEM)
    second = compile_artifact(first, trust_context=CompilationTrustContext.TRUSTED_DETERMINISTIC_SYSTEM)
    assert second == first

    from orneur.intelligence.ocl.errors import EvidenceImpersonation
    with pytest.raises(EvidenceImpersonation):
        compile_artifact(first)  # default UNTRUSTED -- must fail closed, same as checkpoint restore


def test_compile_of_compiled_artifact_idempotent_across_all_collection_kinds():
    from orneur.intelligence.ocl.causal import CausalHypothesis
    from orneur.intelligence.ocl.graph import CognitiveRelation
    from orneur.intelligence.ocl.proposals import ActionIntent, EscalationRequest, VerificationContract
    from orneur.intelligence.ocl.enums import RelationKind

    a1, a2 = make_atom("a1"), make_atom("a2")
    rel = CognitiveRelation(relation_id="r1", kind=RelationKind.SUPPORTS, source_atom_id="a1", target_atom_id="a2")
    intent = ActionIntent(intent_id="i1", proposed_capability="cap", preconditions=("p1",))
    contract = VerificationContract(contract_id="c1", target_atom_ref="a1", pass_conditions=("x",))
    esc = EscalationRequest(escalation_id="e1", triggering_atom_refs=("a1",), reason_categories=("gap",))
    hyp = CausalHypothesis(hypothesis_id="h1", cause_atom_ref="a1", mechanism="m", predicted_consequence_atom_ref="a2")

    draft = make_artifact(
        atoms=(a1, a2), relations=(rel,), action_intents=(intent,),
        verification_contracts=(contract,), escalation_requests=(esc,), causal_hypotheses=(hyp,),
    )
    first = compile_artifact(draft)
    second = compile_artifact(first)
    assert second == first
    assert digest(first) == digest(second)
