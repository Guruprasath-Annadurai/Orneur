"""
Adaptive, evidence-weighted routing (Phase 7 spec §11-16). Deterministic
and testable, NOT a trained neural router (spec §14 explicitly forbids
fabricating one). Two strict phases, never blurred together (spec §13):

  1. HARD FILTERS -- lifecycle, artifact availability, entitlement,
     context window, caller exclusions, best-effort deployment health/
     circuit-breaker state. A candidate that fails any of these is
     dropped before scoring ever runs; no score can resurrect it.
  2. SOFT RANKING -- role suitability, safety, calibration, lifecycle
     maturity, cost preference. Explicit, documented weights (not hidden
     in a black box), applied only to candidates that survived step 1.

Reuses existing, tested infrastructure rather than re-deriving it:
`orca.registry.model_registry`/`model_spec` for lifecycle,
`orca.registry.checkpoint.CheckpointRecord` for artifact availability,
`orca.cognitive.entitlement` for entitlement, `orca.gateway.deployment`/
`orca.gateway.circuit_breaker` for health where a deployment record
actually exists (see docs/orneur/phase-7/CURRENT_MODEL_ROUTING.md's
disclosed gap: legacy Ollama-tier serving does not populate deployment
records today, so this check is best-effort, not universally enforced).
"""
from __future__ import annotations

from orca.registry.checkpoint import CheckpointRecord
from orca.society.contracts import (
    CognitiveRole,
    ModelCapabilityProfile,
    RoutingCandidate,
    RoutingDecision,
    RoutingReason,
    RoutingRequest,
)
from orca.society.lifecycle import is_experimental, is_lifecycle_disqualified, lifecycle_rank
from orca.society.profiles import list_current_profiles
from orca.society.role_requirements import requirement_for

# Legacy tier a family maps to, for entitlement checks -- reuses
# orca.cognitive.entitlement's existing tier vocabulary rather than
# inventing a second one.
_FAMILY_TO_TIER = {"genesis": "nano", "novus": "core", "aeternum": "ultra"}
_MODEL_ID_TO_TIER = {"orneur-genesis": "nano", "orneur-novus": "core", "orneur-aeternum": "ultra"}


def model_id_to_tier(model_id: str) -> str:
    """The one place a RoutingDecision's selected model_id becomes the
    legacy tier string `orca.truth.llm.gateway_json_call`/
    `orca.serve.registry.resolve_tier_backend` still expect -- Model
    Society routes by role/capability, but the actual serving call today
    still speaks the pre-existing tier vocabulary (see
    docs/orneur/phase-7/CURRENT_MODEL_ROUTING.md)."""
    return _MODEL_ID_TO_TIER.get(model_id, "nano")

# Explicit, testable scoring weights (spec §14). Sum to 1.0.
W_ROLE_SUITABILITY = 0.50
W_SAFETY = 0.20
W_CALIBRATION = 0.15
W_LIFECYCLE_MATURITY = 0.10
W_COST = 0.05


def _default_checkpoint_lookup(checkpoint_id: str) -> CheckpointRecord | None:
    try:
        return CheckpointRecord.load(checkpoint_id)
    except FileNotFoundError:
        return None


def _default_deployment_lookup(model_id: str) -> list:
    from orca.gateway.deployment import list_deployments
    return list_deployments(model_id=model_id)


def _checkpoint_available(checkpoint_id: str, checkpoint_lookup) -> tuple[bool, str]:
    record = checkpoint_lookup(checkpoint_id)
    if record is None:
        return False, f"no CheckpointRecord on file for '{checkpoint_id}'"
    if not record.is_routable():
        return False, f"checkpoint availability={record.availability}, not LOCAL"
    return True, "available"


def _deployment_health_ok(model_id: str, allow_experimental: bool, deployment_lookup) -> tuple[bool, str]:
    """
    Best-effort: only enforced when a ModelDeployment record actually
    exists for this model_id. No deployment records exist today for the
    legacy tier-based Ollama serving path (see CURRENT_MODEL_ROUTING.md) --
    absence of a record is NOT treated as unhealthy, only a present,
    unhealthy record is. `deployment_lookup` is injectable (default: real
    `orca.gateway.deployment.list_deployments`) so unit tests that pass
    synthetic profiles are not accidentally coupled to real, global
    on-disk deployment state (a real hazard found during this phase's own
    development -- see ADAPTIVE_ROUTER.md's disclosed gap).
    """
    deployments = deployment_lookup(model_id)
    if not deployments:
        return True, "no deployment record on file -- health check skipped (documented gap)"
    if any(d.is_routable(allow_experimental=allow_experimental) for d in deployments):
        return True, "at least one routable deployment found"
    return False, "no deployment for this model_id is currently routable (health/lifecycle/warmup)"


def _entitlement_ok(family: str, allowed_capability_classes: list[str]) -> tuple[bool, str]:
    if not allowed_capability_classes:
        return True, "no entitlement constraint supplied -- not checked"
    from orca.cognitive.entitlement import tier_to_class

    tier = _FAMILY_TO_TIER.get(family, "core")
    required_class = tier_to_class(tier).value
    if required_class in allowed_capability_classes:
        return True, f"entitlement permits {required_class}"
    return False, f"entitlement does not permit {required_class} (family={family})"


def _build_candidate(family: str, profile: ModelCapabilityProfile | None, request: RoutingRequest, checkpoint_lookup, deployment_lookup) -> RoutingCandidate:
    if profile is None:
        # Aeternum: family is defined but has no trained checkpoint at all.
        # Always represented explicitly as a rejected candidate so its
        # absence is auditable, never silently omitted (spec §10/§22/§47).
        return RoutingCandidate(
            model_id=f"orneur-{family}",
            checkpoint_id=f"orneur-{family}(absent)",
            profile=ModelCapabilityProfile(model_id=f"orneur-{family}", checkpoint_id=f"orneur-{family}(absent)", lifecycle_state="ABSENT"),
            eligible=False,
            rejection_reasons=[RoutingReason.AETERNUM_ABSENT] if family == "aeternum" else [RoutingReason.NO_ELIGIBLE_CANDIDATE],
        )

    candidate = RoutingCandidate(model_id=profile.model_id, checkpoint_id=profile.checkpoint_id, profile=profile)
    reasons: list[RoutingReason] = []

    if profile.checkpoint_id in request.exclude_model_ids:
        reasons.append(RoutingReason.EXCLUDED_BY_CALLER)

    if is_lifecycle_disqualified(profile.lifecycle_state):
        reasons.append(RoutingReason.LIFECYCLE_DISQUALIFIED)
    elif is_experimental(profile.lifecycle_state) and not request.allow_experimental:
        reasons.append(
            RoutingReason.NOVUS_REJECTED_LIFECYCLE if family == "novus" else RoutingReason.LIFECYCLE_DISQUALIFIED
        )

    available, _ = _checkpoint_available(profile.checkpoint_id, checkpoint_lookup)
    if not available:
        reasons.append(RoutingReason.ARTIFACT_UNAVAILABLE)

    requirement = requirement_for(request.role)
    if profile.context_length is not None and profile.context_length < requirement.min_context_tokens:
        reasons.append(RoutingReason.CONTEXT_REQUIREMENT_UNMET)

    entitled, _ = _entitlement_ok(family, request.allowed_capability_classes)
    if not entitled:
        reasons.append(RoutingReason.ENTITLEMENT_LIMIT)

    healthy, _ = _deployment_health_ok(profile.model_id, request.allow_experimental, deployment_lookup)
    if not healthy:
        reasons.append(RoutingReason.DEPLOYMENT_UNHEALTHY)

    candidate.eligible = not reasons
    candidate.rejection_reasons = reasons
    return candidate


def _score(candidate: RoutingCandidate, role: CognitiveRole, cost_sensitive: bool) -> tuple[float, dict[str, float]]:
    profile = candidate.profile
    cap = profile.capability_for(role)
    role_suitability = float(cap.score) if cap.is_measured else 0.0

    safety = 1.0 if profile.safety_status not in ("NOT_PROMOTABLE",) and profile.safety_status != "UNMEASURED" else (
        0.0 if profile.safety_status == "NOT_PROMOTABLE" else 0.3
    )
    calibration = float(profile.calibration_status) if isinstance(profile.calibration_status, (int, float)) else 0.0
    lifecycle_maturity = max(0.0, lifecycle_rank(profile.lifecycle_state)) / 3.0
    cost = 1.0 if (profile.cost_class == "LOCAL_SELF_HOSTED" or not cost_sensitive) else 0.5

    breakdown = {
        "role_suitability": role_suitability * W_ROLE_SUITABILITY,
        "safety": safety * W_SAFETY,
        "calibration": calibration * W_CALIBRATION,
        "lifecycle_maturity": lifecycle_maturity * W_LIFECYCLE_MATURITY,
        "cost": cost * W_COST,
    }
    return sum(breakdown.values()), breakdown


def route(
    request: RoutingRequest,
    profiles: dict[str, ModelCapabilityProfile | None] | None = None,
    checkpoint_lookup=None,
    deployment_lookup=None,
) -> RoutingDecision:
    """
    Deterministic routing decision for a single CognitiveRole request.
    `profiles` defaults to the real current profiles
    (orca.society.profiles.list_current_profiles); `checkpoint_lookup`/
    `deployment_lookup` default to the real on-disk registry/deployment
    readers. All three are overridable so unit tests can be fully
    hermetic (never accidentally coupled to real, global ORCA_HOME state).
    """
    profiles = profiles if profiles is not None else list_current_profiles()
    checkpoint_lookup = checkpoint_lookup or _default_checkpoint_lookup
    deployment_lookup = deployment_lookup or _default_deployment_lookup

    candidates = [_build_candidate(family, profile, request, checkpoint_lookup, deployment_lookup) for family, profile in profiles.items()]

    for c in candidates:
        if c.eligible:
            c.score, c.score_breakdown = _score(c, request.role, request.cost_sensitive)

    eligible = [c for c in candidates if c.eligible]
    decision = RoutingDecision(
        requested_role=request.role,
        trace_id=request.trace_id,
        eligible_candidates=[c.checkpoint_id for c in eligible],
        rejected_candidates=[c.checkpoint_id for c in candidates if not c.eligible],
        rejection_reasons={c.checkpoint_id: [r.value for r in c.rejection_reasons] for c in candidates if not c.eligible},
    )

    if not eligible:
        decision.reasons.append(RoutingReason.NO_ELIGIBLE_CANDIDATE.value)
        return decision

    # Deterministic tie-break: highest score, then lexical checkpoint_id.
    best = sorted(eligible, key=lambda c: (-c.score, c.checkpoint_id))[0]
    decision.selected_model_id = best.model_id
    decision.selected_checkpoint_id = best.checkpoint_id
    decision.capability_evidence = list(best.profile.capability_for(request.role).evaluation_ids)
    decision.degraded = best.profile.lifecycle_state != "PRODUCTION"
    decision.reasons.append(RoutingReason.SELECTED.value)
    if best.profile.model_id == "orneur-genesis":
        decision.reasons.append(RoutingReason.LEGACY_GENESIS_SELECTED_FOR_FAST_ROLE.value)
    if best.profile.model_id == "orneur-novus" and requirement_for(request.role).requires_verification:
        decision.reasons.append(RoutingReason.VERIFICATION_QUALITY_PREFERRED.value)
    if request.latency_budget_ms is not None and request.latency_budget_ms < 5000 and best.model_id == "orneur-genesis":
        decision.reasons.append(RoutingReason.LOW_LATENCY_PREFERENCE.value)
    return decision
