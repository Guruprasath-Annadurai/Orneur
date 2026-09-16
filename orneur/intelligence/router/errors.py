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
