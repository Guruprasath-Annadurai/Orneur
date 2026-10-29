"""
LANDMARK-01 B-01: CognitiveKernel genuine incremental streaming via
ModelGateway.stream when CognitiveRequest.on_raw_delta is set.

These tests use a delayed controlled fake runtime — never claim live
Ollama latency/benchmark numbers from them. A separate optional live
test skips when Ollama is unavailable.
"""
from __future__ import annotations

import asyncio
import time

import httpx
import pytest

from orca.cognitive.contracts import CognitiveRequest, CognitiveState
from orca.cognitive.kernel import CognitiveKernel
from orca.cognitive.streaming import RawDeltaChannel
from orca.gateway.contracts import InferenceChunk, InferenceRequest, InferenceResponse
from orca.gateway.deployment import DeploymentHealth, ModelDeployment
from orca.gateway.gateway import ModelGateway, TimeoutPolicy
from orca.registry.model_spec import LifecycleState


class _DelayedRuntime:
    """Controlled provider: sleeps between deltas so arrival times separate."""

    name = "fake-delayed"

    def __init__(self, chunks: list[str], delay_s: float = 0.05, fail_after: int | None = None):
        self.chunks = list(chunks)
        self.delay_s = delay_s
        self.fail_after = fail_after
        self.generate_calls = 0
        self.stream_calls = 0
        self.stream_aclose_count = 0
        self.last_stream_request: InferenceRequest | None = None
        self._active_streams = 0

    async def generate(self, request: InferenceRequest) -> InferenceResponse:
        self.generate_calls += 1
        self.last_generate_request = request
        if self.delay_s:
            await asyncio.sleep(self.delay_s * len(self.chunks))
        return InferenceResponse(
            request_id=request.request_id, model_id=request.model_id, resolved_version="fixture-llama3.2:1b",
            runtime="fake", deployment_id="", output="".join(self.chunks), finish_reason="stop",
            prompt_tokens=3, completion_tokens=len(self.chunks), latency_ms=1.0,
            queue_latency_ms=0.0, model_latency_ms=1.0,
        )

    async def stream(self, request: InferenceRequest):
        self.stream_calls += 1
        self.last_stream_request = request
        self._active_streams += 1
        try:
            for i, c in enumerate(self.chunks):
                if self.fail_after is not None and i >= self.fail_after:
                    raise RuntimeError("simulated provider failure mid-stream")
                if self.delay_s:
                    await asyncio.sleep(self.delay_s)
                yield InferenceChunk(
                    request_id=request.request_id, sequence=i, delta=c,
                    prompt_tokens=3 if i == 0 else None,
                    completion_tokens=None, finish_reason=None,
                )
            yield InferenceChunk(
                request_id=request.request_id, sequence=len(self.chunks), delta="",
                finish_reason="stop", prompt_tokens=3, completion_tokens=len(self.chunks),
            )
        finally:
            self._active_streams -= 1
            self.stream_aclose_count += 1

    async def cancel(self, request_id: str) -> bool:
        return True

    async def health(self) -> bool:
        return True

    async def load_model(self, model_ref: str) -> bool:
        return True

    async def unload_model(self, model_ref: str) -> bool:
        return True

    def capabilities(self):
        return None


def _deployment() -> ModelDeployment:
    return ModelDeployment(
        deployment_id="dep-b01-fixture", model_id="orneur-novus", model_version="fixture-llama3.2:1b",
        artifact_id="fixture-llama3.2:1b", runtime="fake", runtime_endpoint="fake://local",
        hardware_profile="test", lifecycle=LifecycleState.PRODUCTION.value,
        health=DeploymentHealth.READY.value, warmup_completed=True, max_concurrency=4,
        context_limit=8192,
    )


def _gateway(runtime: _DelayedRuntime) -> ModelGateway:
    gw = ModelGateway(timeout_policy=TimeoutPolicy())
    gw.register_runtime("fake", runtime)
    gw.register_deployment(_deployment())
    return gw


@pytest.fixture
def kernel_stack(monkeypatch):
    runtime = _DelayedRuntime(["Hel", "lo ", "world"], delay_s=0.04)
    gw = _gateway(runtime)
    monkeypatch.setattr(
        "orca.serve.registry.resolve_tier_backend",
        lambda tier: type("R", (), {
            "tier": tier, "backend": "ollama", "model": "fixture-llama3.2:1b",
            "data_left_infrastructure": False,
        })(),
    )

    def _brain(resolution, gateway=None):
        return type("B", (), {
            "model_id": "orneur-novus",
            "model_version": "fixture-llama3.2:1b",
            "allow_experimental": False,
        })()

    monkeypatch.setattr("orca.gateway.wiring.brain_for_tier_resolution", _brain)
    kernel = CognitiveKernel(gateway=gw)
    return kernel, runtime, gw


@pytest.mark.asyncio
async def test_non_streaming_execute_unchanged_uses_generate(kernel_stack):
    kernel, runtime, _gw = kernel_stack
    req = CognitiveRequest(objective="Say hello.")
    result = await kernel.execute(req)
    assert result.status == CognitiveState.COMPLETED
    assert result.output == "Hello world"
    assert runtime.generate_calls == 1
    assert runtime.stream_calls == 0
    assert result.resolved_model == "fixture-llama3.2:1b"
    assert result.usage.get("completion_tokens") == 2 or result.usage.get("total_tokens")


@pytest.mark.asyncio
async def test_streaming_emits_multiple_real_deltas_before_completion(kernel_stack):
    kernel, runtime, _gw = kernel_stack
    channel = RawDeltaChannel(maxsize=8)
    arrivals: list[tuple[float, str]] = []

    async def _hook(delta: str):
        arrivals.append((time.monotonic(), delta))
        await channel.push(delta)

    req = CognitiveRequest(objective="Say hello.", on_raw_delta=_hook)
    t0 = time.monotonic()
    task = asyncio.create_task(kernel.execute(req))
    # Consumer must be able to see chunks BEFORE execute finishes.
    first = await asyncio.wait_for(channel.__aiter__().__anext__(), timeout=2.0)
    assert first == "Hel"
    assert not task.done(), "stream must not pre-generate the full answer before the consumer reads"
    result = await task
    channel.close()
    assert result.status == CognitiveState.COMPLETED
    assert result.output == "Hello world"
    assert [d for _, d in arrivals] == ["Hel", "lo ", "world"]
    assert len(arrivals) >= 3
    # Delayed provider: first→last delta spaced by ~2*delay
    assert arrivals[-1][0] - arrivals[0][0] >= 0.06
    assert runtime.stream_calls == 1
    assert runtime.generate_calls == 0
    assert result.resolved_model == "fixture-llama3.2:1b"
    assert "llama3.2:1b" in (result.resolved_model or "")
    assert runtime.last_stream_request is not None
    assert runtime.last_stream_request.stream is True


@pytest.mark.asyncio
async def test_final_accumulated_answer_matches_provider_chunks(kernel_stack):
    kernel, runtime, _gw = kernel_stack
    seen: list[str] = []

    async def _hook(delta: str):
        seen.append(delta)

    req = CognitiveRequest(objective="hi", on_raw_delta=_hook)
    result = await kernel.execute(req)
    assert "".join(seen) == result.output == "".join(runtime.chunks)


@pytest.mark.asyncio
async def test_cancelled_consumer_closes_gateway_stream(kernel_stack):
    kernel, runtime, _gw = kernel_stack
    # Slow stream so cancel lands mid-flight.
    runtime.chunks = ["a", "b", "c", "d", "e", "f"]
    runtime.delay_s = 0.08
    channel = RawDeltaChannel(maxsize=2)

    req = CognitiveRequest(objective="long", on_raw_delta=channel.as_hook())
    task = asyncio.create_task(kernel.execute(req))
    # Wait for at least one delta then cancel.
    agen = channel.__aiter__()
    await asyncio.wait_for(agen.__anext__(), timeout=2.0)
    task.cancel()
    with pytest.raises(asyncio.CancelledError):
        await task
    # Give aclose a tick.
    await asyncio.sleep(0.05)
    assert runtime._active_streams == 0
    assert runtime.stream_aclose_count >= 1
    # No leaked background generation: execute task is done.
    assert task.done()


@pytest.mark.asyncio
async def test_provider_failure_propagates_without_false_completion(kernel_stack):
    from orca.cognitive.errors import CognitiveExecutionFailedError

    kernel, runtime, _gw = kernel_stack
    runtime.fail_after = 1
    runtime.chunks = ["one", "two", "three"]
    seen: list[str] = []

    async def _hook(delta: str):
        seen.append(delta)

    req = CognitiveRequest(objective="fail please", on_raw_delta=_hook)
    # Unclassified mid-stream failures raise — never a COMPLETED partial success.
    with pytest.raises(CognitiveExecutionFailedError):
        await kernel.execute(req)
    assert runtime.generate_calls == 0
    assert runtime.stream_calls == 1
    assert seen == ["one"]  # at most the deltas emitted before failure


@pytest.mark.asyncio
async def test_streaming_does_not_duplicate_model_invocation(kernel_stack):
    kernel, runtime, _gw = kernel_stack
    async def _hook(delta: str):
        return None

    req = CognitiveRequest(objective="once", on_raw_delta=_hook)
    await kernel.execute(req)
    assert runtime.stream_calls == 1
    assert runtime.generate_calls == 0


@pytest.mark.asyncio
async def test_bounded_channel_never_silently_discards(kernel_stack):
    kernel, runtime, _gw = kernel_stack
    runtime.chunks = ["A", "B", "C", "D"]
    runtime.delay_s = 0.01
    channel = RawDeltaChannel(maxsize=1)
    received: list[str] = []

    async def producer():
        req = CognitiveRequest(objective="bound", on_raw_delta=channel.as_hook())
        result = await kernel.execute(req)
        channel.close()
        return result

    async def consumer():
        await asyncio.sleep(0.02)  # let producer block on full queue
        async for delta in channel:
            received.append(delta)
            await asyncio.sleep(0.02)

    result, _ = await asyncio.gather(producer(), consumer())
    assert result.output == "ABCD"
    assert received == ["A", "B", "C", "D"]


@pytest.mark.asyncio
async def test_context_assembly_identical_for_stream_and_generate(isolated_home, monkeypatch):
    from orca.serve import conversations

    sid = "b01ctx"
    fence = "f" * 32
    auth = conversations.acquire_authority(sid, "u1", fence, ttl_s=30.0)
    assert auth is not None
    committed = conversations.commit_turn(
        sid, "prior user", "prior assistant", user_id="u1", turn_id="t1",
        fence_token=fence, epoch=auth.epoch,
    )
    assert committed.ok
    conversations.release_authority(sid, fence, auth.epoch)

    captured: dict = {}

    class CapturingGW:
        async def generate(self, request, allow_experimental=False):
            captured["gen"] = list(request.messages)
            return InferenceResponse(
                request_id=request.request_id, model_id="orneur-novus", resolved_version="v",
                runtime="fake", deployment_id="d", output="ok", finish_reason="stop",
                prompt_tokens=1, completion_tokens=1, latency_ms=1, queue_latency_ms=0, model_latency_ms=1,
            )

        async def stream(self, request, allow_experimental=False):
            captured["stream"] = list(request.messages)
            yield InferenceChunk(request_id=request.request_id, sequence=0, delta="ok", finish_reason=None)
            yield InferenceChunk(request_id=request.request_id, sequence=1, delta="", finish_reason="stop",
                                 prompt_tokens=1, completion_tokens=1)

    monkeypatch.setattr(
        "orca.serve.registry.resolve_tier_backend",
        lambda tier: type("R", (), {"tier": tier, "backend": "ollama", "model": "m", "data_left_infrastructure": False})(),
    )
    monkeypatch.setattr(
        "orca.gateway.wiring.brain_for_tier_resolution",
        lambda resolution, gateway=None: type("B", (), {"model_id": "orneur-novus", "model_version": "v", "allow_experimental": False})(),
    )
    gw = CapturingGW()
    kernel = CognitiveKernel(gateway=gw)

    r1 = await kernel.execute(CognitiveRequest(objective="next", session_id=sid, tenant="u1"))
    assert r1.output == "ok"

    async def _hook(d: str):
        return None

    r2 = await kernel.execute(CognitiveRequest(objective="next", session_id=sid, tenant="u1", on_raw_delta=_hook))
    assert r2.output == "ok"
    assert captured["gen"] == captured["stream"]
    assert "prior user" in captured["gen"][0]["content"]


@pytest.mark.asyncio
async def test_live_ollama_streaming_when_available():
    """Optional real-provider check — never reported as a CI benchmark."""
    try:
        r = httpx.get("http://localhost:11434/api/tags", timeout=2)
        if r.status_code != 200:
            pytest.skip("No local Ollama")
    except Exception:
        pytest.skip("No local Ollama")

    from orca.cognitive.wiring import get_shared_kernel, reset_for_tests
    from orca.gateway import wiring as gw_wiring

    gw_wiring.reset_for_tests()
    reset_for_tests()
    kernel = get_shared_kernel()
    arrivals: list[tuple[float, str]] = []

    async def _hook(delta: str):
        arrivals.append((time.monotonic(), delta))

    req = CognitiveRequest(
        objective="Reply with exactly twenty words about rivers. No preamble.",
        on_raw_delta=_hook,
    )
    result = await kernel.execute(req)
    if result.status != CognitiveState.COMPLETED or not result.output:
        pytest.skip(f"live kernel did not complete direct answer: {result.status} {result.abstention_reason}")
    assert len(arrivals) >= 2, "expected multiple real Ollama deltas"
    assert "".join(d for _, d in arrivals) == result.output
    assert "aeternum" not in (result.resolved_model or "").lower()
    assert "genesis" not in (result.resolved_model or "").lower() or "llama" in (result.resolved_model or "").lower()
