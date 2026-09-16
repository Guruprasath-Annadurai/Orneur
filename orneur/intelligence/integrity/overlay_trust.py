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

from orneur.intelligence.integrity.enums import IntegrityOverlayTrustContext

UNTRUSTED = IntegrityOverlayTrustContext.UNTRUSTED
TRUSTED_PHASE18_RUNTIME = IntegrityOverlayTrustContext.TRUSTED_PHASE18_RUNTIME


def is_valid_overlay_trust_context(value: object) -> bool:
    """Deliberately isinstance(), not `value in {...}` -- a bare string
    equal to a member's .value must fail this check."""
    return isinstance(value, IntegrityOverlayTrustContext)
