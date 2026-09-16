"""
Overlay trust boundary for Phase 19. Repeats the lesson Phase 17/18
already learned: trust must come from the invocation boundary supplied
by the CALLER, never from a field inside the payload (overlay.metadata,
proposal.metadata, or any self-declared string). A plain Python string
equal to IntegrityOverlayTrustContext.TRUSTED_PHASE18_RUNTIME.value is
NOT a valid trust context.

artifact_id/artifact_digest binding (verify_overlay_binding, checked
separately in evaluator.py) proves which OCL artifact an overlay CLAIMS
to assess. It does NOT prove the overlay was actually produced by
Phase 18's assess_artifact() or that its EpistemicAssessments were not
substituted afterward -- that is what the trust context PLUS the
out-of-band expected_overlay_digest check (evaluator.py) together
establish. This is content-identity verification under a trusted
invocation boundary, not cryptographic provenance/authentication -- no
signature scheme exists in this repository at any layer.
"""
from __future__ import annotations

from orneur.intelligence.epistemic import EpistemicOverlay, verify_overlay_binding
from orneur.intelligence.epistemic import canonical as epistemic_canonical
from orneur.intelligence.epistemic.errors import SourceArtifactMismatch
from orneur.intelligence.integrity import errors
from orneur.intelligence.integrity.enums import IntegrityOverlayTrustContext
from orneur.intelligence.integrity.typecheck import require_string
from orneur.intelligence.ocl.artifact import CognitiveArtifact

UNTRUSTED = IntegrityOverlayTrustContext.UNTRUSTED
TRUSTED_PHASE18_RUNTIME = IntegrityOverlayTrustContext.TRUSTED_PHASE18_RUNTIME


def is_valid_overlay_trust_context(value: object) -> bool:
    """Deliberately isinstance(), not `value in {...}` -- a bare string
    equal to a member's .value must fail this check."""
    return isinstance(value, IntegrityOverlayTrustContext)


def verify_trusted_overlay(
    overlay: EpistemicOverlay,
    artifact: CognitiveArtifact,
    *,
    trust_context: IntegrityOverlayTrustContext,
    expected_overlay_digest: str | None,
) -> str:
    """THE single reusable overlay-trust-boundary seam. Originally
    inlined in evaluator.assess_integrity(); extracted here (same
    behavior, same exceptions, verified by the full pre-existing
    Phase-19 test suite passing unchanged) so any OTHER Phase-19+
    consumer of EpistemicOverlay data -- e.g. Phase 20's router -- can
    reuse this exact check instead of re-deriving (and risking
    weakening) the same security-sensitive logic.

    Verifies, in order: (1) `trust_context` is a genuine
    IntegrityOverlayTrustContext member, never a bare string; (2) it is
    not UNTRUSTED (which always fails closed -- overlay content can
    never be used as epistemic authority without an explicit trusted
    invocation boundary); (3) `expected_overlay_digest` is a non-empty
    string, supplied by the caller from OUTSIDE this call -- callers
    must NEVER compute it from `overlay` itself, which would prove
    nothing; (4) `verify_overlay_binding(overlay, artifact)` succeeds
    (artifact identity/content); (5) `epistemic.canonical.digest(overlay)`
    matches `expected_overlay_digest` (content-identity verification
    under the trusted invocation boundary, NOT cryptographic
    authentication -- no signature scheme exists in this repository).

    Returns the overlay's canonical digest on success (callers that
    already need it, e.g. for their own receipt, avoid recomputing it)."""
    if not is_valid_overlay_trust_context(trust_context):
        raise errors.InvalidOverlayTrustContext(
            f"overlay_trust_context must be a genuine IntegrityOverlayTrustContext member, "
            f"got {type(trust_context).__name__}"
        )
    if trust_context is UNTRUSTED:
        raise errors.UntrustedOverlayRejected(
            "an explicit trust_context=TRUSTED_PHASE18_RUNTIME plus a matching "
            "expected_overlay_digest is required -- an UNTRUSTED overlay cannot be used "
            "as epistemic authority"
        )
    require_string(expected_overlay_digest, where="expected_overlay_digest")

    try:
        verify_overlay_binding(overlay, artifact)
    except SourceArtifactMismatch as exc:
        raise errors.OverlayBindingInvalid(str(exc.detail)) from exc

    overlay_digest = epistemic_canonical.digest(overlay)
    if overlay_digest != expected_overlay_digest:
        raise errors.OverlayProvenanceInvalid(
            "overlay content digest does not match the trusted expected_overlay_digest -- the "
            "overlay's assessments may have been altered/substituted after being produced"
        )
    return overlay_digest
