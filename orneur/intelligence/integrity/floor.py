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

import datetime
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

#: Per-state, strongest-to-weakest presentation strength ordering. Each
#: state's own semantic axis only -- there is no single global ordering
#: across DISPUTE/UNKNOWN/UNVERIFIABLE since they represent different
#: KINDS of epistemic condition, not degrees of the same one.
#: effective_maximum_treatment() walks this ordering and returns the
#: first entry still permitted under an (optional) narrowing policy, so
#: the reported "permitted maximum" is always honest relative to the
#: ACTIVE policy, not just the unmodified hard floor.
TREATMENT_STRENGTH_ORDER: MappingProxyType[EpistemicState, tuple[PresentationTreatment, ...]] = MappingProxyType({
    EpistemicState.KNOWN: (ESTABLISHED, INFERENCE, UNCERTAIN, ABSTAIN),
    EpistemicState.INFERRED: (INFERENCE, UNCERTAIN, ABSTAIN),
    EpistemicState.UNCERTAIN: (UNCERTAIN, ABSTAIN),
    EpistemicState.DISPUTED: (DISPUTE, UNCERTAIN, ABSTAIN),
    EpistemicState.UNKNOWN: (UNKNOWN, ABSTAIN),
    EpistemicState.UNVERIFIABLE: (UNVERIFIABLE, ABSTAIN),
})

#: The single strongest treatment permitted for each state UNDER THE
#: UNMODIFIED HARD FLOOR ONLY. Kept for reference/documentation; callers
#: computing a correction hint for a specific evaluation MUST use
#: effective_maximum_treatment(state, policy) instead, which accounts
#: for any active narrowing policy.
HARD_FLOOR_MAXIMUM_TREATMENT: MappingProxyType[EpistemicState, PresentationTreatment] = MappingProxyType({
    state: order[0] for state, order in TREATMENT_STRENGTH_ORDER.items()
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
    hard_floor = HARD_FLOOR_PERMITTED_TREATMENTS[state]
    if policy is None:
        return hard_floor
    override = policy.stricter_permitted_treatments.get(state)
    if override is None:
        return hard_floor
    return hard_floor & override


def effective_maximum_treatment(state: EpistemicState, policy: IntegrityPolicy | None) -> PresentationTreatment:
    """The strongest treatment actually permitted right now, honoring
    any active narrowing policy -- NOT just the unmodified hard floor.
    Always resolves to a real member: validate_policy() rejects any
    policy override that would leave a state with zero permitted
    treatments (see PHASE19_EPISTEMIC_INTEGRITY_SPEC.md's "Policy
    cannot produce an unsatisfiable state"), so this function never
    faces an empty effective set for a validated policy."""
    effective = effective_permitted_treatments(state, policy)
    for treatment in TREATMENT_STRENGTH_ORDER[state]:
        if treatment in effective:
            return treatment
    # Unreachable for any policy that passed validate_policy(); guarded
    # explicitly rather than silently returning a wrong value.
    raise errors.InvalidIntegrityPolicy(
        f"policy leaves state {state.value} with no permitted treatment at all -- "
        f"this should have been rejected by validate_policy()"
    )


def normalize_policy(policy: IntegrityPolicy) -> IntegrityPolicy:
    """Returns a NEW IntegrityPolicy whose `stricter_permitted_treatments`
    is a deeply-frozen MappingProxyType of {EpistemicState: frozenset(...)}
    -- never the caller's own (possibly still-mutable) mapping/set
    objects. Must be called before validate_policy()/
    effective_permitted_treatments()/policy_digest() so evaluation never
    reads live caller-owned structures a caller could mutate mid-call or
    between repeated calls with "the same" policy object."""
    import dataclasses

    if not isinstance(policy.stricter_permitted_treatments, (dict, MappingProxyType)):
        raise errors.InvalidIntegrityPolicy(
            f"policy.stricter_permitted_treatments must be a mapping, got "
            f"{type(policy.stricter_permitted_treatments).__name__}"
        )
    if len(policy.stricter_permitted_treatments) > MAX_POLICY_STATE_ENTRIES:
        raise errors.InvalidIntegrityPolicy("policy declares too many per-state treatment overrides")

    normalized: dict[EpistemicState, frozenset[PresentationTreatment]] = {}
    for state, declared in policy.stricter_permitted_treatments.items():
        if not isinstance(state, EpistemicState):
            raise errors.InvalidIntegrityPolicy(
                f"policy stricter_permitted_treatments key must be a genuine EpistemicState member, "
                f"got {type(state).__name__}"
            )
        if not isinstance(declared, (frozenset, set, tuple, list)):
            raise errors.InvalidIntegrityPolicy(
                f"policy stricter_permitted_treatments[{state.value!r}] must be a frozenset/set/tuple/list "
                f"of PresentationTreatment members, got {type(declared).__name__}"
            )
        # Validate every member's TYPE before ever calling frozenset() on
        # the collection -- frozenset() itself raises a raw, unhelpful
        # TypeError ("unhashable type") for an unhashable member (a
        # dict/list), which must never escape this function. Iterating
        # the raw `declared` container for the type check, rather than a
        # frozenset built from it, avoids that failure mode entirely.
        for member in declared:
            if not isinstance(member, PresentationTreatment):
                raise errors.InvalidIntegrityPolicy(
                    f"policy stricter_permitted_treatments[{state.value!r}] contains a non-PresentationTreatment "
                    f"member: {type(member).__name__}"
                )
        frozen_declared = frozenset(declared)
        if not frozen_declared:
            raise errors.InvalidIntegrityPolicy(
                f"policy stricter_permitted_treatments[{state.value!r}] is empty -- an empty override would make "
                f"that state permanently unsatisfiable; declare a specific stricter non-empty set instead"
            )
        normalized[state] = frozen_declared

    return dataclasses.replace(policy, stricter_permitted_treatments=MappingProxyType(normalized))


def validate_policy(policy: IntegrityPolicy, *, evaluated_at: str | None) -> None:
    """Reject a policy outright if it declares, for any state, a
    permitted-treatment set that is not a SUBSET of the hard floor's own
    set for that state -- i.e. an attempt to add permission beyond the
    floor. Raised as a typed error rather than silently narrowed away,
    so the attempt is observable and testable (see
    tests/integrity/test_policy_monotonicity.py). Callers MUST pass an
    already-`normalize_policy()`-d policy -- this function assumes
    `stricter_permitted_treatments` is already a clean
    {EpistemicState: frozenset[PresentationTreatment]} mapping."""
    for state, declared in policy.stricter_permitted_treatments.items():
        hard_floor = HARD_FLOOR_PERMITTED_TREATMENTS[state]
        if not declared.issubset(hard_floor):
            raise errors.PolicyAttemptedToWeakenHardFloor(
                f"policy declares {sorted(t.value for t in declared - hard_floor)} for state {state.value}, "
                f"which the hard floor ({sorted(t.value for t in hard_floor)}) does not permit"
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


def parse_aware_iso8601(value: str, *, where: str, error_cls: type[errors.IntegrityError]) -> datetime.datetime:
    """Parse an ISO-8601 timestamp that MUST be offset-aware (carry an
    explicit UTC/offset designator, e.g. 'Z' or '+00:00'). A
    syntactically valid but offset-naive timestamp (no timezone) is
    rejected -- comparing a naive and an aware datetime raises a raw
    TypeError in Python, which must never escape this package's public
    boundary. Malformed timestamps also fail closed here rather than
    ever reaching a bare `datetime.fromisoformat` call inside a
    comparison function."""
    try:
        parsed = datetime.datetime.fromisoformat(value.replace("Z", "+00:00"))
    except ValueError as exc:
        raise error_cls(f"{where} is not a valid ISO-8601 timestamp: {exc}") from exc
    if parsed.tzinfo is None:
        raise error_cls(
            f"{where}={value!r} is offset-naive -- freshness comparisons require an explicit UTC/offset "
            f"timestamp (e.g. a trailing 'Z' or '+00:00'), never an ambiguous naive one"
        )
    return parsed


def is_overlay_stale(*, overlay_assessed_at: str, evaluated_at: str, max_overlay_age_seconds: int) -> bool:
    """Deterministic comparison of two EXPLICITLY supplied, offset-aware
    ISO-8601 timestamps -- never a wall-clock read, never a universal
    age heuristic, never a raw TypeError from mixing naive/aware
    datetimes. A negative age (evaluated_at before overlay_assessed_at)
    is treated as not stale rather than raising -- it is a caller
    ordering oddity, not evidence of staleness. Two timestamps at
    different UTC offsets representing the same instant compare equal
    (Python's aware-datetime subtraction already normalizes offsets
    correctly)."""
    assessed = parse_aware_iso8601(overlay_assessed_at, where="overlay.assessed_at", error_cls=errors.InvalidFreshnessConfiguration)
    evaluated = parse_aware_iso8601(evaluated_at, where="evaluated_at", error_cls=errors.InvalidFreshnessConfiguration)
    age_seconds = (evaluated - assessed).total_seconds()
    if age_seconds <= 0:
        return False
    return age_seconds > max_overlay_age_seconds
