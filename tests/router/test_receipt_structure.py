"""
Phase 20 ROLE/STRUCTURE closure (spec sections 8-19): comprehensive
IntegrityReceipt structural pre-validation. A malformed receipt must
never reach integrity_canonical.digest() -- every adversarial case here
must fail with a typed RouterError, never a raw AttributeError/
TypeError/KeyError/ValueError.
"""
from __future__ import annotations

import dataclasses

import pytest

from orneur.intelligence.epistemic import canonical as epistemic_canonical
from orneur.intelligence.integrity.contracts import DisclosureRequirement, IntegrityViolation
from orneur.intelligence.integrity.enums import IntegrityObligation, IntegrityViolationReason
from orneur.intelligence.router import CognitiveTaskProfile, IntegrityReceiptTrustContext, errors as router_errors
from orneur.intelligence.router.evaluator import route_task
from tests.router.conftest import TRUSTED_PHASE18_RUNTIME, build_known_affirmed_fixture, make_real_integrity_receipt


def _route_with_receipt(overlay, artifact, receipt, *, expected_digest="some-digest-that-is-a-non-empty-string"):
    task = CognitiveTaskProfile(task_id="t")
    return route_task(
        task, overlay=overlay, artifact=artifact,
        overlay_trust_context=TRUSTED_PHASE18_RUNTIME, expected_overlay_digest=epistemic_canonical.digest(overlay),
        integrity_receipt=receipt, integrity_receipt_trust_context=IntegrityReceiptTrustContext.TRUSTED_PHASE19_RUNTIME,
        expected_integrity_receipt_digest=expected_digest,
    )


@pytest.fixture()
def satisfied_receipt():
    compiled, overlay = build_known_affirmed_fixture(atom_id="a1")
    receipt = make_real_integrity_receipt(overlay=overlay, artifact=compiled, atom_id="a1", satisfied=True)
    return compiled, overlay, receipt


@pytest.fixture()
def receipt_with_violation():
    compiled, overlay = build_known_affirmed_fixture(atom_id="a1")
    receipt = make_real_integrity_receipt(overlay=overlay, artifact=compiled, atom_id="a1", satisfied=False)
    return compiled, overlay, receipt


def test_malformed_assertion_assessments_entry_rejected(satisfied_receipt):
    compiled, overlay, receipt = satisfied_receipt
    malformed = dataclasses.replace(receipt, assertion_assessments=(object(),))
    with pytest.raises(router_errors.RouterError):
        _route_with_receipt(overlay, compiled, malformed)


def test_malformed_required_disclosures_entry_rejected(satisfied_receipt):
    compiled, overlay, receipt = satisfied_receipt
    malformed = dataclasses.replace(receipt, required_disclosures=(object(),))
    with pytest.raises(router_errors.RouterError):
        _route_with_receipt(overlay, compiled, malformed)


def test_malformed_violations_entry_rejected(satisfied_receipt):
    compiled, overlay, receipt = satisfied_receipt
    malformed = dataclasses.replace(receipt, violations=(object(),))
    with pytest.raises(router_errors.RouterError):
        _route_with_receipt(overlay, compiled, malformed)


def test_assertion_assessment_bare_string_epistemic_state_rejected(satisfied_receipt):
    compiled, overlay, receipt = satisfied_receipt
    bad_assessment = dataclasses.replace(receipt.assertion_assessments[0], epistemic_state="KNOWN")  # type: ignore[arg-type]
    malformed = dataclasses.replace(receipt, assertion_assessments=(bad_assessment,))
    with pytest.raises(router_errors.InvalidObjectType):
        _route_with_receipt(overlay, compiled, malformed)


def test_assertion_assessment_bare_string_proposed_treatment_rejected(satisfied_receipt):
    compiled, overlay, receipt = satisfied_receipt
    bad_assessment = dataclasses.replace(receipt.assertion_assessments[0], proposed_treatment="ESTABLISHED")  # type: ignore[arg-type]
    malformed = dataclasses.replace(receipt, assertion_assessments=(bad_assessment,))
    with pytest.raises(router_errors.InvalidObjectType):
        _route_with_receipt(overlay, compiled, malformed)


def test_assertion_assessment_non_bool_satisfied_rejected(satisfied_receipt):
    compiled, overlay, receipt = satisfied_receipt
    bad_assessment = dataclasses.replace(receipt.assertion_assessments[0], satisfied="true")  # type: ignore[arg-type]
    malformed = dataclasses.replace(receipt, assertion_assessments=(bad_assessment,))
    with pytest.raises(router_errors.InvalidObjectType):
        _route_with_receipt(overlay, compiled, malformed)


def test_duplicate_assertion_id_in_assessments_rejected(satisfied_receipt):
    compiled, overlay, receipt = satisfied_receipt
    duplicated = receipt.assertion_assessments + receipt.assertion_assessments
    malformed = dataclasses.replace(receipt, assertion_assessments=duplicated)
    with pytest.raises(router_errors.DuplicateAssertionIdInReceipt):
        _route_with_receipt(overlay, compiled, malformed)


def test_disclosure_requirement_bare_string_obligation_rejected(satisfied_receipt):
    compiled, overlay, receipt = satisfied_receipt
    bad_disclosure = DisclosureRequirement(
        assertion_id="pa1", source_atom_id="a1", epistemic_state=receipt.assertion_assessments[0].epistemic_state,
        obligation="DISCLOSE",  # type: ignore[arg-type]
    )
    malformed = dataclasses.replace(receipt, required_disclosures=(bad_disclosure,))
    with pytest.raises(router_errors.InvalidObjectType):
        _route_with_receipt(overlay, compiled, malformed)


def test_disclosure_requirement_wrong_type_rejected(satisfied_receipt):
    compiled, overlay, receipt = satisfied_receipt
    malformed = dataclasses.replace(receipt, required_disclosures=("not-a-disclosure-requirement",))  # type: ignore[arg-type]
    with pytest.raises(router_errors.InvalidObjectType):
        _route_with_receipt(overlay, compiled, malformed)


def test_integrity_violation_bare_string_reason_rejected(receipt_with_violation):
    compiled, overlay, receipt = receipt_with_violation
    bad_violation = dataclasses.replace(receipt.violations[0], reason="POLARITY_MISMATCH")  # type: ignore[arg-type]
    malformed = dataclasses.replace(receipt, violations=(bad_violation,))
    with pytest.raises(router_errors.InvalidObjectType):
        _route_with_receipt(overlay, compiled, malformed)


def test_integrity_violation_wrong_type_for_optional_id_rejected(receipt_with_violation):
    compiled, overlay, receipt = receipt_with_violation
    bad_violation = dataclasses.replace(receipt.violations[0], assertion_id=123)  # type: ignore[arg-type]
    malformed = dataclasses.replace(receipt, violations=(bad_violation,))
    with pytest.raises(router_errors.InvalidObjectType):
        _route_with_receipt(overlay, compiled, malformed)


def test_material_scope_coverage_non_string_member_rejected(satisfied_receipt):
    compiled, overlay, receipt = satisfied_receipt
    malformed = dataclasses.replace(receipt, material_scope_coverage=(1,))  # type: ignore[arg-type]
    with pytest.raises(router_errors.InvalidObjectType):
        _route_with_receipt(overlay, compiled, malformed)


def test_omitted_scope_atom_ids_none_member_rejected(satisfied_receipt):
    compiled, overlay, receipt = satisfied_receipt
    malformed = dataclasses.replace(receipt, omitted_scope_atom_ids=(None,))  # type: ignore[arg-type]
    with pytest.raises(router_errors.InvalidObjectType):
        _route_with_receipt(overlay, compiled, malformed)


def test_metadata_wrong_root_type_rejected(satisfied_receipt):
    compiled, overlay, receipt = satisfied_receipt
    malformed = dataclasses.replace(receipt, metadata=object())  # type: ignore[arg-type]
    with pytest.raises(router_errors.InvalidObjectType):
        _route_with_receipt(overlay, compiled, malformed)


def test_metadata_malformed_nested_value_rejected(satisfied_receipt):
    compiled, overlay, receipt = satisfied_receipt
    malformed = dataclasses.replace(receipt, metadata={"x": float("nan")})
    with pytest.raises(router_errors.RouterError):
        _route_with_receipt(overlay, compiled, malformed)


def test_evaluated_at_wrong_type_rejected(satisfied_receipt):
    compiled, overlay, receipt = satisfied_receipt
    malformed = dataclasses.replace(receipt, evaluated_at=12345)  # type: ignore[arg-type]
    with pytest.raises(router_errors.InvalidObjectType):
        _route_with_receipt(overlay, compiled, malformed)


def test_top_level_string_field_wrong_type_rejected(satisfied_receipt):
    compiled, overlay, receipt = satisfied_receipt
    malformed = dataclasses.replace(receipt, receipt_id=object())  # type: ignore[arg-type]
    with pytest.raises(router_errors.InvalidObjectType):
        _route_with_receipt(overlay, compiled, malformed)


def test_integrity_status_bare_string_rejected(satisfied_receipt):
    compiled, overlay, receipt = satisfied_receipt
    malformed = dataclasses.replace(receipt, integrity_status="SATISFIED")  # type: ignore[arg-type]
    with pytest.raises(router_errors.InvalidObjectType):
        _route_with_receipt(overlay, compiled, malformed)


def test_well_formed_disclosure_and_violation_records_pass_structural_validation():
    """A structurally sound (if synthetic) DisclosureRequirement and
    IntegrityViolation, built from genuine Phase-19 enum members, must
    NOT be rejected -- proving the validator accepts well-formed nested
    records, not just rejects malformed ones."""
    compiled, overlay = build_known_affirmed_fixture(atom_id="a1")
    receipt = make_real_integrity_receipt(overlay=overlay, artifact=compiled, atom_id="a1", satisfied=False)
    good_disclosure = DisclosureRequirement(
        assertion_id="pa1", source_atom_id="a1",
        epistemic_state=receipt.assertion_assessments[0].epistemic_state, obligation=IntegrityObligation.UNCERTAINTY_DISCLOSURE_REQUIRED,
    )
    good_violation = IntegrityViolation(
        reason=IntegrityViolationReason.POLARITY_MISMATCH, assertion_id="pa1", source_atom_id="a1", detail="synthetic detail",
    )
    well_formed = dataclasses.replace(receipt, required_disclosures=(good_disclosure,), violations=(good_violation,))
    expected_digest = epistemic_canonical.digest(overlay)
    from orneur.intelligence.integrity import canonical as integrity_canonical

    task = CognitiveTaskProfile(task_id="t")
    decision = route_task(
        task, overlay=overlay, artifact=compiled,
        overlay_trust_context=TRUSTED_PHASE18_RUNTIME, expected_overlay_digest=expected_digest,
        integrity_receipt=well_formed, integrity_receipt_trust_context=IntegrityReceiptTrustContext.TRUSTED_PHASE19_RUNTIME,
        expected_integrity_receipt_digest=integrity_canonical.digest(well_formed),
    )
    assert decision.status is decision.status  # reaches a real decision without raising
