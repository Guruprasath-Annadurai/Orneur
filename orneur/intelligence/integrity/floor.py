"""
The Phase 19 hard epistemic floor: one centralized, inspectable,
testable deterministic state matrix. No ad hoc `if` statements
scattered across unrelated modules -- evaluator.py consults only this
module's functions.

See docs/orneur/phase-19/PHASE19_EPISTEMIC_INTEGRITY_SPEC.md for the
full audit-ready matrix in prose/table form; this module is its
executable source of truth.

This floor may be NARROWED by an IntegrityPolicy (see
`effective_permitted_treatments` / `validate_policy`) but never widened.
"""
from __future__ import annotations

from types import MappingProxyType

from orneur.intelligence.epistemic import EpistemicState
from orneur.intelligence.integrity import errors
from orneur.intelligence.integrity.contracts import IntegrityPolicy
from orneur.intelligence.integrity.enums import IntegrityObligation, PresentationTreatment
from orneur.intelligence.integrity.limits import MAX_POLICY_STATE_ENTRIES

ESTABLISHED = PresentationTreatment.ESTABLISHED
INFERENCE = PresentationTreatment.INFERENCE
UNCERTAIN = PresentationTreatment.UNCERTAIN
DISPUTE = PresentationTreatment.DISPUTE
UNKNOWN = PresentationTreatment.UNKNOWN
UNVERIFIABLE = PresentationTreatment.UNVERIFIABLE
ABSTAIN = PresentationTreatment.ABSTAIN

#: The hard, non-negotiable ceiling. A KNOWN proposition MAY be
#: presented as ESTABLISHED (subject to polarity matching, checked
#: separately) or any more-cautious treatment; it may never be
#: presented via a treatment belonging to a DIFFERENT semantic axis
#: (DISPUTE/UNKNOWN/UNVERIFIABLE) since that would misrepresent an
#: actually-resolved proposition, not merely hedge it.
HARD_FLOOR_PERMITTED_TREATMENTS: MappingProxyType[EpistemicState, frozenset[PresentationTreatment]] = MappingProxyType({
    EpistemicState.KNOWN: frozenset({ESTABLISHED, INFERENCE, UNCERTAIN, ABSTAIN}),
    EpistemicState.INFERRED: frozenset({INFERENCE, UNCERTAIN, ABSTAIN}),
    EpistemicState.UNCERTAIN: frozenset({UNCERTAIN, ABSTAIN}),
    EpistemicState.DISPUTED: frozenset({DISPUTE, UNCERTAIN, ABSTAIN}),
    EpistemicState.UNKNOWN: frozenset({UNKNOWN, ABSTAIN}),
    EpistemicState.UNVERIFIABLE: frozenset({UNVERIFIABLE, ABSTAIN}),
})

#: The single strongest treatment permitted for each state -- used both
#: to classify "stronger than state" violations and as the "permitted
#: maximum" correction hint on AssertionAssessment (see
#: PHASE19_EPISTEMIC_INTEGRITY_SPEC.md's "Integrity diff").
HARD_FLOOR_MAXIMUM_TREATMENT: MappingProxyType[EpistemicState, PresentationTreatment] = MappingProxyType({
    EpistemicState.KNOWN: ESTABLISHED,
    EpistemicState.INFERRED: INFERENCE,
    EpistemicState.UNCERTAIN: UNCERTAIN,
    EpistemicState.DISPUTED: DISPUTE,
    EpistemicState.UNKNOWN: UNKNOWN,
    EpistemicState.UNVERIFIABLE: UNVERIFIABLE,
})

#: The disclosure obligation inherently attached to a state, independent
#: of which permitted treatment ends up chosen. KNOWN carries none: a
#: fully resolved, one-sided proposition needs no special disclosure
#: beyond correct polarity.
STATE_REQUIRED_OBLIGATION: MappingProxyType[EpistemicState, IntegrityObligation | None] = MappingProxyType({
    EpistemicState.KNOWN: None,
    EpistemicState.INFERRED: IntegrityObligation.QUALIFICATION_REQUIRED,
    EpistemicState.UNCERTAIN: IntegrityObligation.UNCERTAINTY_DISCLOSURE_REQUIRED,
    EpistemicState.DISPUTED: IntegrityObligation.DISPUTE_DISCLOSURE_REQUIRED,
    EpistemicState.UNKNOWN: IntegrityObligation.UNKNOWN_DISCLOSURE_REQUIRED,
    EpistemicState.UNVERIFIABLE: IntegrityObligation.UNVERIFIABLE_DISCLOSURE_REQUIRED,
})

#: States for which omitting a material scope atom entirely is itself a
#: blocking integrity violation (Cognitive Conservation, section 14 of
#: the closure spec). KNOWN/INFERRED omission is recorded for audit
#: (see omitted_scope_atom_ids on the receipt) but does not by itself
#: block -- a resolved or derivable fact silently left out of an answer
#: is a completeness concern outside this protocol's declared scope,
#: whereas silently dropping unresolved material uncertainty is exactly
#: what this protocol exists to catch.
MATERIAL_CONSERVATION_STATES: frozenset[EpistemicState] = frozenset({
    EpistemicState.UNCERTAIN,
    EpistemicState.DISPUTED,
    EpistemicState.UNKNOWN,
    EpistemicState.UNVERIFIABLE,
})


def effective_permitted_treatments(
    state: EpistemicState, policy: IntegrityPolicy | None,
) -> frozenset[PresentationTreatment]:
    """HARD FLOOR intersected with an optional stricter policy -- never
    the policy alone, so a policy can only narrow, by construction."""
    floor = HARD_FLOOR_PERMITTED_TREATMENTS[state]
    if policy is None:
        return floor
    override = policy.stricter_permitted_treatments.get(state)
    if override is None:
        return floor
    return floor & override


def validate_policy(policy: IntegrityPolicy, *, evaluated_at: str | None) -> None:
    """Reject a policy outright if it declares, for any state, a
    permitted-treatment set that is not a SUBSET of the hard floor's own
    set for that state -- i.e. an attempt to add permission beyond the
    floor. Raised as a typed error rather than silently narrowed away,
    so the attempt is observable and testable (see
    tests/integrity/test_policy_monotonicity.py)."""
    if len(policy.stricter_permitted_treatments) > MAX_POLICY_STATE_ENTRIES:
        raise errors.InvalidIntegrityPolicy("policy declares too many per-state treatment overrides")

    for state, declared in policy.stricter_permitted_treatments.items():
        if not isinstance(state, EpistemicState):
            raise errors.InvalidIntegrityPolicy(
                f"policy stricter_permitted_treatments key must be a genuine EpistemicState member, "
                f"got {type(state).__name__}"
            )
        if not isinstance(declared, frozenset) or not all(isinstance(t, PresentationTreatment) for t in declared):
            raise errors.InvalidIntegrityPolicy(
                f"policy stricter_permitted_treatments[{state!r}] must be a frozenset of PresentationTreatment members"
            )
        floor = HARD_FLOOR_PERMITTED_TREATMENTS[state]
        if not declared.issubset(floor):
            raise errors.PolicyAttemptedToWeakenHardFloor(
                f"policy declares {sorted(t.value for t in declared - floor)} for state {state.value}, "
                f"which the hard floor ({sorted(t.value for t in floor)}) does not permit"
            )

    if policy.max_overlay_age_seconds is not None:
        if isinstance(policy.max_overlay_age_seconds, bool) or not isinstance(policy.max_overlay_age_seconds, int):
            raise errors.InvalidFreshnessConfiguration("max_overlay_age_seconds must be a plain int")
        if policy.max_overlay_age_seconds < 0:
            raise errors.InvalidFreshnessConfiguration("max_overlay_age_seconds must be non-negative")
        if evaluated_at is None:
            raise errors.InvalidFreshnessConfiguration(
                "max_overlay_age_seconds requires assess_integrity(evaluated_at=...) to be explicitly "
                "supplied -- freshness is never evaluated from a wall-clock read"
            )


def is_overlay_stale(*, overlay_assessed_at: str, evaluated_at: str, max_overlay_age_seconds: int) -> bool:
    """Deterministic comparison of two EXPLICITLY supplied ISO-8601
    timestamps -- never a wall-clock read, never a universal age
    heuristic. A negative age (evaluated_at before overlay_assessed_at)
    is treated as not stale rather than raising -- it is a caller
    ordering oddity, not evidence of staleness."""
    import datetime

    assessed = datetime.datetime.fromisoformat(overlay_assessed_at.replace("Z", "+00:00"))
    evaluated = datetime.datetime.fromisoformat(evaluated_at.replace("Z", "+00:00"))
    age_seconds = (evaluated - assessed).total_seconds()
    if age_seconds <= 0:
        return False
    return age_seconds > max_overlay_age_seconds
