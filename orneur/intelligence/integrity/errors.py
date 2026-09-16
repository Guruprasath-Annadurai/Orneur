"""
Phase 19 typed error hierarchy, mirroring Phase 18/17's pattern: every
error has a stable machine-readable `code` and a detail message that
never echoes a raw external value's repr. No raw AttributeError/
TypeError/KeyError/ValueError may leak from a malformed external input
at any public boundary.
"""
from __future__ import annotations


class IntegrityError(Exception):
    code: str = "INTEGRITY_ERROR"

    def __init__(self, detail: str):
        self.detail = detail
        super().__init__(f"[{self.code}] {detail}")


class InvalidObjectType(IntegrityError):
    code = "INVALID_OBJECT_TYPE"


class InvalidStructuredValue(IntegrityError):
    code = "INVALID_STRUCTURED_VALUE"


class DuplicateAssertionId(IntegrityError):
    code = "DUPLICATE_ASSERTION_ID"


class DuplicateScopeAtom(IntegrityError):
    code = "DUPLICATE_SCOPE_ATOM"


class UnknownAtomReference(IntegrityError):
    code = "UNKNOWN_ATOM_REFERENCE"


class NonAssessedAtomReference(IntegrityError):
    """An assertion or scope entry references an atom_id that the
    supplied EpistemicOverlay never assessed -- distinct from a
    reference the source OCL artifact never even declared."""

    code = "NON_ASSESSED_ATOM_REFERENCE"


class OverlayBindingInvalid(IntegrityError):
    """The supplied EpistemicOverlay is not bound to the supplied
    CognitiveArtifact (verify_overlay_binding() failed) -- a wrong or
    mutated source artifact. Distinct from OverlayProvenanceInvalid:
    this checks artifact identity/content, not overlay-assessment
    content."""

    code = "OVERLAY_BINDING_INVALID"


class InvalidOverlayTrustContext(IntegrityError):
    """overlay_trust_context is not a genuine
    IntegrityOverlayTrustContext member -- e.g. a bare string equal to
    a member's value. Mirrors the isinstance-based (not
    membership-based) check used throughout OCL/Phase-18's own trust
    boundaries."""

    code = "INVALID_OVERLAY_TRUST_CONTEXT"


class UntrustedOverlayRejected(IntegrityError):
    """overlay_trust_context is the genuine UNTRUSTED enum member (the
    default). assess_integrity() cannot consume overlay content as
    epistemic authority without an explicit trusted invocation
    boundary -- fails closed rather than silently proceeding."""

    code = "UNTRUSTED_OVERLAY_REJECTED"


class OverlayProvenanceInvalid(IntegrityError):
    """The overlay's actual canonical content digest
    (epistemic.canonical.digest(overlay)) does not match the trusted,
    out-of-band expected_overlay_digest supplied by the caller.
    artifact_id/artifact_digest binding alone (OverlayBindingInvalid)
    proves which artifact the overlay CLAIMS to assess; it does NOT
    prove the overlay's own assessment content was not substituted
    after being produced -- this check closes exactly that gap. This is
    content-identity verification under a trusted invocation boundary,
    NOT cryptographic provenance/authentication -- no signature scheme
    exists in this repository at any layer."""

    code = "OVERLAY_PROVENANCE_INVALID"


class InvalidIntegrityPolicy(IntegrityError):
    code = "INVALID_INTEGRITY_POLICY"


class PolicyAttemptedToWeakenHardFloor(IntegrityError):
    """A supplied IntegrityPolicy declared a permitted-treatment set for
    some EpistemicState that is not a SUBSET of the hard floor's own
    permitted set for that state -- i.e. it tried to add permission.
    Rejected outright rather than silently narrowed away, so the
    attempt is observable and testable."""

    code = "POLICY_ATTEMPTED_TO_WEAKEN_HARD_FLOOR"


class InvalidFreshnessConfiguration(IntegrityError):
    code = "INVALID_FRESHNESS_CONFIGURATION"


class PayloadLimitExceeded(IntegrityError):
    code = "PAYLOAD_LIMIT_EXCEEDED"


class IntegrityCanonicalizationError(IntegrityError):
    code = "INTEGRITY_CANONICALIZATION_ERROR"


class IntegrityRequirementNotSatisfied(IntegrityError):
    """Raised by require_integrity() when the resulting receipt's
    integrity_status is not SATISFIED."""

    code = "INTEGRITY_REQUIREMENT_NOT_SATISFIED"
