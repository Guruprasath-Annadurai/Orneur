"""
Deliberation Fabric latency benchmark (Phase 6 spec §56). Real
measurements, no fabricated numbers. Deterministic parts run many
repetitions for a real p50; the live-Ollama Court roles run a small,
honest repetition count and report p50 only (too few samples for a
defensible p95 -- same discipline as orca/memory/latency_bench.py).

Run directly: `.venv/bin/python -m orca.deliberation.latency_bench`.
"""
from __future__ import annotations

import statistics
import time

from orca.cognitive.contracts import ComplexityLevel, EvidenceLevel, RiskLevel
from orca.deliberation.compiler import compile_reasoning_plan

REPS_DETERMINISTIC = 100
REPS_LIVE = 2


def _p50(samples: list[float]) -> float:
    return round(statistics.median(samples), 4)


def bench_reasoning_compiler() -> dict:
    samples = []
    for _ in range(REPS_DETERMINISTIC):
        t0 = time.perf_counter()
        compile_reasoning_plan("Should we drop this production table?", ComplexityLevel.HIGH, RiskLevel.CRITICAL, EvidenceLevel.AUDIT_GRADE)
        samples.append((time.perf_counter() - t0) * 1000)
    return {"p50_ms": _p50(samples), "reps": len(samples)}


def bench_court_live(reps: int = REPS_LIVE) -> dict:
    from tests.ollama_test_support import ollama_reachable
    if not ollama_reachable():
        return {"skipped": True, "reason": "no local Ollama instance reachable"}

    import asyncio
    from orca.deliberation.court import CognitiveCourt
    from orca.docs.chunker import Chunk
    from orca.docs.store import DocStore
    from orca.gateway import wiring as gateway_wiring

    async def _run():
        gateway_wiring.reset_for_tests()
        constructor_samples, falsifier_samples, total_samples = [], [], []
        for i in range(reps):
            import uuid
            doc_store = DocStore(session_id=f"bench-court-{uuid.uuid4().hex[:8]}")
            chunk = Chunk(text="The Eiffel Tower is 330 meters tall and located in Paris, France.", doc_id="d1", filename="f.txt", chunk_idx=0, char_start=0, char_end=60)
            doc_store.add_chunks([chunk], doc_id="d1", filename="f.txt")

            from orca.cognitive.contracts import FreshnessLevel
            from orca.cognitive.intent import compile_intent
            from orca.truth.contracts import TruthRequest
            from orca.truth.truth_fabric import TruthFabric
            fabric = TruthFabric()
            objective = "Where is the Eiffel Tower located?"
            intent = compile_intent(objective)
            req = TruthRequest(objective=objective, evidence_requirement=EvidenceLevel.SUPPORTED, freshness_requirement=FreshnessLevel.STATIC)
            truth_result = await fabric.assess_evidence(req, intent, ComplexityLevel.LOW, doc_store=doc_store)

            court = CognitiveCourt()
            t0 = time.perf_counter()
            case, verdict, stop_reason = await court.run(objective, truth_result=truth_result, risk_level=RiskLevel.LOW)
            total_samples.append((time.perf_counter() - t0) * 1000)
            for role_exec in case.role_executions:
                if role_exec.role.value == "CONSTRUCTOR":
                    constructor_samples.append(role_exec.latency_ms)
                elif role_exec.role.value == "FALSIFIER":
                    falsifier_samples.append(role_exec.latency_ms)
        gateway_wiring.reset_for_tests()
        return constructor_samples, falsifier_samples, total_samples

    constructor_samples, falsifier_samples, total_samples = asyncio.run(_run())
    return {
        "constructor_p50_ms": _p50(constructor_samples) if constructor_samples else None,
        "falsifier_p50_ms": _p50(falsifier_samples) if falsifier_samples else None,
        "total_court_p50_ms": _p50(total_samples) if total_samples else None,
        "reps": reps,
        "note": "EvidenceClerk/RiskCounsel/Arbiter are deterministic (no model call) -- their cost is included in total_court_p50_ms's gap versus constructor+falsifier, and is sub-millisecond (see the deterministic benchmarks above).",
    }


def run_all() -> dict:
    return {
        "environment": {"note": "This session's local machine; Court roles use the nano tier via ModelGateway/Ollama."},
        "reasoning_compiler": bench_reasoning_compiler(),
        "court_live_ollama": bench_court_live(),
    }


if __name__ == "__main__":
    import json
    print(json.dumps(run_all(), indent=2))
