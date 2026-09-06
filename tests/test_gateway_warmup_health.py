"""
Warmup and health-report tests. A deployment must never be marked READY
after a failed warmup, and service/model readiness must stay distinct --
the process can be alive with zero models ready.
"""
from __future__ import annotations

import pytest

from orca.gateway import metrics
from orca.gateway.deployment import DeploymentHealth
from orca.gateway.gateway import ModelGateway
from orca.registry.model_spec import LifecycleState
from tests.test_gateway_model_gateway import _FakeRuntime, _deployment


@pytest.fixture(autouse=True)
def _reset_metrics():
    metrics.reset()
    yield
    metrics.reset()


@pytest.mark.asyncio
async def test_warmup_success_marks_ready(tmp_path, monkeypatch):
    import orca.gateway.deployment as deployment_mod
    monkeypatch.setattr(deployment_mod, "DEPLOYMENT_DIR", tmp_path)

    runtime = _FakeRuntime()
    gw = ModelGateway()
    gw.register_runtime("fake", runtime)
    dep = _deployment(health=DeploymentHealth.STARTING.value, warmup_completed=False)

    result = await gw.warmup(dep)
    assert result is True
    assert dep.health == DeploymentHealth.READY.value
    assert dep.warmup_completed is True


@pytest.mark.asyncio
async def test_warmup_failure_leaves_deployment_not_ready(tmp_path, monkeypatch):
    import orca.gateway.deployment as deployment_mod
    monkeypatch.setattr(deployment_mod, "DEPLOYMENT_DIR", tmp_path)

    runtime = _FakeRuntime(fail=True)
    gw = ModelGateway()
    gw.register_runtime("fake", runtime)
    dep = _deployment(health=DeploymentHealth.STARTING.value, warmup_completed=False)

    result = await gw.warmup(dep)
    assert result is False
    assert dep.health == DeploymentHealth.STARTING.value
    assert dep.warmup_completed is False
    # A deployment that failed warmup must not be routable even if lifecycle says PRODUCTION.
    assert dep.is_routable() is False


@pytest.mark.asyncio
async def test_report_health_distinguishes_service_and_model_readiness():
    runtime = _FakeRuntime()
    gw = ModelGateway()
    gw.register_runtime("fake", runtime)
    gw.register_deployment(_deployment(model_id="orneur-novus"))

    health = gw.report_health()
    assert health["service_live"] is True
    assert health["service_ready"] is True
    assert health["model_readiness"]["orneur-novus"] == "READY"


@pytest.mark.asyncio
async def test_report_health_is_ready_with_zero_models():
    """The service can be alive and ready with no deployments registered at all."""
    gw = ModelGateway()
    gw.register_runtime("fake", _FakeRuntime())
    health = gw.report_health()
    assert health["service_live"] is True
    assert health["service_ready"] is True
    assert health["model_readiness"] == {}


@pytest.mark.asyncio
async def test_report_health_not_ready_with_no_runtimes():
    gw = ModelGateway()
    health = gw.report_health()
    assert health["service_live"] is True
    assert health["service_ready"] is False


@pytest.mark.asyncio
async def test_report_health_shows_candidate_only_for_experimental_deployment():
    runtime = _FakeRuntime()
    gw = ModelGateway()
    gw.register_runtime("fake", runtime)
    gw.register_deployment(_deployment(model_id="orneur-novus", lifecycle=LifecycleState.EXPERIMENTAL.value))

    health = gw.report_health()
    assert health["model_readiness"]["orneur-novus"] == "CANDIDATE_ONLY"


@pytest.mark.asyncio
async def test_metrics_recorded_on_successful_generate():
    from orca.gateway.contracts import InferenceRequest

    runtime = _FakeRuntime()
    gw = ModelGateway()
    gw.register_runtime("fake", runtime)
    gw.register_deployment(_deployment())

    await gw.generate(InferenceRequest(request_id="m-1", model_id="orneur-novus", messages=[{"role": "user", "content": "hi"}]))
    snapshot = metrics.get_snapshot()
    assert snapshot["per_deployment"]["dep-fake-1"]["successes"] == 1
    assert snapshot["per_deployment"]["dep-fake-1"]["requests"] == 1


@pytest.mark.asyncio
async def test_metrics_recorded_on_failure():
    from orca.gateway.contracts import InferenceRequest

    runtime = _FakeRuntime(fail=True)
    gw = ModelGateway()
    gw.register_runtime("fake", runtime)
    gw.register_deployment(_deployment())

    with pytest.raises(Exception):
        await gw.generate(InferenceRequest(request_id="m-2", model_id="orneur-novus", messages=[{"role": "user", "content": "hi"}]))

    snapshot = metrics.get_snapshot()
    assert any("dep-fake-1" in k for k in snapshot["failures_by_code"])
