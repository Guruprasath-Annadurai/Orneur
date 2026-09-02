"""
Memory Continuum latency benchmark (Phase 5.1 spec §23-26). Real
measurements against this machine's actual environment -- no fabricated
numbers. Run directly: `.venv/bin/python -m orca.memory.latency_bench`.

Reports p50 (median) over N repetitions for each deterministic
operation, and separately reports the one operation that legitimately
needs a live Ollama call (Truth Fabric refresh) with a smaller rep count
and an explicit skip if Ollama isn't reachable -- never blending that
cost into the deterministic numbers (spec §26: don't attribute Truth
Fabric's own cost to Memory Continuum).
"""
from __future__ import annotations

import statistics
import time
import uuid

from orca.cognitive.contracts import CognitiveRequest
from orca.cognitive.kernel import CognitiveKernel
from orca.memory import episodic, failure, procedural, retrieval, store
from orca.memory.contracts import (
    MemoryEpisode,
    MemoryQuery,
    MemoryScope,
    MemoryType,
    SemanticMemoryRecord,
    WorkingMemory,
)
from orca.memory.firewall import check as firewall_check

REPS = 50


def _p50(samples: list[float]) -> float:
    return round(statistics.median(samples), 4)


def _time_it(fn, reps: int = REPS) -> list[float]:
    samples = []
    for _ in range(reps):
        t0 = time.perf_counter()
        fn()
        samples.append((time.perf_counter() - t0) * 1000)
    return samples


def bench_working_memory_creation_update() -> dict:
    def _op():
        wm = WorkingMemory(objective="benchmark objective")
        for i in range(5):
            wm.add_entity(f"entity{i}")
            wm.add_recalled_memory_id(f"mem-{i}")
    samples = _time_it(_op)
    return {"p50_ms": _p50(samples), "reps": len(samples)}


def bench_memory_firewall(corpus_size: int = 50) -> dict:
    sid = f"bench-{uuid.uuid4().hex[:8]}"
    record = SemanticMemoryRecord(claim="A fact to check.", scope=MemoryScope.SESSION, scope_id=sid)
    samples = _time_it(lambda: firewall_check(record, MemoryScope.SESSION, sid))
    store.delete_scope(MemoryScope.SESSION, sid)
    return {"p50_ms": _p50(samples), "reps": len(samples)}


def bench_semantic_recall(corpus_size: int = 200) -> dict:
    sid = f"bench-{uuid.uuid4().hex[:8]}"
    for i in range(corpus_size):
        store.save(SemanticMemoryRecord(claim=f"Fact number {i} about the deployed system.", scope=MemoryScope.SESSION, scope_id=sid))
    query = MemoryQuery(scope=MemoryScope.SESSION, scope_id=sid, relevance_text="fact about the deployed system", limit=5)
    samples = _time_it(lambda: retrieval.recall(query), reps=20)
    store.delete_scope(MemoryScope.SESSION, sid)
    return {"p50_ms": _p50(samples), "reps": len(samples), "corpus_size": corpus_size}


def bench_episodic_recall(corpus_size: int = 200) -> dict:
    sid = f"bench-{uuid.uuid4().hex[:8]}"
    for i in range(corpus_size):
        episodic.append_episode(MemoryEpisode(scope=MemoryScope.SESSION, scope_id=sid, event=f"event {i} happened", outcome=f"outcome {i}"))
    samples = _time_it(lambda: episodic.list_episodes(MemoryScope.SESSION, sid), reps=20)
    episodic.delete_ledger(MemoryScope.SESSION, sid)
    return {"p50_ms": _p50(samples), "reps": len(samples), "corpus_size": corpus_size}


def bench_procedural_recall() -> dict:
    sid = f"bench-{uuid.uuid4().hex[:8]}"
    procedural.record_procedure(MemoryScope.SESSION, sid, "deploy model", ["validate", "scan", "canary", "promote"])
    samples = _time_it(lambda: procedural.find_by_name(MemoryScope.SESSION, sid, "deploy model"))
    store.delete_scope(MemoryScope.SESSION, sid)
    return {"p50_ms": _p50(samples), "reps": len(samples)}


def bench_failure_recall(corpus_size: int = 50) -> dict:
    sid = f"bench-{uuid.uuid4().hex[:8]}"
    for i in range(corpus_size):
        failure.record_failure(MemoryScope.SESSION, sid, f"deploy service {i} to production", "direct promote", "canary skipped")
    samples = _time_it(lambda: failure.find_relevant(MemoryScope.SESSION, sid, "deploy production canary"), reps=20)
    store.delete_scope(MemoryScope.SESSION, sid)
    return {"p50_ms": _p50(samples), "reps": len(samples), "corpus_size": corpus_size}


def bench_candidate_promotion() -> dict:
    from orca.memory.arbiter import MemoryArbiter
    from orca.memory.contracts import MemoryCandidate

    sid = f"bench-{uuid.uuid4().hex[:8]}"
    arbiter = MemoryArbiter()

    def _op():
        candidate = MemoryCandidate(extracted_claim=f"A fact {uuid.uuid4().hex[:6]}.", scope=MemoryScope.SESSION, scope_id=sid)
        existing = store.list_records(MemoryType.SEMANTIC, MemoryScope.SESSION, sid)
        decision, _ = arbiter.decide_promotion(candidate, existing)
        if decision.value == "PROMOTED":
            arbiter.promote(candidate)

    samples = _time_it(_op, reps=20)
    store.delete_scope(MemoryScope.SESSION, sid)
    return {"p50_ms": _p50(samples), "reps": len(samples)}


def bench_kernel_fast_path_no_memory() -> dict:
    """spec §24: a plan with no RECALL_MEMORY operation must pay nothing
    extra for the memory subsystem's presence. Measures kernel.plan()
    (pure, synchronous, no I/O) for an objective that does NOT trigger
    RECALL_MEMORY, to isolate planning overhead from any model-call cost."""
    kernel = CognitiveKernel()

    def _op():
        request = CognitiveRequest(objective="What is 2 + 2?")
        kernel.plan(request)

    samples = _time_it(_op, reps=100)
    return {"p50_ms": _p50(samples), "reps": len(samples)}


def bench_truth_refresh(reps: int = 3) -> dict:
    """Spec §26: measured SEPARATELY from Memory Continuum's own recall
    cost, and never blended into it. Requires live Ollama -- returns a
    clear skip marker (not a fabricated number) if unreachable."""
    from tests.ollama_test_support import ollama_reachable
    if not ollama_reachable():
        return {"skipped": True, "reason": "no local Ollama instance reachable"}

    import asyncio
    from orca.memory.contracts import EpistemicState
    from orca.memory.refresh import refresh_stale_memory

    async def _run():
        samples = []
        for _ in range(reps):
            record = SemanticMemoryRecord(
                claim="The Eiffel Tower is located in Paris, France.", scope=MemoryScope.SESSION,
                scope_id=f"bench-{uuid.uuid4().hex[:8]}", epistemic_state=EpistemicState.STALE,
            )
            t0 = time.perf_counter()
            await refresh_stale_memory(record, doc_store=None)
            samples.append((time.perf_counter() - t0) * 1000)
        return samples

    samples = asyncio.run(_run())
    return {"p50_ms": _p50(samples), "reps": len(samples), "note": "no doc_store given -- measures web-search-path cost only, real network conditions in this sandbox may show near-zero web results"}


def bench_fast_path_vs_memory_recall_kernel_roundtrip(reps: int = 3) -> dict:
    """Spec §24: a normal conversational request that does NOT require
    memory recall must not incur memory-subsystem cost. Compares two
    FULL CognitiveKernel.execute() round trips (both make a real Ollama
    call, so both include real model latency) -- one whose plan has no
    RECALL_MEMORY operation, one whose plan does but finds nothing (a
    cold/empty scope). The DIFFERENCE between them isolates the memory
    subsystem's own overhead from shared model-call latency, rather than
    comparing an apples-to-oranges bare function call vs a full request."""
    from tests.ollama_test_support import ollama_reachable
    if not ollama_reachable():
        return {"skipped": True, "reason": "no local Ollama instance reachable"}

    import asyncio
    kernel = CognitiveKernel()

    async def _run_no_memory():
        samples = []
        for _ in range(reps):
            request = CognitiveRequest(objective="What is the capital of France?")  # FACTUAL intent, no memory/search signal -> no RECALL_MEMORY op
            t0 = time.perf_counter()
            await kernel.execute(request)
            samples.append((time.perf_counter() - t0) * 1000)
        return samples

    async def _run_with_memory_recall_empty():
        samples = []
        for _ in range(reps):
            sid = f"bench-{uuid.uuid4().hex[:8]}"
            request = CognitiveRequest(objective="What did I tell you earlier about my project?", session_id=sid)  # MEMORY_RECALL intent
            t0 = time.perf_counter()
            await kernel.execute(request)
            samples.append((time.perf_counter() - t0) * 1000)
            store.delete_scope(MemoryScope.SESSION, sid)
        return samples

    no_memory_samples = asyncio.run(_run_no_memory())
    with_memory_samples = asyncio.run(_run_with_memory_recall_empty())
    return {
        "no_memory_recall_p50_ms": _p50(no_memory_samples), "with_memory_recall_p50_ms": _p50(with_memory_samples),
        "overhead_ms": round(_p50(with_memory_samples) - _p50(no_memory_samples), 2), "reps": reps,
    }


def run_all() -> dict:
    return {
        "environment": {
            "note": "Local disk-backed JSON/JSONL stores, no external database -- see docs/orneur/phase-5/ARCHITECTURE.md",
            "reps_default": REPS,
        },
        "working_memory_creation_update": bench_working_memory_creation_update(),
        "memory_firewall": bench_memory_firewall(),
        "semantic_recall": bench_semantic_recall(),
        "episodic_recall": bench_episodic_recall(),
        "procedural_recall": bench_procedural_recall(),
        "failure_recall": bench_failure_recall(),
        "candidate_promotion": bench_candidate_promotion(),
        "kernel_fast_path_no_memory_plan_only": bench_kernel_fast_path_no_memory(),
    }


if __name__ == "__main__":
    import json
    print(json.dumps(run_all(), indent=2))
