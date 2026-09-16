"""
Closure: strict field-type validation for ResolvedEvidence and
VerificationFeasibilityRecord. Before this closure, a bare string like
status="VERIFIED" (instead of the real EvidenceResolutionStatus.VERIFIED
enum member) did not raise -- it silently fell through resolver logic
(every `is EvidenceResolutionStatus.X` comparison is False for a plain
string) and was misclassified as EVIDENCE_INCONCLUSIVE rather than
rejected outright. Fixed: every ResolvedEvidence/
VerificationFeasibilityRecord field is validated by
resolver._validate_and_normalize_resolved_evidence()/
_validate_and_normalize_feasibility_record() before any semantic use,
raising a typed errors.EpistemicError subclass -- never a raw
AttributeError/TypeError/KeyError.
"""
from __future__ import annotations

import dataclasses

import pytest

from orneur.intelligence.epistemic import errors
from orneur.intelligence.epistemic.enums import EvidenceResolutionStatus, EvidenceStance, VerificationFeasibility
from orneur.intelligence.epistemic.models import ResolvedEvidence, VerificationFeasibilityRecord
from orneur.intelligence.epistemic.resolver import assess_artifact
from tests.epistemic.conftest import ASSESSED_AT, TRUSTED_OCL, TRUSTED_VERIFIER, make_artifact, make_atom, make_evidence, make_feasibility, make_resolved_evidence


def _assess_with_evidence(artifact, resolved_evidence):
    return assess_artifact(
        artifact, ocl_trust_context=TRUSTED_OCL, assessment_context_id="ctx-1", assessed_at=ASSESSED_AT,
        resolved_evidence=resolved_evidence, resolution_trust_context=TRUSTED_VERIFIER,
    )


def _assess_with_feasibility(artifact, feasibility_records):
    return assess_artifact(
        artifact, ocl_trust_context=TRUSTED_OCL, assessment_context_id="ctx-1", assessed_at=ASSESSED_AT,
        feasibility_records=feasibility_records, resolution_trust_context=TRUSTED_VERIFIER,
    )


BASE_ARTIFACT_KW = dict(atoms=(make_atom(atom_id="a1", evidence_refs=("e1",)),), evidence=(make_evidence(evidence_id="e1"),))


@pytest.mark.parametrize("bad_status", ["VERIFIED", None, 1, True, EvidenceStance.SUPPORTS])
def test_malformed_evidence_resolution_status_is_rejected(bad_status):
    artifact = make_artifact(**BASE_ARTIFACT_KW)
    good = make_resolved_evidence(evidence_id="e1", target_atom_id="a1")
    bad = dataclasses.replace(good, status=bad_status)
    with pytest.raises(errors.EpistemicError):
        _assess_with_evidence(artifact, (bad,))


@pytest.mark.parametrize("bad_stance", ["SUPPORTS", None, 1, True, EvidenceResolutionStatus.VERIFIED])
def test_malformed_evidence_stance_is_rejected(bad_stance):
    artifact = make_artifact(**BASE_ARTIFACT_KW)
    good = make_resolved_evidence(evidence_id="e1", target_atom_id="a1")
    bad = dataclasses.replace(good, stance=bad_stance)
    with pytest.raises(errors.EpistemicError):
        _assess_with_evidence(artifact, (bad,))


@pytest.mark.parametrize("bad_feasibility", ["PENDING", None, 1, True, EvidenceStance.SUPPORTS])
def test_malformed_verification_feasibility_is_rejected(bad_feasibility):
    artifact = make_artifact(atoms=(make_atom(atom_id="a1"),))
    good = make_feasibility(target_atom_id="a1")
    bad = dataclasses.replace(good, feasibility=bad_feasibility)
    with pytest.raises(errors.EpistemicError):
        _assess_with_feasibility(artifact, (bad,))


@pytest.mark.parametrize("field", ["evidence_id", "target_atom_id", "resolver_reference"])
@pytest.mark.parametrize("bad_value", [None, 1, True, object()])
def test_malformed_resolved_evidence_string_fields_are_rejected(field, bad_value):
    artifact = make_artifact(**BASE_ARTIFACT_KW)
    good = make_resolved_evidence(evidence_id="e1", target_atom_id="a1")
    bad = dataclasses.replace(good, **{field: bad_value})
    with pytest.raises(errors.EpistemicError):
        _assess_with_evidence(artifact, (bad,))


def test_malformed_resolved_at_timestamp_is_rejected():
    artifact = make_artifact(**BASE_ARTIFACT_KW)
    good = make_resolved_evidence(evidence_id="e1", target_atom_id="a1")
    bad = dataclasses.replace(good, resolved_at="not-a-timestamp")
    with pytest.raises(errors.InvalidStructuredValue):
        _assess_with_evidence(artifact, (bad,))


def test_malformed_recorded_at_timestamp_is_rejected():
    artifact = make_artifact(atoms=(make_atom(atom_id="a1"),))
    good = make_feasibility(target_atom_id="a1")
    bad = dataclasses.replace(good, recorded_at="not-a-timestamp")
    with pytest.raises(errors.InvalidStructuredValue):
        _assess_with_feasibility(artifact, (bad,))


def test_malformed_verifier_reference_type_is_rejected():
    artifact = make_artifact(atoms=(make_atom(atom_id="a1"),))
    good = make_feasibility(target_atom_id="a1")
    bad = dataclasses.replace(good, verifier_reference=12345)
    with pytest.raises(errors.EpistemicError):
        _assess_with_feasibility(artifact, (bad,))


def test_no_raw_exception_types_ever_escape_malformed_input():
    """None of the above may surface as AttributeError/TypeError/KeyError
    -- only typed errors.EpistemicError subclasses."""
    artifact = make_artifact(**BASE_ARTIFACT_KW)
    good = make_resolved_evidence(evidence_id="e1", target_atom_id="a1")
    bad = dataclasses.replace(good, status="VERIFIED")
    try:
        _assess_with_evidence(artifact, (bad,))
        assert False, "expected an exception"
    except errors.EpistemicError:
        pass
    except (AttributeError, TypeError, KeyError) as exc:
        pytest.fail(f"a raw {type(exc).__name__} escaped instead of a typed EpistemicError: {exc}")


def test_wrong_dataclass_type_where_verificationfeasibilityrecord_expected_is_rejected():
    artifact = make_artifact(atoms=(make_atom(atom_id="a1"),))
    fake = ResolvedEvidence(
        evidence_id="e1", target_atom_id="a1", status=EvidenceResolutionStatus.VERIFIED,
        stance=EvidenceStance.SUPPORTS, resolver_reference="r", resolved_at=ASSESSED_AT,
    )
    with pytest.raises(errors.EpistemicError):
        _assess_with_feasibility(artifact, (fake,))
