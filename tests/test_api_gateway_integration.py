"""
Real, end-to-end integration tests through the ACTUAL FastAPI serving
surface (TestClient -> /api/stream), not just the Gateway/adapter unit
tests. This is the strongest proof the cutover actually works: FastAPI's
TestClient drives the app through its own real event loop synchronously,
which is exactly the hazard orca/gateway/sync_bridge.py was built to
survive (a running loop on the calling thread) -- these tests exercise
that in the real production code path, not a synthetic reproduction.

Requires a real, locally-reachable Ollama instance with at least one
installed model; auto-skips (not fails) otherwise.
"""
from __future__ import annotations

import json

import httpx
import pytest
from fastapi.testclient import TestClient

from orca.gateway import wiring


def _ollama_reachable() -> bool:
    try:
        r = httpx.get("http://localhost:11434/api/tags", timeout=2)
        return r.status_code == 200
    except Exception:
        return False


@pytest.fixture(autouse=True)
def _reset_gateway_state():
    wiring.reset_for_tests()
    yield
    wiring.reset_for_tests()


@pytest.fixture
def client():
    from orca.serve.api import app
    return TestClient(app)


def _skip_if_no_ollama():
    if not _ollama_reachable():
        pytest.skip("No local Ollama instance reachable -- skipping live API integration test")


def _parse_sse_events(raw_text: str) -> list[dict]:
    events = []
    for line in raw_text.splitlines():
        if line.startswith("data: "):
            events.append(json.loads(line[len("data: "):]))
    return events


def test_stream_endpoint_produces_real_chunks_through_the_gateway(client):
    """
    The real end-to-end proof: a POST to /api/stream, through FastAPI's
    real routing/auth/moderation/session layers, through the newly-cut-over
    ModelGateway, through OllamaRuntime, to real local Ollama, and back --
    verified by actually reading generated content, not just a 200 status.
    """
    _skip_if_no_ollama()

    with client.stream(
        "POST", "/api/stream",
        json={"message": "Say the word hello and nothing else.", "model_variant": "nano"},
    ) as response:
        assert response.status_code == 200
        raw = "".join(response.iter_text())

    events = _parse_sse_events(raw)
    event_types = [e.get("type") for e in events]
    assert "session" in event_types
    assert "done" in event_types
    # At least one real content chunk must have arrived -- proves actual
    # generation happened through the Gateway, not just plumbing.
    chunk_events = [e for e in events if e.get("type") == "chunk"]
    assert len(chunk_events) >= 1
    full_text = "".join(e.get("text", "") for e in chunk_events)
    assert len(full_text) > 0


def test_stream_endpoint_registers_a_real_deployment_in_the_shared_gateway(client):
    """After a real request, the shared gateway singleton must have a real,
    routable deployment registered for the resolved model -- proving the
    wiring bridge actually ran, not that the endpoint silently fell back to
    something else."""
    _skip_if_no_ollama()

    with client.stream(
        "POST", "/api/stream",
        json={"message": "Hi", "model_variant": "nano"},
    ) as response:
        list(response.iter_text())  # drain the stream

    gw = wiring.get_shared_gateway()
    assert len(gw._deployments) >= 1
    assert "ollama" in gw._runtimes


def test_circuit_breaker_open_prevents_reaching_ollama_through_the_real_api(client, monkeypatch):
    """
    Forces the circuit open for whatever deployment the tier resolves to,
    then verifies the SAME real API endpoint reports an error WITHOUT the
    request ever reaching Ollama -- proving the breaker is honored on the
    real serving path, not just in Gateway-unit tests.
    """
    _skip_if_no_ollama()

    # First request: establishes the real deployment_id the tier resolves to.
    with client.stream("POST", "/api/stream", json={"message": "Hi", "model_variant": "nano"}) as response:
        list(response.iter_text())

    gw = wiring.get_shared_gateway()
    assert len(gw._deployments) >= 1
    deployment_id = next(iter(gw._deployments.keys()))

    # Force the circuit open for that exact deployment.
    for _ in range(gw.circuit_breaker.failure_threshold):
        gw.circuit_breaker.record_failure(deployment_id)

    with client.stream(
        "POST", "/api/stream",
        json={"message": "This should be rejected by the open circuit.", "model_variant": "nano"},
    ) as response:
        raw = "".join(response.iter_text())

    events = _parse_sse_events(raw)
    error_events = [e for e in events if e.get("type") == "error"]
    assert len(error_events) >= 1
    # No successful generation content should have been produced this time.
    chunk_events = [e for e in events if e.get("type") == "chunk"]
    assert len(chunk_events) == 0
