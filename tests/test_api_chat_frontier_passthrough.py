"""
Integration tests for POST /api/chat's frontier-passthrough branch —
verifies the actual wiring in orca/serve/api.py, not just the underlying
registry/backend units in isolation.

Covers the real design property: a frontier-backend response includes
`backend` and `data_left_infrastructure` in the API response itself (not
just internal metrics/audit) — the transparency claim is part of the
product contract with the caller, not an implementation detail.
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
    # raise_server_exceptions=False so a 500 from an unhandled exception in
    # the app is inspectable as a response, not re-raised into the test —
    # matches how a real deployed server actually behaves for callers.
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


def test_frontier_passthrough_response_discloses_backend(client, monkeypatch):
    monkeypatch.setattr(api_module, "_resolve_backend_for_chat", lambda variant: _fake_frontier_resolution())
    monkeypatch.setattr(
        api_module, "_generate_via_frontier_backend",
        lambda resolution, persona, message: _fake_backend_response(),
    )
    monkeypatch.setattr(api_module, "check_input", lambda text: MagicMock(action="allow", flagged_categories=[]))

    resp = client.post("/api/chat", json={"message": "What is 2+2?", "model_variant": "nano"})

    assert resp.status_code == 200
    body = resp.json()
    assert body["response"] == "4"
    assert body["backend"] == "openai"
    assert body["data_left_infrastructure"] is True
    assert body["plan"] == "frontier_passthrough"
    assert body["used_tools"] == []


def test_ollama_backend_does_not_take_frontier_path(client, monkeypatch):
    """A tier resolved to ollama must NOT go through the frontier
    passthrough branch — this would be a real regression if the branch
    condition were ever inverted."""
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

    # Force the ollama-path session/agent machinery to fail fast and
    # predictably rather than actually hitting a real Ollama instance —
    # we only care whether the frontier branch was (correctly) skipped.
    def _raise_session(*a, **k):
        raise RuntimeError("ollama path reached, as expected")

    monkeypatch.setattr(api_module, "_get_session", _raise_session)

    resp = client.post("/api/chat", json={"message": "hi", "model_variant": "nano"})

    assert frontier_called["was_called"] is False
    # 500 is expected here (we deliberately broke the ollama path to prove
    # it's the one that was reached) — the real assertion is the line above.
    assert resp.status_code == 500


def test_frontier_passthrough_redacts_leaked_secrets_from_response(client, monkeypatch):
    """
    Real gap this closes: nothing previously scanned model OUTPUT for
    leaked secrets before returning it to the caller (see orca/serve/dlp.py).
    """
    leaked_key = "sk-" + "a" * 40
    monkeypatch.setattr(api_module, "_resolve_backend_for_chat", lambda variant: _fake_frontier_resolution())
    monkeypatch.setattr(
        api_module, "_generate_via_frontier_backend",
        lambda resolution, persona, message: _fake_backend_response(text=f"Here is a key: {leaked_key}"),
    )
    monkeypatch.setattr(api_module, "check_input", lambda text: MagicMock(action="allow", flagged_categories=[]))

    resp = client.post("/api/chat", json={"message": "give me a key", "model_variant": "nano"})

    assert resp.status_code == 200
    assert leaked_key not in resp.json()["response"]
    assert "REDACTED" in resp.json()["response"]


def test_frontier_generation_error_returns_500_not_crash(client, monkeypatch):
    monkeypatch.setattr(api_module, "_resolve_backend_for_chat", lambda variant: _fake_frontier_resolution())

    def _raise(*a, **k):
        raise RuntimeError("upstream API error")

    monkeypatch.setattr(api_module, "_generate_via_frontier_backend", _raise)
    monkeypatch.setattr(api_module, "check_input", lambda text: MagicMock(action="allow", flagged_categories=[]))

    resp = client.post("/api/chat", json={"message": "hi", "model_variant": "nano"})

    assert resp.status_code == 500
    assert "upstream API error" in resp.json()["error"]
