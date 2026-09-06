"""
Integration tests for POST /api/stream's frontier-passthrough branch —
verifies the actual wiring in orca/serve/api.py, mirroring
tests/test_api_chat_frontier_passthrough.py for the SSE streaming endpoint.

/api/stream was the one live-chat path that previously always drove the
local Ollama-backed AgentLoop regardless of cost-aware routing config
(see orca/serve/routing.py) — these tests cover the fix: a query that
qualifies for escalation now takes a frontier branch here too, and the
finished (non-streaming) frontier response is fake-streamed back as SSE
chunks since Backend.generate() has no token-streaming variant.
"""
from __future__ import annotations

from unittest.mock import MagicMock

import pytest
from fastapi.testclient import TestClient

from orca.serve import api as api_module
from orca.serve.registry import TierResolution
from orca.brain.backends import BackendResponse


@pytest.fixture
def client():
    return TestClient(api_module.app, raise_server_exceptions=False)


def _fake_frontier_resolution():
    return TierResolution(
        tier="core", backend="openai", model="gpt-4o",
        data_left_infrastructure=True, sovereignty_overridden=False,
    )


def _fake_backend_response(text="4"):
    return BackendResponse(
        text=text, backend="openai", model="gpt-4o",
        input_tokens=10, output_tokens=2, cost_usd=0.0001,
        latency_ms=250.0, data_left_infrastructure=True,
    )


def _sse_events(resp):
    events = []
    for line in resp.text.splitlines():
        if line.startswith("data: "):
            import json
            events.append(json.loads(line[len("data: "):]))
    return events


def test_stream_frontier_passthrough_discloses_backend(client, monkeypatch):
    monkeypatch.setattr(api_module, "_resolve_backend_for_chat", lambda variant: _fake_frontier_resolution())
    monkeypatch.setattr(
        api_module, "_generate_via_frontier_backend",
        lambda resolution, persona, message: _fake_backend_response(),
    )
    monkeypatch.setattr(api_module, "check_input", lambda text: MagicMock(action="allow", flagged_categories=[]))

    resp = client.post("/api/stream", json={"message": "What is 2+2?", "model_variant": "nano"})

    assert resp.status_code == 200
    events = _sse_events(resp)
    chunk_text = "".join(e["text"] for e in events if e["type"] == "chunk")
    assert chunk_text == "4"
    done = next(e for e in events if e["type"] == "done")
    assert done["backend"] == "openai"
    assert done["data_left_infrastructure"] is True


def test_stream_ollama_backend_does_not_take_frontier_path(client, monkeypatch):
    frontier_called = {"was_called": False}

    def _fake_frontier_gen(*a, **k):
        frontier_called["was_called"] = True
        return _fake_backend_response()

    ollama_resolution = TierResolution(
        tier="nano", backend="ollama", model="orca-nano",
        data_left_infrastructure=False, sovereignty_overridden=False,
    )
    monkeypatch.setattr(api_module, "_resolve_backend_for_chat", lambda variant: ollama_resolution)
    monkeypatch.setattr(api_module, "_generate_via_frontier_backend", _fake_frontier_gen)
    monkeypatch.setattr(api_module, "check_input", lambda text: MagicMock(action="allow", flagged_categories=[]))

    def _raise_session(*a, **k):
        raise RuntimeError("ollama path reached, as expected")

    monkeypatch.setattr(api_module, "_get_session", _raise_session)

    resp = client.post("/api/stream", json={"message": "hi", "model_variant": "nano"})

    assert frontier_called["was_called"] is False
    assert resp.status_code == 500


def test_stream_frontier_passthrough_redacts_leaked_secrets(client, monkeypatch):
    leaked_key = "sk-" + "a" * 40
    monkeypatch.setattr(api_module, "_resolve_backend_for_chat", lambda variant: _fake_frontier_resolution())
    monkeypatch.setattr(
        api_module, "_generate_via_frontier_backend",
        lambda resolution, persona, message: _fake_backend_response(text=f"Here is a key: {leaked_key}"),
    )
    monkeypatch.setattr(api_module, "check_input", lambda text: MagicMock(action="allow", flagged_categories=[]))

    resp = client.post("/api/stream", json={"message": "give me a key", "model_variant": "nano"})

    assert resp.status_code == 200
    events = _sse_events(resp)
    chunk_text = "".join(e["text"] for e in events if e["type"] == "chunk")
    assert leaked_key not in chunk_text
    assert "REDACTED" in chunk_text


def test_stream_frontier_generation_error_yields_error_event(client, monkeypatch):
    monkeypatch.setattr(api_module, "_resolve_backend_for_chat", lambda variant: _fake_frontier_resolution())

    def _raise(*a, **k):
        raise RuntimeError("upstream API error")

    monkeypatch.setattr(api_module, "_generate_via_frontier_backend", _raise)
    monkeypatch.setattr(api_module, "check_input", lambda text: MagicMock(action="allow", flagged_categories=[]))

    resp = client.post("/api/stream", json={"message": "hi", "model_variant": "nano"})

    assert resp.status_code == 200
    events = _sse_events(resp)
    error = next(e for e in events if e["type"] == "error")
    assert "upstream API error" in error["text"]
