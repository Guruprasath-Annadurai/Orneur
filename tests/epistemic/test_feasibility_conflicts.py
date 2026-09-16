"""
Closure: feasibility record duplicates/conflicts. Reproduced defect:
prior production code did `feasibility_by_atom[target_atom_id] = record`
in a plain loop -- the LAST input record for a given atom silently won,
making the result order-dependent (verified: [PENDING,
STRUCTURALLY_UNVERIFIABLE] -> UNVERIFIABLE, but
[STRUCTURALLY_UNVERIFIABLE, PENDING] -> UNCERTAIN, same input set).
Fixed: any second VerificationFeasibilityRecord for the same
target_atom_id -- identical or not -- fails closed with
ConflictingVerificationFeasibility.
"""
from __future__ import annotations

import pytest

from orneur.intelligence.epistemic import errors
from orneur.intelligence.epistemic.enums import VerificationFeasibility
from orneur.intelligence.epistemic.resolver import assess_artifact
from tests.epistemic.conftest import ASSESSED_AT, TRUSTED_OCL, TRUSTED_VERIFIER, make_artifact, make_atom, make_feasibility


def _assess(artifact, feasibility_records):
    return assess_artifact(
        artifact, ocl_trust_context=TRUSTED_OCL, assessment_context_id="ctx-1", assessed_at=ASSESSED_AT,
        feasibility_records=feasibility_records, resolution_trust_context=TRUSTED_VERIFIER,
    )


def test_exact_duplicate_feasibility_record_fails_closed():
    artifact = make_artifact(atoms=(make_atom(atom_id="a1"),))
    record = make_feasibility(target_atom_id="a1", feasibility=VerificationFeasibility.PENDING)
    with pytest.raises(errors.ConflictingVerificationFeasibility):
        _assess(artifact, (record, record))


def test_pending_and_structurally_unverifiable_for_same_atom_fails_closed():
    artifact = make_artifact(atoms=(make_atom(atom_id="a1"),))
    record_a = make_feasibility(target_atom_id="a1", feasibility=VerificationFeasibility.PENDING)
    record_b = make_feasibility(target_atom_id="a1", feasibility=VerificationFeasibility.STRUCTURALLY_UNVERIFIABLE)
    with pytest.raises(errors.ConflictingVerificationFeasibility):
        _assess(artifact, (record_a, record_b))


def test_temporarily_unavailable_and_available_for_same_atom_fails_closed():
    artifact = make_artifact(atoms=(make_atom(atom_id="a1"),))
    record_a = make_feasibility(target_atom_id="a1", feasibility=VerificationFeasibility.TEMPORARILY_UNAVAILABLE)
    record_b = make_feasibility(target_atom_id="a1", feasibility=VerificationFeasibility.AVAILABLE)
    with pytest.raises(errors.ConflictingVerificationFeasibility):
        _assess(artifact, (record_a, record_b))


def test_reversed_input_order_has_identical_failure_behavior():
    """No 'last record wins' -- both orderings of the same conflicting
    pair must fail identically."""
    artifact = make_artifact(atoms=(make_atom(atom_id="a1"),))
    record_a = make_feasibility(target_atom_id="a1", feasibility=VerificationFeasibility.PENDING)
    record_b = make_feasibility(target_atom_id="a1", feasibility=VerificationFeasibility.STRUCTURALLY_UNVERIFIABLE)

    with pytest.raises(errors.ConflictingVerificationFeasibility):
        _assess(artifact, (record_a, record_b))
    with pytest.raises(errors.ConflictingVerificationFeasibility):
        _assess(artifact, (record_b, record_a))


def test_single_feasibility_record_per_atom_still_works_normally():
    artifact = make_artifact(atoms=(make_atom(atom_id="a1"),))
    record = make_feasibility(target_atom_id="a1", feasibility=VerificationFeasibility.STRUCTURALLY_UNVERIFIABLE)
    overlay = _assess(artifact, (record,))
    assert len(overlay.assessments) == 1


def test_feasibility_records_for_different_atoms_do_not_conflict():
    artifact = make_artifact(atoms=(make_atom(atom_id="a1"), make_atom(atom_id="a2")))
    record_a = make_feasibility(target_atom_id="a1", feasibility=VerificationFeasibility.PENDING)
    record_b = make_feasibility(target_atom_id="a2", feasibility=VerificationFeasibility.STRUCTURALLY_UNVERIFIABLE)
    overlay = _assess(artifact, (record_a, record_b))  # must not raise
    assert len(overlay.assessments) == 2


def test_assessment_context_digest_is_order_independent_for_feasibility_and_evidence():
    """Beyond the fail-closed conflict rule: for two DIFFERENT atoms
    (no conflict), the assessment-context canonicalization itself must
    not depend on input order."""
    from orneur.intelligence.epistemic.canonical import digest

    artifact = make_artifact(atoms=(make_atom(atom_id="a1"), make_atom(atom_id="a2")))
    record_a = make_feasibility(target_atom_id="a1", feasibility=VerificationFeasibility.PENDING)
    record_b = make_feasibility(target_atom_id="a2", feasibility=VerificationFeasibility.STRUCTURALLY_UNVERIFIABLE)

    overlay_ab = _assess(artifact, (record_a, record_b))
    overlay_ba = _assess(artifact, (record_b, record_a))
    assert digest(overlay_ab) == digest(overlay_ba)
