"""
Phase 2.1 integrated-path performance measurement -- unlike Phase 2's
INFERENCE_BASELINE.md (which measured OllamaRuntime directly), this hits
the ACTUAL live HTTP API (/api/stream via a real FastAPI TestClient) so
the numbers include auth/ratelimit/quota/moderation, session/AgentLoop
overhead, GatewayBrain's sync-bridge thread hop, ModelGateway routing
(circuit breaker + concurrency acquire), and OllamaRuntime itself --
the full path real user traffic actually takes post-cutover.
"""
from __future__ import annotations

import json
import time

from fastapi.testclient import TestClient

from orca.gateway import metrics, wiring


def measure_stream(client: TestClient, message: str, model_variant: str = "nano") -> dict:
    start = time.monotonic()
    first_chunk_at = None
    chunk_count = 0
    with client.stream(
        "POST", "/api/stream", json={"message": message, "model_variant": model_variant}
    ) as response:
        for _ in response.iter_text():
            if first_chunk_at is None:
                first_chunk_at = time.monotonic()
            chunk_count += 1
    end = time.monotonic()
    return {
        "ttft_ms": round((first_chunk_at - start) * 1000, 1) if first_chunk_at else None,
        "total_ms": round((end - start) * 1000, 1),
        "chunk_count": chunk_count,
    }


def main():
    wiring.reset_for_tests()
    metrics.reset()

    from orca.serve.api import app
    client = TestClient(app)

    runs = []
    for i in range(3):
        result = measure_stream(client, f"Say hello in exactly three words. (run {i})")
        runs.append(result)
        print(json.dumps(result))

    snapshot = metrics.get_snapshot()
    print("gateway_metrics_snapshot:", json.dumps(snapshot, default=str))

    with open("docs/orneur/phase-2/integrated_baseline_raw.json", "w") as f:
        json.dump({"runs": runs, "gateway_metrics": snapshot}, f, indent=2, default=str)


if __name__ == "__main__":
    main()
