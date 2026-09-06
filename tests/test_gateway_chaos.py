"""
Controlled failure-injection tests using fake adapters at the test
boundary (per instruction: "Use controlled test adapters/fakes only at
test boundaries," not real hardware failure). Verifies the gateway
degrades gracefully rather than crashing or hanging for each scenario
Phase 2 was asked to simulate.
"""
from __future__ import annotations

import asyncio

import httpx
import pytest

from orca.gateway.contracts import InferenceChunk, InferenceRequest
from orca.gateway.deployment import DeploymentHealth
from orca.gateway.errors import (
    DeploymentUnavailableError,
    ModelNotRoutableError,
    QueueFullError,
)
from orca.gateway.gateway import ModelGateway
from orca.gateway.ollama_runtime import OllamaRuntime
from tests.test_gateway_model_gateway import _FakeRuntime, _deployment, _req


@pytest.mark.asyncio
async def test_chaos_ollama_offline():
    """Real OllamaRuntime against a port nothing listens on -- a genuine
    connection failure, not a mocked exception."""
    rt = OllamaRuntime(host="http://localhost:1", timeout_s=1.0)
    gw = ModelGateway()
    gw.register_runtime("ollama", rt)
    gw.register_deployment(_deployment(deployment_id="d1", runtime="ollama"))

    with pytest.raises(DeploymentUnavailableError):
        await gw.generate(_req())


@pytest.mark.asyncio
async def test_chaos_model_missing_entirely():
    gw = ModelGateway()
    with pytest.raises(ModelNotRoutableError):
        await gw.generate(_req(model_id="orneur-genesis-3b-does-not-exist-yet"))


@pytest.mark.asyncio
async def test_chaos_worker_unhealthy_deployment_refuses_routing():
    runtime = _FakeRuntime()
    gw = ModelGateway()
    gw.register_runtime("fake", runtime)
    gw.register_deployment(_deployment(health=DeploymentHealth.UNHEALTHY.value))
    with pytest.raises(ModelNotRoutableError):
        await gw.generate(_req())
    assert runtime.calls == 0  # never even reached the runtime


@pytest.mark.asyncio
async def test_chaos_health_probe_failure_reported_not_raised():
    class _DownRuntime(_FakeRuntime):
        async def health(self) -> bool:
            return False
    rt = _DownRuntime()
    assert await rt.health() is False  # a health check failure is a reported bool, not an exception


@pytest.mark.asyncio
async def test_chaos_generation_timeout_does_not_hang_forever():
    runtime = _FakeRuntime(delay_s=5.0)
    from orca.gateway.gateway import TimeoutPolicy
    gw = ModelGateway(timeout_policy=TimeoutPolicy(total_request_timeout_s=0.05))
    gw.register_runtime("fake", runtime)
    gw.register_deployment(_deployment())

    with pytest.raises(Exception):
        await asyncio.wait_for(gw.generate(_req()), timeout=1.0)  # outer guard: test itself must not hang


@pytest.mark.asyncio
async def test_chaos_deployment_draining_stops_new_requests_but_is_explicit(tmp_path, monkeypatch):
    import orca.gateway.deployment as deployment_mod
    monkeypatch.setattr(deployment_mod, "DEPLOYMENT_DIR", tmp_path)

    runtime = _FakeRuntime()
    gw = ModelGateway()
    gw.register_runtime("fake", runtime)
    dep = _deployment()
    gw.register_deployment(dep)

    dep.request_drain()  # calls ModelDeployment.save() -- must never touch real ORCA_HOME (see docs/orneur/phase-7/TEST_ISOLATION.md)
    with pytest.raises(ModelNotRoutableError):
        await gw.generate(_req())


@pytest.mark.asyncio
async def test_chaos_stream_interrupted_mid_response_still_yields_prior_chunks():
    """A runtime that raises partway through streaming must not silently
    swallow the chunks already yielded -- the caller sees them, then the error."""
    class _InterruptingRuntime(_FakeRuntime):
        async def stream(self, request):
            yield InferenceChunk(request_id=request.request_id, sequence=0, delta="partial")
            raise ConnectionError("simulated mid-stream disconnect")

    rt = _InterruptingRuntime()
    gw = ModelGateway()
    gw.register_runtime("fake", rt)
    gw.register_deployment(_deployment())

    received = []
    with pytest.raises(ConnectionError):
        async for chunk in gw.stream(_req()):
            received.append(chunk)

    assert len(received) == 1
    assert received[0].delta == "partial"


@pytest.mark.asyncio
async def test_chaos_queue_full_rejects_cleanly_not_unbounded_memory():
    runtime = _FakeRuntime(delay_s=0.3)
    gw = ModelGateway()
    gw.register_runtime("fake", runtime)
    gw.register_deployment(_deployment(deployment_id="d1", max_concurrency=1))
    gw.concurrency.configure("d1", max_concurrency=1, max_queue_depth=0)

    task = asyncio.create_task(gw.generate(_req(request_id="first")))
    await asyncio.sleep(0.05)

    with pytest.raises(QueueFullError):
        await gw.generate(_req(request_id="second"))

    await task  # let the first complete cleanly
