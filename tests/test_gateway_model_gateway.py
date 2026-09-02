"""
ModelGateway integration tests -- routing safety, circuit breaker
integration, concurrency/backpressure integration, timeout categories, and
parameter/context validation, all exercised end-to-end through
generate()/stream() using a deterministic fake runtime (no live Ollama
dependency needed for these -- the real adapter is already covered by
tests/test_gateway_ollama_runtime.py's live tests).
"""
from __future__ import annotations

import asyncio

import pytest

from orca.gateway.circuit_breaker import CircuitBreaker, CircuitState
from orca.gateway.concurrency import ConcurrencyLimiter
from orca.gateway.contracts import InferenceChunk, InferenceRequest, InferenceResponse
from orca.gateway.deployment import DeploymentHealth, ModelDeployment
from orca.gateway.errors import (
    CircuitOpenError,
    ContextTooLongError,
    GenerationTimeoutError,
    InvalidParametersError,
    ModelNotRoutableError,
)
from orca.gateway.gateway import ModelGateway, TimeoutPolicy
from orca.registry.model_spec import LifecycleState


class _FakeRuntime:
    """Deterministic test double -- no network, no real model."""
    name = "fake"

    def __init__(self, fail: bool = False, delay_s: float = 0.0, chunks: list[str] | None = None):
        self.fail = fail
        self.delay_s = delay_s
        self.chunks = chunks if chunks is not None else ["hello", " world"]
        self.cancelled_ids: set[str] = set()
        self.calls = 0

    async def generate(self, request: InferenceRequest) -> InferenceResponse:
        self.calls += 1
        self.last_request = request
        if self.delay_s:
            await asyncio.sleep(self.delay_s)
        if self.fail:
            raise RuntimeError("simulated runtime failure")
        return InferenceResponse(
            request_id=request.request_id, model_id=request.model_id, resolved_version="fake-v1",
            runtime="fake", deployment_id="", output="hello world", finish_reason="stop",
            prompt_tokens=2, completion_tokens=2, latency_ms=1.0, queue_latency_ms=0.0, model_latency_ms=1.0,
        )

    async def stream(self, request: InferenceRequest):
        for i, c in enumerate(self.chunks):
            if request.request_id in self.cancelled_ids:
                yield InferenceChunk(request_id=request.request_id, sequence=i, delta="", finish_reason="cancelled")
                return
            if self.delay_s:
                await asyncio.sleep(self.delay_s)
            yield InferenceChunk(request_id=request.request_id, sequence=i, delta=c, finish_reason=None)
        yield InferenceChunk(request_id=request.request_id, sequence=len(self.chunks), delta="", finish_reason="stop")

    async def cancel(self, request_id: str) -> bool:
        self.cancelled_ids.add(request_id)
        return True

    async def health(self) -> bool:
        return True

    async def load_model(self, model_ref: str) -> bool:
        return True

    async def unload_model(self, model_ref: str) -> bool:
        return True

    def capabilities(self):
        return None


def _deployment(**overrides) -> ModelDeployment:
    defaults = dict(
        deployment_id="dep-fake-1", model_id="orneur-novus", model_version="fake-checkpoint",
        artifact_id="fake-checkpoint", runtime="fake", runtime_endpoint="fake://local",
        hardware_profile="test", lifecycle=LifecycleState.PRODUCTION.value,
        health=DeploymentHealth.READY.value, warmup_completed=True, max_concurrency=2,
        context_limit=8192,
    )
    defaults.update(overrides)
    return ModelDeployment(**defaults)


def _req(**overrides):
    defaults = dict(request_id="req-1", model_id="orneur-novus", messages=[{"role": "user", "content": "hi"}])
    defaults.update(overrides)
    return InferenceRequest(**defaults)


def _gateway(runtime: _FakeRuntime, deployment: ModelDeployment, **timeout_overrides) -> ModelGateway:
    policy = TimeoutPolicy(**timeout_overrides) if timeout_overrides else TimeoutPolicy()
    gw = ModelGateway(timeout_policy=policy)
    gw.register_runtime("fake", runtime)
    gw.register_deployment(deployment)
    return gw


# ------------------------------------------------------------ routing safety

@pytest.mark.asyncio
async def test_generate_succeeds_against_routable_deployment():
    runtime = _FakeRuntime()
    gw = _gateway(runtime, _deployment())
    response = await gw.generate(_req())
    assert response.output == "hello world"
    assert response.deployment_id == "dep-fake-1"


@pytest.mark.asyncio
async def test_aeternum_shaped_model_with_no_deployment_is_not_routable():
    """The exact real scenario: a model_id with zero registered deployments
    (Aeternum today) must never be routed, never fall back to another model."""
    gw = ModelGateway()
    with pytest.raises(ModelNotRoutableError) as exc_info:
        await gw.generate(_req(model_id="orneur-aeternum"))
    assert "orneur-aeternum" in str(exc_info.value)


@pytest.mark.asyncio
async def test_experimental_deployment_not_routable_without_policy():
    runtime = _FakeRuntime()
    gw = _gateway(runtime, _deployment(lifecycle=LifecycleState.EXPERIMENTAL.value))
    with pytest.raises(ModelNotRoutableError):
        await gw.generate(_req())


@pytest.mark.asyncio
async def test_experimental_deployment_routable_with_explicit_policy():
    runtime = _FakeRuntime()
    gw = _gateway(runtime, _deployment(lifecycle=LifecycleState.EXPERIMENTAL.value))
    response = await gw.generate(_req(), allow_experimental=True)
    assert response.output == "hello world"


@pytest.mark.asyncio
async def test_rejected_deployment_never_routable_even_with_policy():
    runtime = _FakeRuntime()
    gw = _gateway(runtime, _deployment(lifecycle=LifecycleState.REJECTED.value))
    with pytest.raises(ModelNotRoutableError):
        await gw.generate(_req(), allow_experimental=True)


@pytest.mark.asyncio
async def test_unhealthy_deployment_not_routable():
    runtime = _FakeRuntime()
    gw = _gateway(runtime, _deployment(health=DeploymentHealth.UNHEALTHY.value))
    with pytest.raises(ModelNotRoutableError):
        await gw.generate(_req())


# --------------------------------------------------------- circuit breaker --

@pytest.mark.asyncio
async def test_repeated_failures_open_the_circuit():
    runtime = _FakeRuntime(fail=True)
    gw = _gateway(runtime, _deployment())
    gw.circuit_breaker = CircuitBreaker(failure_threshold=2, open_duration_s=60)

    for _ in range(2):
        with pytest.raises(Exception):
            await gw.generate(_req())

    assert gw.circuit_breaker.state("dep-fake-1") == CircuitState.OPEN
    with pytest.raises(CircuitOpenError):
        await gw.generate(_req())
    # Runtime should NOT have been called a 3rd time -- circuit rejected before reaching it.
    assert runtime.calls == 2


@pytest.mark.asyncio
async def test_success_after_failures_resets_circuit():
    runtime = _FakeRuntime(fail=False)
    gw = _gateway(runtime, _deployment())
    gw.circuit_breaker.record_failure("dep-fake-1")
    response = await gw.generate(_req())
    assert response.output == "hello world"
    assert gw.circuit_breaker.state("dep-fake-1") == CircuitState.CLOSED


# ------------------------------------------------------------- concurrency --

@pytest.mark.asyncio
async def test_concurrency_limit_enforced_through_gateway():
    runtime = _FakeRuntime(delay_s=0.05)
    gw = _gateway(runtime, _deployment(max_concurrency=1))

    results = await asyncio.gather(
        gw.generate(_req(request_id="a")),
        gw.generate(_req(request_id="b")),
    )
    assert len(results) == 2  # both eventually succeed -- second queues behind the first


# ------------------------------------------------------------------ timeout --

@pytest.mark.asyncio
async def test_total_request_timeout_raises_generation_timeout():
    runtime = _FakeRuntime(delay_s=0.5)
    gw = _gateway(runtime, _deployment(), total_request_timeout_s=0.05)
    with pytest.raises(GenerationTimeoutError):
        await gw.generate(_req())


@pytest.mark.asyncio
async def test_first_token_timeout_raises_generation_timeout_on_stream():
    runtime = _FakeRuntime(delay_s=0.2, chunks=["slow"])
    gw = _gateway(runtime, _deployment(), first_token_timeout_s=0.02)
    with pytest.raises(GenerationTimeoutError):
        async for _ in gw.stream(_req()):
            pass


# -------------------------------------------------------- request validation

@pytest.mark.asyncio
async def test_invalid_temperature_rejected():
    runtime = _FakeRuntime()
    gw = _gateway(runtime, _deployment())
    with pytest.raises(InvalidParametersError):
        await gw.generate(_req(temperature=5.0))


@pytest.mark.asyncio
async def test_invalid_max_tokens_rejected():
    runtime = _FakeRuntime()
    gw = _gateway(runtime, _deployment())
    with pytest.raises(InvalidParametersError):
        await gw.generate(_req(max_tokens=0))


@pytest.mark.asyncio
async def test_context_too_long_rejected():
    runtime = _FakeRuntime()
    gw = _gateway(runtime, _deployment(context_limit=10))
    huge_message = [{"role": "user", "content": "x" * 1000}]
    with pytest.raises(ContextTooLongError):
        await gw.generate(_req(messages=huge_message, max_tokens=500))


# ---------------------------------------------------------------- streaming

@pytest.mark.asyncio
async def test_stream_yields_real_chunks_from_fake_runtime():
    runtime = _FakeRuntime(chunks=["a", "b", "c"])
    gw = _gateway(runtime, _deployment())
    chunks = [c async for c in gw.stream(_req())]
    deltas = "".join(c.delta for c in chunks)
    assert deltas == "abc"
    assert chunks[-1].finish_reason == "stop"


# -------------------------------------------------------------- cancellation

@pytest.mark.asyncio
async def test_cancel_propagates_to_runtime():
    runtime = _FakeRuntime()
    gw = _gateway(runtime, _deployment())
    result = await gw.cancel("orneur-novus", "some-request-id")
    assert result is True
    assert "some-request-id" in runtime.cancelled_ids


@pytest.mark.asyncio
async def test_cancel_returns_false_for_unknown_model():
    gw = ModelGateway()
    assert await gw.cancel("orneur-aeternum", "req-x") is False
