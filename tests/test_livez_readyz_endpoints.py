"""
Phase 14 §18-21 -- real tests for the new /livez and /readyz endpoints
that separate liveness ("is the process alive?") from readiness ("can
this worker safely serve traffic right now?"), closing the gap found in
docs/orneur/phase-14/CURRENT_DEPLOYMENT_ARCHITECTURE.md (both probes
previously pointed at the same combined /healthz endpoint).
"""
from __future__ import annotations

import pytest
from fastapi.testclient import TestClient

from orca.serve import api as api_module


@pytest.fixture
def client():
    return TestClient(api_module.app)


def test_livez_never_calls_a_dependency(client, monkeypatch):
    """Liveness must answer without touching any dependency -- verify by
    making resolve_tier_model raise; /livez must still return 200."""
    def _raise(tier, host=None):
        raise RuntimeError("dependency check must never run for liveness")

    monkeypatch.setattr(api_module, "resolve_tier_model", _raise)
    resp = client.get("/livez")
    assert resp.status_code == 200
    assert resp.json()["status"] == "alive"


def test_readyz_ready_when_model_resolves(client, monkeypatch):
    monkeypatch.setattr(api_module, "resolve_tier_model", lambda tier, host=None: "orca-nano")
    resp = client.get("/readyz")
    assert resp.status_code == 200
    body = resp.json()
    assert body["status"] == "ready"
    assert body["dependencies"]["model_runtime"]["status"] == "ok"
    assert "authority_store" in body["dependencies"]


def test_readyz_not_ready_when_model_runtime_unavailable(client, monkeypatch):
    """Spec §21-22: the model runtime is a REQUIRED dependency -- its
    failure must flip readiness to false and return 503, not merely be
    reported as a sub-field."""
    def _raise(tier, host=None):
        raise RuntimeError("No installed Ollama model found for tier 'nano'")

    monkeypatch.setattr(api_module, "resolve_tier_model", _raise)
    resp = client.get("/readyz")
    assert resp.status_code == 503
    body = resp.json()
    assert body["status"] == "not_ready"
    assert body["dependencies"]["model_runtime"]["status"] == "unavailable"


def test_readyz_reports_authority_store_backend(client, monkeypatch):
    """Spec §21: dependencies tracked separately -- readyz must surface
    which authority backend (sqlite/postgres) this worker is actually
    using, without that reporting itself flipping readiness (a reachable
    but non-elevated-only worker is still ready to serve ordinary
    traffic per spec §22/§53)."""
    monkeypatch.setattr(api_module, "resolve_tier_model", lambda tier, host=None: "orca-nano")
    resp = client.get("/readyz")
    assert resp.status_code == 200
    assert resp.json()["dependencies"]["authority_store"]["status"] == "ok"


def test_healthz_contract_unchanged_by_the_new_endpoints(client, monkeypatch):
    """Regression guard: adding /livez and /readyz must not change
    /healthz's existing response shape (status/nano_model/gateway at the
    top level) -- see tests/test_healthz_endpoint.py for the original
    contract this must keep matching."""
    monkeypatch.setattr(api_module, "resolve_tier_model", lambda tier, host=None: "orca-nano")
    resp = client.get("/healthz")
    assert resp.status_code == 200
    body = resp.json()
    assert body["status"] == "ok"
    assert body["nano_model"] == "orca-nano"
    assert "dependencies" not in body
