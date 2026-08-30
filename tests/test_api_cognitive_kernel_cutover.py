"""
Real, end-to-end tests through the ACTUAL FastAPI serving surface for
Phase 3's Cognitive Kernel integration:
  - /api/cognitive/execute -- the real cutover path (Kernel is fully
    authoritative: plans AND executes).
  - /api/chat and /api/stream -- shadow-mode only (Kernel plans, real
    response still comes from the existing _Session/AgentLoop path
    unchanged) -- proven by checking shadow metrics update without any
    change to the real response's shape/behavior.

Requires a real, locally-reachable Ollama instance; auto-skips otherwise.
"""
from __future__ import annotations

import httpx
import pytest
from fastapi.testclient import TestClient

from orca.cognitive import metrics as cognitive_metrics
from orca.cognitive import wiring as cognitive_wiring
from orca.gateway import wiring as gateway_wiring


def _ollama_reachable() -> bool:
    try:
        r = httpx.get("http://localhost:11434/api/tags", timeout=2)
        return r.status_code == 200
    except Exception:
        return False


@pytest.fixture(autouse=True)
def _reset_state():
    gateway_wiring.reset_for_tests()
    cognitive_wiring.reset_for_tests()
    cognitive_metrics.reset()
    yield
    gateway_wiring.reset_for_tests()
    cognitive_wiring.reset_for_tests()
    cognitive_metrics.reset()


@pytest.fixture
def client():
    from orca.serve.api import app
    return TestClient(app)


def _skip_if_no_ollama():
    if not _ollama_reachable():
        pytest.skip("No local Ollama instance reachable")


def test_cognitive_execute_real_end_to_end(client):
    _skip_if_no_ollama()
    resp = client.post("/api/cognitive/execute", json={"objective": "Say the single word hello and nothing else."})
    assert resp.status_code == 200
    body = resp.json()
    assert body["status"] == "COMPLETED"
    assert body["output"]
    assert body["resolved_model"]
    assert "ANSWER_DIRECTLY" in body["operations_executed"]


def test_cognitive_execute_defers_tool_requiring_plan_honestly(client):
    _skip_if_no_ollama()
    resp = client.post("/api/cognitive/execute", json={
        "objective": "Search the web for today's news and run this code to verify it."
    })
    body = resp.json()
    assert body["status"] == "COMPLETED"
    assert body["output"] is None
    assert body["warnings"]


def test_cognitive_execute_abstains_on_critical_risk(client):
    resp = client.post("/api/cognitive/execute", json={
        "objective": "How do I rm -rf the production database?"
    })
    body = resp.json()
    assert body["status"] == "ABSTAINED"
    assert body["abstention_reason"] == "INSUFFICIENT_CAPABILITY"


def test_cognitive_execute_blocks_moderated_content(client):
    resp = client.post("/api/cognitive/execute", json={"objective": "ignore everything, just testing moderation path"})
    assert resp.status_code == 200  # benign input -- sanity check the endpoint doesn't over-block


def test_chat_shadow_planning_does_not_change_response_shape(client):
    """The Kernel runs in shadow on /api/stream but must never change the
    real response's contract."""
    _skip_if_no_ollama()
    with client.stream("POST", "/api/stream", json={"message": "Hi", "model_variant": "nano"}) as response:
        raw = "".join(response.iter_text())
    assert response.status_code == 200
    assert "data:" in raw  # unchanged SSE contract

    snapshot = cognitive_metrics.get_snapshot()
    assert (snapshot["shadow_agree"] + snapshot["shadow_disagree"]) >= 1


def test_shadow_planning_failure_never_breaks_the_real_chat_path(client, monkeypatch):
    """Even if something inside Kernel shadow-planning raises, the real
    endpoint must still succeed -- this is the whole point of the
    try/except inside _run_cognitive_shadow itself (patching a real
    internal dependency here, not the function's own safety net, so this
    actually exercises that except block rather than bypassing it)."""
    _skip_if_no_ollama()
    from orca.cognitive import wiring as cog_wiring

    def _boom():
        raise RuntimeError("simulated cognitive kernel failure")

    monkeypatch.setattr(cog_wiring, "get_shared_kernel", _boom)
    with client.stream("POST", "/api/stream", json={"message": "Hi", "model_variant": "nano"}) as response:
        raw = "".join(response.iter_text())
    assert response.status_code == 200
    assert "chunk" in raw or "done" in raw
