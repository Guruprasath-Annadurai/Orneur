"""
Phase 20 -- Governed Intelligence Router.

Consumes Phase 18 Epistemic State (read-only, via a trusted overlay) and
Phase 19 Epistemic Integrity (read-only, via an optional IntegrityReceipt
plus the REUSED overlay-trust-boundary seam) to deterministically decide
which ORNEUR cognitive family (Genesis/Novus/Aeternum) SHOULD handle a
typed task.

Phase 20 grants NO authority: a RoutingDecision is DATA, never
execution/policy/Court/human-approval/verification-truth/model-
promotion/tool/budget/release authority, and never an authorization to
actually run any model. It does not call any model, tool, or network
endpoint. Routing is not the same thing as permission to execute --
see docs/orneur/phase-20/PHASE20_INTELLIGENCE_ROUTER_SPEC.md's
non-authority doctrine and tests/router/test_no_authority.py.

This package never imports orca.* (see docs' "Relationship to
orca.society.router" section: that is a distinct, lower-layer,
concrete-checkpoint/backend router from an earlier product era: this
package routes at the cognitive-family/role layer, informed by Phase
18/19 signals it does not have).

Only intentional public contracts are exported here.
"""
from __future__ import annotations

from orneur.intelligence.router.canonical import canonicalize, digest, to_canonical_json
from orneur.intelligence.router.contracts import (
    CognitiveTaskProfile,
    IntelligenceCapabilityProfile,
    MaterialEpistemicFactor,
    RoutingCandidateEvaluation,
    RoutingDecision,
)
from orneur.intelligence.router.enums import (
    CURRENT_PROTOCOL_VERSION,
    IMPLEMENTATION_REQUIREMENT_KINDS,
    INVESTIGATIVE_REQUIREMENT_KINDS,
    CognitiveFamily,
    CognitiveRequirementKind,
    CognitiveRole,
    RoutingReasonCode,
    RoutingStatus,
    RuntimeAvailability,
    RuntimeLifecycleState,
)
from orneur.intelligence.router.evaluator import route_task
from orneur.intelligence.router.registry import (
    ELIGIBLE_LIFECYCLE_STATES,
    build_default_capability_registry,
    is_eligible,
    registry_digest,
    validate_registry,
)

__all__ = [
    "CURRENT_PROTOCOL_VERSION",
    "ELIGIBLE_LIFECYCLE_STATES",
    "IMPLEMENTATION_REQUIREMENT_KINDS",
    "INVESTIGATIVE_REQUIREMENT_KINDS",
    "CognitiveFamily",
    "CognitiveRequirementKind",
    "CognitiveRole",
    "CognitiveTaskProfile",
    "IntelligenceCapabilityProfile",
    "MaterialEpistemicFactor",
    "RoutingCandidateEvaluation",
    "RoutingDecision",
    "RoutingReasonCode",
    "RoutingStatus",
    "RuntimeAvailability",
    "RuntimeLifecycleState",
    "build_default_capability_registry",
    "canonicalize",
    "digest",
    "is_eligible",
    "registry_digest",
    "route_task",
    "to_canonical_json",
    "validate_registry",
]
