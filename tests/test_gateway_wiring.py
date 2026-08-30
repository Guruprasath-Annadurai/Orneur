"""
orca/gateway/wiring.py bridges the EXISTING tier router (unchanged) to the
Model Gateway. Verifies: correct family mapping (Genesis/Novus/Aeternum),
idempotent deployment registration, Ollama vs. frontier branching, and the
deliberate EXPERIMENTAL/allow_experimental=True policy for today's live
traffic.
"""
from __future__ import annotations

import pytest

from orca.gateway import wiring
from orca.gateway.deployment import ModelDeployment
from orca.registry.model_spec import LifecycleState
from orca.serve.registry import TierResolution


@pytest.fixture(autouse=True)
def _isolated_gateway():
    wiring.reset_for_tests()
    yield
    wiring.reset_for_tests()


def test_ollama_resolution_maps_tier_to_correct_model_family():
    resolution = TierResolution(tier="core", backend="ollama", model="orca-core-combined-v2", data_left_infrastructure=False)
    brain = wiring.brain_for_tier_resolution(resolution)
    assert brain.model_id == "orneur-novus"
    assert brain.model_version == "orca-core-combined-v2"


def test_nano_tier_maps_to_genesis():
    resolution = TierResolution(tier="nano", backend="ollama", model="orca-nano-v7", data_left_infrastructure=False)
    brain = wiring.brain_for_tier_resolution(resolution)
    assert brain.model_id == "orneur-genesis"


def test_ultra_tier_maps_to_aeternum():
    resolution = TierResolution(tier="ultra", backend="ollama", model="orca-ultra", data_left_infrastructure=False)
    brain = wiring.brain_for_tier_resolution(resolution)
    assert brain.model_id == "orneur-aeternum"


def test_deployment_is_registered_as_experimental_not_production():
    """Honest reflection of reality: nothing has cleared Phase 1's
    promotion gate. The bridge must never claim PRODUCTION."""
    resolution = TierResolution(tier="core", backend="ollama", model="orca-core-combined-v2", data_left_infrastructure=False)
    brain = wiring.brain_for_tier_resolution(resolution)
    deployment = brain._gateway._deployments["ollama-orca-core-combined-v2"]
    assert deployment.lifecycle == LifecycleState.EXPERIMENTAL.value
    assert brain.allow_experimental is True


def test_registration_is_idempotent():
    resolution = TierResolution(tier="core", backend="ollama", model="orca-core-combined-v2", data_left_infrastructure=False)
    brain1 = wiring.brain_for_tier_resolution(resolution)
    brain2 = wiring.brain_for_tier_resolution(resolution)
    # Same shared gateway, same deployment_id -- calling twice must not
    # error or create duplicate/conflicting state.
    assert brain1._gateway is brain2._gateway
    assert len(brain1._gateway._deployments) == 1


def test_frontier_resolution_registers_a_frontier_runtime_and_deployment():
    resolution = TierResolution(tier="core", backend="openai", model="gpt-4o", data_left_infrastructure=True)
    brain = wiring.brain_for_tier_resolution(resolution)
    assert "openai" in brain._gateway._runtimes
    deployment = brain._gateway._deployments["openai-gpt-4o"]
    assert deployment.runtime == "openai"
    assert deployment.hardware_profile == "cloud-api"


def test_get_shared_gateway_returns_the_same_instance_across_calls():
    gw1 = wiring.get_shared_gateway()
    gw2 = wiring.get_shared_gateway()
    assert gw1 is gw2
    assert "ollama" in gw1._runtimes


def test_reset_for_tests_actually_clears_state():
    wiring.get_shared_gateway()
    assert wiring._gateway is not None
    wiring.reset_for_tests()
    assert wiring._gateway is None
    assert wiring._ollama_runtime_registered is False
