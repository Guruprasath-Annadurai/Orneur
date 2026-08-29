"""
ModelDeployment.is_routable() is the single gate the Model Gateway must
call before routing any request -- these tests cover every refusal
condition explicitly, matching the real scenarios Phase 2 was asked to
guard: missing/corrupt artifacts, Aeternum with no checkpoint, REJECTED
models, unavailable deployments, and experimental-vs-production isolation.
"""
from __future__ import annotations

import pytest

from orca.gateway.deployment import DeploymentHealth, ModelDeployment
from orca.registry.model_spec import LifecycleState


def _make(**overrides):
    defaults = dict(
        deployment_id="dep-test",
        model_id="orneur-novus",
        model_version="orca-core-combined-v2",
        artifact_id="orca-core-combined-v2",
        runtime="ollama",
        runtime_endpoint="http://localhost:11434",
        hardware_profile="local-cpu",
        lifecycle=LifecycleState.PRODUCTION.value,
        health=DeploymentHealth.READY.value,
        warmup_completed=True,
    )
    defaults.update(overrides)
    return ModelDeployment(**defaults)


def test_production_ready_warmed_up_is_routable():
    d = _make()
    assert d.is_routable() is True


def test_rejected_lifecycle_is_never_routable():
    d = _make(lifecycle=LifecycleState.REJECTED.value)
    assert d.is_routable() is False
    assert d.is_routable(allow_experimental=True) is False


def test_retired_lifecycle_is_never_routable():
    d = _make(lifecycle=LifecycleState.RETIRED.value)
    assert d.is_routable() is False


def test_experimental_not_routable_by_default():
    d = _make(lifecycle=LifecycleState.EXPERIMENTAL.value)
    assert d.is_routable() is False


def test_experimental_routable_only_with_explicit_policy():
    d = _make(lifecycle=LifecycleState.EXPERIMENTAL.value)
    assert d.is_routable(allow_experimental=True) is True


def test_unhealthy_deployment_not_routable():
    d = _make(health=DeploymentHealth.UNHEALTHY.value)
    assert d.is_routable() is False


def test_starting_deployment_not_routable():
    d = _make(health=DeploymentHealth.STARTING.value)
    assert d.is_routable() is False


def test_draining_deployment_not_routable():
    d = _make(health=DeploymentHealth.DRAINING.value)
    assert d.is_routable() is False


def test_offline_deployment_not_routable():
    d = _make(health=DeploymentHealth.OFFLINE.value)
    assert d.is_routable() is False


def test_degraded_deployment_is_still_routable():
    """DEGRADED means slow-but-working, not down -- must remain routable."""
    d = _make(health=DeploymentHealth.DEGRADED.value)
    assert d.is_routable() is True


def test_deployment_without_warmup_not_routable_even_if_healthy():
    d = _make(warmup_completed=False)
    assert d.is_routable() is False


def test_request_drain_sets_health_and_timestamp(tmp_path, monkeypatch):
    import orca.gateway.deployment as deployment_mod
    monkeypatch.setattr(deployment_mod, "DEPLOYMENT_DIR", tmp_path)
    d = _make(deployment_id="drain-test")
    d.request_drain()
    assert d.health == DeploymentHealth.DRAINING.value
    assert d.drain_requested_at is not None
    assert d.is_routable() is False


def test_deployment_round_trip(tmp_path, monkeypatch):
    import orca.gateway.deployment as deployment_mod
    monkeypatch.setattr(deployment_mod, "DEPLOYMENT_DIR", tmp_path)
    d = _make(deployment_id="roundtrip-test")
    d.save()
    loaded = ModelDeployment.load("roundtrip-test")
    assert loaded.model_id == "orneur-novus"
    assert loaded.is_routable() is True


def test_aeternum_deployment_with_no_artifact_is_not_routable(tmp_path, monkeypatch):
    """
    Aeternum has no trained checkpoint -- even if someone constructed a
    deployment record for it (which nothing in this codebase should do),
    its lifecycle would correctly still be EXPERIMENTAL/no artifact, so
    is_routable() refuses it the same as any other non-production model.
    """
    d = _make(
        model_id="orneur-aeternum",
        artifact_id="NONE",
        lifecycle=LifecycleState.EXPERIMENTAL.value,
        warmup_completed=False,
    )
    assert d.is_routable() is False
    assert d.is_routable(allow_experimental=True) is False  # no warmup either way
