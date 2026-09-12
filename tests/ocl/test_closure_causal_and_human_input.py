"""
Phase 17 final closure sections 6 and 9: observable_test_ref must resolve
to a real TEST_PROPOSAL atom, and HUMAN_INPUT/ProducerKind.HUMAN must
never mean human/owner approval, policy authorization, Court approval, or
Production Proof.
"""
from __future__ import annotations

import pytest

from orneur.intelligence.ocl.causal import CausalHypothesis
from orneur.intelligence.ocl.compiler import compile_artifact
from orneur.intelligence.ocl.enums import AtomKind, ProducerKind, SourceClass
from orneur.intelligence.ocl.errors import DanglingRelation, EvidenceImpersonation, ForbiddenAuthorityConstruct, InvalidRelationShape
from orneur.intelligence.ocl.provenance import Provenance
from tests.ocl.conftest import make_artifact, make_atom


def _hyp(**kw):
    base = dict(hypothesis_id="h1", cause_atom_ref="cause", mechanism="m", predicted_consequence_atom_ref="effect")
    base.update(kw)
    return CausalHypothesis(**base)


def test_observable_test_ref_missing_atom_rejected():
    atoms = (make_atom("cause"), make_atom("effect"))
    hyp = _hyp(observable_test_ref="missing")
    with pytest.raises(DanglingRelation):
        compile_artifact(make_artifact(atoms=atoms, causal_hypotheses=(hyp,)))


def test_observable_test_ref_to_wrong_atom_kind_rejected():
    atoms = (make_atom("cause"), make_atom("effect"), make_atom("test1", kind=AtomKind.ASSERTION))
    hyp = _hyp(observable_test_ref="test1")
    with pytest.raises(InvalidRelationShape):
        compile_artifact(make_artifact(atoms=atoms, causal_hypotheses=(hyp,)))


def test_observable_test_ref_to_test_proposal_atom_accepted():
    atoms = (make_atom("cause"), make_atom("effect"), make_atom("test1", kind=AtomKind.TEST_PROPOSAL))
    hyp = _hyp(observable_test_ref="test1")
    compile_artifact(make_artifact(atoms=atoms, causal_hypotheses=(hyp,)))


def test_observable_test_ref_none_is_valid():
    atoms = (make_atom("cause"), make_atom("effect"))
    hyp = _hyp(observable_test_ref=None)
    compile_artifact(make_artifact(atoms=atoms, causal_hypotheses=(hyp,)))


# ── HUMAN_INPUT is provenance, never approval (section 6) ────────────────

def test_human_input_atom_of_any_kind_compiles_without_needing_evidence_refs():
    """A human may honestly label ANY atom kind as HUMAN_INPUT -- it is not
    in PRIVILEGED_REFERENCE_SOURCE_CLASSES and needs no OBSERVATION_REFERENCE
    kind or evidence_refs to be accepted."""
    atom = make_atom("a1", kind=AtomKind.HYPOTHESIS, source_class=SourceClass.HUMAN_INPUT, content="I think X caused Y")
    compile_artifact(make_artifact(atoms=(atom,)))


def test_human_input_cannot_grant_authority_via_metadata():
    atom = make_atom("a1", source_class=SourceClass.HUMAN_INPUT, metadata={"human_approved": True})
    with pytest.raises(ForbiddenAuthorityConstruct):
        compile_artifact(make_artifact(atoms=(atom,)))


def test_producer_kind_human_cannot_unlock_privileged_evidence_either():
    """Even ProducerKind.HUMAN gets no special trust -- the same
    trust_context gate applies regardless of who the artifact claims to be
    from."""
    from tests.ocl.conftest import make_evidence

    ev = make_evidence("e1")
    atom = make_atom(
        "a1", kind=AtomKind.OBSERVATION_REFERENCE, source_class=SourceClass.MEASURED_EVIDENCE_REFERENCE,
        evidence_refs=("e1",),
    )
    human_provenance = Provenance(producer_kind=ProducerKind.HUMAN, producer_id="a-person")
    with pytest.raises(EvidenceImpersonation):
        compile_artifact(make_artifact(atoms=(atom,), evidence=(ev,), provenance=human_provenance))


def test_human_input_atom_cannot_satisfy_court_or_production_proof_evidence_kinds():
    """A HUMAN_INPUT atom citing an EvidenceAnchor of kind COURT_DECISION/
    PRODUCTION_PROOF still cannot claim a privileged source_class -- OCL
    has no code path where HUMAN_INPUT elevates to
    PRIVILEGED_REFERENCE_SOURCE_CLASSES at all, by construction (it is not
    a member of that set)."""
    from orneur.intelligence.ocl.enums import PRIVILEGED_REFERENCE_SOURCE_CLASSES

    assert SourceClass.HUMAN_INPUT not in PRIVILEGED_REFERENCE_SOURCE_CLASSES
