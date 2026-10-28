from __future__ import annotations

from orca.gateway.wiring import stable_deployment_id
from orca.registry._ids import validate_id


def test_colon_tag_becomes_validation_safe_and_collision_resistant():
    a = stable_deployment_id("ollama", "llama3.2:1b")
    b = stable_deployment_id("ollama", "llama3.2-1b")
    validate_id(a, "deployment_id")
    validate_id(b, "deployment_id")
    assert ":" not in a
    assert a != b
    assert a == stable_deployment_id("ollama", "llama3.2:1b")


def test_brain_for_colon_tag_registers_without_alias(monkeypatch, isolated_home):
    from types import SimpleNamespace

    from orca.gateway.wiring import brain_for_tier_resolution, reset_for_tests

    reset_for_tests()
    resolution = SimpleNamespace(tier="core", backend="ollama", model="llama3.2:1b", data_left_infrastructure=False)
    brain = brain_for_tier_resolution(resolution)
    assert brain.model_version == "llama3.2:1b"
    dep_id = stable_deployment_id("ollama", "llama3.2:1b", "orneur-novus")
    stored = brain._gateway._deployments[dep_id]
    assert stored.model_version == "llama3.2:1b"
    assert stored.artifact_id == "llama3.2:1b"
    from orca.gateway.wiring import TIER_TO_MODEL_ID

    assert stored.model_id == TIER_TO_MODEL_ID["core"]
    assert stored.model_version not in TIER_TO_MODEL_ID.values()
    assert stored.artifact_id not in TIER_TO_MODEL_ID.values()
    assert ":" not in stored.deployment_id
    assert "genesis" not in stored.deployment_id.lower()
    assert "novus" not in stored.deployment_id.lower()
    assert "aeternum" not in stored.deployment_id.lower()


def test_one_ollama_tag_serving_several_tiers_keeps_a_deployment_per_family(isolated_home):
    """Regression (found by the live browser journey): with ONE tag behind every tier -- the normal single-model install -- registering the second
    tier replaced the first tier's deployment (same id, new model_id), so the first tier's next request failed with ModelNotRoutableError."""
    from types import SimpleNamespace

    from orca.gateway.wiring import TIER_TO_MODEL_ID, brain_for_tier_resolution, reset_for_tests

    reset_for_tests()
    gateway = None
    for tier in ("nano", "core", "ultra", "nano", "core"):            # interleaved, as real users on different tiers are
        brain = brain_for_tier_resolution(SimpleNamespace(tier=tier, backend="ollama", model="llama3.2:1b", data_left_infrastructure=False))
        gateway = brain._gateway
    families = {d.model_id for d in gateway._deployments.values() if d.model_version == "llama3.2:1b"}
    assert families == set(TIER_TO_MODEL_ID.values())
    for family in TIER_TO_MODEL_ID.values():
        assert gateway._deployments_for_model(family), f"{family} lost its deployment"
    ids = [d.deployment_id for d in gateway._deployments.values() if d.model_version == "llama3.2:1b"]
    assert len(ids) == len(set(ids)) == 3
    for i in ids:
        validate_id(i, "deployment_id")
        assert ":" not in i
