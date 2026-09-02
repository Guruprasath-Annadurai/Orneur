"""
Phase 7.1 spec §27: Model Society routing must have real health
information for registered deployments -- READY selected, DRAINING/
UNHEALTHY/OFFLINE rejected, open-circuit rejected. Fully hermetic --
synthetic deployment/circuit-breaker lookups, no real disk/runtime state.
"""
from __future__ import annotations

from orca.gateway.circuit_breaker import CircuitBreaker
from orca.gateway.deployment import DeploymentHealth, ModelDeployment
from orca.registry.model_spec import LifecycleState
from orca.society.contracts import CognitiveRole, ModelCapability, ModelCapabilityProfile, ProfileState, RoutingRequest, UNMEASURED
from orca.society.lifecycle import LEGACY_PRODUCTION_SERVING
from orca.society.router import route


def _genesis_profile() -> dict:
    return {
        "genesis": ModelCapabilityProfile(
            model_id="orneur-genesis", checkpoint_id="orca-nano-v7", lifecycle_state=LEGACY_PRODUCTION_SERVING,
            profile_state=ProfileState.UNMEASURED, context_length=4096,
            capabilities={CognitiveRole.CONSTRUCTOR.value: ModelCapability(role=CognitiveRole.CONSTRUCTOR, score=UNMEASURED)},
        ),
        "novus": None,
        "aeternum": None,
    }


def _fake_checkpoint_lookup(checkpoint_id: str):
    class _Rec:
        availability = "LOCAL"
        def is_routable(self) -> bool:
            return True
    return _Rec()


def _deployment(health: str, deployment_id: str = "dep-1") -> ModelDeployment:
    return ModelDeployment(
        deployment_id=deployment_id, model_id="orneur-genesis", model_version="orca-nano-v7", artifact_id="orca-nano-v7",
        runtime="ollama", runtime_endpoint="http://localhost:11434", hardware_profile="local",
        lifecycle=LEGACY_PRODUCTION_SERVING, health=health, warmup_completed=True,
    )


def _route_with_deployment(deployment, circuit_breaker=None):
    request = RoutingRequest(role=CognitiveRole.CONSTRUCTOR)
    return route(
        request, profiles=_genesis_profile(), checkpoint_lookup=_fake_checkpoint_lookup,
        deployment_lookup=lambda model_id: [deployment] if deployment else [],
        circuit_breaker_lookup=lambda: circuit_breaker,
    )


def test_ready_deployment_is_selected():
    decision = _route_with_deployment(_deployment(DeploymentHealth.READY.value))
    assert decision.selected_model_id == "orneur-genesis"


def test_draining_deployment_is_rejected():
    decision = _route_with_deployment(_deployment(DeploymentHealth.DRAINING.value))
    assert decision.selected_model_id is None
    assert "DEPLOYMENT_UNHEALTHY" in decision.rejection_reasons["orca-nano-v7"]


def test_unhealthy_deployment_is_rejected():
    decision = _route_with_deployment(_deployment(DeploymentHealth.UNHEALTHY.value))
    assert decision.selected_model_id is None


def test_offline_deployment_is_rejected():
    decision = _route_with_deployment(_deployment(DeploymentHealth.OFFLINE.value))
    assert decision.selected_model_id is None


def test_open_circuit_deployment_is_rejected_even_if_health_is_ready():
    deployment = _deployment(DeploymentHealth.READY.value)
    breaker = CircuitBreaker(failure_threshold=1)
    breaker.record_failure(deployment.deployment_id)  # opens after 1 failure with threshold=1
    decision = _route_with_deployment(deployment, circuit_breaker=breaker)
    assert decision.selected_model_id is None
    assert "DEPLOYMENT_UNHEALTHY" in decision.rejection_reasons["orca-nano-v7"]


def test_closed_circuit_deployment_is_selected():
    deployment = _deployment(DeploymentHealth.READY.value)
    breaker = CircuitBreaker(failure_threshold=5)
    decision = _route_with_deployment(deployment, circuit_breaker=breaker)
    assert decision.selected_model_id == "orneur-genesis"
