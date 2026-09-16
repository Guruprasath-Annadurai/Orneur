"""
Phase 20 typed error hierarchy, mirroring Phase 19/18/17's pattern.
Deliberately self-contained (not importing epistemic.errors/
integrity.errors directly for validation helpers) for the same reason
Phase 19 learned the hard way: reusing another phase's validator
function reuses its exception types too, leaking a foreign exception
across this package's own public boundary.
"""
from __future__ import annotations


class RouterError(Exception):
    code: str = "ROUTER_ERROR"

    def __init__(self, detail: str):
        self.detail = detail
        super().__init__(f"[{self.code}] {detail}")


class InvalidObjectType(RouterError):
    code = "INVALID_OBJECT_TYPE"


class InvalidStructuredValue(RouterError):
    code = "INVALID_STRUCTURED_VALUE"


class DuplicateRequirementEntry(RouterError):
    code = "DUPLICATE_REQUIREMENT_ENTRY"


class DuplicateRegistryFamily(RouterError):
    code = "DUPLICATE_REGISTRY_FAMILY"


class UnknownEpistemicAtomReference(RouterError):
    """A task references an atom_id the supplied overlay never
    assessed."""

    code = "UNKNOWN_EPISTEMIC_ATOM_REFERENCE"


class InvalidCapabilityRegistry(RouterError):
    code = "INVALID_CAPABILITY_REGISTRY"


class InvalidIntegrityReceipt(RouterError):
    code = "INVALID_INTEGRITY_RECEIPT"


class RouterCanonicalizationError(RouterError):
    code = "ROUTER_CANONICALIZATION_ERROR"


class PayloadLimitExceeded(RouterError):
    code = "PAYLOAD_LIMIT_EXCEEDED"


class InvalidCapabilityRegistryTrustContext(RouterError):
    code = "INVALID_CAPABILITY_REGISTRY_TRUST_CONTEXT"


class UntrustedCapabilityRegistryRejected(RouterError):
    """A caller-supplied capability_registry was presented with the
    UNTRUSTED trust context (or omitted it) -- always fails closed."""

    code = "UNTRUSTED_CAPABILITY_REGISTRY_REJECTED"


class CapabilityRegistryProvenanceInvalid(RouterError):
    """The registry's canonical digest did not match the caller's
    out-of-band expected_registry_digest."""

    code = "CAPABILITY_REGISTRY_PROVENANCE_INVALID"


class InvalidIntegrityReceiptTrustContext(RouterError):
    code = "INVALID_INTEGRITY_RECEIPT_TRUST_CONTEXT"


class UntrustedIntegrityReceiptRejected(RouterError):
    """A supplied IntegrityReceipt was presented with the UNTRUSTED
    trust context (or omitted it) -- always fails closed."""

    code = "UNTRUSTED_INTEGRITY_RECEIPT_REJECTED"


class IntegrityReceiptProvenanceInvalid(RouterError):
    """The receipt's canonical digest did not match the caller's
    out-of-band expected_integrity_receipt_digest."""

    code = "INTEGRITY_RECEIPT_PROVENANCE_INVALID"


class IntegrityReceiptBindingInvalid(RouterError):
    """A provenance-verified IntegrityReceipt does not correspond to
    the artifact/overlay currently being routed (source_artifact_id/
    source_artifact_digest/source_overlay_digest mismatch)."""

    code = "INTEGRITY_RECEIPT_BINDING_INVALID"
