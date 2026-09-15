"""
Phase 18 trust boundary. Repeats the lesson Phase 17 learned: trust must
NEVER come from a field inside an untrusted payload -- it is supplied
exclusively by the caller of resolver.assess_artifact(), as an explicit,
required, strictly-typed keyword argument. A plain Python string that
happens to equal an EpistemicResolutionTrustContext member's value is
NOT a valid trust context.
"""
from __future__ import annotations

from orneur.intelligence.epistemic.enums import EpistemicResolutionTrustContext

UNTRUSTED = EpistemicResolutionTrustContext.UNTRUSTED

#: Trust tiers whose resolution records may establish a *qualified*
#: direct evidence basis (KNOWN) or seed an evidence-rooted derivation
#: (INFERRED). UNTRUSTED resolution batches never qualify, regardless of
#: what an individual record's status/stance fields claim.
TRUSTED_RESOLUTION_CONTEXTS = frozenset({
    EpistemicResolutionTrustContext.TRUSTED_TOOL_RESOLVER,
    EpistemicResolutionTrustContext.TRUSTED_DETERMINISTIC_VERIFIER,
})

#: Only this tier may mint a canonical UNVERIFIABLE state. A tool
#: resolver reporting a failed call, or a model's own LIMITATION atom,
#: is deliberately NOT enough -- UNVERIFIABLE is a high-bar state.
STRUCTURALLY_UNVERIFIABLE_CAPABLE_CONTEXTS = frozenset({
    EpistemicResolutionTrustContext.TRUSTED_DETERMINISTIC_VERIFIER,
})


def is_valid_resolution_trust_context(value: object) -> bool:
    """Deliberately isinstance(), not `value in {...}` -- a bare string
    equal to a member's .value must fail this check (str-mixin Enum
    equality would otherwise let it through)."""
    return isinstance(value, EpistemicResolutionTrustContext)


def is_qualified(trust_context: EpistemicResolutionTrustContext) -> bool:
    return trust_context in TRUSTED_RESOLUTION_CONTEXTS


def can_mint_structurally_unverifiable(trust_context: EpistemicResolutionTrustContext) -> bool:
    return trust_context in STRUCTURALLY_UNVERIFIABLE_CAPABLE_CONTEXTS
