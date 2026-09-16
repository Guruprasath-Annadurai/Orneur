"""
Section 42: structural complexity guard (no quadratic/exponential
blowup), not a fragile wall-clock SLA. Also covers the
require_integrity() convenience API (section 40).
"""
from __future__ import annotations

import time

import pytest

from orneur.intelligence.epistemic.enums import EpistemicPolarity, EvidenceResolutionStatus, EvidenceStance
from orneur.intelligence.epistemic.resolver import assess_artifact
from orneur.intelligence.integrity import errors
from orneur.intelligence.integrity.contracts import IntegrityProposal, ProposedAssertion
from orneur.intelligence.integrity.enums import IntegrityStatus, PresentationTreatment
from tests.integrity.conftest import assess_integrity_trusted as assess_integrity, require_integrity_trusted as require_integrity, ASSESSED_AT, TRUSTED_OCL, TRUSTED_VERIFIER, build_known_affirmed_fixture, make_artifact, make_atom, make_evidence, make_resolved_evidence

N = 500


def test_many_assertions_completes_without_quadratic_blowup():
    atoms = tuple(make_atom(atom_id=f"a{i}", evidence_refs=(f"e{i}",)) for i in range(N))
    evidence = tuple(make_evidence(evidence_id=f"e{i}") for i in range(N))
    artifact = make_artifact(atoms=atoms, evidence=evidence)

    from orneur.intelligence.ocl.compiler import compile_artifact

    compiled = compile_artifact(artifact, trust_context=TRUSTED_OCL)
    resolved = tuple(
        make_resolved_evidence(evidence_id=f"e{i}", target_atom_id=f"a{i}", status=EvidenceResolutionStatus.VERIFIED, stance=EvidenceStance.SUPPORTS)
        for i in range(N)
    )
    overlay = assess_artifact(
        compiled, ocl_trust_context=TRUSTED_OCL, assessment_context_id="ctx-perf", assessed_at=ASSESSED_AT,
        resolved_evidence=resolved, resolution_trust_context=TRUSTED_VERIFIER,
    )
    assertions = tuple(
        ProposedAssertion(f"as{i}", f"a{i}", PresentationTreatment.ESTABLISHED, EpistemicPolarity.AFFIRMED)
        for i in range(N)
    )
    proposal = IntegrityProposal(proposal_id="p1", assertions=assertions)

    start = time.monotonic()
    receipt = assess_integrity(proposal, overlay=overlay, artifact=compiled)
    elapsed = time.monotonic() - start

    assert len(receipt.assertion_assessments) == N
    assert receipt.integrity_status is IntegrityStatus.SATISFIED
    assert elapsed < 10.0, f"{N}-assertion evaluation took {elapsed:.2f}s -- investigate for quadratic behavior"
    print(f"[integrity-perf] n_assertions={N} elapsed={elapsed:.4f}s")


def test_require_integrity_raises_on_unsatisfied_receipt():
    artifact, overlay = build_known_affirmed_fixture()
    proposal = IntegrityProposal(proposal_id="p1", assertions=(ProposedAssertion("as1", "a1", PresentationTreatment.ESTABLISHED, EpistemicPolarity.REFUTED),))
    with pytest.raises(errors.IntegrityRequirementNotSatisfied):
        require_integrity(proposal, overlay=overlay, artifact=artifact)


def test_require_integrity_returns_receipt_when_satisfied():
    artifact, overlay = build_known_affirmed_fixture()
    proposal = IntegrityProposal(proposal_id="p1", assertions=(ProposedAssertion("as1", "a1", PresentationTreatment.ESTABLISHED, EpistemicPolarity.AFFIRMED),))
    receipt = require_integrity(proposal, overlay=overlay, artifact=artifact)
    assert receipt.integrity_status is IntegrityStatus.SATISFIED
