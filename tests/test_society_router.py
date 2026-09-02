"""
Model Society adaptive router tests (Phase 7). Deterministic -- no live
model calls. Uses the REAL current profiles (orca.society.profiles) since
they reflect real, on-disk registry/evaluation state, and also exercises
`route()` against synthetic profiles to test specific hard-filter/scoring
behavior in isolation.
"""
from __future__ import annotations

from orca.society.contracts import (
    CognitiveRole,
    ModelCapability,
    ModelCapabilityProfile,
    ProfileState,
    RoutingReason,
    RoutingRequest,
    UNMEASURED,
)
from orca.society.lifecycle import LEGACY_PRODUCTION_SERVING
from orca.society.router import route


class _FakeCheckpointRecord:
    def __init__(self, available: bool = True):
        self.availability = "LOCAL" if available else "MISSING"

    def is_routable(self) -> bool:
        return self.availability == "LOCAL"


def _fake_checkpoint_lookup(checkpoint_id: str):
    """Every synthetic checkpoint in this test file is treated as LOCALLY
    available -- fully hermetic, never touches real ORCA_HOME state."""
    return _FakeCheckpointRecord(available=True)


def _fake_deployment_lookup(model_id: str) -> list:
    """No deployment records -- matches the real, disclosed default state
    of this codebase's legacy tier-based serving path, without depending
    on whatever happens to be on real disk right now."""
    return []


def _profiles(novus_lifecycle: str = "EXPERIMENTAL") -> dict:
    genesis = ModelCapabilityProfile(
        model_id="orneur-genesis", checkpoint_id="orca-nano-v7",
        lifecycle_state=LEGACY_PRODUCTION_SERVING, profile_state=ProfileState.UNMEASURED,
        context_length=4096,
        capabilities={CognitiveRole.CONSTRUCTOR.value: ModelCapability(role=CognitiveRole.CONSTRUCTOR, score=UNMEASURED)},
    )
    novus = ModelCapabilityProfile(
        model_id="orneur-novus", checkpoint_id="orca-core-combined-v2",
        lifecycle_state=novus_lifecycle, profile_state=ProfileState.MEASURED,
        context_length=8192,
        capabilities={CognitiveRole.VERIFIER.value: ModelCapability(role=CognitiveRole.VERIFIER, score=0.728, evaluation_ids=["novus-combined-v2-full-eval"])},
    )
    return {"genesis": genesis, "novus": novus, "aeternum": None}


def test_aeternum_is_always_rejected_and_never_a_candidate():
    request = RoutingRequest(role=CognitiveRole.CONSTRUCTOR, allow_experimental=True)
    decision = route(request, profiles=_profiles(), checkpoint_lookup=_fake_checkpoint_lookup, deployment_lookup=_fake_deployment_lookup)
    assert decision.selected_model_id != "orneur-aeternum"
    aeternum_id = [c for c in decision.rejected_candidates if "aeternum" in c][0]
    assert RoutingReason.AETERNUM_ABSENT.value in decision.rejection_reasons[aeternum_id]


def test_novus_not_production_routable_without_explicit_opt_in():
    request = RoutingRequest(role=CognitiveRole.VERIFIER, allow_experimental=False)
    decision = route(request, profiles=_profiles(), checkpoint_lookup=_fake_checkpoint_lookup, deployment_lookup=_fake_deployment_lookup)
    assert decision.selected_model_id != "orneur-novus"
    assert "orca-core-combined-v2" in decision.rejection_reasons
    assert RoutingReason.NOVUS_REJECTED_LIFECYCLE.value in decision.rejection_reasons["orca-core-combined-v2"]


def test_novus_routable_in_evaluation_mode_with_explicit_opt_in():
    request = RoutingRequest(role=CognitiveRole.VERIFIER, allow_experimental=True)
    decision = route(request, profiles=_profiles(), checkpoint_lookup=_fake_checkpoint_lookup, deployment_lookup=_fake_deployment_lookup)
    assert decision.selected_model_id == "orneur-novus"
    assert decision.capability_evidence == ["novus-combined-v2-full-eval"]


def test_context_requirement_unmet_is_a_hard_filter():
    request = RoutingRequest(role=CognitiveRole.CODER)  # min_context_tokens=4096
    profiles = _profiles()
    profiles["genesis"].context_length = 1024
    decision = route(request, profiles=profiles)
    assert "orca-nano-v7" in decision.rejection_reasons
    assert RoutingReason.CONTEXT_REQUIREMENT_UNMET.value in decision.rejection_reasons["orca-nano-v7"]


def test_entitlement_hard_filter_cannot_be_overridden_by_score():
    """A caller entitled only to BASIC must never receive Novus, even if
    Novus would score higher and Novus is otherwise lifecycle-eligible
    (spec §13, §46)."""
    request = RoutingRequest(role=CognitiveRole.VERIFIER, allow_experimental=True, allowed_capability_classes=["BASIC"])
    decision = route(request, profiles=_profiles(), checkpoint_lookup=_fake_checkpoint_lookup, deployment_lookup=_fake_deployment_lookup)
    assert decision.selected_model_id != "orneur-novus"
    assert RoutingReason.ENTITLEMENT_LIMIT.value in decision.rejection_reasons["orca-core-combined-v2"]


def test_excluded_by_caller_hard_filter():
    request = RoutingRequest(role=CognitiveRole.CONSTRUCTOR, exclude_model_ids=["orca-nano-v7"], allow_experimental=True)
    decision = route(request, profiles=_profiles(), checkpoint_lookup=_fake_checkpoint_lookup, deployment_lookup=_fake_deployment_lookup)
    assert decision.selected_model_id != "orneur-genesis"


def test_no_eligible_candidate_returns_none_selected_not_a_fallback_guess():
    request = RoutingRequest(role=CognitiveRole.CONSTRUCTOR, exclude_model_ids=["orca-nano-v7"], allow_experimental=False)
    decision = route(request, profiles=_profiles(), checkpoint_lookup=_fake_checkpoint_lookup, deployment_lookup=_fake_deployment_lookup)
    assert decision.selected_model_id is None
    assert RoutingReason.NO_ELIGIBLE_CANDIDATE.value in decision.reasons


def test_evidence_evaluated_capability_wins_over_unmeasured():
    """Novus's real, measured 72.8% VERIFIER score must outrank Genesis's
    UNMEASURED (treated as 0.0, never an assumed average -- spec §9)."""
    request = RoutingRequest(role=CognitiveRole.VERIFIER, allow_experimental=True)
    decision = route(request, profiles=_profiles(), checkpoint_lookup=_fake_checkpoint_lookup, deployment_lookup=_fake_deployment_lookup)
    assert decision.selected_model_id == "orneur-novus"


def test_unmeasured_capability_is_never_treated_as_a_passing_average():
    cap = ModelCapability(role=CognitiveRole.CONSTRUCTOR, score=UNMEASURED)
    assert not cap.is_measured
