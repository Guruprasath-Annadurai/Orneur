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
