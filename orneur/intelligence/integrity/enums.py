"""
Phase 19 closed vocabularies. Every enum is closed: unrecognized values
fail closed. Phase 19 reuses Phase 18's own EpistemicState and
EpistemicPolarity directly (imported, never redefined) -- only genuinely
new Phase-19 concepts (presentation treatment, integrity status,
obligations, violation reasons) get new enums here.
"""
from __future__ import annotations

from enum import Enum


class PresentationTreatment(str, Enum):
    """How a proposed structured assertion wants to present one
    proposition. Closed vocabulary -- no free-form strings, no numeric
    confidence substitute."""

    ESTABLISHED = "ESTABLISHED"
    INFERENCE = "INFERENCE"
    UNCERTAIN = "UNCERTAIN"
    DISPUTE = "DISPUTE"
    UNKNOWN = "UNKNOWN"
    UNVERIFIABLE = "UNVERIFIABLE"
    ABSTAIN = "ABSTAIN"


class IntegrityObligation(str, Enum):
    """An epistemic PRESENTATION obligation -- never execution
    authority, human approval, governance permission, policy approval,
    or model promotion approval."""

    QUALIFICATION_REQUIRED = "QUALIFICATION_REQUIRED"
    DISPUTE_DISCLOSURE_REQUIRED = "DISPUTE_DISCLOSURE_REQUIRED"
    UNCERTAINTY_DISCLOSURE_REQUIRED = "UNCERTAINTY_DISCLOSURE_REQUIRED"
    UNKNOWN_DISCLOSURE_REQUIRED = "UNKNOWN_DISCLOSURE_REQUIRED"
    UNVERIFIABLE_DISCLOSURE_REQUIRED = "UNVERIFIABLE_DISCLOSURE_REQUIRED"
    MORE_EVIDENCE_REQUIRED = "MORE_EVIDENCE_REQUIRED"
    ABSTENTION_REQUIRED = "ABSTENTION_REQUIRED"


class IntegrityViolationReason(str, Enum):
    """Closed, typed reasons an assertion or proposal fails integrity.
    No uncontrolled free-form failure classification."""

    OVERLAY_BINDING_INVALID = "OVERLAY_BINDING_INVALID"
    UNKNOWN_ATOM_REFERENCE = "UNKNOWN_ATOM_REFERENCE"
    DUPLICATE_ASSERTION_ID = "DUPLICATE_ASSERTION_ID"
    DUPLICATE_SCOPE_ATOM = "DUPLICATE_SCOPE_ATOM"
    PRESENTED_STRONGER_THAN_STATE = "PRESENTED_STRONGER_THAN_STATE"
    POLARITY_MISMATCH = "POLARITY_MISMATCH"
    INFERENCE_PRESENTED_AS_FACT = "INFERENCE_PRESENTED_AS_FACT"
    UNCERTAINTY_SUPPRESSED = "UNCERTAINTY_SUPPRESSED"
    DISPUTE_SUPPRESSED = "DISPUTE_SUPPRESSED"
    UNKNOWN_PRESENTED_AS_KNOWLEDGE = "UNKNOWN_PRESENTED_AS_KNOWLEDGE"
    UNVERIFIABLE_PRESENTED_AS_VERIFIED = "UNVERIFIABLE_PRESENTED_AS_VERIFIED"
    REQUIRED_SCOPE_ATOM_OMITTED = "REQUIRED_SCOPE_ATOM_OMITTED"
    REQUIRED_DISCLOSURE_MISSING = "REQUIRED_DISCLOSURE_MISSING"
    STALE_EPISTEMIC_OVERLAY = "STALE_EPISTEMIC_OVERLAY"
    POLICY_ATTEMPTED_TO_WEAKEN_HARD_FLOOR = "POLICY_ATTEMPTED_TO_WEAKEN_HARD_FLOOR"
    MALFORMED_INPUT = "MALFORMED_INPUT"


class IntegrityOverlayTrustContext(str, Enum):
    """Trust context for the EpistemicOverlay supplied to
    assess_integrity(), mirroring orneur.intelligence.epistemic.trust's
    CompilationTrustContext / EpistemicResolutionTrustContext pattern
    exactly: supplied by the CALLER of assess_integrity(), never parsed
    from a payload/metadata field. artifact_id/digest binding
    (verify_overlay_binding) proves which OCL artifact an overlay
    CLAIMS to assess -- it does NOT prove the overlay was actually
    produced by Phase 18's assess_artifact() or that its assessments
    were not substituted afterward. UNTRUSTED overlay input cannot be
    used as epistemic authority: assess_integrity() fails closed unless
    the caller supplies TRUSTED_PHASE18_RUNTIME plus a matching
    out-of-band expected_overlay_digest (see evaluator.py)."""

    UNTRUSTED = "UNTRUSTED"
    TRUSTED_PHASE18_RUNTIME = "TRUSTED_PHASE18_RUNTIME"


class IntegrityStatus(str, Enum):
    """Top-level receipt status. Never a Cognitive Court verdict (ACCEPT/
    REJECT/NEED_MORE_EVIDENCE/ESCALATE/HUMAN_APPROVAL_REQUIRED) -- those
    five are a separate, unrelated contract this package never imports
    or reuses."""

    SATISFIED = "SATISFIED"
    REQUIRES_REVISION = "REQUIRES_REVISION"
    BLOCKED = "BLOCKED"


#: Violations in this set represent a structural/proposal-level problem
#: that changing one assertion's treatment cannot fix by itself --
#: BLOCKED. Everything else is a per-assertion presentation problem a
#: revision could plausibly correct -- REQUIRES_REVISION.
BLOCKING_VIOLATION_REASONS: frozenset[IntegrityViolationReason] = frozenset({
    IntegrityViolationReason.REQUIRED_SCOPE_ATOM_OMITTED,
    IntegrityViolationReason.STALE_EPISTEMIC_OVERLAY,
    IntegrityViolationReason.DUPLICATE_ASSERTION_ID,
    IntegrityViolationReason.DUPLICATE_SCOPE_ATOM,
})

CURRENT_PROTOCOL_VERSION = "19.0.0"
