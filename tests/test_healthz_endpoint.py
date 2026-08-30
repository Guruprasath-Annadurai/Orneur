"""
Tests for GET /healthz — the lightweight liveness/readiness probe added
this session for load balancers/orchestrators to poll frequently, instead
of the much heavier /api/status (which globs every raw training file and
lists all sessions on every call).
"""
from __future__ import annotations

import pytest
from fastapi.testclient import TestClient

from orca.serve import api as api_module


@pytest.fixture
def client():
    return TestClient(api_module.app)


def test_healthy_when_nano_model_resolves(client, monkeypatch):
    monkeypatch.setattr(api_module, "resolve_tier_model", lambda tier, host=None: "orca-nano")

    resp = client.get("/healthz")
    assert resp.status_code == 200
    body = resp.json()
    # Phase 2.1 added an additive "gateway" readiness field (see
    # test_healthz_gateway_readiness.py) -- checking these two fields
    # specifically (the endpoint's original, still-honored contract)
    # rather than exact dict equality, so that addition doesn't count as
    # breaking this test.
    assert body["status"] == "ok"
    assert body["nano_model"] == "orca-nano"


def test_unhealthy_when_no_model_available(client, monkeypatch):
    def _raise(tier, host=None):
        raise RuntimeError("No installed Ollama model found for tier 'nano'")

    monkeypatch.setattr(api_module, "resolve_tier_model", _raise)

    resp = client.get("/healthz")
    assert resp.status_code == 503
    body = resp.json()
    assert body["status"] == "unhealthy"
    assert "nano" in body["reason"]


def test_healthz_does_not_touch_disk_or_sessions(client, monkeypatch):
    """The whole point of /healthz vs /api/status: it must not do the heavy
    disk-globbing/session-listing work — verify by making resolve_tier_model
    the only thing that runs."""
    calls = []
    monkeypatch.setattr(
        api_module, "resolve_tier_model",
        lambda tier, host=None: calls.append(tier) or "orca-nano",
    )

    resp = client.get("/healthz")
    assert resp.status_code == 200
    assert calls == ["nano"]
