"""
Phase 5.1: legacy memory authority fixes -- distill_and_save() no longer
writes/reads the unscoped `all_sessions_summary` blob (a real, confirmed
cross-session read leak reachable via orca/tools/__init__.py's
memory_recall agent tool on the multi-tenant web serving path), and both
distill_and_save() and the CLI's `/remember` command now route through
MemoryArbiter instead of writing an untyped, ungoverned "fact" string.
"""
from __future__ import annotations

import uuid

import pytest

from orca.brain.memory import MemoryEngine, SemanticMemory
from orca.memory import store
from orca.memory.contracts import EpistemicState, MemoryScope, MemoryType


class _FakeBrain:
    def complete(self, messages, system, temperature, max_tokens):
        return "- User is building Project Atlas\n- Uses PostgreSQL"


@pytest.fixture
def two_sessions():
    a, b = f"sess-a-{uuid.uuid4().hex[:8]}", f"sess-b-{uuid.uuid4().hex[:8]}"
    yield a, b
    store.delete_scope(MemoryScope.SESSION, a)
    store.delete_scope(MemoryScope.SESSION, b)


def test_distill_and_save_no_longer_writes_unscoped_summary(two_sessions):
    session_a, _ = two_sessions
    engine = MemoryEngine(session_id=session_a)
    engine.add_turn("user", "I'm building Project Atlas with PostgreSQL")
    engine.add_turn("assistant", "Got it, noted.")
    engine.distill_and_save(_FakeBrain())

    sm = SemanticMemory()
    assert not sm.recall_fact("all_sessions_summary")  # never written anymore (may be pre-existing empty string from other tests' fixtures, never new content)


def test_load_prior_context_never_leaks_across_sessions(two_sessions):
    session_a, session_b = two_sessions
    engine_a = MemoryEngine(session_id=session_a)
    engine_a.add_turn("user", "Session A's private business plan is X")
    engine_a.add_turn("assistant", "Noted.")
    engine_a.distill_and_save(_FakeBrain())

    engine_b = MemoryEngine(session_id=session_b)
    prior_for_b = engine_b.load_prior_context()
    assert "Atlas" not in prior_for_b and "PostgreSQL" not in prior_for_b

    prior_for_a = engine_a.load_prior_context()
    assert prior_for_a  # session A still gets its OWN distilled context


def test_distill_and_save_promotes_via_memory_continuum_at_unverified(two_sessions):
    session_a, _ = two_sessions
    engine = MemoryEngine(session_id=session_a)
    engine.add_turn("user", "I'm building Project Atlas with PostgreSQL")
    engine.add_turn("assistant", "Got it.")
    engine.distill_and_save(_FakeBrain())

    records = store.list_records(MemoryType.SEMANTIC, MemoryScope.SESSION, session_a)
    assert records
    # A raw self-summary with no evidence_refs is never silently KNOWN/SUPPORTED
    assert all(r.epistemic_state == EpistemicState.UNVERIFIED for r in records)
