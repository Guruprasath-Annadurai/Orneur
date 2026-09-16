"""
Phase 18 closed vocabularies.

Doctrine (see docs/orneur/phase-18/PHASE18_EPISTEMIC_STATE_SPEC.md):
  Provenance is not truth. Citation is not verification. Evidence
  reference is not evidence verification. Model confidence is not
  knowledge. Human input is not automatically fact. Missing evidence is
  not falsehood. Contradiction must not be hidden by confidence.
  UNVERIFIABLE is not a synonym for UNKNOWN. KNOWN is not a synonym for
  "the model sounded certain."

Every enum here is closed: unrecognized values fail closed (no aliases,
no silent fallback, no catch-all member). Phase 18 owns these
vocabularies; Phase 17 (OCL)'s SourceClass, AtomKind and RelationKind
are read-only inputs, never redefined here.
"""
from __future__ import annotations

from dataclasses import dataclass
from enum import Enum
from types import MappingProxyType

from orneur.intelligence.ocl.enums import AtomKind, RelationKind


class EpistemicState(str, Enum):
    """A cognitive proposition's assessed knowledge state, relative to an
    explicit evidence/derivation/contradiction/feasibility basis and an
    explicit assessment context. Independently computed -- never
    model-writable (see resolver.assess_artifact)."""

    KNOWN = "KNOWN"
    INFERRED = "INFERRED"
    UNCERTAIN = "UNCERTAIN"
    DISPUTED = "DISPUTED"
    UNKNOWN = "UNKNOWN"
    UNVERIFIABLE = "UNVERIFIABLE"


class EpistemicPolarity(str, Enum):
    """Claim direction, orthogonal to epistemic quality. KNOWN does not
    mean TRUE -- a claim can be KNOWN+AFFIRMED or KNOWN+REFUTED."""

    AFFIRMED = "AFFIRMED"
    REFUTED = "REFUTED"
    MIXED = "MIXED"
    UNRESOLVED = "UNRESOLVED"


class EvidenceResolutionStatus(str, Enum):
    """How a trusted resolver assessed one piece of referenced evidence.
    An EvidenceAnchor (Phase 17) only REFERENCES evidence; this status is
    the separate, out-of-band resolution of that reference."""

    VERIFIED = "VERIFIED"
    UNVERIFIED = "UNVERIFIED"
    STALE = "STALE"
    UNAVAILABLE = "UNAVAILABLE"
    INVALID = "INVALID"


class EvidenceStance(str, Enum):
    """Which direction resolved evidence points, independent of whether
    it was successfully resolved at all."""

    SUPPORTS = "SUPPORTS"
    REFUTES = "REFUTES"
    INCONCLUSIVE = "INCONCLUSIVE"


class EpistemicResolutionTrustContext(str, Enum):
    """Trust context for an entire batch of evidence resolutions /
    feasibility records, supplied by the CALLER of the resolver, never
    parsed from a payload. Mirrors orneur.intelligence.ocl.trust's
    CompilationTrustContext pattern exactly: a bare string equal to a
    member's value is NOT a valid trust context (see trust.py)."""

    UNTRUSTED = "UNTRUSTED"
    TRUSTED_TOOL_RESOLVER = "TRUSTED_TOOL_RESOLVER"
    TRUSTED_DETERMINISTIC_VERIFIER = "TRUSTED_DETERMINISTIC_VERIFIER"


class VerificationFeasibility(str, Enum):
    """Whether verification of a proposition is even possible right now.
    Only TRUSTED_DETERMINISTIC_VERIFIER-tier records may set
    STRUCTURALLY_UNVERIFIABLE (see trust.py); a model or a failed tool
    call may not."""

    AVAILABLE = "AVAILABLE"
    PENDING = "PENDING"
    TEMPORARILY_UNAVAILABLE = "TEMPORARILY_UNAVAILABLE"
    STRUCTURALLY_UNVERIFIABLE = "STRUCTURALLY_UNVERIFIABLE"


class EpistemicReasonCode(str, Enum):
    """Closed, typed reasons for a canonical state assignment. Required
    for auditability; free-form text is never the only explanation."""

    DIRECT_VERIFIED_SUPPORT = "DIRECT_VERIFIED_SUPPORT"
    DIRECT_VERIFIED_REFUTATION = "DIRECT_VERIFIED_REFUTATION"
    EVIDENCE_BACKED_DERIVATION = "EVIDENCE_BACKED_DERIVATION"
    UNVERIFIED_EVIDENCE = "UNVERIFIED_EVIDENCE"
    STALE_EVIDENCE = "STALE_EVIDENCE"
    EVIDENCE_UNAVAILABLE = "EVIDENCE_UNAVAILABLE"
    EVIDENCE_INVALID = "EVIDENCE_INVALID"
    EVIDENCE_INCONCLUSIVE = "EVIDENCE_INCONCLUSIVE"
    VERIFIED_CONTRADICTION = "VERIFIED_CONTRADICTION"
    UNQUALIFIED_CONTRADICTION = "UNQUALIFIED_CONTRADICTION"
    VERIFICATION_PENDING = "VERIFICATION_PENDING"
    TEMPORARY_VERIFICATION_UNAVAILABLE = "TEMPORARY_VERIFICATION_UNAVAILABLE"
    STRUCTURALLY_UNVERIFIABLE = "STRUCTURALLY_UNVERIFIABLE"
    NO_EPISTEMIC_BASIS = "NO_EPISTEMIC_BASIS"
    CONTRADICTED_BY_QUALIFIED_ATOM = "CONTRADICTED_BY_QUALIFIED_ATOM"


class RelationEffect(str, Enum):
    """What a RelationKind contributes to epistemic propagation. Any
    RelationKind not explicitly mapped in RELATION_EPISTEMIC_SEMANTICS
    defaults to NONE -- fail closed, never guess a relation's meaning."""

    SUPPORT = "SUPPORT"
    REFUTATION = "REFUTATION"
    CONFLICT = "CONFLICT"
    NONE = "NONE"


@dataclass(frozen=True)
class RelationEpistemicSemantics:
    effect: RelationEffect
    # True: the relation's *source* atom, once established, propagates
    #       its polarity onto the *target* atom (e.g. SUPPORTS, FALSIFIES).
    # False: the relation's *target* atom, once established, propagates
    #        its polarity onto the *source* atom (e.g. DERIVED_FROM,
    #        where "A DERIVED_FROM B" means B is A's basis).
    # Meaningless for CONFLICT/NONE.
    propagates_from_source_to_target: bool = True


_RELATION_NONE_SEMANTICS = RelationEpistemicSemantics(RelationEffect.NONE)

#: Only relations with a rigorously reasoned-through direction get real
#: semantics here (see docs/orneur/phase-18/PHASE18_EPISTEMIC_STATE_SPEC.md
#: section "Relation semantics"). Every other RelationKind -- including
#: CAUSES and CORRELATES_WITH, which must never automatically prove
#: truth -- contributes RelationEffect.NONE via get_relation_semantics().
RELATION_EPISTEMIC_SEMANTICS: MappingProxyType[RelationKind, RelationEpistemicSemantics] = MappingProxyType({
    RelationKind.SUPPORTS: RelationEpistemicSemantics(
        RelationEffect.SUPPORT, propagates_from_source_to_target=True,
    ),
    RelationKind.CONTRADICTS: RelationEpistemicSemantics(
        RelationEffect.CONFLICT,
    ),
    RelationKind.DERIVED_FROM: RelationEpistemicSemantics(
        RelationEffect.SUPPORT, propagates_from_source_to_target=False,
    ),
    RelationKind.FALSIFIES: RelationEpistemicSemantics(
        RelationEffect.REFUTATION, propagates_from_source_to_target=True,
    ),
})


def get_relation_semantics(kind: RelationKind) -> RelationEpistemicSemantics:
    return RELATION_EPISTEMIC_SEMANTICS.get(kind, _RELATION_NONE_SEMANTICS)


#: Not every OCL atom is a truth proposition. QUESTION, TEST_PROPOSAL,
#: ACTION_PROPOSAL, VERIFICATION_REQUEST, ESCALATION_REQUEST, LIMITATION,
#: CONSTRAINT, DECISION_PROPOSAL, CONFLICT and UNKNOWN are deliberately
#: excluded -- they are requests, proposals, meta-nodes or declarations,
#: not claims that can be resolved true/false. Requesting assessment of
#: an excluded kind raises errors.NonAssessableAtomKind rather than
#: inventing semantics for it.
EPISTEMICALLY_ASSESSABLE_ATOM_KINDS: frozenset[AtomKind] = frozenset({
    AtomKind.ASSERTION,
    AtomKind.OBSERVATION_REFERENCE,
    AtomKind.HYPOTHESIS,
    AtomKind.ASSUMPTION,
    AtomKind.PREDICTION,
    AtomKind.ALTERNATIVE,
    AtomKind.COUNTEREXAMPLE,
    AtomKind.CAUSAL_HYPOTHESIS,
})

CURRENT_SCHEMA_VERSION = "18.0.0"
