"""
Phase 18 typed error hierarchy. Mirrors orneur.intelligence.ocl.errors:
every error has a stable machine-readable `code` and a detail message
that never echoes a raw external value's repr (only type names / IDs).
No raw AttributeError/TypeError/KeyError/ValueError may leak from a
malformed external input at any public boundary.
"""
from __future__ import annotations


class EpistemicError(Exception):
    code: str = "EPISTEMIC_ERROR"

    def __init__(self, detail: str):
        self.detail = detail
        super().__init__(f"[{self.code}] {detail}")


class InvalidEpistemicState(EpistemicError):
    code = "INVALID_EPISTEMIC_STATE"


class InvalidEpistemicObject(EpistemicError):
    code = "INVALID_EPISTEMIC_OBJECT"


class InvalidObjectType(EpistemicError):
    code = "INVALID_OBJECT_TYPE"


class InvalidStructuredValue(EpistemicError):
    code = "INVALID_STRUCTURED_VALUE"


class InvalidResolutionTrustContext(EpistemicError):
    code = "INVALID_RESOLUTION_TRUST_CONTEXT"


class UnknownEvidenceReference(EpistemicError):
    code = "UNKNOWN_EVIDENCE_REFERENCE"


class UnknownAtomReference(EpistemicError):
    code = "UNKNOWN_ATOM_REFERENCE"


class EvidenceAtomMismatch(EpistemicError):
    """A resolution record targets an evidence_id that exists, but is
    not among the target atom's own evidence_refs."""

    code = "EVIDENCE_ATOM_MISMATCH"


class ConflictingEvidenceResolution(EpistemicError):
    """Two resolution records for the same (target_atom_id, evidence_id)
    disagree. A legitimate dispute must be represented by separate
    evidence, not one evidence record claiming mutually exclusive
    outcomes -- fail closed rather than silently picking one."""

    code = "CONFLICTING_EVIDENCE_RESOLUTION"


class InvalidAssessmentContext(EpistemicError):
    code = "INVALID_ASSESSMENT_CONTEXT"


class SourceArtifactMismatch(EpistemicError):
    """An EpistemicOverlay was bound to (or is being reused against) an
    OCL artifact other than the exact one it assessed."""

    code = "SOURCE_ARTIFACT_MISMATCH"


class NonAssessableAtomKind(EpistemicError):
    code = "NON_ASSESSABLE_ATOM_KIND"


class InvalidVerificationFeasibility(EpistemicError):
    code = "INVALID_VERIFICATION_FEASIBILITY"


class EpistemicCanonicalizationError(EpistemicError):
    code = "EPISTEMIC_CANONICALIZATION_ERROR"


class PayloadLimitExceeded(EpistemicError):
    code = "PAYLOAD_LIMIT_EXCEEDED"


class GraphLimitExceeded(EpistemicError):
    code = "GRAPH_LIMIT_EXCEEDED"


class DuplicateOverlayInput(EpistemicError):
    code = "DUPLICATE_OVERLAY_INPUT"
