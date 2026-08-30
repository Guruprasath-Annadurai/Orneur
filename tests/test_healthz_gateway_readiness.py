"""
/healthz's existing contract (status/nano_model) must survive Phase 2.1
unchanged (backward compatibility, per explicit instruction not to
silently break clients) -- the Gateway's readiness report is additive.
"""
from __future__ import annotations

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


def test_healthz_preserves_existing_contract_fields(client):
    if not _ollama_reachable():
        pytest.skip("No local Ollama instance reachable")
    response = client.get("/healthz")
    assert response.status_code == 200
    body = response.json()
    assert "status" in body
    assert "nano_model" in body


def test_healthz_includes_additive_gateway_readiness_field(client):
    if not _ollama_reachable():
        pytest.skip("No local Ollama instance reachable")
    response = client.get("/healthz")
    body = response.json()
    assert "gateway" in body
    assert "service_live" in body["gateway"]
    assert "service_ready" in body["gateway"]
    assert "model_readiness" in body["gateway"]


def test_healthz_model_readiness_reflects_real_traffic(client):
    """Before any chat request, no deployment is registered yet (lazy
    registration) -- after one, the served model shows up as READY."""
    if not _ollama_reachable():
        pytest.skip("No local Ollama instance reachable")

    before = client.get("/healthz").json()
    assert before["gateway"]["model_readiness"] == {}

    with client.stream("POST", "/api/stream", json={"message": "hi", "model_variant": "nano"}) as response:
        list(response.iter_text())

    after = client.get("/healthz").json()
    assert "orneur-genesis" in after["gateway"]["model_readiness"]
    # CANDIDATE_ONLY, not READY -- honest, correct: the live serving path
    # registers deployments as EXPERIMENTAL lifecycle (nothing has cleared
    # Phase 1's promotion gate yet), so report_health() must never claim
    # READY (that's reserved for a genuine PRODUCTION deployment). See
    # docs/orneur/phase-2/LIVE_SERVING_CUTOVER.md's policy-decision section.
    assert after["gateway"]["model_readiness"]["orneur-genesis"] == "CANDIDATE_ONLY"
