"""
SocietyPlan construction for multi-role tasks (Phase 7 spec §17-18).
Never forces cosmetic model diversity -- if the same checkpoint is the
only eligible candidate for two roles, it is used for both and
`same_model_role_overlap` is set honestly (spec §18).
"""
from __future__ import annotations

from orca.society.contracts import CognitiveRole, RoleAssignment, RoutingRequest, SocietyPlan
from orca.society.router import route


def build_court_society_plan(
    *,
    risk_level: str = "LOW",
    complexity_level: str = "LOW",
    evidence_requirement: str = "SUPPORTED",
    allow_experimental: bool = False,
    allowed_capability_classes: list[str] | None = None,
    trace_id: str | None = None,
    profiles: dict | None = None,
    checkpoint_lookup=None,
    deployment_lookup=None,
    exclude_model_ids: list[str] | None = None,
) -> SocietyPlan:
    """
    Builds the Constructor/Falsifier assignment for one Cognitive Court
    invocation. EvidenceClerk/RiskCounsel/Arbiter are NOT included -- they
    remain deterministic, model-free roles (Phase 6 design, unchanged by
    Phase 7 spec §41).

    `exclude_model_ids` (Phase 7.1 spec §12-13): model/checkpoint ids a
    caller's WorldState has recorded as currently unavailable
    (`orca.deliberation.worldstate_ops.unavailable_model_ids`) -- excluded
    from BOTH Constructor's and Falsifier's candidate pool, a real
    WorldState-driven routing consequence, not a cosmetic diversity trick.
    """
    allowed_capability_classes = allowed_capability_classes or []
    exclude_model_ids = exclude_model_ids or []

    constructor_request = RoutingRequest(
        role=CognitiveRole.CONSTRUCTOR, trace_id=trace_id, risk_level=risk_level,
        complexity_level=complexity_level, evidence_requirement=evidence_requirement,
        allow_experimental=allow_experimental, allowed_capability_classes=allowed_capability_classes,
        exclude_model_ids=exclude_model_ids,
    )
    constructor_decision = route(constructor_request, profiles=profiles, checkpoint_lookup=checkpoint_lookup, deployment_lookup=deployment_lookup)

    falsifier_request = RoutingRequest(
        role=CognitiveRole.FALSIFIER, trace_id=trace_id, risk_level=risk_level,
        complexity_level=complexity_level, evidence_requirement=evidence_requirement,
        allow_experimental=allow_experimental, allowed_capability_classes=allowed_capability_classes,
        exclude_model_ids=exclude_model_ids,
        # Do not manufacture cosmetic diversity (spec §18) -- Falsifier is
        # NOT told to exclude Constructor's model beyond WorldState-driven
        # unavailability shared above. If a genuinely different eligible
        # model exists and scores higher, the router will pick it on its
        # own merits; if not, honest same-model overlap follows.
    )
    falsifier_decision = route(falsifier_request, profiles=profiles, checkpoint_lookup=checkpoint_lookup, deployment_lookup=deployment_lookup)

    overlap = (
        constructor_decision.selected_checkpoint_id is not None
        and constructor_decision.selected_checkpoint_id == falsifier_decision.selected_checkpoint_id
    )
    constructor_decision.same_model_role_overlap = overlap
    falsifier_decision.same_model_role_overlap = overlap

    plan = SocietyPlan(
        assignments=[
            RoleAssignment(role=CognitiveRole.CONSTRUCTOR, routing_decision=constructor_decision),
            RoleAssignment(role=CognitiveRole.FALSIFIER, routing_decision=falsifier_decision),
        ],
        # Constructor and Falsifier are independent role assignments and
        # COULD run concurrently -- Phase 6's EpistemicTwin.run() calls
        # Falsifier with Constructor's structured output as input, so they
        # are NOT actually independent at the call-sequencing level (a
        # real, disclosed constraint, not a Phase 7 regression: Falsifier
        # needs Constructor's claims to falsify). parallelizable_groups is
        # therefore empty, not a fabricated concurrency claim.
        parallelizable_groups=[],
        dependencies={CognitiveRole.FALSIFIER.value: [CognitiveRole.CONSTRUCTOR.value]},
        fallbacks={
            CognitiveRole.CONSTRUCTOR.value: "no lower-tier fallback below legacy Genesis exists",
            CognitiveRole.FALSIFIER.value: "no lower-tier fallback below legacy Genesis exists",
        },
        escalation_conditions=["unresolved falsifier objection", "critical contradiction", "risk HIGH/CRITICAL"],
        same_model_role_overlap=overlap,
    )
    return plan
