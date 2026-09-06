"""
FrontierRuntime must never claim real streaming -- the module under test
delegates to orca/brain/backends.py's already-correct, synchronous
Backend.generate(), so these tests mock at that boundary rather than
hitting a real OpenAI/Anthropic API (no key available in this environment,
and not needed to verify the adapter's own contract behavior).
"""
from __future__ import annotations

from dataclasses import dataclass

import pytest

from orca.gateway.contracts import InferenceRequest, StreamingMode
from orca.gateway.frontier_runtime import FrontierRuntime


@dataclass
class _FakeBackendResponse:
    text: str
    backend: str
    model: str
    input_tokens: int
    output_tokens: int
    cost_usd: float
    latency_ms: float
    data_left_infrastructure: bool


class _FakeBackend:
    name = "openai"

    def __init__(self, text="hello world from frontier"):
        self._text = text

    def generate(self, prompt, system="", max_tokens=1024, temperature=0.7):
        return _FakeBackendResponse(
            text=self._text, backend="openai", model="gpt-4o",
            input_tokens=10, output_tokens=5, cost_usd=0.001,
            latency_ms=42.0, data_left_infrastructure=True,
        )


def _req(**overrides):
    defaults = dict(request_id="req-1", model_id="orneur-novus", messages=[{"role": "user", "content": "hi"}])
    defaults.update(overrides)
    return InferenceRequest(**defaults)


def test_capabilities_declare_buffered_only_never_native_streaming():
    rt = FrontierRuntime("openai", api_key="fake-key")
    caps = rt.capabilities()
    assert caps.streaming == StreamingMode.BUFFERED_ONLY
    assert caps.cancellation is False
    assert caps.tool_calling is False


@pytest.mark.asyncio
async def test_health_reflects_api_key_presence():
    assert await FrontierRuntime("openai", api_key="").health() is False
    assert await FrontierRuntime("openai", api_key="sk-real").health() is True


@pytest.mark.asyncio
async def test_generate_delegates_to_backend(monkeypatch):
    rt = FrontierRuntime("openai", api_key="fake-key")
    monkeypatch.setattr("orca.gateway.frontier_runtime.build_backend", lambda *a, **k: _FakeBackend())

    response = await rt.generate(_req())
    assert response.output == "hello world from frontier"
    assert response.runtime == "openai"
    assert response.data_left_infrastructure is True
    assert response.cost_usd == 0.001


@pytest.mark.asyncio
async def test_stream_yields_buffered_chunks_matching_generate_output(monkeypatch):
    rt = FrontierRuntime("openai", api_key="fake-key")
    monkeypatch.setattr("orca.gateway.frontier_runtime.build_backend", lambda *a, **k: _FakeBackend(text="a b c"))

    chunks = [c async for c in rt.stream(_req(request_id="stream-1"))]
    deltas = "".join(c.delta for c in chunks)
    assert deltas == "a b c"
    assert chunks[-1].finish_reason == "stop"


@pytest.mark.asyncio
async def test_stream_cancellation_stops_yielding_further_words(monkeypatch):
    rt = FrontierRuntime("openai", api_key="fake-key")
    monkeypatch.setattr("orca.gateway.frontier_runtime.build_backend", lambda *a, **k: _FakeBackend(text="one two three four five"))

    chunks = []
    stream = rt.stream(_req(request_id="stream-cancel-1"))
    async for chunk in stream:
        chunks.append(chunk)
        if len(chunks) == 1:
            await rt.cancel("stream-cancel-1")
        if chunk.finish_reason == "cancelled":
            break

    assert chunks[-1].finish_reason == "cancelled"
    assert len(chunks) < 5  # did not yield every word


@pytest.mark.asyncio
async def test_load_unload_model_return_false_not_supported():
    rt = FrontierRuntime("openai", api_key="fake-key")
    assert await rt.load_model("gpt-4o") is False
    assert await rt.unload_model("gpt-4o") is False
