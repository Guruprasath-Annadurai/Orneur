"""
Per-turn Memory Continuum ingestion (Phase 5, fixing the audit's Finding
#1 -- docs/orneur/phase-5/CURRENT_MEMORY_ARCHITECTURE.md). The pre-existing
orca/brain/memory.py::MemoryEngine.commit_to_long_term() call in
orca/serve/api.py unconditionally persists EVERY turn to the legacy
vector store, with no significance filter -- that behavior is left
UNCHANGED (removing it risks the existing semantic-search-over-history
feature many other tests/callers depend on; see spec §58's "only replace
behavior that is demonstrably incompatible").

This module is the NEW, additive path: it runs the significance filter
BEFORE anything durable is written to the Memory Continuum's own
episodic ledger. Casual chatter never reaches the ledger at all. This is
an explicit, disclosed transitional state (dual-write), not a completed
migration -- see docs/orneur/phase-5/PHASE_5_CLOSURE.md.
"""
from __future__ import annotations

from orca.memory import episodic
from orca.memory.arbiter import MemoryArbiter
from orca.memory.candidates import extract_candidates
from orca.memory.contracts import MemoryEpisode, MemoryScope, MemoryType, PromotionDecision
from orca.memory import store as memory_store
from orca.memory.significance import assess_significance


def maybe_ingest_turn(session_id: str, user_message: str, assistant_message: str) -> MemoryEpisode | None:
    """Returns the persisted MemoryEpisode if this turn was significant
    enough to record, else None. Never raises -- a memory-ingestion
    failure must never break the chat response it's derived from."""
    try:
        combined = f"{user_message} {assistant_message}"
        is_significant, signals = assess_significance(combined)
        if not is_significant:
            return None

        episode = MemoryEpisode(
            scope=MemoryScope.SESSION, scope_id=session_id, actors=["user", "assistant"],
            event=user_message[:500], outcome=assistant_message[:500],
        )
        episode = episodic.append_episode(episode)

        candidates = extract_candidates(episode)
        arbiter = MemoryArbiter()
        existing = memory_store.list_records(MemoryType.SEMANTIC, MemoryScope.SESSION, session_id) if candidates else []
        for candidate in candidates:
            decision, _reasons = arbiter.decide_promotion(candidate, existing)
            if decision == PromotionDecision.PROMOTED:
                arbiter.promote(candidate)

        return episode
    except Exception:
        return None
