from __future__ import annotations

from orneur.intelligence.ocl.causal import CausalHypothesis, CounterfactualBranch
from orneur.intelligence.ocl.compiler import compile_artifact
from orneur.intelligence.ocl.enums import AtomKind, RelationKind
from tests.ocl.conftest import make_artifact, make_atom, make_relation


def test_causal_hypothesis_and_correlation_relation_are_structurally_distinct():
    """CAUSES and CORRELATES_WITH must remain distinguishable relation
    kinds -- a model emitting a causal edge never upgrades correlation to
    causation just by choosing the CAUSES enum value; it remains a
    hypothesis (see docstring in causal.py) unless externally established."""
    atoms = (
        make_atom("cause", kind=AtomKind.OBSERVATION_REFERENCE),
        make_atom("effect", kind=AtomKind.OBSERVATION_REFERENCE),
    )
    causal_rel = make_relation("r1", RelationKind.CAUSES, "cause", "effect")
    correlated_rel = make_relation("r2", RelationKind.CORRELATES_WITH, "cause", "effect")
    assert causal_rel.kind != correlated_rel.kind
    compile_artifact(make_artifact(atoms=atoms, relations=(causal_rel,)))
    compile_artifact(make_artifact(atoms=atoms, relations=(correlated_rel,)))


def test_causal_hypothesis_object_references_cause_mechanism_and_prediction():
    hyp = CausalHypothesis(
        hypothesis_id="h1", cause_atom_ref="cause", mechanism="X depletes Y",
        predicted_consequence_atom_ref="effect", observable_test_ref="test-1",
    )
    assert hyp.cause_atom_ref == "cause"
    assert hyp.observed_evidence_refs == ()


def test_counterfactual_branch_references_a_causal_hypothesis():
    branch = CounterfactualBranch(
        branch_id="b1", causal_hypothesis_ref="h1", condition_atom_ref="cond1", predicted_atom_ref="pred1",
    )
    assert branch.causal_hypothesis_ref == "h1"
