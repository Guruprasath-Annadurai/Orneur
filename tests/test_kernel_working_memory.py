"""
Phase 5.1: WorkingMemory is now a real, bounded object threaded through
CognitiveKernel's execution (spec §3-6) -- not just a contract. Covers
bounds, lifecycle disposition, and the security requirement that
WorkingMemory can only ever carry memory the Firewall already allowed.
"""
from __future__ import annotations

import uuid

import pytest

from orca.cognitive.contracts import CognitiveRequest
from orca.cognitive.kernel import CognitiveKernel
from orca.memory import episodic, store
from orca.memory.contracts import (
    EpistemicState,
    MemoryScope,
    SemanticMemoryRecord,
    WorkingMemory,
    WorkingMemoryLifecycle,
)


class _FakeTraceBuilder:
    def __init__(self):
        self.memory_traces = []
        self.dispositions = []
        self.operation_outcomes = []

    def record_memory_trace(self, memory_trace):
        self.memory_traces.append(memory_trace)

    def record_working_memory_disposition(self, working_memory_id, lifecycle_state):
        self.dispositions.append((working_memory_id, lifecycle_state))

    def record_operation_outcome(self, outcome):
        self.operation_outcomes.append(outcome)


@pytest.fixture
def sid():
    scope_id = f"test-{uuid.uuid4().hex[:8]}"
    yield scope_id
    episodic.delete_ledger(MemoryScope.SESSION, scope_id)
    store.delete_scope(MemoryScope.SESSION, scope_id)


# ── Bounds (spec §4) ─────────────────────────────────────────────────

def test_working_memory_entity_refs_are_bounded():
    wm = WorkingMemory(objective="test")
    for i in range(50):
        wm.add_entity(f"entity{i}")
    assert len(wm.entities) <= wm.MAX_ENTITY_REFS
    assert wm.entities[-1] == "entity49"  # newest kept
    assert wm.entities[0] != "entity0"    # oldest evicted


def test_working_memory_recalled_memory_refs_are_bounded():
    wm = WorkingMemory(objective="test")
    for i in range(20):
        wm.add_recalled_memory_id(f"mem-{i}")
    assert len(wm.recalled_memory_ids) <= wm.MAX_RECALLED_MEMORY_REFS


def test_working_memory_rejects_oversized_single_item():
    wm = WorkingMemory(objective="test")
    huge = "x" * 9000
    accepted = wm.add_tool_observation(huge)
    assert not accepted
    assert huge not in wm.tool_observations


def test_working_memory_serialized_size_stays_bounded():
    from orca.memory.contracts import MAX_WORKING_MEMORY_SERIALIZED_CHARS
    wm = WorkingMemory(objective="test")
    for i in range(200):
        wm.add_decision(f"decision number {i} with some extra padding text to grow the size")
    assert wm.serialized_size() <= MAX_WORKING_MEMORY_SERIALIZED_CHARS


# ── Lifecycle (spec §5) ──────────────────────────────────────────────

def test_working_memory_starts_created():
    wm = WorkingMemory(objective="test")
    assert wm.lifecycle_state == WorkingMemoryLifecycle.CREATED


@pytest.mark.asyncio
async def test_kernel_discards_working_memory_for_insignificant_turn(sid):
    kernel = CognitiveKernel()
    request = CognitiveRequest(objective="hey, how's it going?", session_id=sid)
    working_memory = WorkingMemory(objective=request.objective)
    working_memory.lifecycle_state = WorkingMemoryLifecycle.ACTIVE
    trace_builder = _FakeTraceBuilder()

    kernel._finalize_working_memory(request, working_memory, "Doing well, thanks!", trace_builder)

    assert working_memory.lifecycle_state == WorkingMemoryLifecycle.DISCARDED
    assert episodic.list_episodes(MemoryScope.SESSION, sid) == []


@pytest.mark.asyncio
async def test_kernel_completes_working_memory_for_significant_turn(sid):
    kernel = CognitiveKernel()
    request = CognitiveRequest(objective="Please remember our staging DB runs on port 5433.", session_id=sid)
    working_memory = WorkingMemory(objective=request.objective)
    working_memory.lifecycle_state = WorkingMemoryLifecycle.ACTIVE
    trace_builder = _FakeTraceBuilder()

    kernel._finalize_working_memory(request, working_memory, "Noted, I'll remember that.", trace_builder)

    assert working_memory.lifecycle_state == WorkingMemoryLifecycle.COMPLETED
    assert episodic.list_episodes(MemoryScope.SESSION, sid)
    assert trace_builder.dispositions  # linked into the trace


@pytest.mark.asyncio
async def test_kernel_discards_working_memory_with_no_session_id():
    kernel = CognitiveKernel()
    request = CognitiveRequest(objective="Please remember X.", session_id=None)
    working_memory = WorkingMemory(objective=request.objective)
    trace_builder = _FakeTraceBuilder()

    kernel._finalize_working_memory(request, working_memory, "Noted.", trace_builder)
    assert working_memory.lifecycle_state == WorkingMemoryLifecycle.DISCARDED


# ── Security: WorkingMemory cannot become a Firewall bypass (spec §6) ──

@pytest.mark.asyncio
async def test_working_memory_never_imports_a_firewall_rejected_memory(sid):
    """A DISPROVEN memory (Firewall-rejected) must never end up in
    WorkingMemory.recalled_memory_ids just because it was relevant."""
    disproven = SemanticMemoryRecord(claim="This was disproven.", scope=MemoryScope.SESSION, scope_id=sid, epistemic_state=EpistemicState.DISPROVEN)
    allowed_record = SemanticMemoryRecord(claim="This is fine.", scope=MemoryScope.SESSION, scope_id=sid)
    store.save(disproven)
    store.save(allowed_record)

    kernel = CognitiveKernel()
    request = CognitiveRequest(objective="tell me about this", session_id=sid)
    plan = kernel.plan(request)
    working_memory = WorkingMemory(objective=request.objective)
    trace_builder = _FakeTraceBuilder()

    await kernel._recall_memory_and_enrich(request, plan, trace_builder, working_memory)

    assert disproven.memory_id not in working_memory.recalled_memory_ids
    assert allowed_record.memory_id in working_memory.recalled_memory_ids


@pytest.mark.asyncio
async def test_working_memory_never_imports_cross_session_memory(sid):
    other_sid = f"other-{uuid.uuid4().hex[:8]}"
    other_record = SemanticMemoryRecord(claim="Another session's secret.", scope=MemoryScope.SESSION, scope_id=other_sid)
    store.save(other_record)

    kernel = CognitiveKernel()
    request = CognitiveRequest(objective="what is the secret?", session_id=sid)
    plan = kernel.plan(request)
    working_memory = WorkingMemory(objective=request.objective)
    trace_builder = _FakeTraceBuilder()

    await kernel._recall_memory_and_enrich(request, plan, trace_builder, working_memory)

    assert other_record.memory_id not in working_memory.recalled_memory_ids
    store.delete_scope(MemoryScope.SESSION, other_sid)
