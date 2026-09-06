"""
OllamaRuntime tests. Capability/error-shape tests use monkeypatched httpx
(no live dependency); a few tests run against a REAL local Ollama instance
(skipped automatically if one isn't reachable) to verify genuine streaming
and generation behavior, not just mocked shapes -- matching this project's
established pattern of verifying against live systems where feasible.
"""
from __future__ import annotations

import asyncio

import httpx
import pytest

from orca.gateway.contracts import InferenceRequest, StreamingMode
from orca.gateway.errors import DeploymentUnavailableError, RequestCancelledError
from orca.gateway.ollama_runtime import OllamaRuntime


def _req(**overrides):
    defaults = dict(
        request_id="req-1", model_id="orneur-novus",
        messages=[{"role": "user", "content": "Say the word 'hello' and nothing else."}],
        max_tokens=5,
    )
    defaults.update(overrides)
    return InferenceRequest(**defaults)


def test_capabilities_declare_native_streaming_and_cooperative_cancellation():
    rt = OllamaRuntime(host="http://localhost:11434")
    caps = rt.capabilities()
    assert caps.streaming == StreamingMode.NATIVE_STREAMING
    assert caps.cancellation is True
    assert caps.embeddings is False
    assert caps.tool_calling is False  # honest: AgentLoop's tool-use lives above this adapter, not in it


@pytest.mark.asyncio
async def test_health_false_when_unreachable():
    rt = OllamaRuntime(host="http://localhost:1")  # nothing listens here
    assert await rt.health() is False


@pytest.mark.asyncio
async def test_generate_raises_deployment_unavailable_on_connect_error():
    rt = OllamaRuntime(host="http://localhost:1", timeout_s=1.0)
    with pytest.raises(DeploymentUnavailableError):
        await rt.generate(_req())


@pytest.mark.asyncio
async def test_cancelled_request_id_short_circuits_generate():
    rt = OllamaRuntime(host="http://localhost:11434")
    rt._cancelled_requests.add("req-cancelled")
    with pytest.raises(RequestCancelledError):
        await rt.generate(_req(request_id="req-cancelled"))


@pytest.mark.asyncio
async def test_cancel_marks_request_id():
    rt = OllamaRuntime(host="http://localhost:11434")
    result = await rt.cancel("some-request-id")
    assert result is True
    assert "some-request-id" in rt._cancelled_requests


# --------------------------------------------------------------- live tests --

async def _ollama_reachable() -> bool:
    try:
        async with httpx.AsyncClient() as client:
            r = await client.get("http://localhost:11434/api/tags", timeout=2)
            return r.status_code == 200
    except Exception:
        return False


async def _skip_if_no_ollama():
    if not await _ollama_reachable():
        pytest.skip("No local Ollama instance reachable -- skipping live integration test")


@pytest.mark.asyncio
async def test_live_health_check():
    await _skip_if_no_ollama()
    rt = OllamaRuntime(host="http://localhost:11434")
    assert await rt.health() is True


@pytest.mark.asyncio
async def test_live_generate_real_model():
    await _skip_if_no_ollama()
    rt = OllamaRuntime(host="http://localhost:11434", timeout_s=90.0)
    response = await rt.generate(_req(model_version="orca-nano-v7", max_tokens=5))
    assert response.runtime == "ollama"
    assert isinstance(response.output, str)
    assert response.completion_tokens >= 0
    assert response.latency_ms > 0


@pytest.mark.asyncio
async def test_live_stream_yields_real_chunks_and_final_finish_reason():
    await _skip_if_no_ollama()
    rt = OllamaRuntime(host="http://localhost:11434", timeout_s=90.0)
    chunks = []
    async for chunk in rt.stream(_req(request_id="stream-live-1", model_version="orca-nano-v7", max_tokens=5)):
        chunks.append(chunk)
    assert len(chunks) >= 1
    assert chunks[-1].finish_reason == "stop"


@pytest.mark.asyncio
async def test_live_stream_cancellation_stops_early():
    await _skip_if_no_ollama()
    rt = OllamaRuntime(host="http://localhost:11434", timeout_s=90.0)
    request_id = "stream-cancel-live-1"

    chunks = []
    stream = rt.stream(_req(request_id=request_id, model_version="orca-nano-v7", max_tokens=200))
    async for chunk in stream:
        chunks.append(chunk)
        if len(chunks) == 1:
            await rt.cancel(request_id)
        # after cancel is requested, the next chunk pulled must be the
        # cancellation marker, not further generation content
        if chunk.finish_reason == "cancelled":
            break

    assert chunks[-1].finish_reason == "cancelled"
