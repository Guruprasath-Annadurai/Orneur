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
    dep_id = stable_deployment_id("ollama", "llama3.2:1b")
    stored = brain._gateway._deployments[dep_id]
    assert stored.model_version == "llama3.2:1b"
    assert stored.artifact_id == "llama3.2:1b"
    assert stored.model_id in {"orneur-novus", "orneur-genesis", "orneur-aeternum"}
    assert ":" not in stored.deployment_id
    assert "genesis" not in stored.deployment_id.lower()
    assert "novus" not in stored.deployment_id.lower()
    assert "aeternum" not in stored.deployment_id.lower()
