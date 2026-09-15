from __future__ import annotations

from orneur.intelligence.epistemic.canonical import digest, to_canonical_json
from orneur.intelligence.epistemic.enums import EvidenceResolutionStatus, EvidenceStance
from orneur.intelligence.epistemic.resolver import assess_artifact
from orneur.intelligence.ocl.enums import RelationKind
from tests.epistemic.conftest import ASSESSED_AT, TRUSTED_OCL, TRUSTED_VERIFIER, make_artifact, make_atom, make_evidence, make_relation, make_resolved_evidence


def _build_overlay(atom_order, relation_order, evidence_order):
    atoms = tuple(make_atom(atom_id=aid, evidence_refs=("e1",) if aid == "a" else ()) for aid in atom_order)
    relations = tuple(make_relation(relation_id=rid, kind=RelationKind.SUPPORTS, source="a", target="b") for rid in relation_order)
    evidence = tuple(make_evidence(evidence_id=eid) for eid in evidence_order)
    artifact = make_artifact(atoms=atoms, relations=relations, evidence=evidence)
    return assess_artifact(
        artifact,
        ocl_trust_context=TRUSTED_OCL,
        resolved_evidence=(make_resolved_evidence(evidence_id="e1", target_atom_id="a", status=EvidenceResolutionStatus.VERIFIED, stance=EvidenceStance.SUPPORTS),),
        resolution_trust_context=TRUSTED_VERIFIER,
        assessment_context_id="ctx-1",
        assessed_at=ASSESSED_AT,
        overlay_id="overlay-fixed",
    )


def test_same_input_same_output_digest():
    overlay1 = _build_overlay(("a", "b"), ("r1",), ("e1",))
    overlay2 = _build_overlay(("a", "b"), ("r1",), ("e1",))
    assert digest(overlay1) == digest(overlay2)
    assert to_canonical_json(overlay1) == to_canonical_json(overlay2)


def test_permuted_atom_order_yields_same_digest():
    overlay1 = _build_overlay(("a", "b"), ("r1",), ("e1",))
    overlay2 = _build_overlay(("b", "a"), ("r1",), ("e1",))
    assert digest(overlay1) == digest(overlay2)


def test_canonical_json_is_deterministic_string():
    overlay = _build_overlay(("a", "b"), ("r1",), ("e1",))
    text1 = to_canonical_json(overlay)
    text2 = to_canonical_json(overlay)
    assert text1 == text2
    assert isinstance(text1, str)


def test_digest_changes_when_content_changes():
    overlay1 = _build_overlay(("a", "b"), ("r1",), ("e1",))
    # Different assessment_context_id changes the context digest, which
    # in turn changes what evidence was considered -- but here we just
    # directly compare against an overlay built with an extra unrelated
    # atom in the graph to show non-identical content changes the digest.
    atoms = (make_atom(atom_id="a", evidence_refs=("e1",)), make_atom(atom_id="b"), make_atom(atom_id="c"))
    artifact = make_artifact(atoms=atoms, evidence=(make_evidence(evidence_id="e1"),))
    overlay2 = assess_artifact(
        artifact,
        ocl_trust_context=TRUSTED_OCL,
        resolved_evidence=(make_resolved_evidence(evidence_id="e1", target_atom_id="a", status=EvidenceResolutionStatus.VERIFIED, stance=EvidenceStance.SUPPORTS),),
        resolution_trust_context=TRUSTED_VERIFIER,
        assessment_context_id="ctx-1",
        assessed_at=ASSESSED_AT,
        overlay_id="overlay-fixed",
    )
    assert digest(overlay1) != digest(overlay2)


def test_no_nan_or_infinity_in_canonical_json():
    overlay = _build_overlay(("a", "b"), ("r1",), ("e1",))
    text = to_canonical_json(overlay)
    assert "NaN" not in text
    assert "Infinity" not in text


def test_canonicalize_is_idempotent():
    from orneur.intelligence.epistemic.canonical import canonicalize

    overlay = _build_overlay(("a", "b"), ("r1",), ("e1",))
    once = canonicalize(overlay)
    twice = canonicalize(once)
    assert once == twice
    assert digest(once) == digest(twice)
