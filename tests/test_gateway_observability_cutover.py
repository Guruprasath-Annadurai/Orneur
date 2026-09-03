"""
Real serving traffic through the cutover must actually emit Gateway
metrics -- not just that metrics.py's functions work in isolation
(already covered by tests/test_gateway_warmup_health.py), but that a real
/api/stream request through the real app produces a real recorded metric.

Phase 7.2 spec §19-22: this test makes a genuine live-Ollama call (through
the full app, not a mock) -- correctly classified `live_ollama_smoke`
(it was NOT marked as such before, so it silently ran inside every
"deterministic" suite pass and was found flaking under full-suite load:
root cause was an uncontrolled-length generation for the prompt "hi",
which a nano-tier model can answer with anywhere from one word to several
sentences, making duration -- and thus exposure to real Ollama queueing
under concurrent load -- unpredictable). Fixed by (1) the correct
`live_ollama_smoke` marker, (2) reusing the project's centralized
`tests/ollama_test_support.py` readiness/warmup helpers instead of a
second, duplicated reachability check, and (3) a prompt engineered for a
short, low-variance reply -- never a mock, never a blind retry, and the
exact same functional assertion (a real request through the real app
produces real recorded Gateway metrics).
"""
from __future__ import annotations

import pytest
from fastapi.testclient import TestClient

from orca.gateway import metrics, wiring
from tests.ollama_test_support import require_ollama, warm_model


@pytest.fixture(autouse=True)
def _reset_state():
    wiring.reset_for_tests()
    metrics.reset()
    yield
    wiring.reset_for_tests()
    metrics.reset()


@pytest.mark.live_ollama_smoke
def test_real_api_request_emits_real_gateway_metrics():
    require_ollama()
    warm_model("nano")  # absorbs any cold-load latency here, not in this test's own timing

    from orca.serve.api import app
    client = TestClient(app)

    with client.stream(
        "POST", "/api/stream", json={"message": "Reply with exactly one word: OK.", "model_variant": "nano"},
    ) as response:
        list(response.iter_text())

    snapshot = metrics.get_snapshot()
    assert len(snapshot["per_deployment"]) >= 1
    deployment_stats = next(iter(snapshot["per_deployment"].values()))
    assert deployment_stats["requests"] >= 1
    assert deployment_stats["successes"] >= 1
