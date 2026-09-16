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
closure and this phase's registry seam both forbid). This module
verifies provenance only; binding the receipt to the CURRENT
artifact/overlay being routed is evaluator.py's responsibility (see
evaluator._validate_receipt_binding), performed strictly after
provenance passes and strictly before `receipt.integrity_status` is
ever consumed.
"""
from __future__ import annotations

from orneur.intelligence.integrity import canonical as integrity_canonical
from orneur.intelligence.integrity.contracts import IntegrityReceipt
from orneur.intelligence.router import errors
from orneur.intelligence.router.enums import IntegrityReceiptTrustContext
from orneur.intelligence.router.typecheck import require_instance, require_string

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
    if not is_valid_integrity_receipt_trust_context(trust_context):
        raise errors.InvalidIntegrityReceiptTrustContext(
            f"trust_context must be a genuine IntegrityReceiptTrustContext member, got {type(trust_context).__name__}"
        )
    if trust_context is UNTRUSTED:
        raise errors.UntrustedIntegrityReceiptRejected("integrity_receipt supplied with UNTRUSTED trust context")
    require_string(expected_receipt_digest, where="expected_integrity_receipt_digest")

    actual_digest = integrity_canonical.digest(receipt)
    if actual_digest != expected_receipt_digest:
        raise errors.IntegrityReceiptProvenanceInvalid(
            "integrity_receipt's canonical digest does not match the out-of-band expected_integrity_receipt_digest"
        )
    return actual_digest
