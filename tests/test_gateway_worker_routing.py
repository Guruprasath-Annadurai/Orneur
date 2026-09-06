"""
Worker-aware routing: a deployment tied to an UNHEALTHY/OFFLINE/DRAINING
or stale worker must not be selected, regardless of the deployment's own
lifecycle/health fields. A deployment with no worker_id is unconstrained
(backward compatible with every deployment registered before this existed).
"""
from __future__ import annotations

from datetime import datetime, timedelta, timezone

import pytest

from orca.gateway.errors import ModelNotRoutableError
from orca.gateway.gateway import ModelGateway
from orca.gateway.worker import Worker, WorkerHealth
from tests.test_gateway_model_gateway import _FakeRuntime, _deployment, _req


def _worker(**overrides):
    defaults = dict(
        worker_id="worker-1", runtime="fake", hardware="test",
        status=WorkerHealth.READY.value, capacity=4, active_requests=0,
        last_heartbeat=datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ"),
    )
    defaults.update(overrides)
    return Worker(**defaults)


@pytest.mark.asyncio
async def test_deployment_with_no_worker_id_is_unconstrained():
    runtime = _FakeRuntime()
    gw = ModelGateway()
    gw.register_runtime("fake", runtime)
    gw.register_deployment(_deployment())  # worker_id defaults to None
    response = await gw.generate(_req())
    assert response.output == "hello world"


@pytest.mark.asyncio
async def test_deployment_refused_when_its_worker_is_unhealthy():
    runtime = _FakeRuntime()
    gw = ModelGateway()
    gw.register_runtime("fake", runtime)
    gw.register_worker(_worker(status=WorkerHealth.UNHEALTHY.value))
    gw.register_deployment(_deployment(worker_id="worker-1"))

    with pytest.raises(ModelNotRoutableError):
        await gw.generate(_req())
    assert runtime.calls == 0


@pytest.mark.asyncio
async def test_deployment_refused_when_its_worker_is_offline():
    runtime = _FakeRuntime()
    gw = ModelGateway()
    gw.register_runtime("fake", runtime)
    gw.register_worker(_worker(status=WorkerHealth.OFFLINE.value))
    gw.register_deployment(_deployment(worker_id="worker-1"))

    with pytest.raises(ModelNotRoutableError):
        await gw.generate(_req())


@pytest.mark.asyncio
async def test_deployment_refused_when_its_worker_is_draining():
    runtime = _FakeRuntime()
    gw = ModelGateway()
    gw.register_runtime("fake", runtime)
    gw.register_worker(_worker(status=WorkerHealth.DRAINING.value))
    gw.register_deployment(_deployment(worker_id="worker-1"))

    with pytest.raises(ModelNotRoutableError):
        await gw.generate(_req())


@pytest.mark.asyncio
async def test_deployment_refused_when_worker_id_references_unregistered_worker():
    runtime = _FakeRuntime()
    gw = ModelGateway()
    gw.register_runtime("fake", runtime)
    gw.register_deployment(_deployment(worker_id="never-registered"))

    with pytest.raises(ModelNotRoutableError):
        await gw.generate(_req())


@pytest.mark.asyncio
async def test_deployment_routable_when_its_worker_is_ready():
    runtime = _FakeRuntime()
    gw = ModelGateway()
    gw.register_runtime("fake", runtime)
    gw.register_worker(_worker(status=WorkerHealth.READY.value))
    gw.register_deployment(_deployment(worker_id="worker-1"))

    response = await gw.generate(_req())
    assert response.output == "hello world"


@pytest.mark.asyncio
async def test_deployment_routable_when_its_worker_is_degraded():
    """DEGRADED means slow-but-working, not down -- must remain routable,
    matching ModelDeployment.is_routable()'s own DEGRADED handling."""
    runtime = _FakeRuntime()
    gw = ModelGateway()
    gw.register_runtime("fake", runtime)
    gw.register_worker(_worker(status=WorkerHealth.DEGRADED.value))
    gw.register_deployment(_deployment(worker_id="worker-1"))

    response = await gw.generate(_req())
    assert response.output == "hello world"


@pytest.mark.asyncio
async def test_stale_heartbeat_stops_routing_even_if_status_says_ready():
    """A worker that hasn't reported within the health interval must not
    remain READY forever, purely because its process still exists."""
    runtime = _FakeRuntime()
    gw = ModelGateway()
    gw.register_runtime("fake", runtime)
    stale_time = (datetime.now(timezone.utc) - timedelta(seconds=120)).strftime("%Y-%m-%dT%H:%M:%SZ")
    gw.register_worker(_worker(status=WorkerHealth.READY.value, last_heartbeat=stale_time))
    gw.register_deployment(_deployment(worker_id="worker-1"))

    with pytest.raises(ModelNotRoutableError):
        await gw.generate(_req())


@pytest.mark.asyncio
async def test_worker_at_full_capacity_stops_routing():
    runtime = _FakeRuntime()
    gw = ModelGateway()
    gw.register_runtime("fake", runtime)
    gw.register_worker(_worker(status=WorkerHealth.READY.value, capacity=1, active_requests=1))
    gw.register_deployment(_deployment(worker_id="worker-1"))

    with pytest.raises(ModelNotRoutableError):
        await gw.generate(_req())


@pytest.mark.asyncio
async def test_capacity_aware_selection_prefers_lower_load_worker():
    """Two otherwise-eligible deployments on two different workers -- the
    one with less active load must be selected, deterministically."""
    runtime = _FakeRuntime()
    gw = ModelGateway()
    gw.register_runtime("fake", runtime)
    gw.register_worker(_worker(worker_id="busy-worker", status=WorkerHealth.READY.value, capacity=10, active_requests=8))
    gw.register_worker(_worker(worker_id="idle-worker", status=WorkerHealth.READY.value, capacity=10, active_requests=0))
    gw.register_deployment(_deployment(deployment_id="dep-busy", worker_id="busy-worker"))
    gw.register_deployment(_deployment(deployment_id="dep-idle", worker_id="idle-worker"))

    response = await gw.generate(_req())
    assert response.deployment_id == "dep-idle"


@pytest.mark.asyncio
async def test_ready_worker_preferred_over_degraded_worker():
    runtime = _FakeRuntime()
    gw = ModelGateway()
    gw.register_runtime("fake", runtime)
    gw.register_worker(_worker(worker_id="degraded-worker", status=WorkerHealth.DEGRADED.value))
    gw.register_worker(_worker(worker_id="ready-worker", status=WorkerHealth.READY.value))
    gw.register_deployment(_deployment(deployment_id="dep-degraded", worker_id="degraded-worker"))
    gw.register_deployment(_deployment(deployment_id="dep-ready", worker_id="ready-worker"))

    response = await gw.generate(_req())
    assert response.deployment_id == "dep-ready"
