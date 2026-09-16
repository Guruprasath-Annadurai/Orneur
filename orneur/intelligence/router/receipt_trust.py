"""
The Phase-20-owned trust-boundary seam for consuming a Phase-19
IntegrityReceipt. Mirrors orneur.intelligence.integrity.overlay_trust's
doctrine exactly, one layer up: isinstance(receipt, IntegrityReceipt)
proves only that the object is shaped like a receipt, never that it was
genuinely produced by a trusted Phase-19 evaluation run for the
artifact/overlay currently being routed. `expected_receipt_digest` MUST
be supplied out-of-band by the trusted Phase-19 caller BEFORE the
receipt crosses into Phase 20 -- this module computes the ACTUAL digest
via orneur.intelligence.integrity.canonical.digest() only to COMPARE
against that out-of-band expectation, never to manufacture it (the same
`expected = digest(incoming_thing)` anti-pattern Phase 19's overlay
closure and this phase's registry seam both forbid).

Required verification order (a receipt is never a "safe to canonicalize"
object merely by being an IntegrityReceipt instance -- canonicalization
walks nested tuples of AssertionAssessment/DisclosureRequirement/
IntegrityViolation records that a dataclass constructor never
type-checks):

  1. isinstance(receipt, IntegrityReceipt)
  2. FULL structural pre-validation of every field, including nested
     records (this module's _validate_receipt_structure) -- BEFORE any
     trust judgment, so a malformed receipt always fails with a clear
     typed structural error rather than an incidental trust-context
     error.
  3. trust_context is a genuine IntegrityReceiptTrustContext member
  4. trust_context is not UNTRUSTED
  5. expected_receipt_digest is a non-empty string
  6. integrity_canonical.digest(receipt) computed (wrapped: any Phase-19
     canonicalization exception is translated to a typed RouterError,
     never left to escape raw)
  7. actual digest compared against expected_receipt_digest

Binding the receipt to the CURRENT artifact/overlay being routed is
evaluator.py's responsibility (see evaluator._validate_receipt_binding),
performed strictly after this function returns and strictly before
`receipt.integrity_status` is ever consumed.
"""
from __future__ import annotations

from orneur.intelligence.epistemic import EpistemicPolarity, EpistemicState
from orneur.intelligence.integrity import canonical as integrity_canonical
from orneur.intelligence.integrity import errors as integrity_errors
from orneur.intelligence.integrity.contracts import (
    AssertionAssessment,
    DisclosureRequirement,
    IntegrityReceipt,
    IntegrityViolation,
)
from orneur.intelligence.integrity.enums import (
    IntegrityObligation,
    IntegrityStatus,
    IntegrityViolationReason,
    PresentationTreatment,
)
from orneur.intelligence.router import errors
from orneur.intelligence.router.enums import IntegrityReceiptTrustContext
from orneur.intelligence.router.freeze import require_mapping_root, validate_and_freeze
from orneur.intelligence.router.typecheck import (
    require_enum_member,
    require_instance,
    require_sequence_container,
    require_string,
)

UNTRUSTED = IntegrityReceiptTrustContext.UNTRUSTED
TRUSTED_PHASE19_RUNTIME = IntegrityReceiptTrustContext.TRUSTED_PHASE19_RUNTIME


def is_valid_integrity_receipt_trust_context(value: object) -> bool:
    return isinstance(value, IntegrityReceiptTrustContext)


def verify_trusted_receipt(
    receipt: IntegrityReceipt, *, trust_context: IntegrityReceiptTrustContext, expected_receipt_digest: str | None,
) -> str:
    """Returns the receipt's verified canonical digest on success.
    Raises a typed RouterError for every failure mode -- never a raw
    exception."""
    require_instance(receipt, IntegrityReceipt, where="integrity_receipt")
    _validate_receipt_structure(receipt)

    if not is_valid_integrity_receipt_trust_context(trust_context):
        raise errors.InvalidIntegrityReceiptTrustContext(
            f"trust_context must be a genuine IntegrityReceiptTrustContext member, got {type(trust_context).__name__}"
        )
    if trust_context is UNTRUSTED:
        raise errors.UntrustedIntegrityReceiptRejected("integrity_receipt supplied with UNTRUSTED trust context")
    require_string(expected_receipt_digest, where="expected_integrity_receipt_digest")

    try:
        actual_digest = integrity_canonical.digest(receipt)
    except integrity_errors.IntegrityError as exc:
        # Defense in depth: structural pre-validation above should make
        # this unreachable for any receipt this function accepts, but a
        # Phase-19 canonicalization exception must never cross this
        # public boundary unwrapped regardless.
        raise errors.IntegrityReceiptCanonicalizationFailed(
            f"integrity_receipt failed Phase-19 canonicalization after passing structural validation: {exc}"
        ) from exc

    if actual_digest != expected_receipt_digest:
        raise errors.IntegrityReceiptProvenanceInvalid(
            "integrity_receipt's canonical digest does not match the out-of-band expected_integrity_receipt_digest"
        )
    return actual_digest


# ── structural pre-validation ───────────────────────────────────────────


def _require_string_or_none(value: object, *, where: str) -> None:
    if value is not None:
        require_string(value, where=where)


def _validate_receipt_structure(receipt: IntegrityReceipt) -> None:
    """Validates every IntegrityReceipt field down to the nested
    AssertionAssessment/DisclosureRequirement/IntegrityViolation record
    level -- enough shape to guarantee canonicalization is safe and
    that `integrity_status` is a genuine enum member before it is ever
    consumed. Every value is checked with this package's own typed
    validators against Phase-19's REAL contract/enum types (never a
    bare string standing in for an enum member)."""
    require_string(receipt.protocol_version, where="integrity_receipt.protocol_version")
    require_string(receipt.receipt_id, where="integrity_receipt.receipt_id")
    require_string(receipt.source_artifact_id, where="integrity_receipt.source_artifact_id")
    require_string(receipt.source_artifact_digest, where="integrity_receipt.source_artifact_digest")
    require_string(receipt.source_overlay_digest, where="integrity_receipt.source_overlay_digest")
    require_string(receipt.proposal_digest, where="integrity_receipt.proposal_digest")
    require_string(receipt.policy_digest, where="integrity_receipt.policy_digest")
    _require_string_or_none(receipt.evaluated_at, where="integrity_receipt.evaluated_at")
    require_enum_member(receipt.integrity_status, IntegrityStatus, where="integrity_receipt.integrity_status")

    assessments = require_sequence_container(receipt.assertion_assessments, where="integrity_receipt.assertion_assessments")
    seen_assertion_ids: set[str] = set()
    for index, assessment in enumerate(assessments):
        _validate_assertion_assessment(assessment, index=index)
        if assessment.assertion_id in seen_assertion_ids:
            raise errors.DuplicateAssertionIdInReceipt(
                f"integrity_receipt.assertion_assessments contains a duplicate assertion_id: {assessment.assertion_id!r}"
            )
        seen_assertion_ids.add(assessment.assertion_id)

    disclosures = require_sequence_container(receipt.required_disclosures, where="integrity_receipt.required_disclosures")
    for index, disclosure in enumerate(disclosures):
        _validate_disclosure_requirement(disclosure, index=index)

    violations = require_sequence_container(receipt.violations, where="integrity_receipt.violations")
    for index, violation in enumerate(violations):
        _validate_integrity_violation(violation, index=index)

    material_scope_coverage = require_sequence_container(receipt.material_scope_coverage, where="integrity_receipt.material_scope_coverage")
    for index, atom_id in enumerate(material_scope_coverage):
        require_string(atom_id, where=f"integrity_receipt.material_scope_coverage[{index}]")

    omitted_scope_atom_ids = require_sequence_container(receipt.omitted_scope_atom_ids, where="integrity_receipt.omitted_scope_atom_ids")
    for index, atom_id in enumerate(omitted_scope_atom_ids):
        require_string(atom_id, where=f"integrity_receipt.omitted_scope_atom_ids[{index}]")

    metadata_root = require_mapping_root(receipt.metadata, where="integrity_receipt.metadata")
    validate_and_freeze(metadata_root, where="integrity_receipt.metadata")


def _validate_assertion_assessment(assessment: object, *, index: int) -> None:
    where = f"integrity_receipt.assertion_assessments[{index}]"
    require_instance(assessment, AssertionAssessment, where=where)
    require_string(assessment.assertion_id, where=f"{where}.assertion_id")
    require_string(assessment.source_atom_id, where=f"{where}.source_atom_id")
    require_enum_member(assessment.epistemic_state, EpistemicState, where=f"{where}.epistemic_state")
    require_enum_member(assessment.epistemic_polarity, EpistemicPolarity, where=f"{where}.epistemic_polarity")
    require_enum_member(assessment.proposed_treatment, PresentationTreatment, where=f"{where}.proposed_treatment")
    require_enum_member(assessment.permitted_maximum_treatment, PresentationTreatment, where=f"{where}.permitted_maximum_treatment")

    obligations = require_sequence_container(assessment.obligations, where=f"{where}.obligations")
    for i, obligation in enumerate(obligations):
        require_enum_member(obligation, IntegrityObligation, where=f"{where}.obligations[{i}]")

    violation_reasons = require_sequence_container(assessment.violation_reasons, where=f"{where}.violation_reasons")
    for i, reason in enumerate(violation_reasons):
        require_enum_member(reason, IntegrityViolationReason, where=f"{where}.violation_reasons[{i}]")

    if not isinstance(assessment.satisfied, bool):
        raise errors.InvalidObjectType(f"{where}.satisfied: expected bool, got {type(assessment.satisfied).__name__}")


def _validate_disclosure_requirement(disclosure: object, *, index: int) -> None:
    where = f"integrity_receipt.required_disclosures[{index}]"
    require_instance(disclosure, DisclosureRequirement, where=where)
    require_string(disclosure.assertion_id, where=f"{where}.assertion_id")
    require_string(disclosure.source_atom_id, where=f"{where}.source_atom_id")
    require_enum_member(disclosure.epistemic_state, EpistemicState, where=f"{where}.epistemic_state")
    require_enum_member(disclosure.obligation, IntegrityObligation, where=f"{where}.obligation")


def _validate_integrity_violation(violation: object, *, index: int) -> None:
    where = f"integrity_receipt.violations[{index}]"
    require_instance(violation, IntegrityViolation, where=where)
    require_enum_member(violation.reason, IntegrityViolationReason, where=f"{where}.reason")
    _require_string_or_none(violation.assertion_id, where=f"{where}.assertion_id")
    _require_string_or_none(violation.source_atom_id, where=f"{where}.source_atom_id")
    require_string(violation.detail, where=f"{where}.detail")
