"""Independent Reliability, Resilience & Bounded Performance Laboratory.

Measures operational performance under explicitly identified workloads:
1. Deterministic synthetic test double (FakeOllama) functional test
2. True concurrent load test via multi-threaded client pool (FakeOllama)
3. Real Ollama live inference latency & TTFT benchmark (real llama3.2:1b)
"""
from __future__ import annotations

import concurrent.futures
import time
import urllib.request
import pytest
from starlette.testclient import TestClient

from tests.fake_ollama import FakeOllama, point_orneur_at
from tests.test_g006_tenant_isolation import _hdr, _signup, client  # noqa: F401


@pytest.fixture
def fake(client, monkeypatch):
    from orca.serve import ratelimit

    ratelimit._local_counters.clear()
    with FakeOllama() as f:
        point_orneur_at(f, monkeypatch)
        yield f


def _ollama_reachable() -> bool:
    try:
        with urllib.request.urlopen("http://127.0.0.1:11434/api/tags", timeout=1.5) as r:
            return r.status == 200
    except Exception:
        return False


class TestReliabilityAndPerformance:
    def test_deterministic_fake_provider_functional(self, client: TestClient, fake: FakeOllama):
        """Functional verification of serving path using deterministic FakeOllama.

        Provider: FakeOllama (Synthetic test double)
        Transport: In-process ASGI TestClient
        Concurrency: Sequential (1 client)
        """
        token, _ = _signup(client)
        t0 = time.perf_counter()
        resp = client.post(
            "/api/chat",
            headers=_hdr(token),
            json={"message": "ping", "model_variant": "core"},
        )
        duration = time.perf_counter() - t0
        assert resp.status_code == 200
        assert resp.json()["response"] == "FAKE-REPLY"
        assert duration < 2.0

    def test_concurrent_client_load_fake_provider(self, client: TestClient, fake: FakeOllama):
        """Concurrent load test using multi-threaded client requests against TestClient.

        Provider: FakeOllama (Synthetic test double)
        Transport: In-process ASGI TestClient
        Concurrency: 4 concurrent worker threads
        """
        token, _ = _signup(client)
        num_workers = 4
        latencies = []
        errors = 0

        def _send(idx: int) -> tuple[int, float]:
            t0 = time.perf_counter()
            r = client.post(
                "/api/chat",
                headers=_hdr(token),
                json={"message": f"concurrent-probe-{idx}", "session_id": f"sess-c-{idx}", "model_variant": "core"},
            )
            return r.status_code, time.perf_counter() - t0

        with concurrent.futures.ThreadPoolExecutor(max_workers=num_workers) as executor:
            futures = [executor.submit(_send, i) for i in range(num_workers)]
            for fut in concurrent.futures.as_completed(futures):
                status_code, dur = fut.result()
                latencies.append(dur)
                if status_code != 200:
                    errors += 1

        assert errors == 0, f"Encountered {errors}/{num_workers} errors under concurrent load"
        assert len(latencies) == num_workers
        assert max(latencies) < 5.0, f"Max concurrent latency exceeded 5s: {max(latencies):.2f}s"

    @pytest.mark.live_ollama_smoke
    def test_live_ollama_real_latency_and_ttft(self):
        """Real-model latency and Time To First Token (TTFT) benchmark.

        Provider: Real Ollama (llama3.2:1b)
        Transport: Direct HTTP / 127.0.0.1:11434
        Concurrency: Sequential (1 client)
        """
        if not _ollama_reachable():
            pytest.skip("Real Ollama not reachable on localhost:11434")

        import json

        payload = json.dumps({
            "model": "llama3.2:1b",
            "prompt": "Say hello in one word.",
            "stream": True,
        }).encode("utf-8")

        req = urllib.request.Request(
            "http://127.0.0.1:11434/api/generate",
            data=payload,
            headers={"Content-Type": "application/json"},
        )

        t0 = time.perf_counter()
        first_chunk_time = None
        total_chunks = 0

        with urllib.request.urlopen(req, timeout=10.0) as resp:
            for line in resp:
                if line.strip():
                    total_chunks += 1
                    if first_chunk_time is None:
                        first_chunk_time = time.perf_counter() - t0

        total_time = time.perf_counter() - t0
        assert first_chunk_time is not None, "Did not receive any streaming chunks from Ollama"
        assert total_chunks > 0

        # Log measured numbers for truthful reporting
        pytest.real_ollama_ttft = first_chunk_time
        pytest.real_ollama_total_time = total_time
