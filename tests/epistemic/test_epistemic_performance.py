"""
Section 40: prove no accidental quadratic/exponential behavior, not a
fragile millisecond SLA. A 1,000-atom chain (worst case for a naive
repeated-full-pass propagation, trivial for the worklist BFS actually
used) must complete comfortably inside a generous ceiling.
"""
from __future__ import annotations

import time

from orneur.intelligence.epistemic.enums import EvidenceResolutionStatus, EvidenceStance
from orneur.intelligence.epistemic.resolver import assess_artifact
from orneur.intelligence.ocl.enums import RelationKind
from tests.epistemic.conftest import ASSESSED_AT, TRUSTED_OCL, TRUSTED_VERIFIER, make_artifact, make_atom, make_evidence, make_relation, make_resolved_evidence

N = 1000


def test_thousand_atom_chain_assessment_completes_without_quadratic_blowup():
    atoms = [make_atom(atom_id="a0", evidence_refs=("e0",))]
    relations = []
    for i in range(1, N):
        atoms.append(make_atom(atom_id=f"a{i}"))
        relations.append(make_relation(relation_id=f"r{i}", kind=RelationKind.SUPPORTS, source=f"a{i - 1}", target=f"a{i}"))

    artifact = make_artifact(atoms=tuple(atoms), relations=tuple(relations), evidence=(make_evidence(evidence_id="e0"),))

    start = time.monotonic()
    overlay = assess_artifact(
        artifact,
        ocl_trust_context=TRUSTED_OCL,
        resolved_evidence=(make_resolved_evidence(evidence_id="e0", target_atom_id="a0", status=EvidenceResolutionStatus.VERIFIED, stance=EvidenceStance.SUPPORTS),),
        resolution_trust_context=TRUSTED_VERIFIER,
        assessment_context_id="ctx-perf",
        assessed_at=ASSESSED_AT,
    )
    elapsed = time.monotonic() - start

    assert len(overlay.assessments) == N
    last = next(a for a in overlay.assessments if a.atom_id == f"a{N - 1}")
    from orneur.intelligence.epistemic.enums import EpistemicState

    assert last.state is EpistemicState.INFERRED
    # Generous ceiling -- this is a no-quadratic-blowup guard, not an SLA.
    assert elapsed < 10.0, f"1000-atom chain assessment took {elapsed:.2f}s -- investigate for quadratic behavior"
    print(f"[epistemic-perf] n_atoms={N} elapsed={elapsed:.4f}s")
