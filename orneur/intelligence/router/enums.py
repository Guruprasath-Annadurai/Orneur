"""
Phase 20 closed vocabularies. Every enum is closed: unrecognized values
fail closed. Reuses Phase 18's EpistemicState/EpistemicPolarity and
Phase 19's IntegrityStatus/IntegrityOverlayTrustContext directly
(imported, never redefined) -- only genuinely new Phase-20 concepts get
new enums here.

RoutingStatus deliberately does NOT reuse the Cognitive Court's closed
verdict vocabulary (ACCEPT/REJECT/NEED_MORE_EVIDENCE/ESCALATE/
HUMAN_APPROVAL_REQUIRED, in orca.mission.cognitive_court) -- routing is
cognitive orchestration DATA, never a Court verdict, never authority.
"""
from __future__ import annotations

from enum import Enum


class CognitiveFamily(str, Enum):
    """The three canonical ORNEUR native cognitive families. Cognitive
    ROLES, not a size/benchmark ranking -- see
    docs/PHASE20_INTELLIGENCE_ROUTER.md's "Model-family truth"."""

    GENESIS = "GENESIS"
    NOVUS = "NOVUS"
    AETERNUM = "AETERNUM"


class CognitiveRole(str, Enum):
    """Mirrors orca.registry.model_spec's canonical role framing (cited,
    not imported -- this package never imports orca.*). A closed enum
    identifier for what is otherwise prose in the model registry."""

    BUILDER_EXECUTOR = "BUILDER_EXECUTOR"
    REASONER_INVESTIGATOR = "REASONER_INVESTIGATOR"
    CRITIC_ARBITER_DISCOVERER = "CRITIC_ARBITER_DISCOVERER"


class RuntimeLifecycleState(str, Enum):
    """Phase 20's OWN closed lifecycle vocabulary, scoped narrowly to
    ROUTING ELIGIBILITY -- not a redefinition or replacement of
    orca.registry.model_spec.LifecycleState (a different, wider concern
    this package does not import). Only EXPERIMENTAL/PROMOTABLE/
    PRODUCTION are ever routing-eligible (see registry.ELIGIBLE_LIFECYCLE_STATES)."""

    NOT_TRAINED = "NOT_TRAINED"
    EXPERIMENTAL = "EXPERIMENTAL"
    PROMOTABLE = "PROMOTABLE"
    PRODUCTION = "PRODUCTION"
    RETIRED = "RETIRED"


class RuntimeAvailability(str, Enum):
    """Whether an EXECUTABLE runtime genuinely exists for a family right
    now -- a model concept/role existing in the registry does NOT imply
    a runtime is available to actually execute it."""

    AVAILABLE = "AVAILABLE"
    UNAVAILABLE = "UNAVAILABLE"


class CognitiveRequirementKind(str, Enum):
    """A closed vocabulary of task-requirement kinds. Not overfit to the
    three current families -- a future family registers which of these
    it supports, the router never hardcodes family<->requirement logic
    outside registry.py."""

    IMPLEMENTATION = "IMPLEMENTATION"
    EXECUTION_PLANNING = "EXECUTION_PLANNING"
    ARCHITECTURE = "ARCHITECTURE"
    INVESTIGATION = "INVESTIGATION"
    CAUSAL_REASONING = "CAUSAL_REASONING"
    UNCERTAINTY_RESOLUTION = "UNCERTAINTY_RESOLUTION"
    CONTRADICTION_RESOLUTION = "CONTRADICTION_RESOLUTION"
    ADVERSARIAL_REVIEW = "ADVERSARIAL_REVIEW"
    SECURITY_SENSITIVE_REASONING = "SECURITY_SENSITIVE_REASONING"
    HIGH_CONSEQUENCE_REASONING = "HIGH_CONSEQUENCE_REASONING"
    VERIFICATION = "VERIFICATION"
    EVIDENCE_SYNTHESIS = "EVIDENCE_SYNTHESIS"
    DISCOVERY_EXPLORATION = "DISCOVERY_EXPLORATION"


#: Requirement kinds that, by themselves, signal the task is primarily
#: investigative/reasoning-shaped -- used to derive a preferred
#: CognitiveRole.REASONER_INVESTIGATOR for primary selection (never a
#: preferred FAMILY -- see evaluator._select_primary). ARCHITECTURE is
#: included: architecture/design reasoning is epistemic-causal work,
#: not implementation, matching Novus's canonical role framing.
INVESTIGATIVE_REQUIREMENT_KINDS: frozenset[CognitiveRequirementKind] = frozenset({
    CognitiveRequirementKind.INVESTIGATION,
    CognitiveRequirementKind.CAUSAL_REASONING,
    CognitiveRequirementKind.UNCERTAINTY_RESOLUTION,
    CognitiveRequirementKind.CONTRADICTION_RESOLUTION,
    CognitiveRequirementKind.EVIDENCE_SYNTHESIS,
    CognitiveRequirementKind.ARCHITECTURE,
})

#: Requirement kinds that signal ordinary implementation/build work --
#: used to derive a preferred CognitiveRole.BUILDER_EXECUTOR.
IMPLEMENTATION_REQUIREMENT_KINDS: frozenset[CognitiveRequirementKind] = frozenset({
    CognitiveRequirementKind.IMPLEMENTATION,
    CognitiveRequirementKind.EXECUTION_PLANNING,
    CognitiveRequirementKind.VERIFICATION,
})

#: Requirement kinds that are themselves PRIMARY critic/discoverer work
#: (not a "review of something else" slot signal -- see
#: _REVIEW_TRIGGER_KINDS in evaluator.py) -- used to derive a preferred
#: CognitiveRole.CRITIC_ARBITER_DISCOVERER for primary selection.
DISCOVERY_REQUIREMENT_KINDS: frozenset[CognitiveRequirementKind] = frozenset({
    CognitiveRequirementKind.DISCOVERY_EXPLORATION,
})


class RoutingStatus(str, Enum):
    """Top-level routing decision status. NEVER a Cognitive Court
    verdict -- see module docstring."""

    SELECTED = "SELECTED"
    INVESTIGATION_REQUIRED = "INVESTIGATION_REQUIRED"
    REVIEW_REQUIRED = "REVIEW_REQUIRED"
    NO_ELIGIBLE_ROUTE = "NO_ELIGIBLE_ROUTE"
    BLOCKED_BY_INTEGRITY = "BLOCKED_BY_INTEGRITY"


class RoutingReasonCode(str, Enum):
    """Closed, typed reasons behind a routing decision or a candidate's
    rejection. No uncontrolled free-form failure classification."""

    ELIGIBLE_CAPABILITY_MATCH = "ELIGIBLE_CAPABILITY_MATCH"
    CAPABILITY_ABSENT = "CAPABILITY_ABSENT"
    RUNTIME_UNAVAILABLE = "RUNTIME_UNAVAILABLE"
    LIFECYCLE_INELIGIBLE = "LIFECYCLE_INELIGIBLE"
    CAUSAL_INVESTIGATION_REQUIRED = "CAUSAL_INVESTIGATION_REQUIRED"
    UNCERTAIN_PREMISE_REQUIRES_INVESTIGATION = "UNCERTAIN_PREMISE_REQUIRES_INVESTIGATION"
    UNKNOWN_PREMISE_REQUIRES_INVESTIGATION = "UNKNOWN_PREMISE_REQUIRES_INVESTIGATION"
    DISPUTED_PREMISE_REQUIRES_REVIEW = "DISPUTED_PREMISE_REQUIRES_REVIEW"
    ADVERSARIAL_REVIEW_REQUIRED = "ADVERSARIAL_REVIEW_REQUIRED"
    ADVERSARIAL_REVIEWER_UNAVAILABLE = "ADVERSARIAL_REVIEWER_UNAVAILABLE"
    INTEGRITY_BLOCKED = "INTEGRITY_BLOCKED"
    NO_CANDIDATE_ELIGIBLE = "NO_CANDIDATE_ELIGIBLE"
    PREFERENCE_NOT_ELIGIBLE = "PREFERENCE_NOT_ELIGIBLE"
    HIGH_CONSEQUENCE_REQUIRES_REVIEW = "HIGH_CONSEQUENCE_REQUIRES_REVIEW"
    NO_COGNITIVE_REQUIREMENT = "NO_COGNITIVE_REQUIREMENT"
    MANDATORY_REVIEWER_CANNOT_BE_PRIMARY_FAMILY = "MANDATORY_REVIEWER_CANNOT_BE_PRIMARY_FAMILY"
    ROLE_ADEQUACY_NOT_SATISFIED = "ROLE_ADEQUACY_NOT_SATISFIED"

class CapabilityRegistryTrustContext(str, Enum):
    """Out-of-band trust judgment for a CALLER-SUPPLIED capability
    registry, mirroring Phase 19's IntegrityOverlayTrustContext
    doctrine one layer up: structural validity (validate_registry())
    proves only that a registry is well-formed, never that it was
    genuinely produced by trusted router configuration. UNTRUSTED (or
    omission) always fails closed. Never satisfied by a bare string
    equal to a member's .value, and never parsed from registry/task
    metadata -- see registry.verify_trusted_registry."""

    UNTRUSTED = "UNTRUSTED"
    TRUSTED_ROUTER_CONFIGURATION = "TRUSTED_ROUTER_CONFIGURATION"


class IntegrityReceiptTrustContext(str, Enum):
    """Out-of-band trust judgment for a CALLER-SUPPLIED Phase-19
    IntegrityReceipt, mirroring IntegrityOverlayTrustContext one layer
    up: isinstance(receipt, IntegrityReceipt) proves only that the
    object is shaped like a receipt, never that it was genuinely
    produced by a trusted Phase-19 evaluation run for the artifact/
    overlay currently being routed. UNTRUSTED (or omission) always
    fails closed -- see receipt_trust.verify_trusted_receipt."""

    UNTRUSTED = "UNTRUSTED"
    TRUSTED_PHASE19_RUNTIME = "TRUSTED_PHASE19_RUNTIME"


CURRENT_PROTOCOL_VERSION = "20.0.0"
