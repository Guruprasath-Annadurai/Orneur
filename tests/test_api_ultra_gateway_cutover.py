"""
Direct-Ollama audit finding (Phase 2.1): unlike /api/chat and /api/stream,
the live /api/ultra SSE endpoint built its own OrcaBrain via get_brain()
inside OrcaUltra.__init__, completely bypassing the Model Gateway -- an
UNEXPECTED_APPLICATION_BYPASS. Fixed by resolving a Gateway-routed brain
the same way _Session.__init__ does and injecting it into OrcaUltra via
its new optional `brain` constructor param. This test proves real traffic
through the real HTTP endpoint now emits real Gateway metrics, the same
way tests/test_gateway_observability_cutover.py proves it for /api/stream.
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


def test_real_ultra_request_emits_real_gateway_metrics(monkeypatch):
    if not _ollama_reachable():
        pytest.skip("No local Ollama instance reachable")

    from orca.serve import api as api_module
    monkeypatch.setattr(api_module, "has_feature", lambda feature: True)

    client = TestClient(api_module.app)

    with client.stream(
        "POST", "/api/ultra", json={"task": "Say hi in one word."}
    ) as response:
        events = list(response.iter_lines())

    assert any('"type": "done"' in e or '"type":"done"' in e for e in events)

    snapshot = metrics.get_snapshot()
    assert len(snapshot["per_deployment"]) >= 1
