"""
Phase 5: CognitiveKernel actually consults Memory Continuum before
answering directly -- fixes the audit's Finding #2
(docs/orneur/phase-5/CURRENT_MEMORY_ARCHITECTURE.md): RECALL_MEMORY was
marked SUPPORTED_NOW but _answer_directly() never consulted memory at
all. Deterministic -- tests _recall_memory_and_enrich() directly (no
Ollama call inside it), not the full execute() round trip.
"""
from __future__ import annotations

import uuid

import pytest

from orca.cognitive.contracts import CognitiveBudget, CognitiveRequest
from orca.cognitive.kernel import CognitiveKernel
from orca.memory import episodic, store
from orca.memory.contracts import EpistemicState, MemoryScope, SemanticMemoryRecord


class _FakeTraceBuilder:
    def __init__(self):
        self.memory_traces = []

    def record_memory_trace(self, memory_trace):
        self.memory_traces.append(memory_trace)


@pytest.fixture
def sid():
    scope_id = f"test-{uuid.uuid4().hex[:8]}"
    yield scope_id
    episodic.delete_ledger(MemoryScope.SESSION, scope_id)
    store.delete_scope(MemoryScope.SESSION, scope_id)


@pytest.mark.asyncio
async def test_recall_enriches_objective_with_relevant_memory(sid):
    record = SemanticMemoryRecord(
        claim="Project Atlas uses PostgreSQL for storage.", entities=["Atlas"],
        scope=MemoryScope.SESSION, scope_id=sid, epistemic_state=EpistemicState.SUPPORTED,
    )
    store.save(record)

    kernel = CognitiveKernel()
    request = CognitiveRequest(objective="What database does Project Atlas use?", session_id=sid)
    plan = kernel.plan(request)
    trace_builder = _FakeTraceBuilder()

    enriched = await kernel._recall_memory_and_enrich(request, plan, trace_builder)
    assert "PostgreSQL" in enriched
    assert trace_builder.memory_traces
    assert record.memory_id in trace_builder.memory_traces[0].memory_ids_recalled


@pytest.mark.asyncio
async def test_recall_never_leaks_across_sessions(sid):
    other_sid = f"other-{uuid.uuid4().hex[:8]}"
    record = SemanticMemoryRecord(claim="Secret project codename is Blackbird.", scope=MemoryScope.SESSION, scope_id=other_sid)
    store.save(record)

    kernel = CognitiveKernel()
    request = CognitiveRequest(objective="What is the secret project codename?", session_id=sid)
    plan = kernel.plan(request)
    enriched = await kernel._recall_memory_and_enrich(request, plan, _FakeTraceBuilder())

    assert "Blackbird" not in enriched
    store.delete_scope(MemoryScope.SESSION, other_sid)


@pytest.mark.asyncio
async def test_recall_never_injects_disproven_memory(sid):
    record = SemanticMemoryRecord(claim="The system uses Model Z.", scope=MemoryScope.SESSION, scope_id=sid, epistemic_state=EpistemicState.DISPROVEN)
    store.save(record)

    kernel = CognitiveKernel()
    request = CognitiveRequest(objective="What model does the system use?", session_id=sid)
    plan = kernel.plan(request)
    enriched = await kernel._recall_memory_and_enrich(request, plan, _FakeTraceBuilder())

    assert "Model Z" not in enriched


@pytest.mark.asyncio
async def test_recall_consumes_memory_operations_budget(sid):
    record = SemanticMemoryRecord(claim="Fact.", scope=MemoryScope.SESSION, scope_id=sid)
    store.save(record)
    kernel = CognitiveKernel()
    request = CognitiveRequest(objective="tell me the fact", session_id=sid, budget_constraints=CognitiveBudget(max_memory_operations=1))
    plan = kernel.plan(request)
    plan.budget.max_memory_operations = 0  # force exhaustion
    enriched = await kernel._recall_memory_and_enrich(request, plan, _FakeTraceBuilder())
    assert enriched == request.objective  # budget exhausted -> degrades to plain objective, never raises
