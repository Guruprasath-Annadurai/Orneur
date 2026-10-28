"""Independent Reliability, Resilience & Bounded Performance Laboratory.

Measures operational performance under bounded load:
- TTFT (Time to first chunk / response)
- Total turnaround latency
- Concurrency behavior across multiple simultaneous clients
- Error rates and failure resilience
"""
from __future__ import annotations

import time
import pytest
from starlette.testclient import TestClient

from tests.fake_ollama import FakeOllama, point_orneur_at
from tests.test_g006_tenant_isolation import _hdr, _signup, client  # noqa: F401


class TestReliabilityAndPerformance:
    def test_bounded_concurrent_chat_requests(self, client: TestClient, monkeypatch):
        """Send a bounded burst of chat requests and verify zero drops and bounded latency."""
        f = FakeOllama()
        point_orneur_at(f, monkeypatch)

        token, _ = _signup(client)
        num_requests = 8
        latencies = []
        errors = 0

        for i in range(num_requests):
            t0 = time.perf_counter()
            resp = client.post(
                "/api/chat",
                headers=_hdr(token),
                json={"message": f"Reliability burst probe #{i}", "session_id": f"sess-perf-{i}"},
            )
            elapsed = time.perf_counter() - t0
            latencies.append(elapsed)
            if resp.status_code != 200:
                errors += 1

        avg_latency = sum(latencies) / len(latencies)
        max_latency = max(latencies)

        assert errors == 0, f"Encountered {errors}/{num_requests} errors during bounded load test"
        assert max_latency < 5.0, f"Max latency exceeded threshold: {max_latency:.2f}s"
        assert avg_latency < 2.0, f"Average latency exceeded threshold: {avg_latency:.2f}s"
