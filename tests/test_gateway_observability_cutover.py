"""
Real serving traffic through the cutover must actually emit Gateway
metrics -- not just that metrics.py's functions work in isolation
(already covered by tests/test_gateway_warmup_health.py), but that a real
/api/stream request through the real app produces a real recorded metric.
"""
from __future__ import annotations

import httpx
import pytest
from fastapi.testclient import TestClient

from orca.gateway import metrics, wiring


def _ollama_reachable() -> bool:
    try:
        r = httpx.get("http://localhost:11434/api/tags", timeout=2)
        return r.status_code == 200
    except Exception:
        return False


@pytest.fixture(autouse=True)
def _reset_state():
    wiring.reset_for_tests()
    metrics.reset()
    yield
    wiring.reset_for_tests()
    metrics.reset()


def test_real_api_request_emits_real_gateway_metrics():
    if not _ollama_reachable():
        pytest.skip("No local Ollama instance reachable")

    from orca.serve.api import app
    client = TestClient(app)

    with client.stream("POST", "/api/stream", json={"message": "hi", "model_variant": "nano"}) as response:
        list(response.iter_text())

    snapshot = metrics.get_snapshot()
    assert len(snapshot["per_deployment"]) >= 1
    deployment_stats = next(iter(snapshot["per_deployment"].values()))
    assert deployment_stats["requests"] >= 1
    assert deployment_stats["successes"] >= 1
