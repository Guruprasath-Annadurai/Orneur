"""
Typed OCL validation errors -- deliberately NOT bare `ValueError` (spec
section 22). Every error carries a stable machine-readable `code` and a
safe (non-secret-leaking) `detail` string. Callers should match on `code`,
not on message text, which may be reworded without notice.
"""
from __future__ import annotations


class OclError(Exception):
    """Base class for every OCL validation/compilation error."""
    code: str = "OCL_ERROR"

    def __init__(self, detail: str):
        self.detail = detail
        super().__init__(f"[{self.code}] {detail}")


class UnsupportedSchemaVersion(OclError):
    code = "UNSUPPORTED_SCHEMA_VERSION"


class InvalidArtifactId(OclError):
    code = "INVALID_ARTIFACT_ID"


class DuplicateAtomId(OclError):
    code = "DUPLICATE_ATOM_ID"


class DanglingRelation(OclError):
    code = "DANGLING_RELATION"


class InvalidRelationShape(OclError):
    code = "INVALID_RELATION_SHAPE"


class InvalidProvenance(OclError):
    code = "INVALID_PROVENANCE"


class ForbiddenAuthorityConstruct(OclError):
    code = "FORBIDDEN_AUTHORITY_CONSTRUCT"


class EvidenceImpersonation(OclError):
    code = "EVIDENCE_IMPERSONATION"


class InvalidNamespace(OclError):
    code = "INVALID_NAMESPACE"


class PayloadLimitExceeded(OclError):
    code = "PAYLOAD_LIMIT_EXCEEDED"


class GraphLimitExceeded(OclError):
    code = "GRAPH_LIMIT_EXCEEDED"


class InvalidTransformation(OclError):
    code = "INVALID_TRANSFORMATION"


class ConservationViolation(OclError):
    code = "CONSERVATION_VIOLATION"


class InvalidCanonicalForm(OclError):
    code = "INVALID_CANONICAL_FORM"


class SecretContentRejected(OclError):
    code = "SECRET_CONTENT_REJECTED"


class DuplicateEvidenceId(OclError):
    code = "DUPLICATE_EVIDENCE_ID"


class DuplicateRelationId(OclError):
    code = "DUPLICATE_RELATION_ID"


class DuplicateActionIntentId(OclError):
    code = "DUPLICATE_ACTION_INTENT_ID"


class DuplicateVerificationContractId(OclError):
    code = "DUPLICATE_VERIFICATION_CONTRACT_ID"


class DuplicateEscalationRequestId(OclError):
    code = "DUPLICATE_ESCALATION_REQUEST_ID"


class DuplicateCausalHypothesisId(OclError):
    code = "DUPLICATE_CAUSAL_HYPOTHESIS_ID"


class DuplicateCounterfactualBranchId(OclError):
    code = "DUPLICATE_COUNTERFACTUAL_BRANCH_ID"


class InvalidStructuredValue(OclError):
    code = "INVALID_STRUCTURED_VALUE"


class InvalidVerificationStatus(OclError):
    code = "INVALID_VERIFICATION_STATUS"


class DuplicateWireKey(OclError):
    code = "DUPLICATE_WIRE_KEY"


class UnknownWireField(OclError):
    code = "UNKNOWN_WIRE_FIELD"


class MissingMandatoryField(OclError):
    code = "MISSING_MANDATORY_FIELD"


class MalformedWireShape(OclError):
    code = "MALFORMED_WIRE_SHAPE"


class ExtensionNamespaceConflict(OclError):
    code = "EXTENSION_NAMESPACE_CONFLICT"


class InvalidTrustContext(OclError):
    code = "INVALID_TRUST_CONTEXT"


class InvalidObjectType(OclError):
    """Raised when a value that must be a specific OCL dataclass or enum
    instance (spec Phase 17 type-parity closure) is something else -- a
    dict, string, int, or wrong-type object standing in for a real
    CognitiveAtom/CognitiveRelation/EvidenceAnchor/Provenance/
    ModelIdentityRef/enum member. Never leaks the value's own repr (which
    could contain sensitive content); only the expected/actual type
    names."""
    code = "INVALID_OBJECT_TYPE"
