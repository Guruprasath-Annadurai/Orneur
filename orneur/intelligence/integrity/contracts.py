"""
Phase 19 structured contracts. All frozen dataclasses, deeply immutable
after construction (see evaluator.py's use of
orneur.intelligence.integrity.freeze.validate_and_freeze -- a small,
deliberate, same-algorithm duplication of Phase 18's own freeze helper,
kept separate only so malformed Phase-19 metadata raises Phase-19's own
typed errors rather than leaking orneur.intelligence.epistemic.errors.*
across this package's public boundary).

Hard architectural decision (see
docs/orneur/phase-19/PHASE19_EPISTEMIC_INTEGRITY_SPEC.md, "Compound
assertions"): a ProposedAssertion references EXACTLY ONE source atom.
Multi-atom/compound assertions are explicitly out of scope for this
version -- inferring AND/OR necessity semantics from a Python list would
be exactly the kind of "fake sophistication" this protocol must not
build. A smaller, formally correct contract is preferable.

Fields such as `trusted`, `verified`, `approved`, `confidence` are
deliberately ABSENT from every contract here -- Phase 18's overlay
remains the only source of epistemic qualification; a proposal cannot
mint its own trust by naming a field that sounds authoritative.
"""
from __future__ import annotations

from dataclasses import dataclass, field
from types import MappingProxyType

from orneur.intelligence.epistemic import EpistemicPolarity, EpistemicState
from orneur.intelligence.integrity.enums import (
    IntegrityObligation,
    IntegrityStatus,
    IntegrityViolationReason,
    PresentationTreatment,
)


@dataclass(frozen=True)
class ProposedAssertion:
    """An UNTRUSTED proposed structured assertion about one atom's
    presentation. `asserted_polarity` is required (non-None) when
    `treatment` is ESTABLISHED or INFERENCE, meaningless otherwise."""

    assertion_id: str
    source_atom_id: str
    treatment: PresentationTreatment
    asserted_polarity: EpistemicPolarity | None = None
    reference: str | None = None
    metadata: MappingProxyType = field(default_factory=lambda: MappingProxyType({}))


@dataclass(frozen=True)
class IntegrityProposal:
    """The untrusted structured answer/assertion contract Phase 19
    evaluates. `required_scope_atom_ids` is the explicit, caller-supplied
    material scope -- Phase 19 does not and cannot infer relevance from
    free-form intent (see PHASE19_EPISTEMIC_INTEGRITY_SPEC.md "Scope and
    conservation")."""

    proposal_id: str
    assertions: tuple[ProposedAssertion, ...] = ()
    required_scope_atom_ids: tuple[str, ...] = ()
    metadata: MappingProxyType = field(default_factory=lambda: MappingProxyType({}))


@dataclass(frozen=True)
class IntegrityPolicy:
    """An OPTIONAL, strictly monotonic policy. `stricter_permitted_treatments`
    may only NARROW the hard floor's permitted-treatment set for a given
    EpistemicState (validated as a subset at evaluation time -- see
    floor.validate_policy) -- it can never widen it. `max_overlay_age_seconds`
    requires the caller to also pass `evaluated_at` to
    evaluator.assess_integrity() -- there is deliberately no second,
    separate "evaluation_at" field here, so there is exactly one source
    of truth for "now" and no wall-clock read is ever implied by the
    policy alone."""

    stricter_permitted_treatments: MappingProxyType = field(default_factory=lambda: MappingProxyType({}))
    max_overlay_age_seconds: int | None = None


@dataclass(frozen=True)
class DisclosureRequirement:
    assertion_id: str
    source_atom_id: str
    epistemic_state: EpistemicState
    obligation: IntegrityObligation


@dataclass(frozen=True)
class IntegrityViolation:
    reason: IntegrityViolationReason
    assertion_id: str | None
    source_atom_id: str | None
    detail: str


@dataclass(frozen=True)
class AssertionAssessment:
    assertion_id: str
    source_atom_id: str
    epistemic_state: EpistemicState
    epistemic_polarity: EpistemicPolarity
    proposed_treatment: PresentationTreatment
    permitted_maximum_treatment: PresentationTreatment
    obligations: tuple[IntegrityObligation, ...] = ()
    violation_reasons: tuple[IntegrityViolationReason, ...] = ()
    satisfied: bool = True


@dataclass(frozen=True)
class IntegrityReceipt:
    protocol_version: str
    receipt_id: str
    source_artifact_id: str
    source_artifact_digest: str
    source_overlay_digest: str
    proposal_digest: str
    policy_digest: str
    evaluated_at: str | None
    assertion_assessments: tuple[AssertionAssessment, ...] = ()
    required_disclosures: tuple[DisclosureRequirement, ...] = ()
    violations: tuple[IntegrityViolation, ...] = ()
    material_scope_coverage: tuple[str, ...] = ()
    omitted_scope_atom_ids: tuple[str, ...] = ()
    integrity_status: IntegrityStatus = IntegrityStatus.SATISFIED
    metadata: MappingProxyType = field(default_factory=lambda: MappingProxyType({}))
