"""
Model Society routing performance (Phase 7 spec §63-64). `bench_routing_decision`
is deterministic (100 reps, real p50). Court's live before/after comparison
reuses `orca.deliberation.latency_bench.bench_court_live` directly rather
than a second implementation -- Court now routes Constructor/Falsifier
through Society by default, so that same benchmark IS the "after" number.

Run directly: `.venv/bin/python -m orca.society.latency_bench`.
"""
from __future__ import annotations

import statistics
import time

from orca.society.contracts import CognitiveRole, RoutingRequest
from orca.society.router import route
from orca.society.society_plan import build_court_society_plan

REPS_DETERMINISTIC = 100


def _p50(samples: list[float]) -> float:
    return round(statistics.median(samples), 4)


def bench_routing_decision() -> dict:
    samples = []
    for _ in range(REPS_DETERMINISTIC):
        t0 = time.perf_counter()
        route(RoutingRequest(role=CognitiveRole.CONSTRUCTOR))
        samples.append((time.perf_counter() - t0) * 1000)
    return {"p50_ms": _p50(samples), "reps": len(samples)}


def bench_society_plan_compilation() -> dict:
    samples = []
    for _ in range(REPS_DETERMINISTIC):
        t0 = time.perf_counter()
        build_court_society_plan()
        samples.append((time.perf_counter() - t0) * 1000)
    return {"p50_ms": _p50(samples), "reps": len(samples)}


if __name__ == "__main__":
    import json

    print(json.dumps({
        "routing_decision": bench_routing_decision(),
        "society_plan_compilation": bench_society_plan_compilation(),
    }, indent=2))
